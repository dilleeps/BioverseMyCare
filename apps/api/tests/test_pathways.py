"""Care pathways (admin templates) and clinician care-plan authoring."""

import uuid
from datetime import date, timedelta

import psycopg
import pytest

from bioverse.agents import hospital_agent as ha
from bioverse.db.seed import DR_RAMAN, ORG, PLAN
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_PARK, PARK, as_user

STATIN = "New statin start"


def templates(client, headers=ADMIN):
    r = client.get("/api/pathways/templates", headers=headers)
    assert r.status_code == 200, r.text
    return {t["name"]: t for t in r.json()}


def today():
    return ha.clock().today


def start(client, **body):
    return client.post("/api/pathways/care-plans", headers=OKAFOR, json=body)


def audits(action):
    with psycopg.connect(DB) as conn:
        return conn.execute(
            "SELECT entity_id::text, patient_id::text, detail FROM audit_events WHERE action = %s ORDER BY id", (action,)
        ).fetchall()


# --- Templates -------------------------------------------------------------------------------------------


def test_seeded_pathways_and_access(client):
    names = set(templates(client))
    assert {STATIN, "Hypertension follow-up", "Dermatology biopsy follow-up"} <= names
    statin = templates(client)[STATIN]
    assert [a["due_offset_days"] for a in statin["actions"]] == [0, 0, 7, 84, 90]
    assert set(templates(client, OKAFOR)) == names, "clinicians can read active templates"
    assert client.get("/api/pathways/templates", headers=MAYA).status_code == 403
    assert client.get("/api/pathways/templates").status_code == 401


PATHWAY = {
    "name": "Migraine review",
    "specialty": "Neurology",
    "description": "Headache diary, then a review.",
    "actions": [
        {"kind": "checkin", "title": "Keep a headache diary", "due_offset_days": 0},
        {"kind": "appointment", "title": "Neurology review", "specialty": "Neurology", "due_offset_days": 28},
    ],
}


def test_admin_creates_and_edits_template(client):
    assert client.post("/api/pathways/templates", headers=OKAFOR, json=PATHWAY).status_code == 403
    assert client.post("/api/pathways/templates", headers=MAYA, json=PATHWAY).status_code == 403

    r = client.post("/api/pathways/templates", headers=ADMIN, json=PATHWAY)
    assert r.status_code == 201, r.text
    created = r.json()
    assert [a["title"] for a in created["actions"]] == ["Keep a headache diary", "Neurology review"]
    assert [a["position"] for a in created["actions"]] == [1, 2]
    assert client.post("/api/pathways/templates", headers=ADMIN, json=PATHWAY).status_code == 409

    edited = {**PATHWAY, "active": False, "actions": list(reversed(PATHWAY["actions"]))}
    r = client.put(f"/api/pathways/templates/{created['id']}", headers=ADMIN, json=edited)
    assert r.status_code == 200
    assert [a["title"] for a in r.json()["actions"]] == ["Neurology review", "Keep a headache diary"]
    assert "Migraine review" not in templates(client, OKAFOR), "inactive templates are hidden from clinicians"
    assert [a[0] for a in audits("pathway_created")] == [created["id"]]
    assert audits("pathway_updated")[-1][2]["active"] is False
    assert client.put("/api/pathways/templates/nope", headers=ADMIN, json=edited).status_code == 404


@pytest.mark.parametrize("change", [
    {"actions": []},
    {"actions": [{"kind": "appointment", "title": "Visit", "due_offset_days": 3}]},
    {"actions": [{"kind": "surgery", "title": "Visit", "due_offset_days": 3}]},
    {"actions": [{"kind": "lab", "title": "Test", "due_offset_days": -1}]},
    {"name": " "},
])
def test_template_validation(client, change):
    assert client.post("/api/pathways/templates", headers=ADMIN, json={**PATHWAY, **change}).status_code == 422


# --- Care plans ---------------------------------------------------------------------------------------------


def test_start_plan_from_template_reaches_the_patient(client):
    statin = templates(client)[STATIN]
    r = start(client, patient_id=P_PARK, pathway_id=statin["id"])
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["title"] == STATIN and plan["status"] == "active" and plan["pathway_name"] == STATIN
    assert [t["title"] for t in plan["tasks"]] == [a["title"] for a in statin["actions"]]
    assert [date.fromisoformat(t["due_on"]) for t in plan["tasks"]] == [
        today() + timedelta(days=a["due_offset_days"]) for a in statin["actions"]]

    seen = client.get(f"/api/patients/{P_PARK}/care-plan", headers=PARK).json()
    assert seen["id"] == plan["id"]
    assert seen["practitioner_name"] == "Dr. Adaeze Okafor"
    assert seen["total_count"] == 5

    created = audits("care_plan_created")
    assert created[-1][:2] == (plan["id"], P_PARK)
    assert created[-1][2]["pathway_id"] == statin["id"]

    again = start(client, patient_id=P_PARK, pathway_id=statin["id"])
    assert again.status_code == 409
    assert again.json()["detail"]["plan_id"] == plan["id"]
    listed = {p["id"]: p for p in client.get("/api/pathways/care-plans", headers=OKAFOR).json()}
    assert listed[plan["id"]]["total_count"] == 5
    picker = {p["id"]: p for p in client.get("/api/pathways/patients", headers=OKAFOR).json()}
    assert picker[P_PARK]["active_plan_id"] == plan["id"]


def test_blank_plan_and_edited_template_tasks(client):
    assert start(client, patient_id=P_PARK, title="Blank").status_code == 422
    assert start(client, patient_id=P_PARK, title="Blank", tasks=[]).status_code == 422
    tasks = [{"kind": "lifestyle", "title": "Walk 20 minutes a day", "due_on": str(today() + timedelta(days=1))},
             {"kind": "referral", "title": "See a dietitian", "due_on": str(today() + timedelta(days=30))}]
    assert start(client, patient_id=P_PARK, title="Prediabetes", tasks=tasks).status_code == 422, "referral needs a specialty"
    tasks[1]["specialty"] = "Nutrition"
    far = [{**tasks[0], "due_on": str(today() + timedelta(days=900))}]
    assert start(client, patient_id=P_PARK, title="Prediabetes", tasks=far).status_code == 422
    r = start(client, patient_id=P_PARK, title="Prediabetes", tasks=tasks)
    assert r.status_code == 201, r.text
    assert r.json()["pathway_id"] is None
    assert [t["title"] for t in r.json()["tasks"]] == ["Walk 20 minutes a day", "See a dietitian"]


def test_only_panel_patients_and_only_clinicians(client):
    stranger = str(uuid.uuid4())
    with psycopg.connect(DB) as conn:
        conn.execute(
            "INSERT INTO patients (id, organization_id, name, birth_date, insurance_plan) VALUES (%s, %s, 'Quinn Arlo', '1980-01-01', %s)",
            (stranger, ORG, PLAN),
        )
    statin = templates(client)[STATIN]["id"]
    assert start(client, patient_id=stranger, pathway_id=statin).status_code == 403
    assert start(client, patient_id="not-a-uuid", pathway_id=statin).status_code == 404
    assert start(client, patient_id=P_PARK, pathway_id=str(uuid.uuid4())).status_code == 404
    body = {"patient_id": P_PARK, "pathway_id": statin}
    assert client.post("/api/pathways/care-plans", headers=ADMIN, json=body).status_code == 403
    assert client.post("/api/pathways/care-plans", headers=MAYA, json=body).status_code == 403


def test_edit_reorder_and_complete(client):
    plan = start(client, patient_id=P_PARK, pathway_id=templates(client)["Hypertension follow-up"]["id"]).json()
    tasks = plan["tasks"]
    client.patch(f"/api/care-plan-tasks/{tasks[0]['id']}", headers=PARK, json={"status": "done"})

    def body(items, title="Blood pressure plan"):
        return {"title": title, "tasks": [{k: t.get(k) for k in ("id", "kind", "title", "detail", "specialty", "due_on")}
                                          for t in items]}

    moved = str(today() + timedelta(days=45))
    new_order = [tasks[3], tasks[0], {**tasks[1], "due_on": moved},
                 {"kind": "medication", "title": "Start amlodipine 5 mg", "due_on": str(today())}]  # drops tasks[2]
    r = client.put(f"/api/pathways/care-plans/{plan['id']}", headers=OKAFOR, json=body(new_order))
    assert r.status_code == 200, r.text
    edited = r.json()
    assert edited["title"] == "Blood pressure plan"
    assert [t["title"] for t in edited["tasks"]] == [tasks[3]["title"], tasks[0]["title"], tasks[1]["title"], "Start amlodipine 5 mg"]
    assert edited["tasks"][2]["due_on"] == moved
    assert edited["tasks"][1]["status"] == "done", "completion survives a reorder"
    assert tasks[2]["id"] not in {t["id"] for t in edited["tasks"]}
    detail = audits("care_plan_updated")[-1]
    assert detail[1] == P_PARK
    assert detail[2] == {"added": 1, "removed": 1, "changed": 1, "reordered": True, "title_changed": True}

    # Completed tasks stay as recorded.
    done_edit = [dict(t) for t in edited["tasks"]]
    done_edit[1]["title"] = "Something else"
    assert client.put(f"/api/pathways/care-plans/{plan['id']}", headers=OKAFOR, json=body(done_edit)).status_code == 422
    without_done = [t for t in edited["tasks"] if t["status"] != "done"]
    assert client.put(f"/api/pathways/care-plans/{plan['id']}", headers=OKAFOR, json=body(without_done)).status_code == 422
    foreign = edited["tasks"] + [{**edited["tasks"][0], "id": str(uuid.uuid4())}]
    assert client.put(f"/api/pathways/care-plans/{plan['id']}", headers=OKAFOR, json=body(foreign)).status_code == 422
    assert client.put(f"/api/pathways/care-plans/{plan['id']}", headers=OKAFOR, json=body([])).status_code == 422

    r = client.post(f"/api/pathways/care-plans/{plan['id']}/complete", headers=OKAFOR)
    assert r.status_code == 200 and r.json()["status"] == "completed" and r.json()["completed_at"]
    assert audits("care_plan_completed")[-1][2] == {"open_tasks": 3}
    assert client.get(f"/api/patients/{P_PARK}/care-plan", headers=PARK).json() is None
    assert client.post(f"/api/pathways/care-plans/{plan['id']}/complete", headers=OKAFOR).status_code == 409
    assert client.put(f"/api/pathways/care-plans/{plan['id']}", headers=OKAFOR, json=body(edited["tasks"])).status_code == 409

    # With the old plan completed, a new one may start.
    assert start(client, patient_id=P_PARK, pathway_id=templates(client)[STATIN]["id"]).status_code == 201


def test_other_clinicians_cannot_touch_the_plan(client):
    plan = start(client, patient_id=P_PARK, pathway_id=templates(client)[STATIN]["id"]).json()
    raman_user = str(uuid.uuid4())
    with psycopg.connect(DB) as conn:
        conn.execute(
            "INSERT INTO users (id, role, display_name, email, organization_id) VALUES (%s, 'clinician', 'Dr. Priya Raman', 'p.raman@northside.example', %s)",
            (raman_user, ORG),
        )
        conn.execute("UPDATE practitioners SET user_id = %s WHERE id = %s", (raman_user, DR_RAMAN))
    raman = as_user(raman_user)
    assert client.get(f"/api/pathways/care-plans/{plan['id']}", headers=raman).status_code == 404
    assert client.post(f"/api/pathways/care-plans/{plan['id']}/complete", headers=raman).status_code == 404
    assert plan["id"] not in {p["id"] for p in client.get("/api/pathways/care-plans", headers=raman).json()}
    assert client.get(f"/api/pathways/care-plans/{plan['id']}", headers=MAYA).status_code == 403
