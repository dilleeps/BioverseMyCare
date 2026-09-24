"""Medical students never reach identifiable patient data.

Walks every API route in the app (app.routes) and calls it as the demo student:
- every route with a patient-scoped path or query parameter, filled with real IDs from the seeded demo
  records, must answer 401, 403 or 404 (another 4xx for writes whose body is refused first), never 2xx;
- every clinician-only, workforce and admin route must answer 403;
- every other GET route must not return a patient's name or record number.
"""

import re
import uuid
from datetime import date

import psycopg
from fastapi.routing import APIRoute

from bioverse.auth import assert_patient_access, require_admin, require_clinician, require_staff_or_admin
from bioverse.db.seeds.ids import DR_OKAFOR, ORG, P_MAYA, _id
from bioverse.main import app
from tests.conftest import DB, as_user

STUDENT = as_user(_id(16001))

# Path parameters that name a patient or something belonging to one, and where to find a real value.
PATIENT_SCOPED = {
    "patient_id": None,  # the demo patient
    "appointment_id": "SELECT id::text FROM appointments WHERE patient_id = %(p)s",
    "claim_id": "SELECT id::text FROM claims WHERE patient_id = %(p)s",
    "coverage_id": "SELECT id::text FROM coverages WHERE patient_id = %(p)s",
    "payment_id": "SELECT id::text FROM payments WHERE patient_id = %(p)s",
    "statement_id": "SELECT id::text FROM patient_statements WHERE patient_id = %(p)s",
    "conversation_id": "SELECT id::text FROM conversations WHERE patient_id = %(p)s",
    "document_id": "SELECT id::text FROM document_references WHERE patient_id = %(p)s",
    "thread_id": "SELECT id::text FROM communication_threads WHERE patient_id = %(p)s",
    "draft_id": "SELECT id::text FROM communication_drafts WHERE patient_id = %(p)s",
    "report_id": "SELECT id::text FROM diagnostic_reports WHERE patient_id = %(p)s",
    "task_id": "SELECT t.id::text FROM care_plan_tasks t JOIN care_plans c ON c.id = t.care_plan_id WHERE c.patient_id = %(p)s",
    "plan_id": "SELECT id::text FROM care_plans WHERE patient_id = %(p)s",
    "referral_id": "SELECT id::text FROM service_requests WHERE patient_id = %(p)s",
    "rx_id": "SELECT id::text FROM medication_requests WHERE patient_id = %(p)s",
    "dispense_id": "SELECT id::text FROM medication_dispenses WHERE patient_id = %(p)s",
    "goal_id": "SELECT id::text FROM wellness_goals WHERE patient_id = %(p)s",
    "item_id": "SELECT id::text FROM review_items WHERE patient_id IS NOT NULL",
    "contact_id": "SELECT id::text FROM emergency_contacts",
    "caregiver_user_id": "SELECT user_id::text FROM related_persons",
    "request_id": "SELECT id::text FROM refill_requests",
    "question_id": "SELECT id::text FROM appointment_questions",
    "interest_id": "SELECT id::text FROM research_subjects",
    "notification_id": "SELECT id::text FROM notifications WHERE patient_id IS NOT NULL",
    "event_id": "SELECT id::text FROM audit_events WHERE patient_id IS NOT NULL",
    "query_id": "SELECT id::text FROM evidence_queries",
    "grant_id": "SELECT id::text FROM break_glass_grants",
    "incident_id": "SELECT id::text FROM safety_incidents",
    "application_id": "SELECT id::text FROM financial_assistance_applications",
}
CHECKLIST_ITEM = "SELECT id::text FROM appointment_checklist_items"
LOOKUPS = {"checklist_item_id": CHECKLIST_ITEM, "service_code": "SELECT code FROM service_prices"}
OTHER_PARAMS = {
    "practitioner_id": DR_OKAFOR, "organization_id": ORG, "code": "x", "scope": "ai_processing", "category": "x",
    "name": "x", "day": date.today().isoformat(), "taken_on": date.today().isoformat(),
    "rest": f"Patient/{P_MAYA}",
}
PATIENT_QUERY_PARAMS = {"patient_id", "patient", "subject"}
STAFF_GUARDS = {require_clinician, require_staff_or_admin, require_admin}


def api_routes():
    """(path, route) for every API route. Newer FastAPI nests included routers; walk them."""
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:  # older FastAPI: app.routes is already flat
        return [(r.path, r) for r in app.routes if isinstance(r, APIRoute)]
    return [(c.path, c.original_route) for c in iter_route_contexts(app.routes)
            if isinstance(c.original_route, APIRoute) and c.path.startswith("/api/")]


def guards(route: APIRoute) -> set:
    found, stack = set(), list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        if dep.call is not None:
            found.add(getattr(dep.call, "__wrapped__", dep.call))
            name = getattr(dep.call, "__name__", "")
            if name.startswith("require_") and name not in ("require_patient", "require_student"):
                found.add("custom_staff_guard")
        stack.extend(dep.dependencies)
    return found


def real_ids() -> dict[str, str]:
    values = {"patient_id": P_MAYA}
    with psycopg.connect(DB) as conn:
        for param, sql in list(PATIENT_SCOPED.items()) + list(LOOKUPS.items()):
            if sql is None:
                continue
            row = conn.execute(sql + " LIMIT 1", {"p": P_MAYA}).fetchone()
            values[param] = row[0] if row else str(uuid.uuid4())
    return values


def fill(path: str, ids: dict[str, str]) -> str:
    def value(m):
        name = m.group(1)
        if name == "item_id" and "checklist" in path:
            return ids["checklist_item_id"]
        return ids.get(name) or OTHER_PARAMS.get(name) or str(uuid.uuid4())
    return re.sub(r"{(\w+)(?::\w+)?}", value, path)


def call(client, method: str, url: str):
    kwargs = {"headers": STUDENT}
    if method in ("POST", "PUT", "PATCH"):
        kwargs["json"] = {}
    return client.request(method, url, **kwargs)


def test_student_demo_user_exists(client):
    users = client.get("/api/session/demo-users").json()
    priya = next(u for u in users if u["id"] == _id(16001))
    assert priya["role"] == "student" and priya["display_name"] == "Priya Raman" and priya["subtitle"] == "Medical student"
    me = client.get("/api/me", headers=STUDENT).json()
    assert me["role"] == "student" and me["patient_id"] is None and me["practitioner_id"] is None


def test_assert_patient_access_refuses_students(client):
    from bioverse.auth import User

    student = User(id=_id(16001), role="student", display_name="Priya Raman", organization_id=ORG,
                   patient_id=None, practitioner_id=None)
    with psycopg.connect(DB) as conn:
        try:
            assert_patient_access(conn, student, P_MAYA)
        except Exception as exc:  # noqa: BLE001
            assert getattr(exc, "status_code", None) == 403
        else:
            raise AssertionError("a student reached a patient record")


def test_student_is_refused_on_every_patient_scoped_route(client):
    ids = real_ids()
    walked, leaks = 0, []
    for path, route in api_routes():
        params = set(re.findall(r"{(\w+)", path))
        query = {p.name for p in route.dependant.query_params}
        scoped = params & set(PATIENT_SCOPED)
        patient_query = query & PATIENT_QUERY_PARAMS
        if not scoped and not patient_query and not path.startswith("/api/fhir/R4/{rest"):
            continue
        url = fill(path, ids)
        # Patient query parameters get the demo patient; other required ones a real value, so a refusal
        # can't hide behind a validation error.
        query_values = {q: P_MAYA for q in patient_query}
        for p in route.dependant.query_params:
            if p.name not in query_values and (p.field_info.is_required() if hasattr(p, "field_info") else p.required):
                query_values[p.name] = ids.get(p.name) or OTHER_PARAMS.get(p.name) or "x"
        if query_values:
            url += "?" + "&".join(f"{k}={v}" for k, v in sorted(query_values.items()))
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            res = call(client, method, url)
            walked += 1
            ok = res.status_code in (401, 403, 404) if method == "GET" else 400 <= res.status_code < 500
            if not ok:
                leaks.append(f"{method} {path} -> {res.status_code}")
    assert walked >= 60, walked  # the walk really covered the app
    assert leaks == []


def test_fhir_search_by_patient_is_refused(client):
    for url in (f"/api/fhir/R4/Patient/{P_MAYA}", f"/api/fhir/R4/Patient/{P_MAYA}/$everything",
                f"/api/fhir/R4/Observation?patient={P_MAYA}", f"/api/fhir/R4/Observation?subject=Patient/{P_MAYA}",
                "/api/fhir/R4/Patient"):
        res = client.get(url, headers=STUDENT)
        assert res.status_code in (400, 401, 403, 404), (url, res.status_code)


def test_clinician_workforce_and_admin_routes_refuse_students(client):
    ids = real_ids()
    checked, allowed = 0, []
    for path, route in api_routes():
        g = guards(route)
        if not (g & STAFF_GUARDS or "custom_staff_guard" in g):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            res = call(client, method, fill(path, ids))
            checked += 1
            if res.status_code != 403:
                allowed.append(f"{method} {path} -> {res.status_code}")
    assert checked >= 50, checked
    assert allowed == []


def test_open_get_routes_show_students_no_patient_identifiers(client):
    with psycopg.connect(DB) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM patients").fetchall()]
        mrns = [r[0] for r in conn.execute("SELECT value FROM patient_identifiers").fetchall()]
    exposed = []
    for path, route in api_routes():
        if "GET" not in route.methods or "{" in path or path == "/api/session/demo-users":
            continue  # the demo identity switcher lists demo people by design
        res = client.get(path, headers=STUDENT)
        if res.status_code < 400:
            body = res.text
            exposed += [f"{path}: {n}" for n in names + mrns if n in body]
    assert exposed == []
