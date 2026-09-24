"""Pharmacy: fills, refills (auto and clinician-approved), adherence, interactions, access control."""

from datetime import date, timedelta

import psycopg
import pytest

from bioverse.agents.triage import rules_triage
from bioverse.db.seed import DR_LINDQVIST, ORG, P_HADDAD, U_HADDAD
from bioverse.db.seeds.s050_billing_pharmacy import (
    DISP_ATORVA_1, PH_EASTGATE, REFILL_HADDAD, REVIEW_HADDAD_REFILL, RX_HADDAD_AMLO, RX_MAYA_ATORVA, RX_MAYA_AZITHRO,
)
from bioverse.routers.pharmacy import adherence_stats, clinic_today
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, PARK, as_user

HADDAD = as_user(U_HADDAD)


def rx(client, rx_id, headers=MAYA):
    r = client.get(f"/api/pharmacy/prescriptions/{rx_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def pick_up_first_fill(client):
    r = client.post(f"/api/pharmacy/fills/{DISP_ATORVA_1}/pickup", headers=MAYA)
    assert r.status_code == 200 and r.json()["status"] == "picked_up"


# --- Prescriptions and fills ---------------------------------------------------------------------


def test_seeded_prescriptions(client):
    body = client.get("/api/pharmacy/prescriptions", headers=MAYA).json()
    by_id = {p["id"]: p for p in body["prescriptions"]}
    atorva = by_id[RX_MAYA_ATORVA]
    assert atorva["status"] == "active" and atorva["dispense_status"] == "ready"
    assert atorva["pharmacy_name"] == "Riverside Pharmacy" and atorva["refills_remaining"] == 5
    assert atorva["adherence"]["tracking"] is False  # not picked up yet
    assert by_id[RX_MAYA_AZITHRO]["status"] == "completed"
    detail = rx(client, RX_MAYA_ATORVA)
    assert detail["drug_info"]["name"] == "Atorvastatin" and "not medical advice" in detail["drug_info"]["notice"]


def test_refill_with_refills_remaining_is_sent_to_pharmacy(client):
    url = f"/api/pharmacy/prescriptions/{RX_MAYA_ATORVA}/refill-requests"
    busy = client.post(url, headers=MAYA, json={})
    assert busy.status_code == 409 and busy.json()["detail"]["code"] == "fill_in_progress"

    pick_up_first_fill(client)
    assert client.post(f"/api/pharmacy/fills/{DISP_ATORVA_1}/pickup", headers=MAYA).status_code == 409

    r = client.post(url, headers=MAYA, json={"note": "Going away next week"})
    assert r.status_code == 201
    assert r.json()["requires_approval"] is False and r.json()["status"] == "sent_to_pharmacy"
    fill_id = r.json()["dispense_id"]
    after = rx(client, RX_MAYA_ATORVA)
    assert after["refills_remaining"] == 4 and after["dispense_status"] == "sent"
    assert after["latest_fill"]["fill_number"] == 2

    # The demo pharmacy moves it along: sent -> received -> ready, then nothing more.
    assert client.post(f"/api/pharmacy/fills/{fill_id}/simulate-update", headers=MAYA).json()["status"] == "received"
    assert client.post(f"/api/pharmacy/fills/{fill_id}/simulate-update", headers=MAYA).json()["status"] == "ready"
    assert client.post(f"/api/pharmacy/fills/{fill_id}/simulate-update", headers=MAYA).status_code == 409
    assert client.post(f"/api/pharmacy/fills/{fill_id}/pickup", headers=PARK).status_code == 404

    with psycopg.connect(DB) as conn:
        n = conn.execute(
            "SELECT count(*) FROM review_items WHERE kind = 'refill_request' AND patient_id = %s", (P_MAYA,)
        ).fetchone()[0]
        audited = conn.execute(
            "SELECT count(*) FROM audit_events WHERE action = 'refill_sent_to_pharmacy' AND patient_id = %s", (P_MAYA,)
        ).fetchone()[0]
    assert n == 0, "auto-sent refills never reach the clinician queue"
    assert audited == 1


def test_refill_without_refills_needs_clinician_and_approval_flow(client):
    pick_up_first_fill(client)
    with psycopg.connect(DB) as conn:
        conn.execute("UPDATE medication_requests SET refills_remaining = 0 WHERE id = %s", (RX_MAYA_ATORVA,))

    r = client.post(f"/api/pharmacy/prescriptions/{RX_MAYA_ATORVA}/refill-requests", headers=MAYA,
                    json={"note": "Please renew"})
    assert r.status_code == 201 and r.json()["requires_approval"] is True
    req_id = r.json()["id"]
    again = client.post(f"/api/pharmacy/prescriptions/{RX_MAYA_ATORVA}/refill-requests", headers=MAYA, json={})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "pending"

    queue = client.get("/api/clinician/review-queue", headers=OKAFOR).json()
    item = next(i for i in queue if i["kind"] == "refill_request" and i["patient_id"] == P_MAYA)
    assert item["link"] == "/clinician/refills" and "Atorvastatin 20 mg" in item["title"]

    refills = client.get("/api/pharmacy/clinician/refill-requests", headers=OKAFOR).json()
    assert {x["id"] for x in refills} == {req_id, REFILL_HADDAD}
    mine = next(x for x in refills if x["id"] == req_id)
    assert mine["patient_note"] == "Please renew" and "interactions" in mine

    url = f"/api/pharmacy/clinician/refill-requests/{req_id}/decision"
    assert client.post(url, headers=MAYA, json={"decision": "approve"}).status_code == 403
    assert client.post(url, headers=OKAFOR, json={"decision": "approve", "additional_refills": 20}).status_code == 422
    ok = client.post(url, headers=OKAFOR, json={"decision": "approve", "note": "Continue", "additional_refills": 2})
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and ok.json()["dispense_id"]
    assert client.post(url, headers=OKAFOR, json={"decision": "deny", "note": "x"}).status_code == 409

    after = rx(client, RX_MAYA_ATORVA)
    assert after["refills_remaining"] == 2 and after["dispense_status"] == "sent"
    assert after["refill_requests"][0]["status"] == "approved"
    queue = client.get("/api/clinician/review-queue", headers=OKAFOR).json()
    assert item["id"] not in {i["id"] for i in queue}, "deciding the refill resolves the review item"
    with psycopg.connect(DB) as conn:
        actions = [r[0] for r in conn.execute(
            "SELECT action FROM audit_events WHERE patient_id = %s AND action LIKE 'refill_%%'", (P_MAYA,)
        ).fetchall()]
    assert "refill_requested" in actions and "refill_approved" in actions


def test_refill_denial_needs_note_and_only_prescriber_decides(client):
    url = f"/api/pharmacy/clinician/refill-requests/{REFILL_HADDAD}/decision"
    with psycopg.connect(DB) as conn:
        other = conn.execute(
            """
            INSERT INTO users (role, display_name, email, organization_id) VALUES ('clinician', 'Dr. Erik Lindqvist',
            'e.lindqvist@northside.example', %s) RETURNING id::text
            """,
            (ORG,),
        ).fetchone()[0]
        conn.execute("UPDATE practitioners SET user_id = %s WHERE id = %s", (other, DR_LINDQVIST))
    assert client.post(url, headers=as_user(other), json={"decision": "approve"}).status_code == 403
    assert client.get("/api/pharmacy/clinician/refill-requests", headers=as_user(other)).json() == []

    assert client.post(url, headers=OKAFOR, json={"decision": "deny"}).status_code == 422
    d = client.post(url, headers=OKAFOR, json={"decision": "deny", "note": "Let's review your blood pressure first."})
    assert d.status_code == 200 and d.json()["status"] == "denied"
    with psycopg.connect(DB) as conn:
        status, resolution = conn.execute(
            "SELECT status, resolution FROM review_items WHERE id = %s", (REVIEW_HADDAD_REFILL,)
        ).fetchone()
        fills = conn.execute(
            "SELECT count(*) FROM medication_dispenses WHERE medication_request_id = %s", (RX_HADDAD_AMLO,)
        ).fetchone()[0]
    assert status == "resolved" and resolution.startswith("refill_denied")
    assert fills == 1, "a denied refill creates no fill"
    seen = rx(client, RX_HADDAD_AMLO, HADDAD)["refill_requests"][0]
    assert seen["status"] == "denied" and "blood pressure" in seen["decision_note"]


def test_inactive_prescription_cannot_be_refilled(client):
    r = client.post(f"/api/pharmacy/prescriptions/{RX_MAYA_AZITHRO}/refill-requests", headers=MAYA, json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_active"
    assert client.post(f"/api/pharmacy/prescriptions/{RX_MAYA_ATORVA}/refill-requests", headers=MAYA,
                       json={"quantity": 999}).status_code == 422


# --- Adherence ----------------------------------------------------------------------------------


def test_adherence_stats_math():
    today = date(2026, 5, 20)
    d = lambda n: today - timedelta(days=n)  # noqa: E731
    s = adherence_stats({d(0), d(1), d(2), d(4), d(5)}, d(9), today)
    # Today is logged, so the 7-day window is d(6)..d(0): 5 of 7.
    assert (s["taken_7"], s["days_7"], s["pct_7"]) == (5, 7, 71)
    assert (s["taken_30"], s["days_30"], s["pct_30"]) == (5, 10, 50)
    assert s["streak"] == 3 and s["taken_today"]

    # Today not logged yet: it isn't a miss; window is d(7)..d(1).
    s = adherence_stats({d(1), d(2), d(3)}, d(20), today)
    assert (s["taken_7"], s["days_7"], s["pct_7"]) == (3, 7, 43)
    assert s["streak"] == 3 and not s["taken_today"]

    # Started yesterday, no doses logged today yet.
    s = adherence_stats({d(1)}, d(1), today)
    assert (s["pct_7"], s["days_7"], s["streak"]) == (100, 1, 1)
    assert adherence_stats(set(), None, today)["tracking"] is False
    assert adherence_stats(set(), today, today)["pct_7"] is None


def test_dose_logging(client):
    url = f"/api/pharmacy/prescriptions/{RX_MAYA_ATORVA}/doses"
    assert client.post(url, headers=MAYA, json={}).status_code == 409  # not picked up yet
    pick_up_first_fill(client)
    r = client.post(url, headers=MAYA, json={})
    assert r.status_code == 201
    a = r.json()["adherence"]
    assert a["pct_7"] == 100 and a["streak"] == 1 and a["taken_today"]
    assert client.post(url, headers=MAYA, json={}).status_code == 201  # idempotent
    today = clinic_today()
    assert client.post(url, headers=MAYA, json={"taken_on": str(today + timedelta(days=1))}).status_code == 422
    assert client.post(url, headers=MAYA, json={"taken_on": str(today - timedelta(days=8))}).status_code == 422
    assert client.post(url, headers=OKAFOR, json={}).status_code == 403
    assert client.post(f"/api/pharmacy/prescriptions/{RX_HADDAD_AMLO}/doses", headers=MAYA, json={}).status_code == 403

    undo = client.delete(f"{url}/{today}", headers=MAYA)
    assert undo.status_code == 200 and undo.json()["adherence"]["taken_today"] is False
    with psycopg.connect(DB) as conn:
        acts = {r[0] for r in conn.execute("SELECT action FROM audit_events WHERE patient_id = %s", (P_MAYA,)).fetchall()}
    assert {"dose_logged", "dose_unlogged", "fill_picked_up"} <= acts


def test_seeded_low_adherence_shows_in_brief(client):
    detail = rx(client, RX_HADDAD_AMLO, HADDAD)
    assert detail["adherence"]["pct_7"] < 80
    brief = client.get(f"/api/clinician/patients/{P_HADDAD}/brief", headers=OKAFOR).json()
    assert "Low medication adherence" in brief["attention_flags"]
    assert "Refill request pending" in brief["attention_flags"]
    assert any("Amlodipine 5 mg" in b["text"] and "adherence" in b["text"] for b in brief["bullets"])
    maya = client.get(f"/api/clinician/patients/{P_MAYA}/brief", headers=OKAFOR).json()
    assert "Low medication adherence" not in maya["attention_flags"]


def test_timeline_has_prescription_events(client):
    pick_up_first_fill(client)
    events = client.get(f"/api/patients/{P_MAYA}/story", headers=MAYA).json()["events"]
    titles = [e["title"] for e in events]
    assert "Prescription started · Atorvastatin 20 mg" in titles
    assert "Prescription filled · Atorvastatin 20 mg" in titles
    assert "Picked up · Atorvastatin 20 mg" in titles
    keys = [(e["type"], e["ref_id"]) for e in events]
    assert len(keys) == len(set(keys))


# --- Interactions and drug information ----------------------------------------------------------


def test_interactions_from_curated_table(client):
    mine = client.get("/api/pharmacy/interactions", headers=MAYA).json()
    assert [w["between"] for w in mine["warnings"]] == [["Atorvastatin", "Grapefruit juice"]]
    assert "not exhaustive" in mine["notice"]

    cand = client.get("/api/pharmacy/interactions?candidate=clarithromycin", headers=MAYA).json()
    major = [w for w in cand["warnings"] if w["severity"] == "major"]
    assert major and major[0]["between"] == ["Atorvastatin", "Clarithromycin"] and major[0]["involves_candidate"]

    rana = client.get("/api/pharmacy/interactions?candidate=simvastatin", headers=HADDAD).json()
    assert [w["severity"] for w in rana["warnings"]] == ["moderate"]
    assert "20 mg" in rana["warnings"][0]["summary"]

    assert client.get("/api/pharmacy/interactions?candidate=ibuprofen", headers=MAYA).status_code == 404
    assert client.get(f"/api/pharmacy/interactions?patient_id={P_HADDAD}", headers=MAYA).status_code == 403
    assert client.get(f"/api/pharmacy/interactions?patient_id={P_HADDAD}", headers=OKAFOR).status_code == 200
    assert client.get("/api/pharmacy/drugs/ibuprofen", headers=MAYA).status_code == 404
    assert client.get("/api/pharmacy/drugs/amlodipine", headers=MAYA).json()["call_doctor_if"]


# --- Pharmacies and access control --------------------------------------------------------------


def test_pharmacy_directory_and_preference(client):
    all_ = client.get("/api/pharmacy/pharmacies", headers=MAYA).json()["pharmacies"]
    assert len(all_) == 4 and all_[0]["distance_km"] <= all_[-1]["distance_km"]
    h24 = client.get("/api/pharmacy/pharmacies?open_24_hours=true", headers=MAYA).json()["pharmacies"]
    assert [p["id"] for p in h24] == [PH_EASTGATE]

    r = client.put("/api/pharmacy/preferred-pharmacy", headers=MAYA, json={"pharmacy_id": PH_EASTGATE})
    assert r.status_code == 200 and r.json()["pharmacy"]["open_24_hours"]
    assert client.put("/api/pharmacy/preferred-pharmacy", headers=OKAFOR, json={"pharmacy_id": PH_EASTGATE}).status_code == 403
    assert client.put("/api/pharmacy/preferred-pharmacy", headers=MAYA, json={"pharmacy_id": "nope"}).status_code == 404

    # Refills go to the newly preferred pharmacy.
    pick_up_first_fill(client)
    client.post(f"/api/pharmacy/prescriptions/{RX_MAYA_ATORVA}/refill-requests", headers=MAYA, json={})
    assert rx(client, RX_MAYA_ATORVA)["latest_fill"]["pharmacy_name"] == "Eastgate 24-Hour Pharmacy"


def test_role_denials(client):
    assert client.get("/api/pharmacy/prescriptions", headers=ADMIN).status_code == 403
    assert client.get(f"/api/pharmacy/prescriptions?patient_id={P_HADDAD}", headers=MAYA).status_code == 403
    assert client.get("/api/pharmacy/prescriptions", headers=OKAFOR).status_code == 400
    assert client.get(f"/api/pharmacy/prescriptions?patient_id={P_MAYA}", headers=OKAFOR).status_code == 200
    assert client.get(f"/api/pharmacy/prescriptions/{RX_HADDAD_AMLO}", headers=MAYA).status_code == 403
    assert client.get("/api/pharmacy/clinician/refill-requests", headers=MAYA).status_code == 403
    assert client.get("/api/pharmacy/clinician/refill-requests", headers=ADMIN).status_code == 403
    assert client.get("/api/pharmacy/prescriptions?patient_id=not-a-uuid", headers=OKAFOR).status_code == 404


@pytest.mark.parametrize("text,intent", [
    ("I need a refill", "pharmacy"),
    ("where do I pick up my prescription", "pharmacy"),
    ("change my pharmacy", "pharmacy"),
    ("show my medication schedule", "care_plan"),
    ("I feel dizzy since starting my medication", "symptom"),
    ("chest pain after my prescription", "symptom"),
])
def test_pharmacy_intent_routing(text, intent):
    assert rules_triage([{"role": "user", "content": text}], {}).intent == intent, text
