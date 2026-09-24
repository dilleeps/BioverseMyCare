"""Mental wellbeing: PHQ-9 / GAD-7 scoring and bands, the item-9 crisis path, journal screening, reminders,
front-door routing through the orchestrator, access control and audit."""

from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse import mind_escalation
from bioverse.jobs import run_job
from bioverse.mind_instruments import INSTRUMENTS, band, score
from tests.conftest import DB, MAYA, OKAFOR, P_MAYA, PARK


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def submit(client, instrument, items, headers=MAYA, **extra):
    return client.post(f"/api/mind/patients/{P_MAYA}/responses", headers=headers,
                       json={"instrument": instrument, "items": items, **extra})


# --- Scoring --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("total,expected", [
    (0, "minimal"), (4, "minimal"), (5, "mild"), (9, "mild"), (10, "moderate"), (14, "moderate"),
    (15, "moderately_severe"), (19, "moderately_severe"), (20, "severe"), (27, "severe"),
])
def test_phq9_bands_at_every_edge(total, expected):
    assert band("phq9", total)[0] == expected


@pytest.mark.parametrize("total,expected", [
    (0, "minimal"), (4, "minimal"), (5, "mild"), (9, "mild"), (10, "moderate"), (14, "moderate"),
    (15, "severe"), (21, "severe"),
])
def test_gad7_bands_at_every_edge(total, expected):
    assert band("gad7", total)[0] == expected


def test_scoring_totals_and_validation():
    assert score("phq9", [3] * 9)["total"] == 27
    assert score("gad7", [3] * 7)["total"] == 21
    r = score("phq9", [2, 2, 2, 2, 2, 0, 0, 0, 0])
    assert (r["total"], r["severity"], r["needs_review"], r["crisis"]) == (10, "moderate", True, False)
    assert score("gad7", [1, 1, 1, 1, 1, 0, 0])["needs_review"] is False
    for bad in ([0] * 8, [0] * 10, [0] * 8 + [4], [0] * 8 + [-1], [True] + [0] * 8):
        with pytest.raises(ValueError):
            score("phq9", bad)


def test_validated_wording_and_codes():
    phq, gad = INSTRUMENTS["phq9"], INSTRUMENTS["gad7"]
    assert phq["items"][8] == "Thoughts that you would be better off dead or of hurting yourself in some way"
    assert phq["items"][0] == "Little interest or pleasure in doing things"
    assert gad["items"][1] == "Not being able to stop or control worrying"
    assert [o["label"] for o in phq["options"]] == ["Not at all", "Several days", "More than half the days", "Nearly every day"]
    assert phq["stem"].startswith("Over the last 2 weeks")
    assert (phq["loinc"], gad["loinc"]) == ("44261-6", "70274-6")
    assert len(phq["items"]) == 9 and len(gad["items"]) == 7


# --- Crisis path ------------------------------------------------------------------------------------------------


def test_item9_above_zero_is_a_crisis_even_with_a_minimal_total(client):
    r = submit(client, "phq9", [0, 0, 0, 0, 0, 0, 0, 0, 1])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total"] == 1 and body["severity"] == "minimal"
    crisis = body["crisis"]
    assert crisis["crisis_line"] == "988" and crisis["emergency_number"] == "911"
    assert "call or text 988" in crisis["message"].lower() and "911" in crisis["message"]
    assert crisis["care_team_notified"] is True

    with db() as conn:
        item = conn.execute(
            "SELECT kind, priority, link, practitioner_id::text, ref_id::text FROM review_items WHERE kind = 'mind_crisis'"
        ).fetchone()
        assert item["priority"] == "urgent" and item["link"] == f"/clinician/mind/{P_MAYA}"
        assert item["ref_id"] == body["id"]
        note = conn.execute(
            """
            SELECT n.priority, n.title, n.channels FROM notifications n JOIN practitioners pr ON pr.user_id = n.user_id
            WHERE n.kind = 'wellbeing_review' AND pr.id::text = %s
            """,
            (item["practitioner_id"],),
        ).fetchone()
        assert note["priority"] == "urgent" and "sms" in note["channels"]
        assert "item 9" not in note["title"].lower() and "suicid" not in note["title"].lower()  # no clinical detail out of app
        obs = conn.execute(
            "SELECT category, value, loinc_code FROM observations WHERE patient_id = %s AND loinc_code = '44261-6' "
            "ORDER BY effective_at DESC LIMIT 1", (P_MAYA,)).fetchone()
        assert obs == {"category": "survey", "value": 1, "loinc_code": "44261-6"}
        assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = 'wellbeing_review_raised'").fetchone()["n"] == 1

    # The clinician sees it at the top of the Mood & anxiety view and in the brief.
    view = client.get(f"/api/mind/patients/{P_MAYA}/results", headers=OKAFOR).json()
    assert view["open_items"][0]["priority"] == "urgent"
    brief = client.get(f"/api/clinician/patients/{P_MAYA}/brief", headers=OKAFOR).json()
    assert "PHQ-9 item 9 positive" in brief["attention_flags"]


def test_support_message_is_never_blocked_when_the_alert_fails(client, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("queue down")

    monkeypatch.setattr(mind_escalation, "care_team_practitioner", broken)
    r = submit(client, "phq9", [1, 1, 1, 1, 1, 1, 1, 1, 3])
    assert r.status_code == 201
    assert r.json()["crisis"]["crisis_line"] == "988"
    assert r.json()["crisis"]["care_team_notified"] is False
    # The response itself is still stored.
    with db() as conn:
        assert conn.execute("SELECT crisis FROM mind_questionnaire_responses WHERE id = %s", (r.json()["id"],)).fetchone()["crisis"]


def test_support_endpoint_needs_no_sign_in(client):
    r = client.get("/api/mind/support")
    assert r.status_code == 200 and r.json()["crisis"]["crisis_line"] == "988"


def test_moderate_score_raises_a_routine_review_and_mild_does_not(client):
    mild = submit(client, "gad7", [1, 1, 1, 1, 1, 0, 0]).json()
    assert mild["severity"] == "mild" and mild["review_requested"] is False and mild["crisis"] is None
    moderate = submit(client, "gad7", [2, 2, 2, 2, 2, 0, 0], difficulty="Very difficult").json()
    assert moderate["severity"] == "moderate" and moderate["review_requested"] is True
    with db() as conn:
        rows = conn.execute("SELECT kind, priority FROM review_items WHERE kind LIKE 'mind%%'").fetchall()
    assert rows == [{"kind": "mind_score", "priority": "routine"}]

    item_id = client.get(f"/api/mind/patients/{P_MAYA}/results", headers=OKAFOR).json()["open_items"][0]["id"]
    # Linked items must be decided in the module's own screen, not acknowledged away in the core queue.
    assert client.post(f"/api/clinician/review-items/{item_id}/resolve", headers=OKAFOR,
                       json={"action": "acknowledge"}).status_code == 409
    done = client.post(f"/api/mind/review-items/{item_id}/resolve", headers=OKAFOR, json={"note": "Called, booked review"})
    assert done.status_code == 200
    assert client.get(f"/api/mind/patients/{P_MAYA}/results", headers=OKAFOR).json()["open_items"] == []


def test_bad_submissions_are_rejected(client):
    assert submit(client, "phq9", [0] * 7).status_code == 422
    assert submit(client, "gad7", [0, 0, 0, 0, 0, 0, 5]).status_code == 422
    assert submit(client, "phq9", [0] * 9, difficulty="Kind of").status_code == 422


# --- Journal ---------------------------------------------------------------------------------------------------


def test_journal_crisis_language_shows_support_and_alerts(client):
    r = client.post(f"/api/mind/patients/{P_MAYA}/journal", headers=MAYA,
                    json={"mood": 1, "tags": ["stress"], "note": "Honestly I don't want to be here anymore"})
    assert r.status_code == 201
    assert r.json()["crisis"]["crisis_line"] == "988"
    with db() as conn:
        assert conn.execute("SELECT priority FROM review_items WHERE kind = 'mind_journal'").fetchone()["priority"] == "urgent"
        assert conn.execute("SELECT red_flag_level FROM mind_journal_entries WHERE id = %s",
                            (r.json()["id"],)).fetchone()["red_flag_level"] == "crisis"


def test_journal_notes_stay_private_unless_shared(client):
    client.post(f"/api/mind/patients/{P_MAYA}/journal", headers=MAYA, json={"mood": 3, "note": "private thought"})
    client.post(f"/api/mind/patients/{P_MAYA}/journal", headers=MAYA, json={"mood": 4, "note": "ok to share", "shared": True})
    seen = client.get(f"/api/mind/patients/{P_MAYA}/journal", headers=OKAFOR).json()["entries"]
    notes = {e["note"] for e in seen}
    assert "ok to share" in notes and "private thought" not in notes
    assert {e["mood"] for e in seen} >= {3, 4}
    mine = client.get(f"/api/mind/patients/{P_MAYA}/journal", headers=MAYA).json()["entries"]
    assert "private thought" in {e["note"] for e in mine}


# --- Access and audit ------------------------------------------------------------------------------------------------


def test_access_control_and_audit(client):
    assert client.get(f"/api/mind/patients/{P_MAYA}/results", headers=PARK).status_code == 403
    assert client.post(f"/api/mind/patients/{P_MAYA}/journal", headers=PARK, json={"mood": 3}).status_code == 403
    assert submit(client, "phq9", [0] * 9, headers=OKAFOR).status_code == 403
    assert client.get(f"/api/mind/patients/{P_MAYA}/results").status_code == 401
    patient_view = client.get(f"/api/mind/patients/{P_MAYA}/results", headers=MAYA).json()
    assert "open_items" not in patient_view and "responses" not in patient_view["instruments"]["phq9"]
    client.get(f"/api/mind/patients/{P_MAYA}/results", headers=OKAFOR)
    with db() as conn:
        row = conn.execute(
            "SELECT patient_id::text FROM audit_events WHERE action = 'mind_results_viewed' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["patient_id"] == P_MAYA


# --- Front door --------------------------------------------------------------------------------------------------


def start(client):
    return client.post("/api/conversations", headers=MAYA).json()["id"]


def say(client, cid, text):
    r = client.post(f"/api/conversations/{cid}/messages", headers=MAYA, json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()["messages"][-1]["payload"]


@pytest.mark.parametrize("text", ["Can I check my mood?", "I'd like to take an anxiety test", "depression screening please"])
def test_mood_intents_route_to_mind(client, text):
    payload = say(client, start(client), text)
    assert payload == {"kind": "link", "to": "/mind", "label": "Open mood & mind"}


def test_mood_intent_never_bypasses_crisis_screening(client):
    payload = say(client, start(client), "check my mood, I don't want to be alive anymore")
    assert payload["kind"] == "emergency" and payload["level"] == "crisis" and payload["crisis_line"] == "988"
    payload = say(client, start(client), "anxiety test. I keep thinking about suicide")
    assert payload["kind"] == "emergency" and payload["crisis_line"] == "988"
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM review_items WHERE kind = 'red_flag' AND priority = 'urgent'"
                            ).fetchone()["n"] >= 2


# --- Reminders, seed, timeline -----------------------------------------------------------------------------------------


def test_retest_reminders_are_opt_in_and_idempotent(client):
    now = datetime.now(timezone.utc)
    with db() as conn:
        assert run_job(conn, "mind_retest_reminders", now)["detail"] == {"reminders": 0}   # Maya's last check was 2 days ago
        later = now + timedelta(weeks=5)
        assert run_job(conn, "mind_retest_reminders", later)["detail"] == {"reminders": 2}
        assert run_job(conn, "mind_retest_reminders", later)["detail"] == {"reminders": 0}
        assert conn.execute("SELECT count(*) AS n FROM notifications WHERE kind = 'mind_retest'").fetchone()["n"] == 2
    # Opting out stops them.
    client.put(f"/api/mind/patients/{P_MAYA}/preferences", headers=MAYA, json={"retest_reminders": False, "retest_weeks": 2})
    with db() as conn:
        assert run_job(conn, "mind_retest_reminders", now + timedelta(weeks=9))["detail"] == {"reminders": 0}
    assert client.put(f"/api/mind/patients/{P_MAYA}/preferences", headers=MAYA,
                      json={"retest_reminders": True, "retest_weeks": 6}).status_code == 422


def test_seeded_results_are_mild_and_on_the_timeline(client):
    view = client.get(f"/api/mind/patients/{P_MAYA}/results", headers=MAYA).json()
    assert [h["severity"] for h in view["instruments"]["phq9"]["history"]] == ["mild", "mild"]
    assert [h["severity"] for h in view["instruments"]["gad7"]["history"]] == ["mild", "mild"]
    brief = client.get(f"/api/clinician/patients/{P_MAYA}/brief", headers=OKAFOR).json()
    assert any(b["text"].startswith("PHQ-9 5/27, mild") for b in brief["bullets"])
    timeline = client.get(f"/api/clinician/patients/{P_MAYA}/brief", headers=OKAFOR).json()["timeline"]
    assert any(e["type"] == "questionnaire" for e in timeline)
