"""FHIR R4 read API and terminology service: resource shapes, access control, OperationOutcome, audit."""

import re

import psycopg
from psycopg.rows import dict_row

from bioverse import consent
from bioverse.db.seed import DR_OKAFOR, ORG, P_HADDAD
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, P_PARK, PARK

BASE = "/api/fhir/R4"
REF = re.compile(r"^(Patient|Practitioner|Organization|Observation|DiagnosticReport|Encounter|Immunization|CarePlan|"
                 r"Appointment|AllergyIntolerance|Consent|DocumentReference)/[A-Za-z0-9\-.]{1,64}$")
ID = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def get(client, path, headers=MAYA, **params):
    r = client.get(BASE + path, headers=headers, params=params)
    assert r.headers["content-type"].startswith("application/fhir+json"), r.headers["content-type"]
    return r


def references(node):
    """Every Reference.reference string anywhere in a resource."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "reference" and isinstance(v, str):
                yield v
            else:
                yield from references(v)
    elif isinstance(node, list):
        for v in node:
            yield from references(v)


def assert_valid(resource):
    """Structural checks shared by every resource: type, id format, no empty values, reference formats."""
    assert resource["resourceType"]
    assert ID.match(resource["id"])
    if "meta" in resource and "lastUpdated" in resource["meta"]:
        assert INSTANT.match(resource["meta"]["lastUpdated"])

    def no_empty(node):
        if isinstance(node, dict):
            assert node, "empty object"
            for v in node.values():
                assert v not in ("", None, [], {}), node
                no_empty(v)
        elif isinstance(node, list):
            for v in node:
                no_empty(v)

    no_empty(resource)
    for ref in references(resource):
        assert REF.match(ref), ref


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def test_capability_statement_is_public_and_lists_what_is_implemented(client):
    r = get(client, "/metadata", headers={})
    assert r.status_code == 200
    cs = r.json()
    assert cs["resourceType"] == "CapabilityStatement"
    assert cs["fhirVersion"] == "4.0.1"
    assert cs["kind"] == "instance" and cs["format"] == ["json"]
    types = {res["type"] for res in cs["rest"][0]["resource"]}
    assert {"Patient", "Practitioner", "Organization", "Observation", "DiagnosticReport", "Encounter", "Immunization",
            "CarePlan", "Appointment", "AllergyIntolerance", "Consent", "CodeSystem"} <= types
    patient = next(res for res in cs["rest"][0]["resource"] if res["type"] == "Patient")
    assert patient["operation"][0]["name"] == "everything"


def test_patient_read_shape(client):
    r = get(client, f"/Patient/{P_MAYA}")
    assert r.status_code == 200
    p = r.json()
    assert_valid(p)
    assert p["resourceType"] == "Patient" and p["id"] == P_MAYA
    assert p["birthDate"] == "1972-03-09"
    assert p["name"][0]["family"] == "Thornton" and p["name"][0]["given"] == ["Maya"]
    assert p["managingOrganization"]["reference"] == f"Organization/{ORG}"
    mrn = next(i for i in p["identifier"] if i["system"].endswith("/mrn"))
    assert mrn["value"] == "NSH-0201" and mrn["type"]["coding"][0]["code"] == "MR"
    assert p["communication"][0]["language"]["coding"][0]["code"] == "es"
    assert "lastUpdated" in p["meta"]


def test_access_rules_return_operation_outcome(client):
    # A patient can't read someone else, directly or by search.
    for path, params in [(f"/Patient/{P_PARK}", {}), ("/Observation", {"patient": P_PARK}),
                         (f"/Patient/{P_PARK}/$everything", {})]:
        r = get(client, path, **params)
        assert r.status_code == 403
        oo = r.json()
        assert oo["resourceType"] == "OperationOutcome"
        assert oo["issue"][0]["severity"] == "error" and oo["issue"][0]["code"] == "forbidden"

    missing = get(client, f"/Patient/{P_MAYA}", headers={})
    assert missing.status_code == 401 and missing.json()["resourceType"] == "OperationOutcome"

    unknown = get(client, "/Patient/00000000-0000-0000-0000-000000009999", headers=OKAFOR)
    assert unknown.status_code == 404 and unknown.json()["issue"][0]["code"] == "not-found"
    assert get(client, "/Patient/not-a-uuid", headers=OKAFOR).status_code == 404

    no_param = get(client, "/Observation")
    assert no_param.status_code == 400 and no_param.json()["issue"][0]["code"] == "invalid"

    unsupported = get(client, "/MedicationRequest", patient=P_MAYA)
    assert unsupported.status_code == 404 and unsupported.json()["resourceType"] == "OperationOutcome"
    write = client.post(BASE + "/Patient", headers=MAYA, json={"resourceType": "Patient"})
    assert write.status_code == 405 and write.json()["resourceType"] == "OperationOutcome"

    # Clinicians in the organization can read; the reads are audited with the patient's id.
    assert get(client, f"/Patient/{P_MAYA}", headers=OKAFOR).status_code == 200
    with db() as conn:
        rows = conn.execute(
            "SELECT actor_role, agent, entity_type, patient_id::text FROM audit_events WHERE action = 'fhir_read'"
        ).fetchall()
    assert {"actor_role": "clinician", "agent": None, "entity_type": "Patient", "patient_id": P_MAYA} in rows
    assert all(r["patient_id"] != P_PARK for r in rows), "refused reads must not be recorded as reads"


def test_observation_search_codes_units_ranges(client):
    r = get(client, "/Observation", patient=f"Patient/{P_MAYA}")
    assert r.status_code == 200
    b = r.json()
    assert b["resourceType"] == "Bundle" and b["type"] == "searchset"
    assert b["total"] == len(b["entry"])
    labs = [e for e in b["entry"] if e["resource"]["category"][0]["coding"][0]["code"] == "laboratory"]
    assert len(labs) == 12
    for e in labs:
        o = e["resource"]
        assert_valid(o)
        assert e["fullUrl"].endswith(f"/api/fhir/R4/Observation/{o['id']}")
        assert e["search"]["mode"] == "match"
        assert o["status"] == "final"
        assert o["subject"]["reference"] == f"Patient/{P_MAYA}"
        coding = o["code"]["coding"][0]
        assert coding["system"] == "http://loinc.org" and re.match(r"^\d+-\d$", coding["code"])
        q = o["valueQuantity"]
        assert q["system"] == "http://unitsofmeasure.org" and q["code"] == "mg/dL"
        assert o["interpretation"][0]["coding"][0]["system"].endswith("v3-ObservationInterpretation")
        assert o["referenceRange"][0].get("low") or o["referenceRange"][0].get("high")
        assert INSTANT.match(o["effectiveDateTime"])
    ldl = [e["resource"] for e in b["entry"] if e["resource"]["code"]["coding"][0]["code"] == "13457-7"]
    latest = max(ldl, key=lambda o: o["effectiveDateTime"])
    assert latest["valueQuantity"]["value"] == 148
    assert latest["interpretation"][0]["coding"][0]["code"] == "H"
    assert latest["referenceRange"][0]["high"]["value"] == 100


def test_diagnostic_report_references_results_and_hides_unapproved_drafts(client):
    maya = get(client, "/DiagnosticReport", patient=P_MAYA).json()
    obs_ids = {e["resource"]["id"] for e in get(client, "/Observation", patient=P_MAYA).json()["entry"]}
    assert maya["total"] == 3
    for e in maya["entry"]:
        dr = e["resource"]
        assert_valid(dr)
        assert dr["status"] == "final"
        assert dr["category"][0]["coding"][0]["code"] == "LAB"
        assert dr["code"]["coding"][0]["code"] == "24331-1"  # Lipid panel
        assert len(dr["result"]) == 4
        assert {ref["reference"].split("/")[1] for ref in dr["result"]} <= obs_ids
        assert dr["conclusion"]  # all of Maya's explanations are approved
        assert dr["resultsInterpreter"][0]["reference"].startswith("Practitioner/")

    park = get(client, "/DiagnosticReport", headers=PARK, patient=P_PARK).json()["entry"][0]["resource"]
    assert "conclusion" not in park, "a pending draft must never leave through FHIR"


def test_encounters_immunizations_care_plan_allergies(client):
    enc = get(client, "/Encounter", patient=P_MAYA).json()
    assert enc["total"] == 2
    e = enc["entry"][0]["resource"]
    assert_valid(e)
    assert e["status"] == "finished" and e["class"]["code"] == "AMB"
    assert e["participant"][0]["individual"]["reference"].startswith("Practitioner/")
    assert e["text"]["div"].startswith('<div xmlns="http://www.w3.org/1999/xhtml">')

    imm = get(client, "/Immunization", patient=P_MAYA).json()["entry"][0]["resource"]
    assert_valid(imm)
    assert imm["status"] == "completed" and imm["vaccineCode"]["text"] == "Influenza vaccine"
    assert imm["patient"]["reference"] == f"Patient/{P_MAYA}"

    plan = get(client, "/CarePlan", patient=P_MAYA).json()["entry"][0]["resource"]
    assert_valid(plan)
    assert plan["status"] == "active" and plan["intent"] == "plan"
    assert plan["author"]["reference"] == f"Practitioner/{DR_OKAFOR}"
    kinds = [a["detail"]["kind"] for a in plan["activity"]]
    assert kinds == ["ServiceRequest", "MedicationRequest", "Appointment", "ServiceRequest", "CommunicationRequest"]
    assert plan["activity"][0]["detail"]["status"] == "completed"
    assert plan["activity"][1]["detail"]["status"] == "not-started"

    allergy = get(client, "/AllergyIntolerance", patient=P_MAYA).json()["entry"][0]["resource"]
    assert_valid(allergy)
    assert allergy["code"]["text"] == "Penicillin"
    assert allergy["code"]["coding"][0]["system"] == "http://snomed.info/sct"
    assert allergy["clinicalStatus"]["coding"][0]["code"] == "active"
    haddad = get(client, "/AllergyIntolerance", headers=OKAFOR, patient=P_HADDAD).json()
    assert haddad["entry"][0]["resource"]["code"]["text"] == "Sulfa drugs"
    # Stable ids across reads.
    again = get(client, "/AllergyIntolerance", patient=P_MAYA).json()["entry"][0]["resource"]
    assert again["id"] == allergy["id"]


def test_appointment_and_consent(client):
    with db() as conn:
        slot = conn.execute(
            "SELECT id::text FROM slots WHERE practitioner_id = %s AND status = 'free' ORDER BY starts_at LIMIT 1",
            (DR_OKAFOR,),
        ).fetchone()["id"]
    booked = client.post("/api/appointments", headers=MAYA, json={"slot_id": slot, "reason": "Follow-up"})
    assert booked.status_code == 201
    appt = get(client, "/Appointment", patient=P_MAYA).json()["entry"][0]["resource"]
    assert_valid(appt)
    assert appt["status"] == "booked" and appt["minutesDuration"] == 20
    assert {p["actor"]["reference"] for p in appt["participant"]} == {f"Patient/{P_MAYA}", f"Practitioner/{DR_OKAFOR}"}
    assert appt["start"] < appt["end"]

    with db() as conn:
        consent.set_status(conn, patient_id=P_MAYA, scope="research_matching", status="granted", actor=None)
        consent.set_status(conn, patient_id=P_MAYA, scope="ai_processing", status="denied", actor=None)
    consents = {e["resource"]["provision"]["code"][0]["coding"][0]["code"]: e["resource"]
                for e in get(client, "/Consent", patient=P_MAYA).json()["entry"]}
    research = consents["research_matching"]
    assert_valid(research)
    assert research["status"] == "active" and research["scope"]["coding"][0]["code"] == "research"
    assert research["provision"]["type"] == "permit" and research["policyRule"]["coding"][0]["code"] == "OPTIN"
    assert consents["ai_processing"]["provision"]["type"] == "deny"
    assert research["patient"]["reference"] == f"Patient/{P_MAYA}"


def test_everything_is_complete_and_self_contained(client):
    with db() as conn:
        consent.set_status(conn, patient_id=P_MAYA, scope="research_matching", status="granted", actor=None)
    r = get(client, f"/Patient/{P_MAYA}/$everything")
    assert r.status_code == 200
    b = r.json()
    assert b["resourceType"] == "Bundle" and b["type"] == "searchset"
    assert b["link"][0]["relation"] == "self"
    by_type: dict[str, list] = {}
    for e in b["entry"]:
        res = e["resource"]
        assert_valid(res)
        assert e["fullUrl"] == f"http://testserver/api/fhir/R4/{res['resourceType']}/{res['id']}"
        by_type.setdefault(res["resourceType"], []).append(res)

    with db() as conn:
        counts = conn.execute(
            """
            SELECT (SELECT count(*) FROM observations WHERE patient_id = %(p)s) AS obs,
                   (SELECT count(*) FROM diagnostic_reports WHERE patient_id = %(p)s) AS reports,
                   (SELECT count(*) FROM encounters WHERE patient_id = %(p)s) AS enc,
                   (SELECT count(*) FROM immunizations WHERE patient_id = %(p)s) AS imm,
                   (SELECT count(*) FROM care_plans WHERE patient_id = %(p)s) AS plans,
                   (SELECT count(*) FROM consents WHERE patient_id = %(p)s) AS consents
            """,
            {"p": P_MAYA},
        ).fetchone()
    assert len(by_type["Patient"]) == 1 and by_type["Patient"][0]["id"] == P_MAYA
    assert len(by_type["Observation"]) == counts["obs"]
    assert sum(o["category"][0]["coding"][0]["code"] == "laboratory" for o in by_type["Observation"]) == 12
    assert len(by_type["DiagnosticReport"]) == counts["reports"] == 3
    assert len(by_type["Encounter"]) == counts["enc"]
    assert len(by_type["Immunization"]) == counts["imm"]
    assert len(by_type["CarePlan"]) == counts["plans"]
    assert len(by_type["Consent"]) == counts["consents"] >= 1  # other modules seed consents too (caregivers)
    assert len(by_type["AllergyIntolerance"]) == 1
    assert len(by_type["Organization"]) == 1
    assert {p["id"] for p in by_type["Practitioner"]} == {DR_OKAFOR, "00000000-0000-0000-0000-000000000305"}
    assert b["total"] == len(b["entry"]) - 3  # organization and practitioners are includes

    # Every reference inside the bundle resolves to an entry in the bundle.
    present = {f"{e['resource']['resourceType']}/{e['resource']['id']}" for e in b["entry"]}
    dangling = {ref for e in b["entry"] for ref in references(e["resource"])} - present
    assert not dangling, dangling

    with db() as conn:
        row = conn.execute(
            "SELECT detail FROM audit_events WHERE action = 'fhir_read' AND patient_id = %s ORDER BY id DESC LIMIT 1",
            (P_MAYA,),
        ).fetchone()
    assert row["detail"]["interaction"] == "everything"


def test_practitioner_and_organization(client):
    pr = get(client, f"/Practitioner/{DR_OKAFOR}").json()
    assert_valid(pr)
    assert pr["name"][0]["family"] == "Okafor" and pr["name"][0]["prefix"] == ["Dr."]
    assert any(i["value"] == "D301" for i in pr["identifier"])
    org = get(client, f"/Organization/{ORG}").json()
    assert_valid(org)
    assert org["name"] == "Northside Health"
    assert get(client, "/Organization/00000000-0000-0000-0000-000000000002").status_code == 404


def test_terminology_lookup_and_validate(client):
    r = get(client, "/CodeSystem/$lookup", system="http://loinc.org", code="13457-7")
    assert r.status_code == 200
    params = {p["name"]: p for p in r.json()["parameter"]}
    assert r.json()["resourceType"] == "Parameters"
    assert params["display"]["valueString"].startswith("Cholesterol in LDL")
    assert params["name"]["valueString"] == "LOINC"
    notices = [p for p in r.json()["parameter"] if p["name"] == "property" and p["part"][0]["valueCode"] == "subset-notice"]
    assert "subset" in notices[0]["part"][1]["valueString"].lower()

    for system, code, display in [("http://snomed.info/sct", "55822004", "Hyperlipidemia"),
                                  ("icd-10", "E78.5", "Hyperlipidemia, unspecified"),
                                  ("RxNorm", "83367", "atorvastatin"),
                                  ("http://unitsofmeasure.org", "mg/dL", "milligram per deciliter")]:
        found = get(client, "/CodeSystem/$lookup", system=system, code=code).json()
        assert next(p for p in found["parameter"] if p["name"] == "display")["valueString"] == display

    missing = get(client, "/CodeSystem/$lookup", system="http://loinc.org", code="99999-9")
    assert missing.status_code == 404 and missing.json()["resourceType"] == "OperationOutcome"
    assert get(client, "/CodeSystem/$lookup", system="http://example.org/cs", code="x").status_code == 404
    assert get(client, "/CodeSystem/$lookup", system="http://loinc.org").status_code == 400
    assert get(client, "/CodeSystem/$lookup", headers={}, system="http://loinc.org", code="13457-7").status_code == 401

    ok = get(client, "/CodeSystem/$validate-code", url="http://loinc.org", code="4548-4", display="HbA1c").json()
    assert ok["parameter"][0] == {"name": "result", "valueBoolean": True}
    bad = get(client, "/CodeSystem/$validate-code", url="http://loinc.org", code="4548-4", display="Glucose").json()
    assert bad["parameter"][0]["valueBoolean"] is False

    systems = get(client, "/CodeSystem", headers=ADMIN).json()
    assert {e["resource"]["content"] for e in systems["entry"]} == {"fragment"}
    assert all("subset" in e["resource"]["title"] for e in systems["entry"])
