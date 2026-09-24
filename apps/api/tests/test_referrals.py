"""Referral Manager: lifecycle, access, expiry, flags, booking detection, brief lines and timeline."""

from datetime import date, timedelta

import psycopg

from bioverse.db.seed import DR_WEISS, P_HADDAD
from bioverse.db.seeds.s020_visits import IMAGING, REF_HADDAD_PC, REF_MAYA_ECHO, REF_PARK_PC
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, P_PARK, PARK
from tests.test_visits import make_appt, set_status


def create(client, **overrides):
    body = {
        "patient_id": P_PARK,
        "specialty": "Neurology",
        "target_practitioner_id": DR_WEISS,
        "reason": "Recurring headaches with visual aura.",
        "required_documents": ["Referral letter", "Headache diary"],
        "provided_documents": ["Referral letter"],
        **overrides,
    }
    r = client.post("/api/referrals", headers=OKAFOR, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def move(client, rid, status, headers=OKAFOR, note=None):
    return client.post(f"/api/referrals/{rid}/status", headers=headers, json={"status": status, "note": note})


def test_seeded_echo_referral_books_through_the_navigator(client):
    mine = client.get("/api/referrals", headers=MAYA).json()
    assert [r["id"] for r in mine] == [REF_MAYA_ECHO]
    echo = mine[0]
    assert echo["status"] == "accepted"
    assert echo["requester"]["name"] == "Dr. Adaeze Okafor"
    assert echo["plain"]["action"] == {"kind": "book", "label": "Book an appointment", "to": "/care/find?specialty=Imaging"}
    assert "flags" not in echo, "internal flags are for the care team"

    options = client.get("/api/care/options?specialty=Imaging", headers=MAYA).json()["options"]
    assert options[0]["practitioner_id"] == IMAGING
    assert options[0]["location"] == "Northside Heart Centre"
    booked = client.post("/api/appointments", headers=MAYA, json={"slot_id": options[0]["next_slot"]["id"]}).json()

    # Detected on the next read: the referral is scheduled against that appointment.
    echo = client.get(f"/api/referrals/{REF_MAYA_ECHO}", headers=MAYA).json()
    assert echo["status"] == "scheduled"
    assert echo["appointment"]["id"] == booked["id"]
    assert echo["plain"]["action"]["to"] == "/visits"
    assert [h["to_status"] for h in echo["history"]] == ["draft", "sent", "accepted", "scheduled"]
    assert echo["history"][2]["actor"] == "Northside Front Desk"
    assert echo["history"][3]["actor"] == "Bioverse (automatic)"

    # Cancelling the appointment puts the referral back to "accepted" so the patient can rebook.
    client.post(f"/api/appointments/{booked['id']}/cancel", headers=MAYA)
    echo = client.get(f"/api/referrals/{REF_MAYA_ECHO}", headers=MAYA).json()
    assert echo["status"] == "accepted" and echo["appointment"] is None
    assert "cancelled" in echo["plain"]["headline"]


def test_completed_visit_closes_the_loop(client):
    appt = make_appt(P_MAYA, -5, practitioner_id=IMAGING)
    assert client.get(f"/api/referrals/{REF_MAYA_ECHO}", headers=OKAFOR).json()["status"] == "scheduled"
    assert client.post(f"/api/visits/{appt}/check-in", headers=MAYA).status_code == 200
    assert set_status(client, appt, "roomed", room="Echo 1").status_code == 200
    assert set_status(client, appt, "in_progress").status_code == 200
    assert set_status(client, appt, "completed").status_code == 200
    echo = client.get(f"/api/referrals/{REF_MAYA_ECHO}", headers=MAYA).json()
    assert echo["status"] == "completed"
    events = client.get(f"/api/patients/{P_MAYA}/story", headers=MAYA).json()["events"]
    titles = [e["title"] for e in events]
    assert "Referral completed · Imaging" in titles
    assert "Referral sent · Imaging" in titles


def test_lifecycle_and_invalid_transitions(client):
    r = create(client)
    assert r["status"] == "draft"
    assert r["target"]["id"] == DR_WEISS
    assert r["missing_documents"] == ["Headache diary"]
    assert {f["code"] for f in r["flags"]} == {"missing_documents"}
    assert r["id"] not in [x["id"] for x in client.get("/api/referrals", headers=PARK).json()], "drafts stay internal"
    assert client.get(f"/api/referrals/{r['id']}", headers=PARK).status_code == 404

    assert move(client, r["id"], "accepted").status_code == 409, "a draft must be sent first"
    assert move(client, r["id"], "sent", headers=ADMIN).status_code == 403, "only the referring clinician sends"
    sent = move(client, r["id"], "sent")
    assert sent.status_code == 200 and sent.json()["status"] == "sent"
    with psycopg.connect(DB) as conn:
        item = conn.execute(
            "SELECT practitioner_id::text, link, status FROM review_items WHERE kind = 'referral' AND ref_id = %s",
            (r["id"],),
        ).fetchone()
    assert item == (DR_WEISS, "/clinician/referrals", "open")

    for bad in ("completed", "scheduled", "sent"):
        res = move(client, r["id"], bad)
        assert res.status_code == 409, bad
        assert res.json()["detail"]["code"] == "invalid_transition"
    assert move(client, r["id"], "accepted", headers=PARK).status_code == 403
    assert client.post(f"/api/referrals/{r['id']}/status", headers=OKAFOR, json={"status": "expired"}).status_code == 422

    accepted = move(client, r["id"], "accepted", headers=ADMIN)
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["status"] == "accepted"
    assert body["history"][-1]["actor"] == "Northside Operations"
    with psycopg.connect(DB) as conn:
        assert conn.execute(
            "SELECT status FROM review_items WHERE kind = 'referral' AND ref_id = %s", (r["id"],)
        ).fetchone()[0] == "resolved"
        audited = conn.execute(
            "SELECT count(*) FROM audit_events WHERE entity_id = %s AND patient_id = %s AND action LIKE 'referral_%%'",
            (r["id"], P_PARK),
        ).fetchone()[0]
    assert audited == 3  # draft, sent, accepted

    patient_view = next(x for x in client.get("/api/referrals", headers=PARK).json() if x["id"] == r["id"])
    assert patient_view["plain"]["action"]["to"] == "/care/find?specialty=Neurology"

    assert move(client, r["id"], "scheduled", headers=ADMIN).status_code == 200
    assert move(client, r["id"], "completed").status_code == 200
    assert move(client, r["id"], "cancelled").status_code == 409, "completed is final"

    # Documents on a closed referral can't change; on an open one they must be from the required list.
    assert client.put(f"/api/referrals/{r['id']}/documents", headers=OKAFOR, json={"provided": []}).status_code == 409


def test_decline_needs_a_reason_and_notifies_the_referrer(client):
    r = create(client, send=True)
    assert r["status"] == "sent"
    assert move(client, r["id"], "declined").status_code == 422
    res = move(client, r["id"], "declined", note="Please try primary care first.")
    assert res.status_code == 200 and res.json()["status"] == "declined"
    queue = client.get("/api/clinician/review-queue", headers=OKAFOR).json()
    assert any(i["kind"] == "referral" and "declined" in i["title"] for i in queue)
    plain = next(x for x in client.get("/api/referrals", headers=PARK).json() if x["id"] == r["id"])["plain"]
    assert "couldn't accept" in plain["headline"]


def test_documents_update(client):
    r = create(client)
    bad = client.put(f"/api/referrals/{r['id']}/documents", headers=OKAFOR, json={"provided": ["Something else"]})
    assert bad.status_code == 422
    ok = client.put(f"/api/referrals/{r['id']}/documents", headers=OKAFOR,
                    json={"provided": ["Referral letter", "Headache diary"]})
    assert ok.status_code == 200
    assert ok.json()["missing_documents"] == []
    assert ok.json()["flags"] == []
    assert client.put(f"/api/referrals/{r['id']}/documents", headers=PARK, json={"provided": []}).status_code == 403


def test_expiry_on_read(client):
    r = create(client, send=True, provided_documents=["Referral letter", "Headache diary"],
               expires_on=(date.today() + timedelta(days=3)).isoformat())
    assert {f["code"] for f in r["flags"]} == {"expiring"}

    with psycopg.connect(DB) as conn:
        conn.execute("UPDATE service_requests SET expires_on = current_date - 2 WHERE id = %s", (r["id"],))

    listed = next(x for x in client.get("/api/referrals", headers=OKAFOR).json() if x["id"] == r["id"])
    assert listed["status"] == "expired"
    assert {f["code"] for f in listed["flags"]} == {"expired"}
    assert move(client, r["id"], "accepted").status_code == 409

    detail = client.get(f"/api/referrals/{r['id']}", headers=PARK).json()
    assert detail["history"][-1]["to_status"] == "expired"
    assert detail["history"][-1]["actor"] == "Bioverse (automatic)"
    assert "expired" in detail["plain"]["headline"]

    past = client.post("/api/referrals", headers=OKAFOR, json={
        "patient_id": P_PARK, "specialty": "Neurology", "reason": "Headaches",
        "expires_on": (date.today() - timedelta(days=5)).isoformat()})
    assert past.status_code == 422


def test_seeded_flags_for_the_referring_clinician(client):
    mine = {r["id"]: r for r in client.get("/api/referrals", headers=OKAFOR).json()}
    assert {REF_MAYA_ECHO, REF_HADDAD_PC, REF_PARK_PC} <= set(mine)
    assert {f["code"] for f in mine[REF_HADDAD_PC]["flags"]} == {"missing_documents", "expiring"}
    assert {f["code"] for f in mine[REF_PARK_PC]["flags"]} == {"leaking"}
    assert mine[REF_MAYA_ECHO]["flags"] == []
    assert mine[REF_HADDAD_PC]["age_days"] in (11, 12)

    incoming = client.get("/api/referrals?view=incoming", headers=OKAFOR).json()
    assert {REF_MAYA_ECHO, REF_HADDAD_PC, REF_PARK_PC} <= {r["id"] for r in incoming}
    one = client.get(f"/api/referrals?view=patient&patient_id={P_HADDAD}", headers=OKAFOR).json()
    assert [r["id"] for r in one] == [REF_HADDAD_PC]
    directory = client.get("/api/referrals/directory", headers=OKAFOR).json()
    assert "Imaging" in directory["specialties"]


def test_patients_only_see_their_own_referrals(client):
    assert client.get(f"/api/referrals/{REF_MAYA_ECHO}", headers=PARK).status_code == 404
    assert client.get(f"/api/referrals/{REF_MAYA_ECHO}", headers=MAYA).status_code == 200
    assert REF_MAYA_ECHO not in [r["id"] for r in client.get("/api/referrals", headers=PARK).json()]
    assert client.get("/api/referrals/not-a-uuid", headers=MAYA).status_code == 404
    assert client.get(f"/api/referrals?view=patient&patient_id={P_MAYA}", headers=PARK).json() == \
        client.get("/api/referrals", headers=PARK).json(), "a patient's view is always their own"
    assert client.post("/api/referrals", headers=MAYA, json={
        "patient_id": P_MAYA, "specialty": "Imaging", "reason": "I want one"}).status_code == 403
    assert move(client, REF_MAYA_ECHO, "cancelled", headers=MAYA).status_code == 403
    assert client.get("/api/referrals/directory", headers=MAYA).status_code == 403


def test_create_validates_directory(client):
    r = client.post("/api/referrals", headers=OKAFOR, json={
        "patient_id": P_PARK, "specialty": "Dermatology", "target_practitioner_id": DR_WEISS, "reason": "Rash"})
    assert r.status_code == 422
    r = client.post("/api/referrals", headers=OKAFOR, json={"patient_id": P_PARK, "specialty": "Podiatry", "reason": "Feet"})
    assert r.status_code == 422
    r = client.post("/api/referrals", headers=OKAFOR, json={
        "patient_id": P_PARK, "target_practitioner_id": IMAGING, "reason": "Echo", "priority": "urgent"})
    assert r.status_code == 201
    assert r.json()["specialty"] == "Imaging"
    assert r.json()["days_to_expiry"] == 30


def test_brief_lines_and_intent(client):
    brief = client.get(f"/api/clinician/patients/{P_MAYA}/brief", headers=OKAFOR).json()
    lines = [b for b in brief["bullets"] if b["source"]["type"] == "service_request"]
    assert len(lines) == 1 and "Imaging" in lines[0]["text"]
    assert "Referral pending" in brief["attention_flags"]

    haddad = client.get(f"/api/clinician/patients/{P_HADDAD}/brief", headers=OKAFOR).json()
    assert "Referral expiring" in haddad["attention_flags"]
    assert any("Missing: Medication list" in b["text"] for b in haddad["bullets"])

    cid = client.post("/api/conversations", headers=MAYA).json()["id"]
    convo = client.post(f"/api/conversations/{cid}/messages", headers=MAYA, json={"text": "Where is my referral?"}).json()
    assert convo["messages"][-1]["payload"]["to"] == "/referrals"
