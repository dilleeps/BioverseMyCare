"""In-hospital wayfinding: routing on the seeded building, directions from geometry, closures, access."""

import itertools
import math

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse.agents.triage import rules_triage
from bioverse.db import close_pool
from bioverse.db.migrate import migrate
from bioverse.db.seed import DR_OKAFOR, U_FRONTDESK, seed
from bioverse.db.seeds.s190_wayfinding import BUILDING
from bioverse.routers import wayfinding as wf
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, PARK, as_user

FRONTDESK = as_user(U_FRONTDESK)


@pytest.fixture(scope="module")
def graph():
    """The seeded building, loaded once. Tests below work on in-memory copies."""
    close_pool()
    migrate(DB, reset=True)
    seed(DB)
    with psycopg.connect(DB, row_factory=dict_row) as conn:
        return wf.load_graph(conn, BUILDING)


def route(g, frm, to, **kw):
    return wf.plan_route(g, wf.resolve(g, frm), wf.resolve(g, to, allow_nearest=True), step_free=kw.get("step_free", False),
                         slow=kw.get("slow", False))


def kinds(g, r):
    ids = r["node_ids"]
    out = []
    for a, b in zip(ids, ids[1:]):
        edge = next(e for e in g.adj[a] if e.other(a) == b)
        out.append((edge.kind, edge.segment))
    return out


def text(r):
    return "\n".join(s["text"] for s in r["steps"])


# --- Geometry ------------------------------------------------------------------------------------------


def test_turn_direction_math():
    east, south, west, north = (1, 0), (0, 1), (-1, 0), (0, -1)
    # Plan coordinates grow downward, so heading east then south is a right turn.
    assert wf.turn_word(wf.turn_angle(east, south)) == "right"
    assert wf.turn_word(wf.turn_angle(east, north)) == "left"
    assert wf.turn_word(wf.turn_angle(north, west)) == "left"
    assert wf.turn_word(wf.turn_angle(north, east)) == "right"
    assert wf.turn_word(wf.turn_angle(east, (1, 0.2))) == "straight"
    assert wf.turn_word(wf.turn_angle(east, (1, 1))) == "slight right"
    assert wf.turn_word(wf.turn_angle(east, west)) == "around"
    assert wf.turn_angle(east, south) == pytest.approx(90)
    # Walking north, a room to the west is on the left and one to the east on the right.
    assert wf.side_of(north, (0, 0), (-5, 0)) == "left"
    assert wf.side_of(north, (0, 0), (5, -1)) == "right"
    assert wf.side_of(north, (0, 0), (0, -9)) == "ahead"
    assert wf.facing_vector(270) == pytest.approx((0, -1), abs=1e-9)


def test_legs_split_only_at_real_turns():
    n = [wf.Node(str(i), "f", 1, "Level 1", "junction", None, None, x, y) for i, (x, y) in
         enumerate([(0, 0), (10, 0), (20, 0.5), (20, 10)])]
    e = [wf.Edge(f"e{i}", n[i].id, n[i + 1].id, 10, True, "walk", "Corridor") for i in range(3)]
    legs = wf.split_legs(n, e)
    assert [len(leg.edges) for leg in legs] == [2, 1]


# --- Dijkstra on the seeded building -----------------------------------------------------------------


def test_shortest_path_matches_brute_force_on_one_floor(graph):
    """On Level 1, compare Dijkstra with an exhaustive search over simple paths from the entrance."""
    g = graph
    level1 = {i for i, n in g.nodes.items() if n.level == 1}
    src = g.node_by_code("NS-ENTRANCE").id
    best: dict[str, float] = {src: 0.0}
    stack = [(src, {src}, 0.0)]
    while stack:
        node, seen, cost = stack.pop()
        for e in g.adj[node]:
            nxt = e.other(node)
            if e.kind != "walk" or nxt not in level1 or nxt in seen:
                continue
            c = cost + e.meters / wf.PACE_M_PER_S["normal"]
            if c < best.get(nxt, math.inf) - 1e-9:
                best[nxt] = c
            stack.append((nxt, seen | {nxt}, c))
    for target in sorted(level1)[:40]:
        p = wf.shortest(g, src, {target})
        assert p is not None
        assert p.cost_s == pytest.approx(best[target])
        assert p.cost_s == pytest.approx(sum(wf.edge_cost(e, False, "normal") for e in p.edges))


def test_entrance_to_pharmacy_route(graph):
    r = route(graph, "NS-ENTRANCE", "pharmacy")
    assert r["found"] and r["floors"] == [1]
    # 25 m through the lobby, 35 m west along the corridor, 3 m into the pharmacy.
    assert r["distance_m"] == 63
    assert r["duration_s"] == pytest.approx(63 / 1.2, abs=0.51)
    slow = route(graph, "NS-ENTRANCE", "pharmacy", slow=True)
    assert slow["duration_s"] == pytest.approx(63 / 0.7, abs=0.51) and slow["pace"] == "slow"
    assert r["to_area"]["name"] == "Outpatient Pharmacy"
    assert r["steps"][-1]["text"] == "The Outpatient Pharmacy is on your left."
    assert "Turn left into the Level 1 corridor and walk 35 m." in text(r)


def test_elevator_wait_and_floor_changes_are_costed(graph):
    r = route(graph, "NS-ENTRANCE", "cardiology")
    # Floors you walk on: the elevator passes Level 2 without it being part of the route summary.
    assert r["found"] and r["floors"] == [1, 3]
    assert ("elevator", "Elevator A") in kinds(graph, r)
    walk_s = r["distance_m"] / 1.2
    rides = wf.ELEVATOR_WAIT_S + 2 * (wf.ELEVATOR_PER_LEVEL_S + wf.FLOOR_CHANGE_S)
    assert r["duration_s"] == round(walk_s + rides)


def test_text_steps_turns_landmarks_and_floor_changes(graph):
    r = route(graph, "NS-ENTRANCE", "cardiology")
    steps = [s["text"] for s in r["steps"]]
    assert steps[0] == "Start at the Main Entrance on Level 1."
    assert steps[1].startswith("Walk straight ahead through the Main Lobby")
    assert "the Information Desk on your left" in steps[1]
    assert "Take Elevator A up to Level 3." in steps
    assert any(s.startswith("Leave Elevator A, turn left into the Level 3 corridor") for s in steps)
    assert steps[-1] == "The Heart Centre Reception is on your right."
    change = next(s for s in r["steps"] if s["kind"] == "floor_change")
    assert change["floor_level"] == 1
    assert [seg["floor_level"] for seg in r["segments"]] == [1, 3]
    assert {m["text"] for m in r["markers"]} == {"Elevator A to Level 3", "Arrive by Elevator A"}

    down = route(graph, "NS-3-HEART", "cafe")
    assert "Take Elevator B down to Level 1." in text(down)
    assert down["steps"][-1]["text"] == "The Garden Cafe is on your left."


def test_step_free_avoids_stairs_and_escalators(graph):
    default = route(graph, "NS-ENTRANCE", "imaging")
    assert ("escalator", "Escalator") in kinds(graph, default)
    assert "Take the escalator up to Level 2." in text(default)
    assert default["step_free"] is False

    step_free = route(graph, "NS-ENTRANCE", "imaging", step_free=True)
    assert step_free["found"] and step_free["step_free"] is True
    used = {k for k, _ in kinds(graph, step_free)}
    assert used <= {"walk", "elevator"} and "elevator" in used
    assert step_free["duration_s"] > default["duration_s"]

    # From every sign to every destination, a step-free route never uses stairs or escalators.
    codes = [n.code for n in graph.nodes.values() if n.code]
    slugs = [a.slug for a in graph.areas if a.slug]
    for frm, to in itertools.product(codes, slugs):
        r = route(graph, frm, to, step_free=True)
        assert r["found"], (frm, to)
        assert {k for k, _ in kinds(graph, r)} <= {"walk", "elevator"}, (frm, to)


def test_closed_edges_reroute_and_explain(graph):
    g = graph.with_closed(graph.segment_edges("Elevator A"), "Elevator A out of service")
    r = route(g, "NS-ENTRANCE", "cardiology", step_free=True)
    assert r["found"]
    assert ("elevator", "Elevator B") in kinds(g, r)
    assert ("elevator", "Elevator A") not in kinds(g, r)
    assert r["notices"][0]["segment"] == "Elevator A"
    assert "Your route avoids it" in r["notices"][0]["text"]

    both = g.with_closed(g.segment_edges("Elevator B"), "Elevator B out of service")
    none = route(both, "NS-ENTRANCE", "cardiology", step_free=True)
    assert none["found"] is False and none["steps"] == []
    assert "Every step-free route there is closed right now" in none["explanation"]
    assert "Elevator A is closed (Elevator A out of service)" in none["explanation"]
    assert "Elevator B is closed (Elevator B out of service)" in none["explanation"]
    assert "Information Desk" in none["explanation"]

    stairs = route(both, "NS-ENTRANCE", "cardiology")
    assert stairs["found"] and {"stairs"} & {k for k, _ in kinds(both, stairs)}

    # From the parking level with both elevators closed, only the East stairs are left: no step-free way up.
    only_stairs = route(g.with_closed(g.segment_edges("Elevator B"), "Elevator B out of service"),
                   "NS-P-LIFT-A", "main-entrance", step_free=True)
    assert only_stairs["found"] is False
    assert "Every step-free route there is closed right now" in only_stairs["explanation"]


def test_no_step_free_route_without_closures():
    """A floor reached only by stairs explains that there is no step-free way at all."""
    f = {"id": "f", "level": 1, "name": "Level 1", "short_name": "1", "width_m": 10, "height_m": 10}
    nodes = {
        "a": wf.Node("a", "f1", 1, "Level 1", "junction", "Lobby", "A-SIGN", 0, 0),
        "b": wf.Node("b", "f2", 2, "Level 2", "stairs", "Loft", None, 0, 0),
    }
    edges = {"e": wf.Edge("e", "a", "b", 14, False, "stairs", "Loft stairs")}
    g = wf.Graph(nodes, edges, [], {1: f, 2: {**f, "level": 2}})
    r = wf.plan_route(g, wf.resolve(g, "A-SIGN"), wf.Point({"b"}, None, nodes["b"], "Loft"), step_free=True, slow=False)
    assert r["found"] is False
    assert r["explanation"].startswith("There is no step-free route to this place")


def test_nearest_restroom_and_already_there(graph):
    r = route(graph, "NS-3-HEART", "nearest:restroom")
    assert r["floors"] == [3] and r["to_area"]["slug"] == "restrooms-3"
    assert r["steps"][-1]["text"] == "The restrooms are on your right."
    same = route(graph, "NS-ENTRANCE", "main-entrance")
    assert same["found"] and [s["text"] for s in same["steps"]] == ["You're already at the Main Entrance."]


# --- API: access control, appointments, closures -----------------------------------------------------------


def test_route_api_for_any_signed_in_role(client):
    assert client.get("/api/wayfinding/route?from=NS-ENTRANCE&to=cardiology").status_code == 401
    for who in (MAYA, OKAFOR, ADMIN, FRONTDESK):
        r = client.get("/api/wayfinding/route?from=ns-entrance&to=cardiology&step_free=true", headers=who)
        assert r.status_code == 200, r.text
        assert r.json()["found"] and r.json()["step_free"]
    assert client.get("/api/wayfinding/route?from=NOPE-123&to=cardiology", headers=MAYA).status_code == 404
    assert client.get("/api/wayfinding/signs/NS-3-LIFT-B", headers=MAYA).json()["floor_name"] == "Level 3"
    assert client.get("/api/wayfinding/signs/nope", headers=MAYA).status_code == 404

    b = client.get("/api/wayfinding/building", headers=MAYA).json()
    assert [f["short_name"] for f in b["floors"]] == ["P", "1", "2", "3"]
    assert {"pharmacy", "cardiology", "parking", "cafe", "blood-draw", "imaging"} <= {d["slug"] for d in b["destinations"]}
    assert b["starts"][0]["group"] == "Entrances" and b["closed"] == []


def test_next_appointment_resolves_to_the_heart_centre(client):
    # Seeded visits sit at fixed clinic times today, so whether one is still ahead depends on the clock.
    with psycopg.connect(DB) as conn:
        conn.execute("UPDATE appointments SET status = 'cancelled' WHERE patient_id = %s", (P_MAYA,))
    r = client.get("/api/wayfinding/my-next-appointment", headers=MAYA)
    assert r.status_code == 200 and r.json()["appointment"] is None
    assert client.get("/api/wayfinding/my-next-appointment", headers=OKAFOR).status_code == 403
    assert client.get("/api/wayfinding/my-next-appointment", headers=ADMIN).status_code == 403

    with psycopg.connect(DB) as conn:
        slot = conn.execute(
            """
            INSERT INTO slots (practitioner_id, starts_at, mode, status)
            VALUES (%s, date_trunc('minute', now()) + interval '3 hours 7 minutes 11 seconds', 'in_person', 'booked') RETURNING id
            """,
            (DR_OKAFOR,),
        ).fetchone()[0]
        conn.execute("INSERT INTO appointments (patient_id, practitioner_id, slot_id, reason) VALUES (%s, %s, %s, 'Follow-up')",
                     (P_MAYA, DR_OKAFOR, slot))
    body = client.get("/api/wayfinding/my-next-appointment", headers=MAYA).json()
    assert body["appointment"]["specialty"] == "Cardiology"
    assert body["destination"]["slug"] == "cardiology" and body["destination"]["floor_name"] == "Level 3"
    route_ = client.get(f"/api/wayfinding/route?from=NS-P-LIFT-A&to={body['destination']['area_id']}", headers=MAYA).json()
    assert route_["found"] and route_["to_area"]["slug"] == "cardiology"
    # Another patient never sees Maya's appointment.
    park = client.get("/api/wayfinding/my-next-appointment", headers=PARK).json()["appointment"]
    assert park is None or park["id"] != body["appointment"]["id"]


def test_imaging_at_the_heart_centre_resolves_by_location_and_specialty(client):
    with psycopg.connect(DB, row_factory=dict_row) as conn:
        dest = wf.destination_for(conn, "00000000-0000-0000-0000-000000000001", "Imaging", "Northside Heart Centre")
        assert dest["slug"] == "echocardiography"
        assert wf.destination_for(conn, "00000000-0000-0000-0000-000000000001", "Dermatology",
                                  "Northside Clinic")["slug"] == "northside-clinic"
        assert wf.destination_for(conn, "00000000-0000-0000-0000-000000000001", "Primary care",
                                  "Eastgate Family Practice") is None


def last_audit(action):
    with psycopg.connect(DB) as conn:
        return conn.execute(
            "SELECT entity_id::text, actor_role, detail FROM audit_events WHERE action = %s ORDER BY id DESC LIMIT 1",
            (action,),
        ).fetchone()


def test_closures_access_audit_and_live_rerouting(client):
    body = {"segment": "Elevator A", "reason": "Elevator A out of service"}
    assert client.post("/api/wayfinding/closures", json=body).status_code == 401
    assert client.post("/api/wayfinding/closures", headers=MAYA, json=body).status_code == 403
    assert client.post("/api/wayfinding/closures", headers=OKAFOR, json=body).status_code == 403
    assert client.get("/api/wayfinding/admin", headers=MAYA).status_code == 403
    assert client.get("/api/wayfinding/admin", headers=OKAFOR).json()["can_edit"] is False
    assert client.post("/api/wayfinding/closures", headers=ADMIN, json={"reason": "x y z"}).status_code == 422
    assert client.post("/api/wayfinding/closures", headers=ADMIN, json={"segment": "Nope", "reason": "Wet floor"}).status_code == 404

    closed = client.post("/api/wayfinding/closures", headers=ADMIN, json=body)
    assert closed.status_code == 201, closed.text
    closure = closed.json()
    assert closure["active"] and closure["closed_by"] == "Northside Operations"
    assert client.post("/api/wayfinding/closures", headers=FRONTDESK, json=body).status_code == 409
    audit = last_audit("wayfinding_closure_opened")
    assert audit[0] == closure["id"] and audit[1] == "admin"
    assert audit[2]["segment"] == "Elevator A" and audit[2]["reason"] == "Elevator A out of service"

    # Patients see the detour and the notice at once.
    r = client.get("/api/wayfinding/route?from=NS-ENTRANCE&to=cardiology&step_free=true", headers=MAYA).json()
    assert "Take Elevator B up to Level 3." in text(r)
    assert r["notices"][0]["text"].startswith("Elevator A is closed (Elevator A out of service).")
    marks = client.get("/api/wayfinding/building", headers=MAYA).json()["closed"]
    assert {m["floor_level"] for m in marks} == {0, 1, 2, 3} and all("point" in m for m in marks)

    # The front desk closes Elevator B too: now there is no step-free route, and the patient is told why.
    b = client.post("/api/wayfinding/closures", headers=FRONTDESK, json={"segment": "Elevator B", "reason": "Power cut"})
    assert b.status_code == 201
    blocked = client.get("/api/wayfinding/route?from=NS-ENTRANCE&to=cardiology&step_free=true", headers=MAYA).json()
    assert blocked["found"] is False and "Information Desk" in blocked["explanation"]

    segments = {s["segment"]: s for s in client.get("/api/wayfinding/admin", headers=FRONTDESK).json()["segments"]}
    assert segments["Elevator A"]["status"] == "closed" and segments["Elevator A"]["floors"] == ["P", "1", "2", "3"]
    assert segments["Level 1 corridor, east"]["status"] == "open"

    assert client.post(f"/api/wayfinding/closures/{closure['id']}/reopen", headers=MAYA).status_code == 403
    reopened = client.post(f"/api/wayfinding/closures/{closure['id']}/reopen", headers=FRONTDESK)
    assert reopened.status_code == 200 and reopened.json()["reopened_by"] == "Northside Front Desk"
    assert client.post(f"/api/wayfinding/closures/{closure['id']}/reopen", headers=ADMIN).status_code == 409
    assert client.post("/api/wayfinding/closures/not-an-id/reopen", headers=ADMIN).status_code == 404
    assert last_audit("wayfinding_closure_reopened")[0] == closure["id"]
    again = client.get("/api/wayfinding/route?from=NS-ENTRANCE&to=cardiology&step_free=true", headers=MAYA).json()
    assert "Take Elevator A up to Level 3." in text(again) and again["notices"] == []

    log = client.get("/api/wayfinding/admin", headers=ADMIN).json()["closures"]
    assert [c["segment"] for c in log[:3]] == ["Elevator B", "Elevator A", "Elevator B"]
    assert log[2]["reason"] == "Scheduled maintenance"  # the seeded, reopened closure


def test_closing_a_corridor_by_edge(client):
    admin = client.get("/api/wayfinding/admin", headers=ADMIN).json()
    assert len(admin["signs"]) >= 14 and all(s["path"].startswith("/find-your-way?from=NS-") for s in admin["signs"])
    with psycopg.connect(DB) as conn:
        edge = conn.execute(
            "SELECT id::text FROM wf_edges WHERE segment = 'Level 1 corridor, west' ORDER BY meters DESC LIMIT 1"
        ).fetchone()[0]
    r = client.post("/api/wayfinding/closures", headers=ADMIN, json={"edge_ids": [edge], "reason": "Wet floor"})
    assert r.status_code == 201 and r.json()["segment"] is None
    marks = client.get("/api/wayfinding/building", headers=MAYA).json()["closed"]
    assert len(marks) == 1 and marks[0]["line"] and marks[0]["reason"] == "Wet floor"
    assert client.post("/api/wayfinding/closures", headers=ADMIN,
                       json={"edge_ids": [edge], "segment": "Elevator A", "reason": "Both"}).status_code == 422


# --- Front door ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("message,intent", [
    ("Where is the pharmacy?", "wayfinding_pharmacy"),
    ("how do I get to cardiology", "wayfinding_cardiology"),
    ("Where do I park?", "wayfinding_parking"),
    ("where are the restrooms", "wayfinding"),
    ("I need a refill of my prescription", "pharmacy"),
    ("I have chest pain, how do I get to cardiology", "symptom"),
])
def test_front_door_intents(message, intent):
    assert rules_triage([{"role": "user", "content": message}], {"allergies": []}).intent == intent
