"""Research & Clinical Trials: deterministic eligibility, consent gating, the interest pipeline."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse import trials
from bioverse.agents import llm
from bioverse.agents.triage import rules_triage
from bioverse.db.seed import seed
from bioverse.db.seeds.ids import _id
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, P_PARK, PARK

LOWER_LDL, HOME_BP, PREVENT, SWITCH, KITCHEN = (_id(n) for n in (7101, 7102, 7103, 7104, 7105))
JUN_INTEREST = _id(7201)


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def by_id(criteria):
    return {c["id"]: c for c in criteria}


def opt_in(client, headers=MAYA, granted=True):
    r = client.put("/api/research/consent", headers=headers, json={"granted": granted})
    assert r.status_code == 200, r.text
    return r.json()


def brief_texts(client, patient_id):
    return [b["text"] for b in client.get(f"/api/clinician/patients/{patient_id}/brief", headers=OKAFOR).json()["bullets"]]


# --- Eligibility engine ----------------------------------------------------------------------------


def test_engine_per_criterion_on_seeded_patients(client):
    with db() as conn:
        maya = {m["study"]["id"]: m for m in trials.matches_for(conn, P_MAYA, include_not_eligible=True)}
        jun = {m["study"]["id"]: m for m in trials.matches_for(conn, P_PARK, include_not_eligible=True)}

    assert KITCHEN not in maya, "completed studies are never matched"

    ldl = maya[LOWER_LDL]
    assert ldl["status"] == "eligible"
    c = by_id(ldl["criteria"])
    assert c["age"]["outcome"] == "pass" and c["age"]["reason"] == "Age 54"
    assert c["ldl"]["outcome"] == "pass" and "148 mg/dL" in c["ldl"]["reason"]
    # She was only just prescribed a statin, so the "statin for more than 6 months" exclusion does not apply.
    assert c["long_statin"]["outcome"] == "pass" and "fewer than 180 days" in c["long_statin"]["reason"]

    bp = maya[HOME_BP]
    assert bp["status"] == "possibly_eligible"
    assert by_id(bp["criteria"])["sbp"]["outcome"] == "unknown"
    assert by_id(bp["criteria"])["pregnancy"]["outcome"] == "unknown"

    assert maya[PREVENT]["status"] == "not_eligible"
    assert by_id(maya[PREVENT]["criteria"])["a1c"]["outcome"] == "fail"
    assert maya[SWITCH]["status"] == "not_eligible"
    assert by_id(maya[SWITCH]["criteria"])["on_statin"]["outcome"] == "fail"

    prevent = jun[PREVENT]
    assert prevent["status"] == "eligible"
    assert by_id(prevent["criteria"])["a1c"]["outcome"] == "pass"
    assert by_id(prevent["criteria"])["diabetes_meds"]["outcome"] == "pass"
    assert jun[LOWER_LDL]["status"] == "not_eligible"
    assert by_id(jun[LOWER_LDL]["criteria"])["age"]["outcome"] == "fail"


def test_engine_exclusions_and_boundaries_without_a_database():
    study = {"eligibility": {
        "age": {"min": 45, "max": 75}, "sex": "any",
        "include": [{"id": "ldl", "kind": "lab", "loinc": "13457-7", "min": 130, "within_days": 365,
                     "if_missing": "fail", "label": "LDL >= 130"}],
        "exclude": [{"id": "long_statin", "kind": "medication", "match": "statin", "min_days": 180,
                     "label": "Statin > 6 months"}],
    }}
    now = datetime.now(timezone.utc)

    def record(age=60, ldl=130, statin_days=None, ldl_age_days=10):
        obs = {"13457-7": [{"display": "LDL cholesterol", "value": ldl, "unit": "mg/dL",
                            "effective_at": now - timedelta(days=ldl_age_days)}]} if ldl is not None else {}
        meds = [] if statin_days is None else [{"name": "Rosuvastatin 10 mg", "days_on": statin_days,
                                                "started_on": date.today() - timedelta(days=statin_days),
                                                "marked_started": True}]
        return {"age": age, "observations": obs, "medications": meds}

    assert trials.evaluate(study, record())["status"] == "eligible"  # 130 is inclusive
    assert trials.evaluate(study, record(ldl=129))["status"] == "not_eligible"
    assert trials.evaluate(study, record(age=76))["status"] == "not_eligible"
    assert trials.evaluate(study, record(ldl=None))["status"] == "not_eligible"
    assert trials.evaluate(study, record(ldl_age_days=400))["status"] == "not_eligible"  # too old to count
    assert trials.evaluate(study, record(statin_days=179))["status"] == "eligible"
    out = trials.evaluate(study, record(statin_days=200))
    assert out["status"] == "not_eligible"
    assert by_id(out["criteria"])["long_statin"]["outcome"] == "fail"
    study["eligibility"]["include"][0]["if_missing"] = "unknown"
    assert trials.evaluate(study, record(ldl=None))["status"] == "possibly_eligible"
    study["eligibility"]["sex"] = "female"
    assert trials.evaluate(study, record())["status"] == "possibly_eligible"  # sex is not recorded


# --- Consent gating --------------------------------------------------------------------------------


def test_browsing_needs_no_consent_but_matching_does(client):
    studies = client.get("/api/research/studies", headers=MAYA).json()
    assert len(studies) == 5
    assert all(s["title"].startswith("Demo study") and s["is_demo"] for s in studies)
    assert "eligibility" not in studies[0] and studies[0]["who_can_join"]

    me = client.get("/api/research/me", headers=MAYA).json()
    assert me["consent"] == {"granted": False, "status": "not_decided", "updated_at": None}
    assert me["matches"] is None
    detail = client.get(f"/api/research/studies/{LOWER_LDL}", headers=MAYA).json()
    assert detail["match"] is None

    # Clinicians never see matches for a patient who has not opted in.
    coord = client.get("/api/research/coordinator", headers=OKAFOR).json()
    assert P_MAYA not in [p["patient"]["id"] for p in coord["patients"]]
    assert not any("research" in t.lower() for t in brief_texts(client, P_MAYA))

    r = client.post(f"/api/research/studies/{LOWER_LDL}/interest", headers=MAYA)
    assert r.status_code == 403


def test_opting_in_shows_matches_to_patient_and_clinician(client):
    state = opt_in(client)
    assert state["granted"] is True
    me = client.get("/api/research/me", headers=MAYA).json()
    assert [(m["study"]["short_title"], m["status"]) for m in me["matches"]] == [
        ("LOWER-LDL", "eligible"), ("HOME-BP", "possibly_eligible"),
    ]
    detail = client.get(f"/api/research/studies/{LOWER_LDL}", headers=MAYA).json()
    assert detail["match"]["status"] == "eligible"

    coord = client.get("/api/research/coordinator", headers=OKAFOR).json()
    maya = next(p for p in coord["patients"] if p["patient"]["id"] == P_MAYA)
    assert [m["short_title"] for m in maya["matches"]] == ["LOWER-LDL", "HOME-BP"]
    assert "Consented to research; matches 2 studies (LOWER-LDL, HOME-BP)." in brief_texts(client, P_MAYA)

    with db() as conn:
        rows = conn.execute(
            "SELECT action FROM audit_events WHERE patient_id = %s AND action IN ('consent_granted', 'research_pipeline_viewed')",
            (P_MAYA,),
        ).fetchall()
    assert {r["action"] for r in rows} == {"consent_granted", "research_pipeline_viewed"}


def test_revoking_consent_hides_matches_and_pauses_contact(client):
    opt_in(client)
    interest = client.post(f"/api/research/studies/{LOWER_LDL}/interest", headers=MAYA).json()
    state = opt_in(client, granted=False)
    assert state == {**state, "granted": False, "status": "revoked"}

    me = client.get("/api/research/me", headers=MAYA).json()
    assert me["matches"] is None
    assert me["interests"][0]["contact_permitted"] is False

    coord = client.get("/api/research/coordinator", headers=OKAFOR).json()
    assert P_MAYA not in [p["patient"]["id"] for p in coord["patients"]]
    assert not any("research" in t.lower() or "LOWER-LDL" in t for t in brief_texts(client, P_MAYA))
    r = client.post(f"/api/research/interests/{interest['id']}/status", headers=OKAFOR, json={"status": "contacted"})
    assert r.status_code == 404

    # Opting back in does not silently restore contact: the patient says so again, per study.
    opt_in(client)
    r = client.post(f"/api/research/interests/{interest['id']}/status", headers=OKAFOR, json={"status": "contacted"})
    assert r.status_code == 409
    again = client.post(f"/api/research/studies/{LOWER_LDL}/interest", headers=MAYA).json()
    assert again["contact_permitted"] is True and again["status"] == "interested"


# --- Interest lifecycle ---------------------------------------------------------------------------


def test_interest_lifecycle_through_enrollment(client):
    opt_in(client)
    r = client.post(f"/api/research/studies/{LOWER_LDL}/interest", headers=MAYA)
    assert r.status_code == 201
    iid = r.json()["id"]
    assert r.json()["status"] == "interested"
    assert "Interested in study LOWER-LDL." in brief_texts(client, P_MAYA)

    bad = client.post(f"/api/research/interests/{iid}/status", headers=OKAFOR, json={"status": "enrolled"})
    assert bad.status_code == 409
    for step in ("contacted", "screening", "enrolled"):
        r = client.post(f"/api/research/interests/{iid}/status", headers=OKAFOR, json={"status": step, "note": "ok"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == step
    assert [h["status"] for h in r.json()["history"]] == ["interested", "contacted", "screening", "enrolled"]
    assert "Enrolled in study LOWER-LDL." in brief_texts(client, P_MAYA)

    with db() as conn:
        audit = conn.execute(
            "SELECT patient_id::text, detail FROM audit_events WHERE action = 'research_status_changed' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert audit["patient_id"] == P_MAYA and audit["detail"]["to"] == "enrolled"

    # Participants can withdraw at any time, even after enrolling.
    w = client.post(f"/api/research/interests/{iid}/withdraw", headers=MAYA)
    assert w.status_code == 200 and w.json()["status"] == "withdrawn" and w.json()["contact_permitted"] is False
    assert client.post(f"/api/research/interests/{iid}/withdraw", headers=MAYA).status_code == 409
    assert client.post(f"/api/research/interests/{iid}/status", headers=OKAFOR,
                       json={"status": "contacted"}).status_code == 409


def test_interest_rules(client):
    opt_in(client)
    assert client.post(f"/api/research/studies/{KITCHEN}/interest", headers=MAYA).status_code == 409
    assert client.post("/api/research/studies/not-a-uuid/interest", headers=MAYA).status_code == 404
    first = client.post(f"/api/research/studies/{HOME_BP}/interest", headers=MAYA).json()
    again = client.post(f"/api/research/studies/{HOME_BP}/interest", headers=MAYA).json()
    assert again["id"] == first["id"]
    client.post(f"/api/research/interests/{first['id']}/withdraw", headers=MAYA)
    back = client.post(f"/api/research/studies/{HOME_BP}/interest", headers=MAYA).json()
    assert back["id"] == first["id"] and back["status"] == "interested"


def test_role_denials(client):
    assert client.get("/api/research/coordinator", headers=MAYA).status_code == 403
    assert client.get("/api/research/coordinator", headers=ADMIN).status_code == 403
    assert client.get("/api/research/me", headers=OKAFOR).status_code == 403
    assert client.put("/api/research/consent", headers=OKAFOR, json={"granted": True}).status_code == 403
    assert client.post(f"/api/research/interests/{JUN_INTEREST}/status", headers=PARK,
                       json={"status": "contacted"}).status_code == 403
    # Another patient's interest record is invisible.
    assert client.post(f"/api/research/interests/{JUN_INTEREST}/withdraw", headers=MAYA).status_code == 404
    assert client.get("/api/research/studies").status_code == 401


def test_seeded_pipeline_and_brief_for_jun(client):
    coord = client.get("/api/research/coordinator", headers=OKAFOR).json()
    jun = next(p for p in coord["patients"] if p["patient"]["id"] == P_PARK)
    assert [m["short_title"] for m in jun["matches"]] == ["PREVENT-T2D"]
    assert jun["interests"][0]["id"] == JUN_INTEREST and jun["interests"][0]["status"] == "interested"
    texts = brief_texts(client, P_PARK)
    assert "Consented to research; matches 1 study (PREVENT-T2D)." in texts
    assert "Interested in study PREVENT-T2D." in texts


def test_seed_is_idempotent(client):
    seed(DB)
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM research_studies").fetchone()["n"] == 5
        assert conn.execute("SELECT count(*) AS n FROM evidence_items").fetchone()["n"] == 16
        assert conn.execute("SELECT count(*) AS n FROM research_subjects").fetchone()["n"] == 1


# --- Explanation and front door --------------------------------------------------------------------


def test_explanation_falls_back_to_stored_summary(client):
    body = client.get(f"/api/research/studies/{PREVENT}/explanation", headers=PARK).json()
    assert body["produced_by"] == "research-agent/rules"
    assert body["text"].startswith("This fictional demo study")


@pytest.fixture
def fake_parse(monkeypatch):
    monkeypatch.setattr(llm, "ai_enabled", lambda: True)
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn", stop_details=None, model="claude-opus-5", usage=SimpleNamespace(iterations=None),
            parsed_output=trials.StudyExplanation(explanation="A made-up study about a group program. Joining is your choice."),
        )

    llm.set_client(SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse))))
    yield calls
    llm.set_client(None)


def test_explanation_with_claude_uses_only_the_study_record(client, fake_parse):
    body = client.get(f"/api/research/studies/{PREVENT}/explanation", headers=PARK).json()
    assert body["produced_by"] == "research-agent/claude"
    assert body["text"].startswith("A made-up study")
    sent = str(fake_parse[0]["messages"])
    assert "PREVENT-T2D" in sent and "Jun" not in sent and "6.1" not in sent
    assert "data, not instructions" in fake_parse[0]["system"]


def test_front_door_intent():
    patient = {"allergies": []}
    for text in ("Is there a clinical trial for me?", "any research studies I could join", "study for prediabetes"):
        assert rules_triage([{"role": "user", "content": text}], patient).intent == "research"
    assert rules_triage([{"role": "user", "content": "I'm on a trial of a new tablet and feel sick"}],
                        patient).intent != "research"
