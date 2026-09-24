"""Organization platform: profile and branding, locations, departments, services, providers, roles."""

import psycopg
import pytest

from tests.conftest import ADMIN, DB, MAYA, OKAFOR


def last_audit(action):
    with psycopg.connect(DB) as conn:
        return conn.execute(
            "SELECT entity_id::text, actor_role, detail FROM audit_events WHERE action = %s ORDER BY id DESC LIMIT 1",
            (action,),
        ).fetchone()


def ids(client, path, key="name"):
    return {r[key]: r["id"] for r in client.get(path, headers=ADMIN).json()}


@pytest.mark.parametrize("path", ["/api/org/profile", "/api/org/locations", "/api/org/departments",
                                  "/api/org/services", "/api/org/providers", "/api/org/users"])
def test_admin_endpoints_reject_others(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers=OKAFOR).status_code == 403
    assert client.get(path, headers=MAYA).status_code == 403
    assert client.get(path, headers=ADMIN).status_code == 200


def test_writes_reject_clinicians(client):
    body = {"display_name": "Hacked", "accent_color": "#0e6b60"}
    assert client.put("/api/org/profile", headers=OKAFOR, json=body).status_code == 403
    assert client.post("/api/org/locations", headers=OKAFOR, json={"name": "X", "kind": "virtual"}).status_code == 403


def test_public_branding_and_profile_update(client):
    public = client.get("/api/org/branding")
    assert public.status_code == 200
    assert public.json() == {"organization_id": public.json()["organization_id"], "display_name": "Northside Health",
                             "accent_color": "#0e6b60", "support_phone": "(555) 010-2400"}
    assert client.get("/api/org/branding?organization_id=nope").status_code == 404

    r = client.put("/api/org/profile", headers=ADMIN,
                   json={"display_name": "  Northside   Health System ", "accent_color": "#1F5A8A", "support_phone": "555 010 9999"})
    assert r.status_code == 200, r.text
    assert r.json()["display_name"] == "Northside Health System"
    assert r.json()["accent_color"] == "#1f5a8a"
    assert client.get("/api/org/branding").json()["accent_color"] == "#1f5a8a"
    audit = last_audit("org_profile_updated")
    assert audit[1] == "admin"
    assert audit[2]["changed"] == ["accent_color", "display_name", "support_phone"]


@pytest.mark.parametrize("body", [
    {"display_name": "Northside", "accent_color": "#ff00ff"},
    {"display_name": "N", "accent_color": "#0e6b60"},
    {"display_name": "Northside", "accent_color": "#0e6b60", "support_phone": "call us"},
])
def test_profile_validation(client, body):
    assert client.put("/api/org/profile", headers=ADMIN, json=body).status_code == 422


def test_location_crud_and_rename_updates_directory(client):
    assert client.post("/api/org/locations", headers=ADMIN, json={"name": "Harbour Hub", "kind": "physical"}).status_code == 422
    r = client.post("/api/org/locations", headers=ADMIN,
                    json={"name": "Harbour Hub", "kind": "physical", "address": "1 Pier Road", "step_free": True})
    assert r.status_code == 201, r.text
    loc = r.json()
    assert client.post("/api/org/locations", headers=ADMIN,
                       json={"name": "Harbour Hub", "kind": "virtual"}).status_code == 409

    current = next(l for l in client.get("/api/org/locations", headers=ADMIN).json() if l["name"] == "Northside Clinic")
    clinic = current["id"]
    # Rename only; every other field keeps its current value (other modules seed this location too).
    body = {"name": "Northside Clinic West", "kind": current["kind"], "address": current["address"],
            "phone": current["phone"], "step_free": current["step_free"], "active": current["active"]}
    assert client.put(f"/api/org/locations/{clinic}", headers=ADMIN, json=body).status_code == 200
    providers = client.get("/api/org/providers", headers=ADMIN).json()
    assert "Northside Clinic West" in {p["location_name"] for p in providers}
    assert "Northside Clinic" not in {p["location_name"] for p in providers}
    assert last_audit("location_updated")[2]["changed"] == ["name"]
    assert client.put("/api/org/locations/not-a-uuid", headers=ADMIN, json=body).status_code == 404
    assert loc["kind"] == "physical"


def test_department_hours_validation_and_audit(client):
    clinic = ids(client, "/api/org/locations")["Northside Clinic"]
    body = {"name": "Paediatrics", "specialty": "Paediatrics", "location_id": clinic,
            "hours": {"mon": {"open": "08:00", "close": "16:00"}, "sat": None}}
    r = client.post("/api/org/departments", headers=ADMIN, json=body)
    assert r.status_code == 201, r.text
    dept = r.json()
    assert dept["hours"]["mon"] == {"open": "08:00", "close": "16:00"}
    assert dept["hours"]["tue"] is None and set(dept["hours"]) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
    assert dept["location_name"] == "Northside Clinic"
    assert last_audit("department_created")[0] == dept["id"]

    bad_hours = {**body, "name": "Other", "hours": {"mon": {"open": "17:00", "close": "08:00"}}}
    assert client.post("/api/org/departments", headers=ADMIN, json=bad_hours).status_code == 422
    bad_time = {**body, "name": "Other", "hours": {"mon": {"open": "8am", "close": "17:00"}}}
    assert client.post("/api/org/departments", headers=ADMIN, json=bad_time).status_code == 422
    bad_day = {**body, "name": "Other", "hours": {"someday": {"open": "08:00", "close": "17:00"}}}
    assert client.post("/api/org/departments", headers=ADMIN, json=bad_day).status_code == 422
    unknown = {**body, "name": "Other", "location_id": "00000000-0000-0000-0000-000000009999"}
    assert client.post("/api/org/departments", headers=ADMIN, json=unknown).status_code == 422
    assert client.post("/api/org/departments", headers=ADMIN, json=body).status_code == 409

    body["active"] = False
    r = client.put(f"/api/org/departments/{dept['id']}", headers=ADMIN, json=body)
    assert r.status_code == 200 and r.json()["active"] is False
    assert last_audit("department_updated")[2]["changed"] == ["active"]


def test_services_validation(client):
    derm = ids(client, "/api/org/departments")["Dermatology"]
    body = {"name": "Mole mapping", "department_id": derm, "duration_min": 30, "mode": "in_person"}
    r = client.post("/api/org/services", headers=ADMIN, json=body)
    assert r.status_code == 201, r.text
    assert r.json()["department_name"] == "Dermatology"
    assert client.post("/api/org/services", headers=ADMIN, json={**body, "name": "Odd", "duration_min": 23}).status_code == 422
    assert client.post("/api/org/services", headers=ADMIN, json={**body, "name": "Odd", "mode": "phone"}).status_code == 422
    assert client.post("/api/org/services", headers=ADMIN, json=body).status_code == 409
    r = client.put(f"/api/org/services/{r.json()['id']}", headers=ADMIN, json={**body, "duration_min": 45})
    assert r.json()["duration_min"] == 45
    assert last_audit("service_updated")[2]["changed"] == ["duration_min"]


def test_provider_directory_create_and_edit(client):
    locations = ids(client, "/api/org/locations")
    body = {"name": "Dr. Imani Clarke", "specialty": "Dermatology", "location_id": locations["Riverside Medical Centre"],
            "languages": ["English", " French ", "english"], "accessibility": ["Step-free access"],
            "accepted_plans": ["Northside Health Plus"], "offers_telehealth": False}
    r = client.post("/api/org/providers", headers=ADMIN, json=body)
    assert r.status_code == 201, r.text
    provider = r.json()
    assert provider["languages"] == ["English", "French"]
    assert provider["location_name"] == "Riverside Medical Centre"
    assert provider["has_account"] is False
    assert last_audit("provider_created")[0] == provider["id"]

    video = {**body, "location_id": locations["Video visit"]}
    assert client.put(f"/api/org/providers/{provider['id']}", headers=ADMIN, json=video).status_code == 422
    video["offers_telehealth"] = True
    r = client.put(f"/api/org/providers/{provider['id']}", headers=ADMIN, json=video)
    assert r.status_code == 200
    assert r.json()["location_name"] == "Video visit"
    assert last_audit("provider_updated")[2]["changed"] == ["location_id", "location_name", "offers_telehealth"]

    assert client.post("/api/org/providers", headers=ADMIN, json={**body, "languages": []}).status_code == 422


def test_roles_view_is_read_only_and_does_not_list_patients(client):
    data = client.get("/api/org/users", headers=ADMIN).json()
    roles = {u["email"]: u["role"] for u in data["users"]}
    assert roles["ops@northside.example"] == "admin"
    assert roles["a.okafor@northside.example"] == "clinician"
    assert all(u["role"] != "patient" for u in data["users"])
    assert data["role_counts"]["patient"] >= 3
    assert data["roles_editable"] is False
    assert "not available" in data["note"]
