"""Appointment and Visit Navigator: checklist, check-in window, clinic queue, wait estimate, after-visit summary."""

from datetime import datetime, timedelta, timezone

import psycopg

from bioverse.db.seed import DR_OKAFOR, P_HADDAD, TEAM_DERM_TELE
from bioverse.routers.visits import estimate_wait
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, P_PARK, PARK


def make_appt(patient_id, minutes_from_now, practitioner_id=DR_OKAFOR, reason=None, mode="in_person", duration=20):
    """An appointment at an exact time, including times in the past (the booking API only allows the future)."""
    with psycopg.connect(DB) as conn:
        slot = conn.execute(
            """
            INSERT INTO slots (practitioner_id, starts_at, duration_min, mode, status)
            VALUES (%s, date_trunc('second', now()) + %s * interval '1 minute', %s, %s, 'booked') RETURNING id
            """,
            (practitioner_id, minutes_from_now, duration, mode),
        ).fetchone()[0]
        return conn.execute(
            "INSERT INTO appointments (patient_id, practitioner_id, slot_id, reason) VALUES (%s, %s, %s, %s) RETURNING id::text",
            (patient_id, practitioner_id, slot, reason),
        ).fetchone()[0]


def clinic_day(appointment_id):
    with psycopg.connect(DB) as conn:
        return conn.execute(
            """
            SELECT (s.starts_at AT TIME ZONE 'America/New_York')::date FROM appointments a
            JOIN slots s ON s.id = a.slot_id WHERE a.id = %s
            """,
            (appointment_id,),
        ).fetchone()[0].isoformat()


def visit(client, appointment_id, headers=MAYA):
    body = client.get("/api/visits", headers=headers).json()
    return next(v for v in body["upcoming"] if v["id"] == appointment_id)


def book(client, specialty, reason=None):
    options = client.get(f"/api/care/options?specialty={specialty}", headers=MAYA).json()["options"]
    r = client.post("/api/appointments", headers=MAYA, json={"slot_id": options[0]["next_slot"]["id"], "reason": reason})
    assert r.status_code == 201, r.text
    return r.json()


def set_status(client, appointment_id, status, headers=OKAFOR, **extra):
    return client.post(f"/api/visits/queue/{appointment_id}/status", headers=headers, json={"status": status, **extra})


# --- Before the visit ---------------------------------------------------------------------------------


def test_checklist_persists_and_follows_the_visit(client):
    appt = book(client, "Cardiology", reason="Cholesterol recheck with a fasting blood test")
    v = visit(client, appt["id"])
    keys = [i["item_key"] for i in v["checklist"]]
    assert keys[0] == "medications"
    assert {"insurance", "arrive_early", "fasting", "questions"} <= set(keys)
    assert not any(i["done"] for i in v["checklist"])
    assert v["location"]["address"], "seeded locations carry an address"
    assert v["location"]["parking"]
    assert v["reschedule_to"] == "/care/find?specialty=Cardiology"
    assert v["check_in"]["code"] == "too_early"

    meds = v["checklist"][0]
    r = client.patch(f"/api/visits/checklist/{meds['id']}", headers=MAYA, json={"done": True})
    assert r.status_code == 200 and r.json()["done"] is True
    again = visit(client, appt["id"])
    assert next(i for i in again["checklist"] if i["id"] == meds["id"])["done"] is True
    assert len(again["checklist"]) == len(v["checklist"]), "reloading must not duplicate items"

    # Another patient cannot tick it; unticking works.
    assert client.patch(f"/api/visits/checklist/{meds['id']}", headers=PARK, json={"done": False}).status_code == 404
    assert client.patch(f"/api/visits/checklist/{meds['id']}", headers=MAYA, json={"done": False}).json()["done"] is False
    assert client.patch("/api/visits/checklist/not-a-uuid", headers=MAYA, json={"done": True}).status_code == 404

    with psycopg.connect(DB) as conn:
        n = conn.execute(
            "SELECT count(*) FROM audit_events WHERE action LIKE 'visit_checklist_%%' AND patient_id = %s", (P_MAYA,)
        ).fetchone()[0]
    assert n == 2


def test_video_visit_gets_join_link_and_no_fasting(client):
    appt = book(client, "Dermatology")
    if appt["mode"] != "video":
        # Book the telehealth team explicitly.
        slots = client.get(f"/api/practitioners/{TEAM_DERM_TELE}/slots", headers=MAYA).json()
        appt = client.post("/api/appointments", headers=MAYA, json={"slot_id": slots[0]["id"]}).json()
    v = visit(client, appt["id"])
    assert v["location"]["mode"] == "virtual"
    assert v["location"]["join_url"]
    assert v["location"]["tech_check"]
    keys = {i["item_key"] for i in v["checklist"]}
    assert "tech_check" in keys and "arrive_early" not in keys and "fasting" not in keys


def test_patient_questions_are_screened_for_red_flags(client):
    appt = make_appt(P_MAYA, 3 * 24 * 60)
    r = client.post(f"/api/visits/{appt}/questions", headers=MAYA, json={"text": "Should I keep taking my statin at night?"})
    assert r.status_code == 201
    assert r.json()["safety_notice"] is None
    assert [q["text"] for q in visit(client, appt)["questions"]] == ["Should I keep taking my statin at night?"]

    # Suggested questions come from the latest approved result explanation.
    assert visit(client, appt)["suggested_questions"]

    emergency = client.post(f"/api/visits/{appt}/questions", headers=MAYA,
                            json={"text": "I have crushing chest pain right now"})
    assert emergency.status_code == 409
    assert emergency.json()["detail"]["code"] == "emergency"
    assert len(visit(client, appt)["questions"]) == 1, "an emergency is not filed as a routine question"
    queue = client.get("/api/clinician/review-queue", headers=OKAFOR).json()
    assert queue[0]["kind"] == "red_flag" and queue[0]["patient_id"] == P_MAYA

    assert client.post(f"/api/visits/{appt}/questions", headers=PARK, json={"text": "hello"}).status_code == 404
    qid = visit(client, appt)["questions"][0]["id"]
    assert client.delete(f"/api/visits/questions/{qid}", headers=PARK).status_code == 404
    assert client.delete(f"/api/visits/questions/{qid}", headers=MAYA).status_code == 204
    assert visit(client, appt)["questions"] == []


# --- During the visit --------------------------------------------------------------------------------


def test_check_in_window(client):
    too_early = make_appt(P_MAYA, 90)
    r = client.post(f"/api/visits/{too_early}/check-in", headers=MAYA)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "too_early"

    soon = make_appt(P_MAYA, 30)
    assert visit(client, soon)["check_in"]["allowed"] is True
    assert client.post(f"/api/visits/{soon}/check-in", headers=PARK).status_code == 404
    assert client.post(f"/api/visits/{soon}/check-in", headers=OKAFOR).status_code == 403
    r = client.post(f"/api/visits/{soon}/check-in", headers=MAYA)
    assert r.status_code == 200, r.text
    live = r.json()["live"]
    assert live["status"] == "arrived"
    assert live["position"] == 1
    assert 28 <= live["wait_minutes"] <= 31, "nobody ahead: the wait is the time until the booked start"

    again = client.post(f"/api/visits/{soon}/check-in", headers=MAYA)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_checked_in"

    past = make_appt(P_MAYA, -2 * 24 * 60)
    r = client.post(f"/api/visits/{past}/check-in", headers=MAYA)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "missed"

    with psycopg.connect(DB) as conn:
        row = conn.execute(
            "SELECT patient_id::text FROM audit_events WHERE action = 'visit_arrived' AND entity_id = %s", (soon,)
        ).fetchone()
    assert row[0] == P_MAYA


def test_wait_estimate_counts_visits_ahead():
    now = datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc)

    def row(i, status, arrived_min_ago, start_offset=-10, started_min_ago=None, duration=20):
        return {"appointment_id": str(i), "status": status, "arrived_at": now - timedelta(minutes=arrived_min_ago),
                "starts_at": now + timedelta(minutes=start_offset), "duration_min": duration,
                "started_at": now - timedelta(minutes=started_min_ago) if started_min_ago is not None else None}

    rows = [
        row(1, "in_progress", 40, started_min_ago=12),   # 8 minutes left
        row(2, "roomed", 30),                            # 20
        row(3, "arrived", 20, duration=30),              # 30, waiting ahead
        row(4, "arrived", 5),                            # me
        row(5, "arrived", 1),                            # behind me: not counted
    ]
    est = estimate_wait(rows, rows[3], now)
    assert est == {"position": 2, "ahead": 3, "wait_minutes": 8 + 20 + 30}

    # A long-running visit still counts a few minutes; the booked start time is a floor.
    rows[0] = row(1, "in_progress", 40, started_min_ago=45)
    assert estimate_wait(rows, rows[3], now)["wait_minutes"] == 5 + 20 + 30
    early = row(6, "arrived", 1, start_offset=90)
    assert estimate_wait([early], early, now) == {"position": 1, "ahead": 0, "wait_minutes": 90}
    assert estimate_wait(rows, rows[1], now)["position"] is None


def test_clinic_queue_transitions_wait_and_summary(client):
    maya = make_appt(P_MAYA, -5, reason="Follow-up after starting atorvastatin")
    park = make_appt(P_PARK, -4)
    day = clinic_day(maya)

    assert client.get("/api/visits/queue", headers=MAYA).status_code == 403
    assert client.post(f"/api/visits/{maya}/check-in", headers=MAYA).status_code == 200
    assert set_status(client, park, "arrived").status_code == 200  # front-desk check-in

    q = client.get(f"/api/visits/queue?day={day}", headers=OKAFOR).json()
    rows = {r["id"]: r for r in q["appointments"]}
    assert rows[maya]["status"] == "arrived" and rows[maya]["wait"]["position"] == 1
    assert rows[park]["wait"] == {"position": 2, "ahead": 1, "wait_minutes": 20}
    assert "roomed" in rows[maya]["actions"] and "completed" not in rows[maya]["actions"]
    assert q["practitioner"]["id"] == DR_OKAFOR

    # Invalid transitions are rejected.
    bad = set_status(client, maya, "completed")
    assert bad.status_code == 409 and bad.json()["detail"]["code"] == "invalid_transition"
    assert set_status(client, maya, "in_progress").status_code == 409, "in-person visits are roomed first"
    assert set_status(client, maya, "roomed").status_code == 422, "a room is required"
    assert set_status(client, park, "no_show").status_code == 409, "an arrived patient is not a no-show"

    r = set_status(client, maya, "roomed", room="Room 3")
    assert r.status_code == 200 and r.json()["room"] == "Room 3"
    assert visit(client, maya)["live"]["room"] == "Room 3"
    assert client.get(f"/api/visits/queue?day={day}", headers=OKAFOR).json()["appointments"]
    park_row = next(r for r in client.get(f"/api/visits/queue?day={day}", headers=OKAFOR).json()["appointments"] if r["id"] == park)
    assert park_row["wait"] == {"position": 1, "ahead": 1, "wait_minutes": 20}

    assert set_status(client, maya, "in_progress").status_code == 200
    park_row = next(r for r in client.get(f"/api/visits/queue?day={day}", headers=OKAFOR).json()["appointments"] if r["id"] == park)
    assert 15 <= park_row["wait"]["wait_minutes"] <= 20

    # A summary can only be written after completion, by the treating clinician.
    summary = {"instructions": "Keep taking atorvastatin each evening.", "follow_up": "Cholesterol test in 3 months.",
               "prescriptions": "Atorvastatin 20 mg, 30 tablets"}
    assert client.put(f"/api/visits/queue/{maya}/summary", headers=OKAFOR, json=summary).status_code == 409
    assert set_status(client, maya, "completed").status_code == 200
    assert set_status(client, maya, "roomed", room="Room 1").status_code == 409
    park_row = next(r for r in client.get(f"/api/visits/queue?day={day}", headers=OKAFOR).json()["appointments"] if r["id"] == park)
    assert park_row["wait"] == {"position": 1, "ahead": 0, "wait_minutes": 0}

    assert client.put(f"/api/visits/queue/{maya}/summary", headers=MAYA, json=summary).status_code == 403
    assert client.put(f"/api/visits/queue/{maya}/summary", headers=ADMIN, json=summary).status_code == 403
    r = client.put(f"/api/visits/queue/{maya}/summary", headers=OKAFOR, json=summary)
    assert r.status_code == 200, r.text

    # The patient sees it under past visits; the appointment is no longer upcoming.
    body = client.get("/api/visits", headers=MAYA).json()
    assert maya not in [v["id"] for v in body["upcoming"]]
    latest = body["past"][0]
    assert latest["title"] == "Cardiology visit"
    assert latest["summary"]["instructions"] == summary["instructions"]
    assert latest["summary"]["author"] == "Dr. Adaeze Okafor"

    with psycopg.connect(DB) as conn:
        assert conn.execute("SELECT status FROM appointments WHERE id = %s", (maya,)).fetchone()[0] == "fulfilled"
        actions = {r[0] for r in conn.execute(
            "SELECT action FROM audit_events WHERE entity_id = %s AND patient_id = %s", (maya, P_MAYA))}
    assert {"visit_arrived", "visit_roomed", "visit_in_progress", "visit_completed"} <= actions


def test_no_show_and_video_rules(client):
    later = make_appt(P_HADDAD, 120)
    r = set_status(client, later, "no_show")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "too_early"
    missed = make_appt(P_PARK, -30)
    assert set_status(client, missed, "no_show").status_code == 200
    assert set_status(client, missed, "arrived").status_code == 409

    video = make_appt(P_MAYA, -2, mode="video")
    assert client.post(f"/api/visits/{video}/check-in", headers=MAYA).status_code == 200
    assert set_status(client, video, "in_progress").status_code == 200, "video visits skip the room"

    tomorrow = make_appt(P_MAYA, 2 * 24 * 60)
    r = set_status(client, tomorrow, "arrived")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_today"


def test_seeded_past_visits_and_summary(client):
    body = client.get("/api/visits", headers=MAYA).json()
    kinds = [v["title"] for v in body["past"]]
    assert "Cardiology visit" in kinds and "Annual physical" in kinds
    cardio = next(v for v in body["past"] if v["title"] == "Cardiology visit")
    assert "atorvastatin" in cardio["summary"]["instructions"].lower()
    # Patients see only their own visits; clinicians in the org can look.
    assert client.get(f"/api/visits?patient_id={P_PARK}", headers=MAYA).json()["past"] == body["past"]
    assert client.get(f"/api/visits?patient_id={P_MAYA}", headers=OKAFOR).status_code == 200


def test_seeded_clinic_queue_has_todays_patients(client):
    q = client.get("/api/visits/queue", headers=OKAFOR).json()
    names = [a["patient_name"] for a in q["appointments"]]
    assert "Jun Park" in names and "Rana Haddad" in names


# --- Front door -------------------------------------------------------------------------------------


def say(client, text):
    cid = client.post("/api/conversations", headers=MAYA).json()["id"]
    r = client.post(f"/api/conversations/{cid}/messages", headers=MAYA, json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()["messages"][-1]["payload"]


def test_visit_prep_intent_catches_health_story_prompt(client):
    payload = say(client, "Help me prepare questions for my next visit")
    assert payload == {"kind": "link", "to": "/visits", "label": "Open my visits"}
    assert say(client, "What should I bring to my appointment?")["to"] == "/visits"
    # Symptoms still go to triage, and booking requests are not stolen.
    assert say(client, "I have an itchy rash on my forearm")["kind"] == "care_options"
    assert say(client, "I want to book my appointment with a dermatologist")["kind"] == "care_options"
