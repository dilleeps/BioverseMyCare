from datetime import datetime, time, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

from bioverse import vitals_codes
from bioverse.jobs import load_all, run_job
from bioverse.jobs.dispatch_notifications import in_quiet_hours
from bioverse.notify import cancel, notify, patient_user
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA
from bioverse.db.seed import U_MAYA


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def test_welcome_in_inbox(client):
    r = client.get("/api/notifications", headers=MAYA).json()
    assert r["unread"] >= 1
    assert any(n["kind"] == "welcome" for n in r["items"])


def test_inbox_is_per_user_and_hides_future(client):
    with db() as conn:
        notify(conn, user_id=U_MAYA, kind="test", title="Now", dedupe_key="t1")
        notify(conn, user_id=U_MAYA, kind="test", title="Later", dedupe_key="t2",
               due_at=datetime.now(timezone.utc) + timedelta(hours=2))
        assert notify(conn, user_id=U_MAYA, kind="test", title="Dup", dedupe_key="t1") is None
    titles = [n["title"] for n in client.get("/api/notifications", headers=MAYA).json()["items"]]
    assert "Now" in titles and "Later" not in titles and "Dup" not in titles
    assert client.get("/api/notifications", headers=MAYA).json()["upcoming"] == 1
    okafor = [n["title"] for n in client.get("/api/notifications", headers=OKAFOR).json()["items"]]
    assert "Now" not in okafor


def test_mark_read(client):
    items = client.get("/api/notifications", headers=MAYA).json()["items"]
    nid = items[0]["id"]
    assert client.post(f"/api/notifications/{nid}/read", headers=OKAFOR).status_code == 404
    assert client.post(f"/api/notifications/{nid}/read", headers=MAYA).status_code == 200
    client.post("/api/notifications/read-all", headers=MAYA)
    assert client.get("/api/notifications?unread=true", headers=MAYA).json()["unread"] == 0


def test_preferences_roundtrip_and_validation(client):
    bad = client.put("/api/notifications/preferences", headers=MAYA, json={"phone": "12345"})
    assert bad.status_code == 422
    bad = client.put("/api/notifications/preferences", headers=MAYA, json={"channels": {"x": ["pigeon"]}})
    assert bad.status_code == 422
    ok = client.put("/api/notifications/preferences", headers=MAYA, json={
        "email": "maya@example.org", "phone": "+1 (555) 555-0123",
        "channels": {"medication_reminder": ["in_app", "sms"]}, "quiet_start": "22:00", "quiet_end": "07:00",
    })
    assert ok.status_code == 200, ok.text
    assert ok.json()["phone"] == "+15555550123"
    assert client.get("/api/notifications/preferences", headers=MAYA).json()["email"] == "maya@example.org"


def test_quiet_hours():
    utc = timezone.utc
    assert in_quiet_hours(time(22), time(7), "UTC", datetime(2026, 9, 24, 23, 0, tzinfo=utc))
    assert in_quiet_hours(time(22), time(7), "UTC", datetime(2026, 9, 24, 6, 59, tzinfo=utc))
    assert not in_quiet_hours(time(22), time(7), "UTC", datetime(2026, 9, 24, 12, 0, tzinfo=utc))
    assert not in_quiet_hours(None, None, "UTC", datetime(2026, 9, 24, 23, 0, tzinfo=utc))


def test_dispatch_marks_sent_and_skips_unconfigured_channels(client):
    with db() as conn:
        notify(conn, user_id=U_MAYA, kind="test", title="Email me", channels=["in_app", "email", "sms"],
               dedupe_key="d1")
    with db() as conn:
        result = run_job(conn, "dispatch_notifications")
        assert result["status"] == "succeeded"
        row = conn.execute("SELECT status, delivery FROM notifications WHERE dedupe_key = 'd1'").fetchone()
    assert row["status"] == "sent"
    assert row["delivery"]["email"]["status"] == "skipped"
    assert row["delivery"]["sms"]["status"] == "skipped"


def test_dispatch_holds_non_urgent_in_quiet_hours(client):
    with db() as conn:
        conn.execute(
            "INSERT INTO notification_preferences (user_id, quiet_start, quiet_end, timezone) "
            "VALUES (%s, '00:00', '23:59:59.999', 'UTC')", (U_MAYA,))
        notify(conn, user_id=U_MAYA, kind="test", title="Routine", dedupe_key="q1")
        notify(conn, user_id=U_MAYA, kind="test", title="Urgent", priority="urgent", dedupe_key="q2")
    with db() as conn:
        run_job(conn, "dispatch_notifications")
        status = {r["dedupe_key"]: r["status"] for r in conn.execute(
            "SELECT dedupe_key, status FROM notifications WHERE dedupe_key IN ('q1', 'q2')")}
    assert status == {"q1": "pending", "q2": "sent"}


def test_cancel_and_patient_user(client):
    with db() as conn:
        assert patient_user(conn, P_MAYA) == U_MAYA
        notify(conn, user_id=U_MAYA, kind="test", title="A", dedupe_key="rx:1:a",
               due_at=datetime.now(timezone.utc) + timedelta(hours=1))
        notify(conn, user_id=U_MAYA, kind="test", title="B", dedupe_key="rx:1:b",
               due_at=datetime.now(timezone.utc) + timedelta(hours=1))
        assert cancel(conn, user_id=U_MAYA, dedupe_prefix="rx:1:") == 2


def test_admin_jobs(client):
    assert client.get("/api/admin/jobs", headers=MAYA).status_code == 403
    listing = client.get("/api/admin/jobs", headers=ADMIN).json()
    assert any(j["name"] == "dispatch_notifications" for j in listing["jobs"])
    ran = client.post("/api/admin/jobs/run", headers=ADMIN).json()["results"]
    assert {r["name"] for r in ran} == set(load_all())
    # Nothing is due straight after a run.
    assert client.post("/api/admin/jobs/run", headers=ADMIN).json()["results"] == []
    assert client.post("/api/admin/jobs/nope/run", headers=ADMIN).status_code == 404
    history = client.get("/api/admin/jobs", headers=ADMIN).json()["history"]
    assert history and history[0]["status"] == "succeeded"


def test_vital_codes_interpret():
    bp = vitals_codes.CODES["bp_systolic"]
    assert vitals_codes.interpret(bp, 120) == "N"
    assert vitals_codes.interpret(bp, 145) == "H"
    assert vitals_codes.interpret(bp, 185) == "HH"
    assert vitals_codes.interpret(vitals_codes.CODES["spo2"], 88) == "LL"
    assert vitals_codes.BY_LOINC["8480-6"] is bp


def test_observation_accepts_vital_signs(client):
    with db() as conn:
        conn.execute(
            """
            INSERT INTO observations (patient_id, loinc_code, display, value, unit, interpretation, effective_at,
                                      category, source)
            VALUES (%s, '8480-6', 'Systolic blood pressure', 185, 'mm[Hg]', 'HH', now(), 'vital-signs', 'device')
            """,
            (P_MAYA,),
        )
