"""In-hospital wayfinding demo data (IDs 17000-17999). Idempotent: safe to re-run against a live database.

A fictional building, "Northside Medical Center, Main Building": a parking level and three floors on a
96 x 56 m plate. Every floor has the same spine: a main corridor running east-west (y 25-31), rooms along
both sides, and two vertical cores. Elevator A and the West stairs sit west of centre, Elevator B and the
East stairs east of centre, and an escalator rises from the Level 1 lobby to Level 2.

    Level P  visitor parking, pay station, car entrance from Linden Street
    Level 1  main entrance and lobby, information desk, registration, pharmacy, blood draw lab, cafe,
             Northside Clinic (primary care, dermatology, neurology), physiotherapy
    Level 2  imaging (X-ray, CT, MRI), ultrasound, diabetes clinic, women's health
    Level 3  Northside Heart Centre (cardiology reception, echocardiography, ECG), cardiac rehab

ID ranges:
    17001 building       17010-17013 floors       17100-17399 nodes      17400-17499 areas
    17500-17799 edges    17900-17949 location links                     17950-17999 closures
"""

from __future__ import annotations

import json
import math

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import ORG, _id

BUILDING = _id(17001)
FLOORS = {0: _id(17010), 1: _id(17011), 2: _id(17012), 3: _id(17013)}
FLOOR_INFO = {0: ("Level P", "P"), 1: ("Level 1", "1"), 2: ("Level 2", "2"), 3: ("Level 3", "3")}
WIDTH, HEIGHT = 96, 56
CORRIDOR_Y = 28

NORTH, SOUTH, WEST = 270, 90, 180

U_ADMIN = _id(1001)
CLOSURE_PAST = _id(17950)


def rect(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


class Plan:
    """Collects nodes, areas and edges in a fixed order, so each keeps its ID across reseeds.
    Append new entries at the end of a list; never reorder."""

    def __init__(self) -> None:
        self.nodes: list[dict] = []
        self.areas: list[dict] = []
        self.edges: list[dict] = []
        self._by_key: dict[str, dict] = {}

    def node(self, key, level, kind, x, y, name=None, code=None, facing=None):
        n = {"key": key, "id": _id(17100 + len(self.nodes)), "level": level, "kind": kind, "x": x, "y": y,
             "name": name, "code": code, "facing": facing}
        self.nodes.append(n)
        self._by_key[key] = n
        return key

    def area(self, level, name, kind, polygon, node=None, slug=None, label=None, keywords=(), searchable=True,
             label_at=None):
        self.areas.append({"id": _id(17400 + len(self.areas)), "level": level, "name": name, "kind": kind,
                           "polygon": polygon, "node": node, "slug": slug, "label": label,
                           "keywords": list(keywords), "searchable": searchable, "label_at": label_at})

    def edge(self, a, b, kind="walk", segment=None, meters=None, step_free=None):
        na, nb = self._by_key[a], self._by_key[b]
        if meters is None:
            meters = round(math.hypot(na["x"] - nb["x"], na["y"] - nb["y"]), 1)
        if step_free is None:
            step_free = kind in ("walk", "elevator")
        self.edges.append({"id": _id(17500 + len(self.edges)), "a": a, "b": b, "kind": kind,
                           "segment": segment, "meters": meters, "step_free": step_free})

    def id_of(self, key: str) -> str:
        return self._by_key[key]["id"]


def corridor(p: Plan, level: int, xs: list[int], label: str) -> None:
    """Junctions along the main corridor, joined in order. West of x=46 and east of it close separately."""
    for x in xs:
        if f"{level}:j{x}" not in p._by_key:
            p.node(f"{level}:j{x}", level, "junction", x, CORRIDOR_Y)
    for a, b in zip(xs, xs[1:]):
        side = "west" if b <= 46 else "east"
        p.edge(f"{level}:j{a}", f"{level}:j{b}", segment=f"{label}, {side}")


def door(p: Plan, level: int, key: str, x: int, north: bool, name: str, kind="door", code=None, facing=None):
    """A door on the corridor wall, joined to the corridor junction in front of it."""
    p.node(f"{level}:{key}", level, kind, x, 25 if north else 31, name=name, code=code, facing=facing)


def build() -> Plan:
    p = Plan()

    # --- Vertical cores, on every floor --------------------------------------------------------------
    for level in (0, 1, 2, 3):
        s = FLOOR_INFO[level][1]
        p.node(f"{level}:j37", level, "junction", 37, CORRIDOR_Y, "Elevator A lobby", f"NS-{s}-LIFT-A", NORTH)
        p.node(f"{level}:j69", level, "junction", 69, CORRIDOR_Y, "Elevator B lobby", f"NS-{s}-LIFT-B", NORTH)
        p.node(f"{level}:elA", level, "elevator", 37, 21, "Elevator A")
        p.node(f"{level}:elB", level, "elevator", 69, 21, "Elevator B")
        p.node(f"{level}:stE", level, "stairs", 75, 23, "East stairs")
        if level:
            p.node(f"{level}:stW", level, "stairs", 31, 23, "West stairs")

    # --- Level P: parking ------------------------------------------------------------------------------
    p.node("0:j20", 0, "junction", 20, CORRIDOR_Y)
    p.node("0:j44", 0, "junction", 44, CORRIDOR_Y)
    p.node("0:j75", 0, "junction", 75, CORRIDOR_Y)
    p.node("0:j89", 0, "junction", 89, CORRIDOR_Y)
    p.node("0:pay", 0, "desk", 44, 25, "Pay station")
    p.node("0:carin", 0, "entrance", 89, 42, "Car Park Entrance", "NS-P-ENTRANCE", NORTH)
    corridor(p, 0, [20, 37, 44, 69, 75, 89], "Level P walkway")
    p.edge("0:j44", "0:pay")
    p.edge("0:j89", "0:carin", segment="Level P footpath")

    p.area(0, "Visitor Parking", "parking", rect(2, 2, 94, 54), "0:j37", "parking", "Visitor parking",
           ["car park", "garage", "park", "car", "parking garage"], label_at=(15, 14))
    p.area(0, "Accessible Parking", "parking", rect(26, 31, 48, 41), "0:j37", "accessible-parking", "Accessible bays",
           ["disabled parking", "blue badge", "wheelchair parking"], label_at=(37, 36))
    p.area(0, "Driveway", "corridor", rect(2, 25, 94, 31), label="Driveway", searchable=False, label_at=(56, 28))
    p.area(0, "Car Park Entrance", "entrance", rect(84, 31, 94, 54), "0:carin", "car-park-entrance",
           "Car entrance", ["linden street", "drive in"], label_at=(89, 48))
    p.area(0, "Pay Station", "desk", rect(40, 17, 48, 25), "0:pay", "pay-station", "Pay",
           ["parking ticket", "pay for parking", "validate"])

    # --- Level 1: street level -----------------------------------------------------------------------
    door(p, 1, "clinic", 15, True, "Northside Clinic Reception", code="NS-1-CLINIC", facing=NORTH)
    door(p, 1, "wc", 44, True, "Restrooms")
    door(p, 1, "lab", 57, True, "Blood Draw Lab")
    door(p, 1, "physio", 86, True, "Physiotherapy")
    door(p, 1, "pharm", 11, False, "Outpatient Pharmacy")
    door(p, 1, "reg", 26, False, "Registration Desk", code="NS-1-REG", facing=SOUTH)
    door(p, 1, "cafe", 64, False, "Garden Cafe")
    door(p, 1, "waitE", 86, False, "East Waiting Area")
    p.node("1:entrance", 1, "entrance", 46, 53, "Main Entrance", "NS-ENTRANCE", NORTH)
    p.node("1:lobbyS", 1, "junction", 46, 46)
    p.node("1:lobby", 1, "junction", 46, 40, "Main Lobby")
    p.node("1:info", 1, "desk", 43, 40, "Information Desk", "NS-INFO", WEST)
    p.node("1:esc", 1, "escalator", 54, 46, "Escalator")
    corridor(p, 1, [4, 11, 15, 26, 31, 37, 44, 46, 57, 64, 69, 75, 86, 92], "Level 1 corridor")
    p.edge("1:entrance", "1:lobbyS", segment="Main Lobby")
    p.edge("1:lobbyS", "1:lobby", segment="Main Lobby")
    p.edge("1:lobby", "1:j46", segment="Main Lobby")
    p.edge("1:lobby", "1:info")
    p.edge("1:lobbyS", "1:esc")

    p.area(1, "Northside Clinic", "clinic", rect(2, 2, 28, 25), "1:clinic", "northside-clinic", "Northside Clinic",
           ["primary care", "family doctor", "gp", "dermatology", "skin", "neurology", "dr lindqvist", "dr ferreira",
            "dr weiss"], label_at=(15, 11))
    p.area(1, "Northside Clinic Reception", "desk", rect(9, 19, 21, 25), "1:clinic", label="Reception",
           searchable=False)
    p.area(1, "Blood Draw Lab", "lab", rect(48, 2, 66, 25), "1:lab", "blood-draw", "Blood draw lab",
           ["lab", "laboratory", "blood test", "blood work", "phlebotomy", "urine sample"])
    p.area(1, "Physiotherapy", "clinic", rect(78, 2, 94, 25), "1:physio", "physiotherapy", "Physio",
           ["physio", "physical therapy", "rehab"])
    p.area(1, "Outpatient Pharmacy", "pharmacy", rect(2, 31, 20, 46), "1:pharm", "pharmacy", "Pharmacy",
           ["prescriptions", "medicines", "medication", "refill", "chemist"])
    p.area(1, "Registration Desk", "desk", rect(20, 31, 32, 42), "1:reg", "registration", "Registration",
           ["check in", "admissions", "front desk", "paperwork", "insurance card"])
    p.area(1, "Main Lobby", "waiting", rect(32, 31, 60, 48), "1:lobby", "main-lobby", "Main lobby",
           ["lobby", "atrium", "meeting point"], label_at=(39, 34))
    p.area(1, "Information Desk", "desk", rect(36, 37, 43, 43), "1:info", "information-desk", "Info",
           ["help", "information", "wheelchair", "lost property", "visitor badge"])
    p.area(1, "Escalator to Level 2", "escalator", rect(52, 34, 56, 45), "1:esc", label="Escalator",
           searchable=False)
    p.area(1, "Main Entrance", "entrance", rect(40, 48, 52, 54), "1:entrance", "main-entrance", "Main entrance",
           ["exit", "way out", "front door", "taxi", "drop-off", "bus"])
    p.area(1, "Garden Cafe", "cafe", rect(60, 31, 78, 46), "1:cafe", "cafe", "Garden Cafe",
           ["coffee", "food", "snacks", "cafeteria", "tea", "lunch"])
    p.area(1, "East Waiting Area", "waiting", rect(78, 31, 94, 46), "1:waitE", "east-waiting", "Waiting area",
           ["seating", "waiting room"])

    # --- Level 2: imaging ----------------------------------------------------------------------------
    door(p, 2, "imaging", 15, True, "Imaging Reception", code="NS-2-IMAGING", facing=NORTH)
    door(p, 2, "wc", 44, True, "Restrooms")
    door(p, 2, "us", 57, True, "Ultrasound and Bone Density Unit")
    door(p, 2, "diab", 86, True, "Diabetes and Endocrine Clinic")
    door(p, 2, "imgwait", 11, False, "Imaging Waiting Room")
    door(p, 2, "womens", 64, False, "Women's Health Clinic")
    door(p, 2, "lounge", 86, False, "Family Lounge")
    p.node("2:esc", 2, "escalator", 54, 33, "Escalator")
    corridor(p, 2, [4, 11, 15, 31, 37, 44, 54, 57, 64, 69, 75, 86, 92], "Level 2 corridor")
    p.edge("2:j54", "2:esc")

    p.area(2, "Imaging Department", "imaging", rect(2, 2, 28, 25), "2:imaging", "imaging", "Imaging",
           ["x-ray", "xray", "ct", "ct scan", "mri", "radiology", "scan"], label_at=(15, 11))
    p.area(2, "Imaging Reception", "desk", rect(9, 19, 21, 25), "2:imaging", label="Reception", searchable=False)
    p.area(2, "Ultrasound and Bone Density Unit", "imaging", rect(48, 2, 66, 25), "2:us", "ultrasound", "Ultrasound",
           ["sonogram", "dexa", "bone density", "doppler"])
    p.area(2, "Diabetes and Endocrine Clinic", "clinic", rect(78, 2, 94, 25), "2:diab", "diabetes-clinic",
           "Diabetes clinic", ["endocrinology", "diabetes", "thyroid", "hba1c"])
    p.area(2, "Imaging Waiting Room", "waiting", rect(2, 31, 20, 46), "2:imgwait", "imaging-waiting",
           "Imaging waiting", ["waiting room"])
    p.area(2, "Atrium Seating", "waiting", rect(32, 31, 52, 44), None, label="Atrium (open to Level 1)",
           searchable=False)
    p.area(2, "Escalator to Level 1", "escalator", rect(52, 34, 56, 45), "2:esc", label="Escalator",
           searchable=False)
    p.area(2, "Women's Health Clinic", "clinic", rect(60, 31, 78, 46), "2:womens", "womens-health",
           "Women's health", ["gynecology", "gynaecology", "obstetrics", "prenatal"])
    p.area(2, "Family Lounge", "waiting", rect(78, 31, 94, 46), "2:lounge", "family-lounge", "Family lounge",
           ["seating", "waiting room", "quiet"])

    # --- Level 3: Northside Heart Centre -------------------------------------------------------------
    door(p, 3, "rehab", 15, True, "Cardiac Rehabilitation")
    door(p, 3, "wc", 44, True, "Restrooms")
    door(p, 3, "ecg", 57, True, "ECG and Stress Test Lab")
    door(p, 3, "echo", 86, True, "Echocardiography Lab")
    door(p, 3, "quiet", 11, False, "Quiet Room")
    door(p, 3, "heart", 57, False, "Heart Centre Reception", code="NS-3-HEART", facing=SOUTH)
    door(p, 3, "hwait", 80, False, "Heart Centre Waiting Room")
    corridor(p, 3, [4, 11, 15, 31, 37, 44, 57, 69, 75, 80, 86, 92], "Level 3 corridor")

    p.area(3, "Cardiac Rehabilitation", "clinic", rect(2, 2, 28, 25), "3:rehab", "cardiac-rehab", "Cardiac rehab",
           ["rehab", "exercise", "heart rehab"])
    p.area(3, "ECG and Stress Test Lab", "lab", rect(48, 2, 66, 25), "3:ecg", "ecg", "ECG & stress tests",
           ["ecg", "ekg", "stress test", "holter", "heart monitor"])
    p.area(3, "Echocardiography Lab", "imaging", rect(78, 2, 94, 25), "3:echo", "echocardiography", "Echo",
           ["echo", "heart ultrasound", "echocardiogram"])
    p.area(3, "Quiet Room", "waiting", rect(2, 31, 20, 46), "3:quiet", "quiet-room", "Quiet room",
           ["prayer", "multi-faith", "calm"])
    p.area(3, "Heart Centre Reception", "desk", rect(52, 31, 62, 40), "3:heart", "cardiology", "Heart Centre reception",
           ["cardiology", "heart", "heart centre", "heart center", "cardiologist", "dr okafor", "dr raman",
            "northside heart centre"])
    p.area(3, "Heart Centre Waiting Room", "waiting", rect(62, 31, 94, 41), "3:hwait", "heart-waiting",
           "Heart Centre waiting", ["waiting room"])
    p.area(3, "Northside Heart Centre", "clinic", rect(52, 41, 94, 54), "3:heart", label="Heart Centre exam rooms",
           searchable=False)

    # --- Shared on floors 1-3 ------------------------------------------------------------------------
    for level in (1, 2, 3):
        p.edge(f"{level}:j31", f"{level}:stW")
        p.edge(f"{level}:j44", f"{level}:wc")
        p.area(level, "Restrooms", "restroom", rect(40, 13, 48, 25), f"{level}:wc", f"restrooms-{level}",
               "Restrooms", ["toilet", "toilets", "bathroom", "washroom", "wc", "accessible toilet"])
        p.area(level, "West Stairs", "stairs", rect(28, 12, 34, 25), label="Stairs", searchable=False)
        p.area(level, "Main Corridor", "corridor", rect(2, 25, 94, 31), searchable=False)
    for level in (0, 1, 2, 3):
        p.edge(f"{level}:j37", f"{level}:elA")
        p.edge(f"{level}:j69", f"{level}:elB")
        p.edge(f"{level}:j75", f"{level}:stE")
        p.area(level, "Elevator A", "elevator", rect(34, 16, 40, 25), label="Elevator A", searchable=False)
        p.area(level, "Elevator B", "elevator", rect(66, 16, 72, 25), label="Elevator B", searchable=False)
        p.area(level, "East Stairs", "stairs", rect(72, 12, 78, 25), label="Stairs", searchable=False)

    # Room doors on floors 1-3.
    for key, x in (("1:pharm", 11), ("1:clinic", 15), ("1:reg", 26), ("1:lab", 57), ("1:cafe", 64),
                   ("1:physio", 86), ("1:waitE", 86),
                   ("2:imgwait", 11), ("2:imaging", 15), ("2:us", 57), ("2:womens", 64), ("2:diab", 86),
                   ("2:lounge", 86),
                   ("3:quiet", 11), ("3:rehab", 15), ("3:ecg", 57), ("3:heart", 57), ("3:hwait", 80),
                   ("3:echo", 86)):
        p.edge(f"{key[0]}:j{x}", key)

    # --- Between floors ------------------------------------------------------------------------------
    for a, b in ((0, 1), (1, 2), (2, 3)):
        p.edge(f"{a}:elA", f"{b}:elA", kind="elevator", segment="Elevator A", meters=4.5)
        p.edge(f"{a}:elB", f"{b}:elB", kind="elevator", segment="Elevator B", meters=4.5)
        p.edge(f"{a}:stE", f"{b}:stE", kind="stairs", segment="East stairs", meters=14)
        if a:
            p.edge(f"{a}:stW", f"{b}:stW", kind="stairs", segment="West stairs", meters=14)
    p.edge("1:esc", "2:esc", kind="escalator", segment="Escalator", meters=14)
    return p


PLAN = build()

# Shared locations and departments (resolved by name) -> destination node.
LOCATION_LINKS = [
    # id, location name, department name, specialty, node key, area slug
    (_id(17900), "Northside Heart Centre", None, None, "3:heart", "cardiology"),
    (_id(17901), "Northside Heart Centre", None, "Imaging", "3:echo", "echocardiography"),
    (_id(17902), "Northside Clinic", None, None, "1:clinic", "northside-clinic"),
    (_id(17903), None, "Cardiology", None, "3:heart", "cardiology"),
    (_id(17904), None, "Dermatology", None, "1:clinic", "northside-clinic"),
    (_id(17905), None, "Primary care", None, "1:clinic", "northside-clinic"),
    (_id(17906), None, "Neurology", None, "1:clinic", "northside-clinic"),
]


def run(conn, ctx: SeedContext) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO wf_buildings (id, organization_id, name, campus, address, parking_note, help_note)
        VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        (BUILDING, ORG, "Main Building", "Northside Medical Center", "140 Northside Avenue",
         "Visitor parking is on Level P, under the building. Drive in from Linden Street. Accessible bays are "
         "right next to Elevator A. Both elevators and the East stairs go up from Level P.",
         "Ask at the Information Desk on Level 1, just inside the main entrance, or call (555) 010-4400. "
         "Staff can bring a wheelchair and walk with you."),
    )
    cur.executemany(
        """
        INSERT INTO wf_floors (id, building_id, level, name, short_name, width_m, height_m)
        VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [(fid, BUILDING, level, *FLOOR_INFO[level], WIDTH, HEIGHT) for level, fid in FLOORS.items()],
    )
    cur.executemany(
        """
        INSERT INTO wf_nodes (id, floor_id, kind, name, code, x, y, facing_deg)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [(n["id"], FLOORS[n["level"]], n["kind"], n["name"], n["code"], n["x"], n["y"], n["facing"])
         for n in PLAN.nodes],
    )
    cur.executemany(
        """
        INSERT INTO wf_areas (id, building_id, floor_id, name, label, kind, polygon, label_x, label_y, node_id,
                              slug, keywords, searchable)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [(a["id"], BUILDING, FLOORS[a["level"]], a["name"], a["label"], a["kind"], json.dumps(a["polygon"]),
          a["label_at"][0] if a["label_at"] else None, a["label_at"][1] if a["label_at"] else None,
          PLAN.id_of(a["node"]) if a["node"] else None, a["slug"], a["keywords"], a["searchable"])
         for a in PLAN.areas],
    )
    cur.executemany(
        """
        INSERT INTO wf_edges (id, building_id, from_node, to_node, meters, step_free, kind, segment)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [(e["id"], BUILDING, PLAN.id_of(e["a"]), PLAN.id_of(e["b"]), e["meters"], e["step_free"], e["kind"],
          e["segment"]) for e in PLAN.edges],
    )

    # Link shared locations and departments by name: other modules own their ids.
    locations = dict(conn.execute("SELECT name, id::text FROM locations WHERE organization_id = %s", (ORG,)).fetchall())
    departments = dict(conn.execute("SELECT name, id::text FROM departments WHERE organization_id = %s", (ORG,)).fetchall())
    areas = {a["slug"]: a["id"] for a in PLAN.areas if a["slug"]}
    for link_id, loc, dept, specialty, node, slug in LOCATION_LINKS:
        loc_id = locations.get(loc) if loc else None
        dept_id = departments.get(dept) if dept else None
        if (loc and not loc_id) or (dept and not dept_id):
            continue
        cur.execute(
            """
            INSERT INTO wf_location_nodes (id, organization_id, building_id, location_id, department_id, specialty,
                                           node_id, area_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
            """,
            (link_id, ORG, BUILDING, loc_id, dept_id, specialty, PLAN.id_of(node), areas[slug]),
        )

    # One past closure, reopened, so the closure log is not empty on a fresh demo.
    if conn.execute("SELECT 1 FROM users WHERE id = %s", (U_ADMIN,)).fetchone():
        elevator_b = [e["id"] for e in PLAN.edges if e["segment"] == "Elevator B"]
        cur.execute(
            """
            INSERT INTO wf_closures (id, building_id, segment, edge_ids, reason, closed_by, closed_at,
                                     reopened_by, reopened_at)
            VALUES (%s, %s, 'Elevator B', %s, 'Scheduled maintenance', %s, %s, %s, %s)
            ON CONFLICT DO NOTHING RETURNING id
            """,
            (CLOSURE_PAST, BUILDING, elevator_b, U_ADMIN, ctx.at(ctx.days(-9), 7, 0), U_ADMIN,
             ctx.at(ctx.days(-9), 11, 30)),
        )
        if cur.fetchone():
            cur.execute(
                """
                INSERT INTO audit_events (actor_role, agent, action, entity_type, entity_id, detail)
                VALUES ('system', 'seed', 'wayfinding_closure_seeded', 'wf_closure', %s, %s)
                """,
                (CLOSURE_PAST, json.dumps({"segment": "Elevator B", "reason": "Scheduled maintenance"})),
            )
