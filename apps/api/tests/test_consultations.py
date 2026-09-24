"""Online consultations: directory, requests, the status machine, red flags, access, signaling, ratings."""

from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse.agents.triage import rules_triage
from bioverse.db.seed import U_HADDAD
from bioverse.db.seeds.s120_consultations import (
    CO_MAYA_DERM, CO_MAYA_VIDEO, CO_PARK_POOL, DR_BENALI, DR_CASTELLANO, DR_MENSAH, DR_RIVERA, DR_WHITFIELD, DR_ZHAO,
    U_BENALI, U_CASTELLANO, U_MENSAH, U_RIVERA, U_ZHAO,
)
from bioverse.db.seeds.ids import DR_OKAFOR
from bioverse.jobs import run_job
from bioverse.routers.consultations import TRANSITIONS, can_transition, open_slots
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, P_PARK, PARK, as_user

BENALI = as_user(U_BENALI)
RIVERA = as_user(U_RIVERA)
ZHAO = as_user(U_ZHAO)
MENSAH = as_user(U_MENSAH)
CASTELLANO = as_user(U_CASTELLANO)
HADDAD = as_user(U_HADDAD)


def request(client, headers=MAYA, **body):
    payload = {"mode": "message", "reason": "Question about a dry patch of skin on my hand", "telehealth_consent": True}
    payload.update(body)
    return client.post("/api/consultations", headers=headers, json=payload)


def created(client, headers=MAYA, **body):
    r = request(client, headers, **body)
    assert r.status_code == 201, r.text
    return r.json()


def db():
    return psycopg.connect(DB, row_factory=dict_row)


# --- Directory -----------------------------------------------------------------------------------


def test_directory_lists_only_credentialed_clinicians(client):
    body = client.get("/api/consultations/clinicians", headers=MAYA).json()
    ids = {c["id"] for c in body["clinicians"]}
    assert {DR_OKAFOR, DR_BENALI, DR_RIVERA, DR_WHITFIELD, DR_ZHAO} <= ids
    assert DR_CASTELLANO not in ids   # pending
    assert DR_MENSAH not in ids       # verified once, but past the expiry date
    benali = next(c for c in body["clinicians"] if c["id"] == DR_BENALI)
    assert benali["verified"]["board_certification"] == "American Board of Dermatology"
    assert any(ch["demo"] for ch in benali["verified"]["checks"]) and benali["verified"]["verified_at"]
    assert benali["rating"] == {"average": 5.0, "count": 1}
    assert benali["fee_cents"] == 7500 and benali["years_in_practice"] == 11
    assert benali["next_available_at"] is not None
    assert benali["estimate"]["patient_cents"] == 1500   # telehealth copay on the demo plan
    assert "Psychiatry" in body["filters"]["specialties"] and "Spanish" in body["filters"]["languages"]


def test_directory_filters(client):
    def ids(**params):
        return {c["id"] for c in client.get("/api/consultations/clinicians", headers=MAYA, params=params).json()["clinicians"]}

    assert ids(specialty="dermatology") == {DR_BENALI}
    assert ids(language="Spanish") == {DR_RIVERA}
    assert DR_RIVERA in ids(mode="phone") and DR_BENALI not in ids(mode="phone")
    assert ids(specialty="Family medicine", mode="phone", language="spanish") == {DR_RIVERA}
    assert ids(specialty="Neurology") == set()
    profile = client.get(f"/api/consultations/clinicians/{DR_RIVERA}", headers=MAYA).json()
    assert len(profile["slots"]) > 0 and profile["reviews"][0]["stars"] == 4
    assert client.get(f"/api/consultations/clinicians/{DR_MENSAH}", headers=MAYA).status_code == 404
    specs = {s["specialty"]: s for s in client.get("/api/consultations/specialties", headers=MAYA).json()}
    assert specs["Family medicine"]["clinicians"] == 1 and specs["Psychiatry"]["modes"] == ["video", "phone"]


def test_open_slots_respect_hours_and_bookings():
    now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)  # Monday, 08:00 in New York
    hours = {"mon": ["09:00", "11:00"]}
    slots = open_slots(hours, 30, set(), now, days=0)
    assert [s.strftime("%H:%M") for s in slots] == ["09:00", "09:30", "10:00", "10:30"]
    taken = {slots[1].timestamp()}
    assert len(open_slots(hours, 30, taken, now, days=0)) == 3
    late = datetime(2026, 9, 21, 14, 45, tzinfo=timezone.utc)  # 10:45: lead time excludes everything left
    assert open_slots(hours, 30, set(), late, days=0) == []


# --- Requests ------------------------------------------------------------------------------------


def test_request_specific_clinician(client):
    c = created(client, practitioner_id=DR_BENALI)
    assert c["status"] == "requested" and c["practitioner"]["id"] == DR_BENALI and c["fee_cents"] == 7500
    assert c["first_available"] is False and c["can"]["cancel"] and not c["can"]["rate"]
    assert "intake" not in c   # the pre-consult summary is for the clinician
    seen = client.get(f"/api/consultations/{c['id']}", headers=BENALI).json()
    intake = seen["intake"]
    assert seen["intake_produced_by"] == "consult-intake/rules"
    assert intake["allergies"] == ["Penicillin"]
    assert any(m.startswith("Atorvastatin 20 mg") for m in intake["medications"])
    assert any("LDL cholesterol 148" in r for r in intake["recent_results"])
    assert "dry patch" in intake["summary"] and "Red-flag screen negative" in intake["safety"]
    assert seen["can"]["accept"] and seen["can"]["decline"] and not seen["can"]["claim"]
    with db() as conn:
        kinds = conn.execute(
            "SELECT user_id::text AS u, kind FROM notifications WHERE dedupe_key = %s", (f"consult:{c['id']}:requested",)
        ).fetchall()
    assert {k["u"] for k in kinds} == {U_BENALI, "00000000-0000-0000-0000-000000000101"}
    assert {k["kind"] for k in kinds} == {"consultation"}


def test_request_validation(client):
    assert request(client, practitioner_id=DR_BENALI, telehealth_consent=False).status_code == 422
    assert request(client).status_code == 422   # neither clinician nor specialty
    assert request(client, practitioner_id=DR_BENALI, mode="phone").status_code == 422
    r = request(client, practitioner_id=DR_MENSAH)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_available"
    r = request(client, specialty="Psychiatry", mode="message")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_available"
    # Video needs one of the clinician's open times.
    assert request(client, practitioner_id=DR_BENALI, mode="video").status_code == 422
    bad_time = (datetime.now(timezone.utc) + timedelta(days=2)).replace(hour=3, minute=7)
    r = request(client, practitioner_id=DR_BENALI, mode="video", scheduled_at=bad_time.isoformat())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "slot_taken"
    assert client.post("/api/consultations", headers=OKAFOR, json={"mode": "message", "reason": "x" * 5,
                                                                     "telehealth_consent": True}).status_code == 403


def test_video_request_books_a_slot_once(client):
    slot = client.get(f"/api/consultations/clinicians/{DR_ZHAO}", headers=MAYA).json()["slots"][0]
    c = created(client, practitioner_id=DR_ZHAO, mode="video", scheduled_at=slot)
    assert c["scheduled_at"] is not None
    again = client.get(f"/api/consultations/clinicians/{DR_ZHAO}", headers=PARK).json()["slots"]
    assert slot not in again
    r = request(client, PARK, practitioner_id=DR_ZHAO, mode="video", scheduled_at=slot)
    assert r.status_code == 409


def test_open_request_limit(client):
    for _ in range(2):   # Maya already has one open (the video consult)
        created(client, practitioner_id=DR_RIVERA)
    r = request(client, practitioner_id=DR_RIVERA)
    assert r.status_code == 409 and "open consults" in r.text


# --- Red flags -----------------------------------------------------------------------------------


def test_emergency_in_request_blocks_and_escalates(client):
    r = request(client, practitioner_id=DR_RIVERA, reason="My throat is closing up after a bee sting")
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "emergency" and d["emergency_number"] and "emergency" in d["message"]
    assert d["care_team_notified"] is True
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM consultations WHERE patient_id = %s AND reason LIKE %s",
                            (P_MAYA, "%throat%")).fetchone()["n"] == 0
        item = conn.execute("SELECT practitioner_id::text, priority FROM review_items WHERE kind = 'red_flag' "
                            "AND title LIKE 'Red flag in online consult%%'").fetchone()
        assert item["priority"] == "urgent" and item["practitioner_id"] == DR_OKAFOR   # Maya's care team


def test_crisis_in_request_shows_crisis_line(client):
    r = request(client, specialty="Family medicine", reason="I don't want to be alive anymore")
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "emergency" and d["crisis_line"] == "988"


def test_chest_symptoms_need_the_safety_check(client):
    reason = "I've had some chest tightness on and off since yesterday"
    r = request(client, practitioner_id=DR_OKAFOR, reason=reason)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "safety_check"
    assert r.json()["detail"]["options"]
    bad = request(client, practitioner_id=DR_OKAFOR, reason=reason,
                  safety_check={"topic": "chest", "selected": ["breathless"]})
    assert bad.status_code == 409 and bad.json()["detail"]["code"] == "emergency"
    ok = request(client, practitioner_id=DR_OKAFOR, reason=reason, safety_check={"topic": "chest", "selected": ["none"]})
    assert ok.status_code == 201
    intake = client.get(f"/api/consultations/{ok.json()['id']}", headers=OKAFOR).json()["intake"]
    assert "safety check answered" in intake["safety"]


def test_emergency_message_in_consult(client):
    r = client.post(f"/api/consultations/{CO_MAYA_VIDEO}/messages", headers=MAYA,
                    json={"body": "Now I'm having crushing chest pain going down my arm"})
    assert r.status_code == 201
    body = r.json()
    assert body["emergency"]["kind"] == "emergency" and body["flagged"] is True
    last = body["messages"][-1]
    assert last["author_kind"] == "system" and last["payload"]["kind"] == "emergency"
    doc = client.get(f"/api/consultations/{CO_MAYA_VIDEO}", headers=OKAFOR).json()
    assert doc["flag_reason"] == "chest pain with warning signs"
    with db() as conn:
        n = conn.execute("SELECT priority FROM notifications WHERE title LIKE 'Urgent: red flag%%'").fetchone()
        assert n["priority"] == "urgent"
    brief = client.get(f"/api/clinician/patients/{P_MAYA}/brief", headers=OKAFOR).json()
    assert "Red flag in online consult" in str(brief)
    # Routine messages carry on after, and notify the clinician.
    ok = client.post(f"/api/consultations/{CO_MAYA_VIDEO}/messages", headers=MAYA, json={"body": "Thanks, I'm ok now"})
    assert ok.status_code == 201 and "emergency" not in ok.json()


# --- Status machine ------------------------------------------------------------------------------


def test_transition_table():
    assert can_transition("requested", "accepted") and can_transition("accepted", "in_progress")
    assert can_transition("in_progress", "completed")
    for bad in [("requested", "completed"), ("requested", "in_progress"), ("completed", "cancelled"),
                ("declined", "accepted"), ("cancelled", "requested"), ("in_progress", "cancelled"),
                ("accepted", "declined")]:
        assert not can_transition(*bad), bad
    assert all(not TRANSITIONS[s] for s in ("completed", "cancelled", "declined"))


def test_full_flow_accept_start_complete(client):
    c = created(client, practitioner_id=DR_RIVERA)
    cid = c["id"]
    assert client.post(f"/api/consultations/{cid}/complete", headers=RIVERA,
                       json={"summary": "Too early to complete this"}).status_code == 409
    assert client.post(f"/api/consultations/{cid}/start", headers=RIVERA).status_code == 409
    r = client.post(f"/api/consultations/{cid}/accept", headers=RIVERA)
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert client.post(f"/api/consultations/{cid}/accept", headers=RIVERA).status_code == 409
    assert client.post(f"/api/consultations/{cid}/decline", headers=RIVERA, json={"reason": "Too late"}).status_code == 409
    # The clinician's first message starts the consult.
    r = client.post(f"/api/consultations/{cid}/messages", headers=RIVERA, json={"body": "Hi Maya, how long has it been dry?"})
    assert r.json()["status"] == "in_progress"
    assert client.post(f"/api/consultations/{cid}/cancel", headers=MAYA, json={}).status_code == 409
    done = client.post(f"/api/consultations/{cid}/complete", headers=RIVERA,
                       json={"summary": "Mild hand eczema. Use a thick fragrance-free cream after washing.",
                             "follow_up": "Message me in two weeks if not better."})
    assert done.status_code == 200 and done.json()["status"] == "completed"
    mine = client.get(f"/api/consultations/{cid}", headers=MAYA).json()
    assert mine["summary"].startswith("Mild hand eczema") and mine["can"]["rate"] and not mine["can"]["message"]
    assert client.post(f"/api/consultations/{cid}/messages", headers=MAYA, json={"body": "one more thing"}).status_code == 409
    assert client.post(f"/api/consultations/{cid}/cancel", headers=RIVERA, json={"reason": "x"}).status_code == 409
    with db() as conn:
        keys = {r["dedupe_key"].rsplit(":", 1)[1] for r in conn.execute(
            "SELECT dedupe_key FROM notifications WHERE dedupe_key LIKE %s AND kind = 'consultation'",
            (f"consult:{cid}:%",)).fetchall()}
        actions = [r["action"] for r in conn.execute(
            "SELECT action FROM audit_events WHERE entity_id = %s ORDER BY id", (cid,)).fetchall()]
    assert {"requested", "accepted", "in_progress", "completed"} <= keys
    assert actions[:1] == ["consult_requested"] and "consult_completed" in actions


def test_decline_and_cancel(client):
    c = created(client, practitioner_id=DR_RIVERA)
    assert client.post(f"/api/consultations/{c['id']}/decline", headers=RIVERA, json={}).status_code == 422
    r = client.post(f"/api/consultations/{c['id']}/decline", headers=RIVERA,
                    json={"reason": "This needs an in-person exam. Please book a clinic visit."})
    assert r.json()["status"] == "declined"
    assert client.get(f"/api/consultations/{c['id']}", headers=MAYA).json()["decline_reason"].startswith("This needs")
    c2 = created(client, practitioner_id=DR_RIVERA)
    r = client.post(f"/api/consultations/{c2['id']}/cancel", headers=MAYA, json={"reason": "Feeling better"})
    assert r.json()["status"] == "cancelled" and r.json()["cancelled_by"] == "patient"
    assert client.post(f"/api/consultations/{c2['id']}/accept", headers=RIVERA).status_code == 409


def test_first_available_claim(client):
    c = created(client, specialty="Dermatology")
    assert c["practitioner"] is None and c["first_available"] and c["fee_cents"] == 7500
    q = client.get("/api/consultations/clinician/queue", headers=BENALI).json()
    assert c["id"] in [x["id"] for x in q["unclaimed"]] and q["credential"]["credentialed"]
    assert client.post(f"/api/consultations/{c['id']}/accept", headers=BENALI).status_code == 403
    r = client.post(f"/api/consultations/{c['id']}/claim", headers=BENALI)
    assert r.status_code == 200 and r.json()["status"] == "accepted" and r.json()["practitioner"]["id"] == DR_BENALI
    assert client.post(f"/api/consultations/{c['id']}/claim", headers=BENALI).status_code == 409
    q = client.get("/api/consultations/clinician/queue", headers=BENALI).json()
    assert c["id"] in [x["id"] for x in q["active"]] and c["id"] not in [x["id"] for x in q["unclaimed"]]


def test_seeded_pool_request_in_okafor_queue(client):
    q = client.get("/api/consultations/clinician/queue", headers=OKAFOR).json()
    assert [x["id"] for x in q["unclaimed"]] == [CO_PARK_POOL]
    assert CO_MAYA_VIDEO in [x["id"] for x in q["active"]]
    assert q["specialty"] == "Cardiology"


# --- Credential gating ----------------------------------------------------------------------------


def _addressed_to(practitioner_id):
    with db() as conn:
        cid = conn.execute(
            """
            INSERT INTO consultations (patient_id, practitioner_id, requested_practitioner_id, specialty, mode, reason,
                                       telehealth_consent)
            VALUES (%s, %s, %s, 'Family medicine', 'message', 'Question', true) RETURNING id::text
            """,
            (P_MAYA, practitioner_id, practitioner_id),
        ).fetchone()["id"]
    return cid


def test_expired_or_pending_clinicians_cannot_accept_or_claim(client):
    for who, pid in ((MENSAH, DR_MENSAH), (CASTELLANO, DR_CASTELLANO)):
        cid = _addressed_to(pid)
        r = client.post(f"/api/consultations/{cid}/accept", headers=who)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "not_credentialed"
        assert client.get(f"/api/consultations/{cid}", headers=who).json()["can"]["accept"] is False
    pool = created(client, PARK, specialty="Family medicine")
    q = client.get("/api/consultations/clinician/queue", headers=MENSAH).json()
    assert q["credential"]["credentialed"] is False and q["unclaimed"] == []
    assert client.get(f"/api/consultations/{pool['id']}", headers=MENSAH).status_code == 404
    assert client.post(f"/api/consultations/{pool['id']}/claim", headers=MENSAH).status_code == 404


def test_license_suspended_mid_consult_blocks_prescribing(client):
    with db() as conn:
        conn.execute("UPDATE practitioner_credentials SET status = 'suspended' WHERE practitioner_id = %s", (DR_OKAFOR,))
    client.post(f"/api/consultations/{CO_MAYA_VIDEO}/start", headers=OKAFOR)
    r = client.post(f"/api/consultations/{CO_MAYA_VIDEO}/complete", headers=OKAFOR, json={
        "summary": "Statin going well.", "prescription": {"drug_code": "amlodipine", "strength": "5 mg",
                                                           "sig": "Take 1 tablet daily", "quantity": 30}})
    assert r.status_code == 403


# --- Access control -------------------------------------------------------------------------------


def test_patients_only_see_their_own(client):
    assert client.get(f"/api/consultations/{CO_MAYA_DERM}", headers=PARK).status_code == 404
    assert client.post(f"/api/consultations/{CO_MAYA_VIDEO}/messages", headers=PARK, json={"body": "hi"}).status_code == 404
    assert client.post(f"/api/consultations/{CO_MAYA_VIDEO}/cancel", headers=PARK, json={}).status_code == 404
    assert client.get(f"/api/consultations/{CO_PARK_POOL}", headers=MAYA).status_code == 404
    assert client.get("/api/consultations/not-a-uuid", headers=MAYA).status_code == 404
    assert client.get(f"/api/consultations?patient_id={P_PARK}", headers=MAYA).status_code == 403
    mine = client.get("/api/consultations", headers=MAYA).json()
    assert {c["id"] for c in mine} == {CO_MAYA_DERM, CO_MAYA_VIDEO}


def test_clinicians_see_assigned_or_their_specialty_pool_only(client):
    # Benali (dermatology) can't read Okafor's consult, or a cardiology request nobody has claimed.
    assert client.get(f"/api/consultations/{CO_MAYA_VIDEO}", headers=BENALI).status_code == 404
    assert client.get(f"/api/consultations/{CO_PARK_POOL}", headers=BENALI).status_code == 404
    assert client.post(f"/api/consultations/{CO_PARK_POOL}/claim", headers=BENALI).status_code == 404
    assert client.get(f"/api/consultations/{CO_PARK_POOL}", headers=OKAFOR).status_code == 200
    assert client.get(f"/api/consultations/{CO_MAYA_DERM}", headers=OKAFOR).status_code == 404
    # Once Okafor claims it, the pool view is gone for everyone else in cardiology.
    client.post(f"/api/consultations/{CO_PARK_POOL}/claim", headers=OKAFOR)
    assert client.get(f"/api/consultations/{CO_PARK_POOL}", headers=OKAFOR).status_code == 200
    assert client.get(f"/api/consultations/{CO_MAYA_VIDEO}", headers=ADMIN).status_code == 404
    assert client.get("/api/consultations/clinician/queue", headers=MAYA).status_code == 403
    # The workspace panel: summaries for a patient in the clinician's organization, and audited.
    panel = client.get(f"/api/consultations?patient_id={P_MAYA}", headers=BENALI).json()
    derm = next(c for c in panel if c["id"] == CO_MAYA_DERM)
    assert derm["can_open"] is True and derm["summary"].startswith("Most likely")
    assert next(c for c in panel if c["id"] == CO_MAYA_VIDEO)["can_open"] is False
    assert client.get("/api/consultations", headers=ADMIN).status_code == 403


# --- Prescribing -----------------------------------------------------------------------------------


def test_complete_with_prescription_and_interaction_check(client):
    client.post(f"/api/consultations/{CO_MAYA_VIDEO}/start", headers=OKAFOR)
    check = client.get(f"/api/consultations/{CO_MAYA_VIDEO}/prescribe-check?drug_code=clarithromycin", headers=OKAFOR).json()
    assert any(w["severity"] == "major" and w["involves_candidate"] for w in check["warnings"])
    assert check["allergies"] == ["Penicillin"]
    rx = {"drug_code": "clarithromycin", "strength": "500 mg", "sig": "Take 1 tablet twice daily for 7 days",
          "quantity": 14}
    body = {"summary": "Chest infection symptoms; antibiotic started.", "prescription": rx}
    r = client.post(f"/api/consultations/{CO_MAYA_VIDEO}/complete", headers=OKAFOR, json=body)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "interaction"
    body["prescription"] = {**rx, "acknowledge_interactions": True}
    r = client.post(f"/api/consultations/{CO_MAYA_VIDEO}/complete", headers=OKAFOR, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["prescription"]["drug_name"] == "Clarithromycin"
    meds = client.get("/api/pharmacy/prescriptions", headers=MAYA).json()["prescriptions"]
    new = next(p for p in meds if p["drug_code"] == "clarithromycin")
    assert new["status"] == "active" and new["prescriber_name"] == "Dr. Adaeze Okafor"


def test_unknown_drug_rejected(client):
    client.post(f"/api/consultations/{CO_MAYA_VIDEO}/start", headers=OKAFOR)
    r = client.post(f"/api/consultations/{CO_MAYA_VIDEO}/complete", headers=OKAFOR, json={
        "summary": "Done and dusted today.", "prescription": {"drug_code": "unobtainium", "strength": "1 mg",
                                                              "sig": "Take one daily", "quantity": 1}})
    assert r.status_code == 422
    assert client.get(f"/api/consultations/{CO_MAYA_VIDEO}", headers=MAYA).json()["status"] == "in_progress"


# --- Ratings ---------------------------------------------------------------------------------------


def _completed(client):
    c = created(client, practitioner_id=DR_RIVERA)
    client.post(f"/api/consultations/{c['id']}/accept", headers=RIVERA)
    client.post(f"/api/consultations/{c['id']}/start", headers=RIVERA)
    client.post(f"/api/consultations/{c['id']}/complete", headers=RIVERA, json={"summary": "All sorted, nothing more needed."})
    return c["id"]


def test_ratings(client):
    assert client.post(f"/api/consultations/{CO_MAYA_VIDEO}/rating", headers=MAYA, json={"stars": 5}).status_code == 409
    assert client.post(f"/api/consultations/{CO_MAYA_DERM}/rating", headers=MAYA, json={"stars": 4}).status_code == 409
    cid = _completed(client)
    assert client.post(f"/api/consultations/{cid}/rating", headers=MAYA, json={"stars": 6}).status_code == 422
    assert client.post(f"/api/consultations/{cid}/rating", headers=MAYA, json={"stars": 0}).status_code == 422
    assert client.post(f"/api/consultations/{cid}/rating", headers=PARK, json={"stars": 1}).status_code == 404
    r = client.post(f"/api/consultations/{cid}/rating", headers=MAYA, json={"stars": 2, "comment": "Fine but slow"})
    assert r.status_code == 201 and r.json()["comment_status"] == "published" and r.json()["emergency"] is None
    rivera = client.get(f"/api/consultations/clinicians/{DR_RIVERA}", headers=MAYA).json()
    assert rivera["rating"] == {"average": 3.0, "count": 2}
    assert rivera["reviews"][0]["comment"] == "Fine but slow"


def test_rating_comment_is_moderated_by_red_flag_screen(client):
    cid = _completed(client)
    r = client.post(f"/api/consultations/{cid}/rating", headers=MAYA,
                    json={"stars": 3, "comment": "Honestly I want to die, nothing helps"})
    assert r.status_code == 201
    assert r.json()["comment_status"] == "withheld" and r.json()["emergency"]["crisis_line"] == "988"
    reviews = client.get(f"/api/consultations/clinicians/{DR_RIVERA}", headers=MAYA).json()["reviews"]
    assert all("want to die" not in (x["comment"] or "") for x in reviews)
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM review_items WHERE kind = 'red_flag' AND practitioner_id = %s",
                            (DR_RIVERA,)).fetchone()["n"] == 1


# --- Video signaling --------------------------------------------------------------------------------


def test_signaling_round_trip(client):
    base = f"/api/consultations/{CO_MAYA_VIDEO}/signals"
    first = client.get(base, headers=MAYA).json()
    assert first["peer_present"] is False and first["signals"] == []
    assert client.post(base, headers=MAYA, json={"kind": "join"}).status_code == 201
    assert client.post(base, headers=OKAFOR, json={"kind": "join"}).status_code == 201
    assert client.get(f"/api/consultations/{CO_MAYA_VIDEO}", headers=MAYA).json()["status"] == "in_progress"
    doc = client.get(base, headers=OKAFOR, params={"after": 0}).json()
    assert doc["peer_present"] is True and [s["kind"] for s in doc["signals"]] == ["join"]
    cursor = doc["cursor"]
    assert client.post(base, headers=OKAFOR, json={"kind": "offer"}).status_code == 422
    client.post(base, headers=OKAFOR, json={"kind": "offer", "payload": {"type": "offer", "sdp": "v=0 offer"}})
    client.post(base, headers=OKAFOR, json={"kind": "ice", "payload": {"candidate": "candidate:1 1 udp 1 10.0.0.1 5000 typ host"}})
    got = client.get(base, headers=MAYA, params={"after": 0}).json()
    assert [s["kind"] for s in got["signals"]] == ["join", "offer", "ice"]   # only the other party's
    assert got["signals"][1]["payload"]["sdp"] == "v=0 offer"
    client.post(base, headers=MAYA, json={"kind": "answer", "payload": {"type": "answer", "sdp": "v=0 answer"}})
    back = client.get(base, headers=OKAFOR, params={"after": cursor}).json()
    assert [s["kind"] for s in back["signals"]] == ["answer"]
    client.post(base, headers=MAYA, json={"kind": "leave"})
    assert client.get(base, headers=OKAFOR).json()["peer_present"] is False
    big = {"type": "offer", "sdp": "x" * 25000}
    assert client.post(base, headers=OKAFOR, json={"kind": "offer", "payload": big}).status_code == 413
    assert client.post(base, headers=MAYA, json={"kind": "bogus"}).status_code == 422


def test_signaling_access(client):
    base = f"/api/consultations/{CO_MAYA_VIDEO}/signals"
    assert client.get(base, headers=PARK).status_code == 404
    assert client.post(base, headers=BENALI, json={"kind": "join"}).status_code == 404
    assert client.get(f"/api/consultations/{CO_MAYA_DERM}/signals", headers=MAYA).status_code == 409   # message consult
    assert client.post(f"/api/consultations/{CO_PARK_POOL}/signals", headers=OKAFOR, json={"kind": "join"}).status_code == 403


def test_switch_video_to_messages(client):
    r = client.post(f"/api/consultations/{CO_MAYA_VIDEO}/switch-to-message", headers=MAYA,
                    json={"why": "Camera permission denied"})
    assert r.status_code == 200 and r.json()["mode"] == "message"
    assert "switched this consult to secure messages" in r.json()["messages"][-1]["body"]
    assert client.get(f"/api/consultations/{CO_MAYA_VIDEO}/signals", headers=MAYA).status_code == 409


def test_rtc_config(client, monkeypatch):
    assert client.get("/api/consultations/rtc-config", headers=MAYA).json() == {"ice_servers": [], "configured": False}
    monkeypatch.setenv("BIOVERSE_ICE_SERVERS", '[{"urls": "stun:stun.example.org:3478"}, {"nope": 1}]')
    body = client.get("/api/consultations/rtc-config", headers=MAYA).json()
    assert body["ice_servers"] == [{"urls": "stun:stun.example.org:3478"}] and body["configured"]
    monkeypatch.setenv("BIOVERSE_ICE_SERVERS", "not json")
    assert client.get("/api/consultations/rtc-config", headers=MAYA).json()["ice_servers"] == []


# --- Integration ----------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["Can I talk to a doctor online?", "I want to see a doctor now",
                                  "Do you do video visits?", "book an online consultation"])
def test_front_door_intents(text):
    assert rules_triage([{"role": "user", "content": text}], {"allergies": []}).intent == "online_consult"


@pytest.mark.parametrize("text", ["I have chest pain and want to see a doctor now", "I have an itchy rash"])
def test_symptoms_stay_with_triage(text):
    assert rules_triage([{"role": "user", "content": text}], {"allergies": []}).intent != "online_consult"


def test_brief_and_timeline(client):
    brief = client.get(f"/api/clinician/patients/{P_MAYA}/brief", headers=OKAFOR).json()
    text = str(brief)
    assert "Online video consult in Cardiology with you" in text
    assert "Online consult, Dermatology" in text
    story = client.get(f"/api/patients/{P_MAYA}/story", headers=MAYA).json()
    titles = [e["title"] for e in story["events"]]
    assert "Online consult · Dermatology" in titles


def test_housekeeping_expires_stale_requests_and_old_signals(client):
    with db() as conn:
        res = run_job(conn, "consult_housekeeping", datetime.now(timezone.utc) + timedelta(days=4))
        assert res["status"] == "succeeded"
        assert res["detail"]["expired_requests"] == 1   # Park's unclaimed cardiology message request
        row = conn.execute("SELECT status, cancelled_by FROM consultations WHERE id = %s", (CO_PARK_POOL,)).fetchone()
        assert row == {"status": "cancelled", "cancelled_by": "system"}


def test_reminder_before_video_consult(client):
    with db() as conn:
        at = conn.execute("SELECT scheduled_at FROM consultations WHERE id = %s", (CO_MAYA_VIDEO,)).fetchone()["scheduled_at"]
        res = run_job(conn, "consult_housekeeping", at - timedelta(minutes=30))
        assert res["detail"]["reminded"] == 1
        again = run_job(conn, "consult_housekeeping", at - timedelta(minutes=20))
        assert again["detail"]["reminded"] == 0
