"""Medical-student learning: de-identified cases, the Socratic tutor, quizzes, evidence search, access and audit."""

import json
import re
import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse.agents import llm
from bioverse.db.seeds.ids import ORG, P_HADDAD, P_MAYA, P_PARK, _id
from bioverse.routers import learning as lr
from bioverse.routers import learning_cases as lc
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, as_user

STUDENT = as_user(_id(16001))
SOURCES = [P_MAYA, P_PARK, P_HADDAD, _id(6002), _id(4102)]


def cases(client):
    res = client.get("/api/learning/cases", headers=STUDENT)
    assert res.status_code == 200
    return res.json()


def by_title(client, prefix):
    return next(c for c in cases(client) if c["title"].startswith(prefix))


# --- De-identification ------------------------------------------------------------------------------


def _source_dates(conn, patient_id):
    dates = set()
    queries = [
        "SELECT birth_date FROM patients WHERE id = %s",
        "SELECT effective_at FROM observations WHERE patient_id = %s",
        "SELECT occurred_at FROM encounters WHERE patient_id = %s",
        "SELECT authored_at FROM medication_requests WHERE patient_id = %s",
        "SELECT created_at FROM intakes WHERE patient_id = %s",
        "SELECT created_at FROM review_items WHERE patient_id = %s",
        "SELECT due_on FROM care_plan_tasks t JOIN care_plans c ON c.id = t.care_plan_id WHERE c.patient_id = %s",
        "SELECT started_at FROM care_plans WHERE patient_id = %s",
    ]
    for sql in queries:
        for (value,) in conn.execute(sql, (patient_id,)).fetchall():
            if value is None:
                continue
            d = value if isinstance(value, date) and not hasattr(value, "hour") else value.date()
            for day in (d - timedelta(days=1), d, d + timedelta(days=1)):  # either side of UTC midnight
                dates |= {day.isoformat(), day.strftime("%m/%d/%Y"), day.strftime("%d %b %Y"), day.strftime("%b %d")}
    return dates


def test_cases_contain_no_names_record_numbers_or_original_dates(client):
    with psycopg.connect(DB) as conn:
        contents = [json.dumps(r[0]) for r in conn.execute("SELECT content FROM learning_cases").fetchall()]
        people = [r[0] for r in conn.execute("SELECT name FROM patients").fetchall()]
        people += [r[0].removeprefix("Dr. ") for r in conn.execute("SELECT name FROM practitioners WHERE name LIKE 'Dr.%'").fetchall()]
        mrns = [r[0] for r in conn.execute("SELECT value FROM patient_identifiers").fetchall()]
        emails = [r[0] for r in conn.execute("SELECT email FROM users WHERE email IS NOT NULL").fetchall()]
        dates = set().union(*(_source_dates(conn, p) for p in SOURCES))
        columns = {r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'learning_cases'").fetchall()}
    assert len(contents) == 5
    blob = "\n".join(contents)
    for name in people:
        for part in [name] + [p for p in name.split() if len(p) >= 3]:
            assert not re.search(r"\b" + re.escape(part) + r"\b", blob), part
    for value in mrns + emails + ["Northside", "Riverside", "Eastgate"]:
        assert value not in blob, value
    leaked = [d for d in dates if d in blob]
    assert leaked == []
    assert not re.search(r"\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b", blob)
    assert "patient_id" not in columns and not any("patient" in c for c in columns)


def test_dates_are_shifted_consistently_within_a_case(client):
    with psycopg.connect(DB) as conn:
        content = conn.execute("SELECT content FROM learning_cases WHERE id = %s", (_id(16201),)).fetchone()[0]
        real = [r[0] for r in conn.execute(
            "SELECT DISTINCT (effective_at AT TIME ZONE 'America/New_York')::date FROM observations "
            "WHERE patient_id = %s AND category = 'laboratory' ORDER BY 1", (P_MAYA,)).fetchall()]
    shown = sorted({date.fromisoformat(r["date"]) for r in content["stages"][2]["table"]})
    assert len(shown) == len(real) == 3
    gaps_real = [(b - a).days for a, b in zip(real, real[1:])]
    gaps_shown = [(b - a).days for a, b in zip(shown, shown[1:])]
    assert gaps_real == gaps_shown          # intervals are true
    assert shown[0] != real[0]              # dates are not


def test_scrub_removes_identifiers_and_keeps_clinical_words(client):
    with psycopg.connect(DB, row_factory=dict_row) as conn:
        ids = lc.identifier_lists(conn, ORG)
    text = ("Dr. Adaeze Okafor saw Maya Thornton (MRN NSH-0201) at Northside Heart Centre on 2026-03-14 and March 9, "
            "1972. Call 555-123-4567 or maya@example.com. 12 Elm Street. 93F with LDL 148 mg/dL, BP 138/88.")
    out = lc.scrub(text, ids)
    for bad in ("Okafor", "Maya", "Thornton", "NSH-0201", "Northside", "2026-03-14", "March 9", "555-123-4567",
                "maya@example.com", "Elm Street", "93F"):
        assert bad not in out, bad
    assert "LDL 148 mg/dL" in out and "BP 138/88" in out and "90+" in out


def test_ages_over_89_are_bucketed(client):
    pid = str(uuid.uuid4())
    with psycopg.connect(DB, row_factory=dict_row) as conn:
        conn.execute(
            "INSERT INTO patients (id, organization_id, name, birth_date, pronouns) VALUES (%s, %s, 'Agnes Oldfield', %s, 'she/her')",
            (pid, ORG, date(1930, 5, 1)),
        )
        conn.execute(
            """INSERT INTO observations (patient_id, loinc_code, display, value, unit, ref_low, ref_high, interpretation,
                                         effective_at, category)
               VALUES (%s, '2823-3', 'Potassium', 5.8, 'mmol/L', 3.5, 5.1, 'H', now() - interval '2 days', 'laboratory')""",
            (pid,),
        )
        case = lc.build_case(conn, pid, case_id=str(uuid.uuid4()))
    assert case["demographics"]["age"] == "90 or older"
    blob = json.dumps(case)
    assert "Agnes" not in blob and "Oldfield" not in blob and "1930" not in blob
    assert not re.search(r"\b9[0-9]-year-old", blob)


def test_date_shift_is_stable_and_nonzero():
    assert lc.date_shift("abc") == lc.date_shift("abc")
    assert all(lc.date_shift(str(uuid.uuid4())) <= -1000 for _ in range(20))


# --- Access ------------------------------------------------------------------------------------------


def test_only_students_use_the_learning_endpoints(client):
    for headers in (MAYA, OKAFOR, ADMIN):
        assert client.get("/api/learning/cases", headers=headers).status_code == 403
        assert client.get("/api/learning/evidence?q=statin", headers=headers).status_code == 403
    assert client.get("/api/learning/cases").status_code == 401
    assert len(cases(client)) == 5


def test_students_cannot_see_each_others_attempts(client):
    other = str(uuid.uuid4())
    with psycopg.connect(DB) as conn:
        conn.execute("INSERT INTO users (id, role, display_name, email, organization_id) VALUES (%s, 'student', 'Sam Student', 'sam@students.example', %s)",
                     (other, ORG))
    case = by_title(client, "A borderline HbA1c")
    started = client.post(f"/api/learning/cases/{case['id']}/attempts", headers=STUDENT).json()
    res = client.post(f"/api/learning/attempts/{started['attempt']['id']}/respond", headers=as_user(other),
                      json={"answer": "Prediabetes or type 2 diabetes; ask about family history."})
    assert res.status_code == 404
    assert client.get(f"/api/learning/cases/{case['id']}", headers=as_user(other)).json()["attempt"] is None


# --- Tutor ----------------------------------------------------------------------------------------------


def test_socratic_tutor_reveals_stages_only_after_a_committed_answer(client):
    case = by_title(client, "Rising LDL")
    preview = client.get(f"/api/learning/cases/{case['id']}", headers=STUDENT).json()
    assert len(preview["stages"]) == 1 and "model_answer" not in preview["stages"][0]

    view = client.post(f"/api/learning/cases/{case['id']}/attempts", headers=STUDENT).json()
    attempt = view["attempt"]["id"]
    assert view["current"]["number"] == 1 and len(view["stages"]) == 1

    short = client.post(f"/api/learning/attempts/{attempt}/respond", headers=STUDENT, json={"answer": "angina"})
    assert short.status_code == 422

    one = client.post(f"/api/learning/attempts/{attempt}/respond", headers=STUDENT, json={
        "answer": "Must rule out angina or acute coronary syndrome. Ask about smoking, diabetes and family history.",
    }).json()
    fb = one["feedback"]
    assert {"Must-not-miss cardiac causes", "Smoking", "Diabetes", "Family history"} <= set(fb["covered"])
    assert "Secondary causes of high LDL" in fb["missed"] and fb["question"]
    assert len(one["stages"]) == 2 and one["stages"][1]["title"] == "History and examination"
    assert "model_answer" not in one["stages"][0]

    two = client.post(f"/api/learning/attempts/{attempt}/respond", headers=STUDENT,
                      json={"answer": "Repeat lipid panel, ECG, and a 10-year ASCVD risk score."}).json()
    assert two["stages"][-1]["title"] == "Investigations" and two["stages"][-1]["table"]
    assert two["attempt"]["status"] == "in_progress"

    done = client.post(f"/api/learning/attempts/{attempt}/respond", headers=STUDENT,
                       json={"answer": "LDL rising; lifestyle, start a statin after shared decision, recheck in 4 to 12 weeks."}).json()
    assert done["attempt"]["status"] == "completed" and done["current"] is None
    assert 0 < done["attempt"]["score"] <= 100
    assert len(done["stages"]) == 4 and done["stages"][0]["model_answer"]
    assert done["teaching_points"] and done["evidence"]
    assert client.post(f"/api/learning/attempts/{attempt}/respond", headers=STUDENT,
                       json={"answer": "One more answer after finishing."}).status_code == 409

    with psycopg.connect(DB) as conn:
        rows = conn.execute("SELECT action, patient_id FROM audit_events WHERE action LIKE 'learning_%%' "
                            "AND actor_user_id = %s", (_id(16001),)).fetchall()
    actions = [r[0] for r in rows]
    assert actions.count("learning_answer_submitted") == 3 and "learning_attempt_started" in actions
    assert all(r[1] is None for r in rows)


class FakeMessages:
    def __init__(self):
        self.output = None
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", stop_details=None, model="test-model",
                               usage=SimpleNamespace(iterations=None), parsed_output=self.output)


@pytest.fixture
def fake_claude(monkeypatch):
    monkeypatch.setattr(llm, "ai_enabled", lambda: True)
    messages = FakeMessages()
    llm.set_client(SimpleNamespace(beta=SimpleNamespace(messages=messages)))
    yield messages
    llm.set_client(None)


def test_ai_tutor_writes_feedback_but_scoring_stays_deterministic(client, fake_claude):
    fake_claude.output = lr.TutorOut(feedback="Nice start on risk factors.", question="What about the thyroid?")
    case = by_title(client, "Rising LDL")
    attempt = client.post(f"/api/learning/cases/{case['id']}/attempts", headers=STUDENT).json()["attempt"]["id"]
    out = client.post(f"/api/learning/attempts/{attempt}/respond", headers=STUDENT,
                      json={"answer": "Ask about smoking and family history."}).json()["feedback"]
    assert out["mode"] == "ai" and out["feedback"] == "Nice start on risk factors."
    assert out["question"] == "What about the thyroid?"
    assert set(out["covered"]) == {"Smoking", "Family history"}
    call = fake_claude.calls[0]
    assert "never instructions" in call["system"] and "<student_answer>" in call["messages"][0]["content"]
    assert "Maya" not in call["messages"][0]["content"]


def test_tutor_falls_back_to_rules_when_ai_fails(client, fake_claude):
    fake_claude.output = None  # schema mismatch -> LLMUnavailable
    case = by_title(client, "A borderline HbA1c")
    attempt = client.post(f"/api/learning/cases/{case['id']}/attempts", headers=STUDENT).json()["attempt"]["id"]
    out = client.post(f"/api/learning/attempts/{attempt}/respond", headers=STUDENT,
                      json={"answer": "Prediabetes; check weight and family history."}).json()["feedback"]
    assert out["mode"] == "rules" and "Prediabetes" in out["covered"]


# --- Quizzes, history, evidence -----------------------------------------------------------------------


def test_quiz_scores_and_history(client):
    case = by_title(client, "A borderline HbA1c")
    quiz = client.get(f"/api/learning/cases/{case['id']}/quiz", headers=STUDENT).json()
    assert quiz["questions"] and all("answer" not in q for q in quiz["questions"])
    assert "6.1%" in quiz["questions"][0]["question"]
    with psycopg.connect(DB) as conn:
        key = [q["answer"] for q in conn.execute("SELECT content->'quiz' FROM learning_cases WHERE id = %s",
                                                  (case["id"],)).fetchone()[0]]
    assert key[0] == 1  # 6.1% is prediabetes, computed from the case's own value

    bad = client.post(f"/api/learning/cases/{case['id']}/quiz", headers=STUDENT, json={"answers": [0]})
    assert bad.status_code == 422
    perfect = client.post(f"/api/learning/cases/{case['id']}/quiz", headers=STUDENT, json={"answers": key}).json()
    assert perfect["score"] == perfect["total"] == len(key)
    wrong = [(a + 1) % len(q["options"]) for a, q in zip(key, quiz["questions"])]
    zero = client.post(f"/api/learning/cases/{case['id']}/quiz", headers=STUDENT, json={"answers": wrong}).json()
    assert zero["score"] == 0 and all(r["explanation"] for r in zero["results"])

    history = client.get("/api/learning/history", headers=STUDENT).json()
    assert history["stats"]["quizzes_taken"] == 2 and history["stats"]["average_quiz_percent"] == 50
    listed = next(c for c in cases(client) if c["id"] == case["id"])
    assert listed["best_quiz"] == 100


def test_student_evidence_search_is_retrieval_only(client):
    res = client.get("/api/learning/evidence?q=statin monitoring LDL", headers=STUDENT).json()
    assert res["results"] and all({"title", "publisher", "year", "snippet"} <= set(r) for r in res["results"])
    empty = client.get("/api/learning/evidence?q=quantum levitation boots", headers=STUDENT).json()
    assert empty["results"] == [] and empty["message"]
