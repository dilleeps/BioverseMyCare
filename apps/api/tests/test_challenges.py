"""Challenges and rewards: progress from real data, streaks, the daily job (idempotent), completion,
family challenges with consent, demo rewards, fairness, access control and audit."""

from datetime import datetime, time, timedelta, timezone

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse.agents.triage import rules_triage
from bioverse.challenge_engine import REWARDS, progress
from bioverse.config import clinic_today, clinic_tz
from bioverse.db.seeds.ids import _id
from bioverse.jobs import run_job
from tests.conftest import DB, MAYA, OKAFOR, P_MAYA, P_PARK, PARK

U_DAVID, P_DAVID = _id(6003), _id(6004)
DAVID = {"X-Bioverse-User": U_DAVID}


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def job(now=None):
    with db() as conn:
        return run_job(conn, "challenge_progress", now or datetime.now(timezone.utc))["detail"]


def steps(patient_id, day, value):
    with db() as conn:
        conn.execute(
            """INSERT INTO observations (patient_id, loinc_code, display, value, unit, interpretation, effective_at,
                                         category, source)
               VALUES (%s, '41950-7', 'Steps in 24 hours', %s, '/d', 'N', %s, 'activity', 'device')""",
            (patient_id, value, datetime.combine(day, time(12), tzinfo=clinic_tz())))
        conn.commit()


def join(client, definition, headers=PARK, patient=P_PARK):
    r = client.post(f"/api/challenges/patients/{patient}/enrollments", headers=headers, json={"definition_id": definition})
    assert r.status_code == 201, r.text
    return next(e for e in r.json()["active"] if e["definition_id"] == definition)


def backdate(enrollment_id, days):
    with db() as conn:
        conn.execute("UPDATE challenge_enrollments SET started_on = started_on - %s, ends_on = ends_on - %s WHERE id = %s",
                     (days, days, enrollment_id))
        conn.commit()


# --- Seed ------------------------------------------------------------------------------------------------------------


def test_mayas_seeded_streak_points_and_perk(client):
    me = client.get(f"/api/challenges/patients/{P_MAYA}", headers=MAYA).json()
    active = me["active"][0]
    assert active["definition_id"] == "steps_7k_7d"
    assert active["progress"]["current_streak"] == 5 and active["progress"]["periods_met"] == 5
    assert me["points"] == 120
    assert {"complete_hydration_8_7d", "streak_3", "first_goal_day"} <= {b["badge"] for b in me["badges"]}
    assert len(me["redemptions"]) == 1 and me["redemptions"][0]["code"].startswith("DEMO-")
    assert {f["name"] for f in me["family"]} == {"David", "Eleanor"}
    # The daily job adds nothing on top of what the seed already awarded.
    detail = job()
    assert detail["points"] == 0 and detail["badges"] == 0
    assert client.get(f"/api/challenges/patients/{P_MAYA}", headers=MAYA).json()["points"] == 120


# --- Progress from real data -----------------------------------------------------------------------------------------


def test_progress_counts_observations_wellness_entries_and_the_meal_log(client):
    e = join(client, "steps_7k_7d")
    backdate(e["id"], 2)
    today = clinic_today()
    steps(P_PARK, today - timedelta(days=2), 7200)
    steps(P_PARK, today - timedelta(days=2), 3000)        # the day's highest reading counts
    steps(P_PARK, today - timedelta(days=1), 6500)
    # Logged through the challenge screen: stored as an ordinary activity observation.
    r = client.post(f"/api/challenges/patients/{P_PARK}/log", headers=PARK, json={"metric": "steps", "value": 8000})
    assert r.status_code == 201
    p = next(x for x in r.json()["active"] if x["id"] == e["id"])["progress"]
    assert [x["met"] for x in p["periods"][:3]] == [True, False, True]
    assert p["periods_met"] == 2 and p["current_streak"] == 1 and p["today_value"] == 8000

    veg = join(client, "veg_5_7d")
    client.post(f"/api/nutrition/patients/{P_PARK}/meals", headers=PARK,
                json={"meal": "dinner", "items": [{"food_id": "broccoli-cooked", "servings": 3}, {"food_id": "mixed-greens", "servings": 1}]})
    me = client.get(f"/api/challenges/patients/{P_PARK}", headers=PARK).json()
    vp = next(x for x in me["active"] if x["id"] == veg["id"])["progress"]
    assert vp["today_value"] == 5 and vp["periods_met"] == 1


def test_weekly_active_minutes(client):
    e = join(client, "active_150_week")
    for v in (60, 45):
        client.post(f"/api/challenges/patients/{P_PARK}/log", headers=PARK, json={"metric": "active_minutes", "value": v})
    me = client.get(f"/api/challenges/patients/{P_PARK}", headers=PARK).json()
    p = next(x for x in me["active"] if x["id"] == e["id"])["progress"]
    assert p["required"] == 1 and p["today_value"] == 105 and p["periods_met"] == 0
    client.post(f"/api/challenges/patients/{P_PARK}/log", headers=PARK, json={"metric": "active_minutes", "value": 45})
    detail = job()
    assert detail["completed"] == 1
    with db() as conn:
        assert conn.execute("SELECT status FROM challenge_enrollments WHERE id = %s", (e["id"],)).fetchone()["status"] == "completed"


# --- The daily job ------------------------------------------------------------------------------------------------------


def test_job_completes_awards_and_is_idempotent(client):
    e = join(client, "steps_7k_7d")
    backdate(e["id"], 6)
    today = clinic_today()
    for i in range(7):
        steps(P_PARK, today - timedelta(days=6 - i), 7000 + i * 100)   # exactly 7,000 counts as met
    first = job()
    assert first["completed"] == 1
    me = client.get(f"/api/challenges/patients/{P_PARK}", headers=PARK).json()
    assert me["points"] == 7 * 10 + 100
    assert {"first_goal_day", "streak_3", "streak_7", "complete_steps_7k_7d"} <= {b["badge"] for b in me["badges"]}
    assert me["past"][0]["status"] == "completed"
    with db() as conn:
        notes = conn.execute("SELECT title FROM notifications WHERE kind = 'challenge' AND patient_id = %s ORDER BY title",
                             (P_PARK,)).fetchall()
        n_notes = len(notes)
        assert "Challenge complete" in {n["title"] for n in notes}
        assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = 'challenge_completed'").fetchone()["n"] == 1

    second = job()
    assert second["points"] == 0 and second["badges"] == 0 and second["notifications"] == 0
    assert client.get(f"/api/challenges/patients/{P_PARK}", headers=PARK).json()["points"] == 170
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM notifications WHERE kind = 'challenge' AND patient_id = %s",
                            (P_PARK,)).fetchone()["n"] == n_notes
    # The completed challenge is on the timeline.
    from bioverse.timeline.challenges import events
    with db() as conn:
        assert [ev["title"] for ev in events(conn, P_PARK, None)] == ["Challenge completed"]


def test_unfinished_challenge_ends_kindly(client):
    e = join(client, "steps_7k_7d")
    backdate(e["id"], 10)
    steps(P_PARK, clinic_today() - timedelta(days=9), 9000)
    detail = job()
    assert detail["ended"] == 1
    with db() as conn:
        n = conn.execute("SELECT body FROM notifications WHERE dedupe_key = %s", (f"challenge:{e['id']}:ended",)).fetchone()
    assert "1 of 7 days" in n["body"] and "Start again" in n["body"]
    assert client.get(f"/api/challenges/patients/{P_PARK}", headers=PARK).json()["points"] == 10


def test_progress_function_streak_ignores_unfinished_today(client):
    e = join(client, "steps_7k_7d")
    backdate(e["id"], 2)
    steps(P_PARK, clinic_today() - timedelta(days=2), 8000)
    steps(P_PARK, clinic_today() - timedelta(days=1), 8000)
    with db() as conn:
        row = conn.execute("SELECT id::text, patient_id::text, definition_id, started_on, ends_on FROM challenge_enrollments WHERE id = %s",
                           (e["id"],)).fetchone()
        p = progress(conn, row, clinic_today())
    assert p["current_streak"] == 2 and p["periods"][2]["today"] and not p["periods"][2]["met"]


# --- Opt-in and rules ---------------------------------------------------------------------------------------------------


def test_joining_is_explicit_and_once(client):
    assert client.get(f"/api/challenges/patients/{P_PARK}", headers=PARK).json()["active"] == []
    e = join(client, "hydration_8_7d")
    assert client.post(f"/api/challenges/patients/{P_PARK}/enrollments", headers=PARK,
                       json={"definition_id": "hydration_8_7d"}).status_code == 409
    assert client.post(f"/api/challenges/patients/{P_PARK}/enrollments", headers=PARK,
                       json={"definition_id": "nope"}).status_code == 404
    left = client.post(f"/api/challenges/enrollments/{e['id']}/leave", headers=PARK).json()
    assert left["active"] == []
    assert client.post(f"/api/challenges/enrollments/{e['id']}/leave", headers=PARK).status_code == 409


def test_critical_blood_pressure_log_warns_and_alerts(client):
    join(client, "bp_daily_14d")
    r = client.post(f"/api/challenges/patients/{P_PARK}/log", headers=PARK, json={"metric": "bp", "systolic": 186, "diastolic": 112})
    assert r.status_code == 201
    assert "911" in r.json()["warning"]
    with db() as conn:
        rows = conn.execute("SELECT loinc_code, interpretation, panel_id FROM observations WHERE patient_id = %s AND category = 'vital-signs'",
                            (P_PARK,)).fetchall()
        assert {x["loinc_code"] for x in rows} == {"8480-6", "8462-4"} and len({x["panel_id"] for x in rows}) == 1
        assert conn.execute("SELECT priority FROM review_items WHERE kind = 'vital_alert' AND patient_id = %s",
                            (P_PARK,)).fetchone()["priority"] == "urgent"
    ok = client.post(f"/api/challenges/patients/{P_PARK}/log", headers=PARK, json={"metric": "bp", "systolic": 118, "diastolic": 76})
    assert ok.json()["warning"] is None
    assert client.post(f"/api/challenges/patients/{P_PARK}/log", headers=PARK, json={"metric": "bp", "systolic": 120}).status_code == 422


# --- Family ----------------------------------------------------------------------------------------------------------------


def test_family_challenge_needs_each_members_own_consent(client):
    assert client.post(f"/api/challenges/patients/{P_MAYA}/teams", headers=MAYA,
                       json={"definition_id": "hydration_8_7d", "invite": [P_PARK]}).status_code == 403
    assert client.post(f"/api/challenges/patients/{P_MAYA}/teams", headers=MAYA,
                       json={"definition_id": "bp_daily_14d", "invite": [P_DAVID]}).status_code == 422
    r = client.post(f"/api/challenges/patients/{P_MAYA}/teams", headers=MAYA,
                    json={"definition_id": "hydration_8_7d", "invite": [P_DAVID]})
    assert r.status_code == 201
    team = r.json()["teams"][0]
    assert team["members"] == [{"name": "David", "status": "invited"}, {"name": "You", "status": "joined"}]

    david = client.get(f"/api/challenges/patients/{P_DAVID}", headers=DAVID).json()
    assert david["active"] == [] and david["teams"][0]["my_status"] == "invited"
    with db() as conn:
        assert conn.execute("SELECT title FROM notifications WHERE kind = 'challenge' AND patient_id = %s",
                            (P_DAVID,)).fetchone()["title"] == "You're invited to a family challenge"
    assert client.post(f"/api/challenges/teams/{team['id']}/respond", headers=PARK, json={"accept": True}).status_code == 404
    joined = client.post(f"/api/challenges/teams/{team['id']}/respond", headers=DAVID, json={"accept": True}).json()
    assert joined["active"][0]["team_id"] == team["id"]
    assert client.post(f"/api/challenges/teams/{team['id']}/respond", headers=DAVID, json={"accept": True}).status_code == 409

    # Combined progress only: no one's points or per-person numbers.
    client.post(f"/api/nutrition/patients/{P_DAVID}/meals", headers=DAVID,
                json={"meal": "lunch", "items": [{"food_id": "water-bottle", "servings": 4}]})
    t = client.get(f"/api/challenges/patients/{P_MAYA}", headers=MAYA).json()["teams"][0]
    assert t["together"] == {"met": 1, "needed": 14, "percent": 7}
    assert set(t["members"][0]) == {"name", "status"}
    assert "points" not in str({k: v for k, v in t.items() if k != "challenge"})


# --- Rewards ---------------------------------------------------------------------------------------------------------------


def test_rewards_are_fictional_and_redemption_checks_the_balance(client):
    cat = client.get("/api/challenges/catalog", headers=MAYA).json()
    assert "demo" in cat["reward_note"].lower() and "fictional" in cat["reward_note"].lower()
    for r in REWARDS:
        assert any(w in (r["title"] + r["description"]).lower() for w in ("demo", "fictional", "imaginary", "made-up", "pretend"))
    assert client.post(f"/api/challenges/patients/{P_MAYA}/redemptions", headers=MAYA,
                       json={"reward_id": "demo-market"}).status_code == 409     # 250 > 120
    r = client.post(f"/api/challenges/patients/{P_MAYA}/redemptions", headers=MAYA, json={"reward_id": "demo-tree"})
    assert r.status_code == 201
    body = r.json()
    assert body["points"] == 70 and body["redeemed"]["code"].startswith("DEMO-")
    assert [x["reward_id"] for x in body["redemptions"]] == ["demo-tree", "demo-smoothie"]
    assert client.post(f"/api/challenges/patients/{P_MAYA}/redemptions", headers=PARK,
                       json={"reward_id": "demo-tree"}).status_code == 403
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = 'reward_redeemed'").fetchone()["n"] == 1


# --- Access, fairness, front door ------------------------------------------------------------------------------------------


def test_access_and_no_leaderboard(client):
    assert client.get(f"/api/challenges/patients/{P_MAYA}", headers=PARK).status_code == 403
    assert client.post(f"/api/challenges/patients/{P_MAYA}/enrollments", headers=OKAFOR,
                       json={"definition_id": "veg_5_7d"}).status_code == 403
    assert client.get(f"/api/challenges/patients/{P_MAYA}", headers=OKAFOR).status_code == 200
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = 'challenges_viewed'").fetchone()["n"] == 1
    paths = [r.path for r in client.app.routes if getattr(r, "path", "").startswith("/api/challenges")]
    assert not any("leaderboard" in p or "ranking" in p for p in paths)


@pytest.mark.parametrize("text", ["join a challenge", "show me the steps challenge", "how many points do I have? my points"])
def test_challenge_intent(text):
    assert rules_triage([{"role": "user", "content": text}], {"age": 40}).intent == "challenges"
