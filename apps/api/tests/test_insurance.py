"""Insurance connections: payers, eligibility, card, card scan, claims (837P/277CA/835), prior auth, jobs."""

import base64
import time
import urllib.error
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse.agents.triage import rules_triage
from bioverse.db.seed import P_HADDAD, U_FRONTDESK, U_HADDAD
from bioverse.db.seeds.s170_insurance import (
    COV_MAYA, COV_PARK, PA_MAYA_ECHO, PARK_NEW_MEMBER_ID, PAYER_EVERGREEN, PAYER_HARBORLINE, PAYER_SUMMIT,
)
from bioverse.jobs import run_job
from bioverse.payers import card_token
from bioverse.payers.gateway import GatewayError
from bioverse.payers.http import HttpClearinghouse
from bioverse.payers.simulated import SimulatedClearinghouse
from bioverse.x12 import build_270, build_837p, parse_271, parse_277ca
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, P_PARK, PARK, as_user
from tests.test_x12 import claim as x12_claim
from tests.test_x12 import env as x12_env
from tests.test_x12 import inquiry as x12_inquiry

FRONT = as_user(U_FRONTDESK)
HADDAD = as_user(U_HADDAD)
CL_CARDIO, CL_LIPID_NEW = "00000000-0000-0000-0000-000000005104", "00000000-0000-0000-0000-000000005105"


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def audit_count(action: str, patient_id: str | None = None) -> int:
    with db() as conn:
        if patient_id:
            return conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = %s AND patient_id = %s",
                                (action, patient_id)).fetchone()["n"]
        return conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = %s", (action,)).fetchone()["n"]


# --- Payer registry and connections ------------------------------------------------------------------


def test_payer_registry_and_connection_admin(client):
    body = client.get("/api/insurance/payers", headers=ADMIN).json()
    payers = {p["name"]: p for p in body["payers"]}
    assert set(payers) == {"Evergreen Mutual Health", "Harborline Health Plan", "Summit Crest Benefits"}
    assert payers["Evergreen Mutual Health"]["status"] == "connected"
    assert payers["Harborline Health Plan"]["connection_type"] == "fhir_payer_api"
    assert "CARIN Blue Button" in payers["Harborline Health Plan"]["fhir_profiles"]
    assert payers["Harborline Health Plan"]["status"] == "disconnected"
    assert client.get("/api/insurance/payers", headers=FRONT).status_code == 200
    assert client.get("/api/insurance/payers", headers=MAYA).status_code == 403
    assert client.get("/api/insurance/payers", headers=OKAFOR).status_code == 403

    url = f"/api/insurance/payers/{PAYER_HARBORLINE}"
    assert client.post(f"{url}/connect", headers=FRONT, json={}).status_code == 403
    # A secret VALUE is refused: only a secret's name is stored.
    r = client.post(f"{url}/connect", headers=ADMIN, json={"credentials_secret_name": "sk-live-9f8e7d6c5b4a"})
    assert r.status_code == 422 and "NAME of the secret" in r.json()["detail"]
    r = client.post(f"{url}/connect", headers=ADMIN, json={"gateway": "http"})
    assert r.status_code == 422 and "BIOVERSE_CLEARINGHOUSE_URL" in r.json()["detail"]
    assert client.post(f"{url}/test", headers=ADMIN).status_code == 409

    r = client.post(f"{url}/connect", headers=ADMIN, json={"credentials_secret_name": "HARBORLINE_API_TOKEN"})
    assert r.status_code == 200 and r.json()["status"] == "connected"
    assert r.json()["credentials_secret_name"] == "HARBORLINE_API_TOKEN"
    t = client.post(f"{url}/test", headers=ADMIN).json()
    assert t["last_test_ok"] is True and "Demo" in t["last_test_message"] and "fhir.harborline.example" in t["last_test_message"]
    assert client.post(f"{url}/disconnect", headers=ADMIN).json()["status"] == "disconnected"
    assert audit_count("payer_connected") == 1 and audit_count("payer_disconnected") == 1
    assert audit_count("payer_connection_tested") == 1


# --- Eligibility --------------------------------------------------------------------------------------


def test_patient_eligibility_check_plain_language_and_x12_storage(client):
    r = client.post(f"/api/insurance/coverage/{COV_MAYA}/eligibility", headers=MAYA)
    assert r.status_code == 200
    check = r.json()
    assert check["status"] == "active" and check["simulated"] and "Simulated" in check["notice"]
    assert "You've met $420 of your $1,500 deductible." in check["summary"]
    assert "Specialist visits: $50 copay." in check["summary"]
    assert check["benefits"]["deductible_individual"]["met_cents"] == 42000
    assert check["benefits"]["deductible_family"]["total_cents"] == 300000
    assert {c["service_type"] for c in check["benefits"]["copays"]} >= {"98", "UC", "88"}

    mine = client.get(f"/api/insurance/eligibility/{check['id']}", headers=MAYA).json()
    assert "request_x12" not in mine
    staff = client.get(f"/api/insurance/eligibility/{check['id']}", headers=FRONT).json()
    assert staff["request_x12"].startswith("ISA*") and "ST*270*" in staff["request_x12"]
    assert "ST*271*" in staff["response_x12"] and "EB*C*IND*30***23*1500" in staff["response_x12"]
    assert client.get(f"/api/insurance/eligibility/{check['id']}", headers=PARK).status_code == 403

    # Billing's own screen shows the check.
    billing = client.get("/api/billing/coverage", headers=MAYA).json()["coverages"][0]
    assert billing["last_check"]["outcome"] == "active"
    assert audit_count("insurance_eligibility_checked", P_MAYA) == 1

    park = client.post(f"/api/insurance/coverage/{COV_PARK}/eligibility", headers=PARK).json()
    assert park["status"] == "inactive" and "not active" in park["summary"][0]
    assert client.post(f"/api/insurance/coverage/{COV_PARK}/eligibility", headers=MAYA).status_code == 403
    assert client.post(f"/api/insurance/coverage/{COV_MAYA}/eligibility", headers=OKAFOR).status_code == 403
    assert client.post(f"/api/insurance/coverage/{COV_MAYA}/eligibility", headers=FRONT).json()["status"] == "active"


def test_disconnected_payer_is_a_readable_error(client):
    client.post(f"/api/insurance/payers/{PAYER_EVERGREEN}/disconnect", headers=ADMIN)
    check = client.post(f"/api/insurance/coverage/{COV_MAYA}/eligibility", headers=MAYA).json()
    assert check["status"] == "error"
    assert "Evergreen Mutual Health is not connected" in check["error"]
    assert check["summary"][0].startswith("We couldn't check this coverage right now")


def test_patients_see_only_their_coverage_staff_see_their_org(client):
    mine = client.get("/api/insurance/coverage", headers=MAYA).json()
    assert mine["coverages"][0]["id"] == COV_MAYA and mine["coverages"][0]["rx_bin"] == "999123"
    assert mine["coverages"][0]["latest_check"]["status"] == "active"      # the seeded check
    assert [a["id"] for a in mine["prior_authorizations"]] == [PA_MAYA_ECHO]
    assert client.get(f"/api/insurance/coverage?patient_id={P_PARK}", headers=MAYA).status_code == 403
    assert client.get("/api/insurance/coverage", headers=OKAFOR).status_code == 403
    assert client.get("/api/insurance/coverage", headers=FRONT).status_code == 400
    assert client.get(f"/api/insurance/coverage?patient_id={P_MAYA}", headers=FRONT).status_code == 200
    with db() as conn:
        conn.execute("INSERT INTO organizations (id, name) VALUES ('00000000-0000-0000-0000-000000015999', 'Elsewhere')")
        conn.execute("UPDATE patients SET organization_id = '00000000-0000-0000-0000-000000015999' WHERE id = %s", (P_HADDAD,))
    assert client.get(f"/api/insurance/coverage?patient_id={P_HADDAD}", headers=FRONT).status_code == 404

    desk = client.get("/api/insurance/front-desk", headers=FRONT).json()
    maya = next(p for p in desk["patients"] if p["id"] == P_MAYA)
    assert maya["coverage"]["payer_display"] == "Evergreen Mutual Health"
    assert client.get("/api/insurance/front-desk", headers=MAYA).status_code == 403


# --- Digital card --------------------------------------------------------------------------------------


def test_card_token_sign_verify_expiry_and_tamper(monkeypatch):
    monkeypatch.setenv("BIOVERSE_CARD_SECRET", "test-secret-" + "x" * 30)
    token, expires = card_token.sign(COV_MAYA, now=1_800_000_000)
    assert token.startswith("BVC1.") and len(token) < 90
    claims = card_token.verify(token, now=1_800_000_000 + 60)
    assert claims.coverage_id == COV_MAYA and claims.expires_at == expires == 1_800_000_000 + card_token.TTL_SECONDS

    with pytest.raises(card_token.TokenError) as e:
        card_token.verify(token, now=expires)
    assert e.value.code == "expired"

    body = token[len(card_token.PREFIX):]
    flipped = body[:10] + ("A" if body[10] != "A" else "B") + body[11:]
    with pytest.raises(card_token.TokenError) as e:
        card_token.verify(card_token.PREFIX + flipped, now=1_800_000_000)
    assert e.value.code in ("bad_signature", "malformed")

    monkeypatch.setenv("BIOVERSE_CARD_SECRET", "a-different-secret-" + "y" * 30)
    with pytest.raises(card_token.TokenError) as e:
        card_token.verify(token, now=1_800_000_000)
    assert e.value.code == "bad_signature"
    assert not card_token.using_default_secret()
    monkeypatch.delenv("BIOVERSE_CARD_SECRET")
    assert card_token.using_default_secret()

    for junk in ("", "hello", "BVC1.!!!", "BVC1.AAAA"):
        with pytest.raises(card_token.TokenError) as e:
            card_token.verify(junk)
        assert e.value.code == "malformed"


def test_digital_card_and_front_desk_verification(client):
    body = client.get("/api/insurance/card", headers=MAYA).json()
    card = body["card"]
    assert card["payer"] == "Evergreen Mutual Health" and card["member_id"] == "NHP-4821-7730"
    assert (card["rx_bin"], card["rx_pcn"], card["rx_group"]) == ("999123", "BVDEMO", "EVGRX01")
    assert card["member_phone"] == "1-800-555-0142" and card["group_number"] == "NS-1001"
    assert {"label": "Specialist visits", "amount_cents": 5000} in card["copays"]
    assert "Wallet" in body["wallet_notice"]
    assert client.get("/api/insurance/card", headers=FRONT).status_code == 403

    token = body["token"]
    assert client.post("/api/insurance/card/verify", headers=MAYA, json={"token": token}).status_code == 403
    v = client.post("/api/insurance/card/verify", headers=FRONT, json={"token": token})
    assert v.status_code == 200
    out = v.json()
    assert out["valid"] and out["patient"]["name"] == "Maya Thornton" and out["coverage"]["member_id"] == "NHP-4821-7730"
    assert out["coverage"]["active_today"] and out["latest_check"]["status"] == "active"
    assert out["dev_secret"] is True
    assert audit_count("insurance_card_verified", P_MAYA) == 1
    assert audit_count("insurance_card_viewed", P_MAYA) == 1

    tampered = token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB")
    bad = client.post("/api/insurance/card/verify", headers=FRONT, json={"token": tampered})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "bad_signature"
    old, _ = card_token.sign(COV_MAYA, now=time.time() - 2 * card_token.TTL_SECONDS)
    expired = client.post("/api/insurance/card/verify", headers=FRONT, json={"token": old})
    assert expired.status_code == 422 and expired.json()["detail"]["code"] == "expired"
    assert "refresh" in expired.json()["detail"]["message"]
    assert audit_count("insurance_card_verify_failed") == 2


# --- Card scan and reported coverage ------------------------------------------------------------------


def test_card_scan_rules_mode_and_limits(client):
    tiny_png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()
    r = client.post("/api/insurance/card-scan", headers=MAYA, json={"image": tiny_png, "media_type": "image/png"})
    assert r.status_code == 200
    assert r.json()["mode"] == "rules" and all(v is None for v in r.json()["fields"].values())
    assert "not kept" in r.json()["message"]
    big = base64.b64encode(b"\x00" * (5 * 1024 * 1024 + 10)).decode()
    assert client.post("/api/insurance/card-scan", headers=MAYA,
                       json={"image": big, "media_type": "image/jpeg"}).status_code == 413
    assert client.post("/api/insurance/card-scan", headers=MAYA,
                       json={"image": tiny_png, "media_type": "application/pdf"}).status_code == 422
    assert client.post("/api/insurance/card-scan", headers=FRONT,
                       json={"image": tiny_png, "media_type": "image/png"}).status_code == 403
    with db() as conn:
        cols = {r["column_name"] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'reported_coverages'").fetchall()}
        detail = conn.execute("SELECT detail FROM audit_events WHERE action = 'insurance_card_scanned'").fetchone()["detail"]
    assert not {"image", "photo", "image_data"} & cols
    assert detail["photo_stored"] is False


def test_reported_card_verified_becomes_billing_coverage(client):
    # Jun's employer plan ended; he adds his new Summit Crest card by hand.
    r = client.post("/api/insurance/reported-coverage", headers=PARK, json={
        "payer_ref": PAYER_SUMMIT, "member_id": PARK_NEW_MEMBER_ID.lower(), "group_number": "SC-2207",
        "rx_bin": "610999", "rx_pcn": "SCRX", "rx_group": "SCG22", "source": "manual"})
    assert r.status_code == 201 and r.json()["status"] == "unverified"
    rid = r.json()["id"]
    assert client.post(f"/api/insurance/reported-coverage/{rid}/verify", headers=MAYA).status_code == 403
    v = client.post(f"/api/insurance/reported-coverage/{rid}/verify", headers=PARK).json()
    assert v["status"] == "verified" and v["coverage_id"]
    billing = client.get("/api/billing/coverage", headers=PARK).json()["coverages"]
    new = next(c for c in billing if c["id"] == v["coverage_id"])
    assert new["eligible_today"] and new["plan_name"] == "Summit Crest Silver PPO"
    assert new["deductible_cents"] == 250000 and new["copays"]["specialist"] == 6000 and new["coinsurance_pct"] == 30
    card = client.get("/api/insurance/card", headers=PARK).json()["card"]
    assert card["payer"] == "Summit Crest Benefits" and card["rx_bin"] == "610999"
    assert client.post(f"/api/insurance/reported-coverage/{rid}/verify", headers=PARK).status_code == 409

    wrong = client.post("/api/insurance/reported-coverage", headers=PARK,
                        json={"payer_ref": PAYER_SUMMIT, "member_id": "SCB-000000-00"}).json()
    nf = client.post(f"/api/insurance/reported-coverage/{wrong['id']}/verify", headers=FRONT).json()
    assert nf["status"] == "not_found" and "couldn't find a member" in nf["check"]["summary"][0]
    assert client.post("/api/insurance/reported-coverage", headers=PARK, json={"member_id": "X12345"}).status_code == 422


# --- Claims --------------------------------------------------------------------------------------------


def test_claim_cycle_837_277ca_835_posts_to_billing(client):
    work = client.get("/api/insurance/claims/worklist", headers=FRONT).json()
    assert CL_LIPID_NEW in {w["claim_id"] for w in work["ready"]}
    seeded = next(s for s in work["submissions"] if s["claim_id"] == CL_CARDIO)
    assert seeded["status"] == "paid" and seeded["ack_category"] == "A2"
    assert any(c["posting_status"] == "posted" for r in work["remittances"] for c in r["claims"])
    assert client.get("/api/insurance/claims/worklist", headers=MAYA).status_code == 403
    assert client.get("/api/insurance/claims/worklist", headers=OKAFOR).status_code == 403

    target = {"claim_id": CL_LIPID_NEW}
    missing = client.post("/api/insurance/claims/preview", headers=FRONT, json={**target, "diagnosis_codes": []})
    assert missing.status_code == 422
    assert "At least one diagnosis code is required" in missing.json()["detail"]["errors"]
    preview = client.post("/api/insurance/claims/preview", headers=FRONT, json={**target, "diagnosis_codes": ["E78.5"]}).json()
    assert "SV1*HC:80061*95*UN*1***1~" in preview["x12_837"] and "HI*ABK:E785~" in preview["x12_837"]

    sub = client.post("/api/insurance/claims/submit", headers=FRONT, json={**target, "diagnosis_codes": ["E78.5"]})
    assert sub.status_code == 201, sub.text
    s = sub.json()
    assert s["status"] == "accepted" and s["ack_message"].startswith("Accepted into adjudication")
    assert s["payer_claim_number"].startswith("EVG")
    assert client.post("/api/insurance/claims/submit", headers=FRONT,
                       json={**target, "diagnosis_codes": ["E78.5"]}).status_code == 409
    detail = client.get(f"/api/insurance/claims/submissions/{s['id']}", headers=FRONT).json()
    assert parse_277ca(detail["x12_277ca"]).claims[0].accepted

    fetched = client.post("/api/insurance/remittances/fetch", headers=FRONT).json()
    assert fetched["remittances"] == 1 and fetched["claims_posted"] == 1
    assert client.post("/api/insurance/remittances/fetch", headers=FRONT).json()["remittances"] == 0

    claim = client.get(f"/api/billing/claims/{CL_LIPID_NEW}", headers=MAYA).json()
    # Lab: allowed $45, all toward Maya's deductible.
    assert claim["status"] == "paid" and claim["eob"]["deductible_cents"] == 4500 and claim["eob"]["plan_paid_cents"] == 0
    statements = client.get("/api/billing/statements", headers=MAYA).json()["statements"]
    assert any(st["claim_id"] == CL_LIPID_NEW and st["amount_cents"] == 4500 for st in statements)
    cov = client.get("/api/billing/coverage", headers=MAYA).json()["coverages"][0]
    assert cov["deductible_remaining_cents"] == 108000 - 4500
    after = client.post(f"/api/insurance/coverage/{COV_MAYA}/eligibility", headers=MAYA).json()
    assert "You've met $465 of your $1,500 deductible." in after["summary"]     # the payer's accumulator moved too
    with db() as conn:
        n = conn.execute("SELECT count(*) AS n FROM notifications WHERE kind = 'insurance_claim_processed'").fetchone()["n"]
    assert n == 1
    assert audit_count("insurance_remittance_posted", P_MAYA) == 1
    assert audit_count("insurance_claim_submitted", P_MAYA) == 1


def test_denial_without_prior_auth_shows_carc_in_plain_language(client):
    with db() as conn:
        claim_id = conn.execute(
            """
            INSERT INTO claims (patient_id, coverage_id, practitioner_id, service_code, service_name, category,
                                service_date, billed_cents, status)
            VALUES (%s, %s, '00000000-0000-0000-0000-000000000301', 'ECHO', 'Echocardiogram', 'imaging',
                    current_date - 1, 180000, 'submitted') RETURNING id::text
            """,
            (P_MAYA, COV_MAYA),
        ).fetchone()["id"]
    draft = client.post("/api/insurance/claims/draft", headers=FRONT, json={"claim_id": claim_id}).json()
    assert draft["prior_authorization_required"] and draft["prior_authorization"] is None      # still pended
    client.post("/api/insurance/claims/submit", headers=FRONT, json={"claim_id": claim_id, "diagnosis_codes": ["R07.9"]})
    run = client.post("/api/insurance/remittances/fetch", headers=FRONT).json()
    assert run["claims_posted"] == 1
    claim = client.get(f"/api/billing/claims/{claim_id}", headers=MAYA).json()
    assert claim["status"] == "denied" and "prior authorization" in claim["denial_reason"]
    sub = next(s for s in client.get("/api/insurance/claims/worklist", headers=FRONT).json()["submissions"]
               if s["claim_id"] == claim_id)
    assert sub["status"] == "denied" and sub["denial"][0]["reason_code"] == "197"
    assert "prior authorization" in sub["denial"][0]["plain"]


def test_prior_auth_tracker_and_approved_auth_travels_on_the_claim(client):
    assert client.get("/api/insurance/prior-auths", headers=MAYA).json()[0]["status"] == "pended"
    assert client.get("/api/insurance/prior-auths", headers=OKAFOR).status_code == 403
    staff_list = client.get("/api/insurance/prior-auths", headers=FRONT).json()
    assert PA_MAYA_ECHO in {a["id"] for a in staff_list}
    url = f"/api/insurance/prior-auths/{PA_MAYA_ECHO}"
    assert client.patch(url, headers=MAYA, json={"status": "approved"}).status_code == 403
    today = datetime.now().date()
    r = client.patch(url, headers=FRONT, json={"status": "approved", "valid_from": str(today - timedelta(days=5)),
                                               "valid_to": str(today + timedelta(days=60))})
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["decided_at"]
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM notifications WHERE kind = 'prior_auth_decided'").fetchone()["n"] == 1
        claim_id = conn.execute(
            """
            INSERT INTO claims (patient_id, coverage_id, practitioner_id, service_code, service_name, category,
                                service_date, billed_cents, status)
            VALUES (%s, %s, '00000000-0000-0000-0000-000000000301', 'ECHO', 'Echocardiogram', 'imaging',
                    current_date, 180000, 'submitted') RETURNING id::text
            """,
            (P_MAYA, COV_MAYA),
        ).fetchone()["id"]
    preview = client.post("/api/insurance/claims/preview", headers=FRONT,
                          json={"claim_id": claim_id, "diagnosis_codes": ["R07.9"]}).json()
    assert "REF*G1*EVG-PA-26-00417~" in preview["x12_837"]

    new = client.post("/api/insurance/prior-auths", headers=FRONT, json={
        "patient_id": P_MAYA, "procedure_code": "93306", "description": "Repeat echo", "diagnosis_codes": ["bad"]})
    assert new.status_code == 422
    new = client.post("/api/insurance/prior-auths", headers=FRONT, json={
        "patient_id": P_MAYA, "procedure_code": "93306", "description": "Repeat echo", "diagnosis_codes": ["I10"]})
    assert new.status_code == 201 and new.json()["status"] == "submitted" and new.json()["payer_name"] == "Evergreen Mutual Health"
    assert audit_count("prior_auth_requested", P_MAYA) == 1 and audit_count("prior_auth_updated", P_MAYA) == 1


def test_835_import_unmatched_duplicate_and_unbalanced(client):
    from tests.test_x12 import remittance
    from bioverse.x12 import build_835
    from bioverse.db.seeds.s170_insurance import ORG_NPI

    remit = remittance()
    remit.payee.npi = ORG_NPI
    text = build_835(remit, x12_env(9001))
    r = client.post("/api/insurance/remittances/import", headers=FRONT, json={"x12": text})
    assert r.status_code == 201
    assert {c["posting_status"] for c in r.json()["claims"]} == {"unmatched"}
    again = client.post("/api/insurance/remittances/import", headers=FRONT, json={"x12": text}).json()
    assert again["duplicate"] is True
    bad = client.post("/api/insurance/remittances/import", headers=FRONT,
                      json={"x12": text.replace("CAS*PR*3*50~", "CAS*PR*3*40~")})
    assert bad.status_code == 422 and any("does not equal" in e for e in bad.json()["detail"]["errors"])
    remits = client.get("/api/insurance/remittances", headers=FRONT).json()
    imported = next(x for x in remits if x["source"] == "imported")
    assert imported["provider_adjustment_cents"] == 1375
    assert {p["label"] for p in imported["provider_adjustments"]} == {"Overpayment recovery", "Interest owed"}


# --- Simulated gateway and HTTP adapter --------------------------------------------------------------


def test_simulated_clearinghouse_member_checks(client):
    from bioverse.db.seeds.s170_insurance import ORG_NPI
    from bioverse.x12.models import Provider, Subscriber

    with db() as conn:
        sim = SimulatedClearinghouse(conn)
        provider = Provider(name="Northside Health", npi=ORG_NPI)
        ok = parse_271(sim.eligibility(build_270(x12_inquiry(provider=provider), x12_env())))
        assert ok.status == "active" and ok.deductible_individual.remaining_cents == 108000
        unknown = x12_inquiry(provider=provider, subscriber=Subscriber(
            first_name="Maya", last_name="Thornton", birth_date=datetime(1972, 3, 9).date(), member_id="NOPE-1"))
        assert parse_271(sim.eligibility(build_270(unknown, x12_env()))).rejections[0].code == "75"
        wrong_dob = x12_inquiry(provider=provider, subscriber=Subscriber(
            first_name="Maya", last_name="Thornton", birth_date=datetime(1980, 1, 1).date(), member_id="NHP-4821-7730"))
        assert parse_271(sim.eligibility(build_270(wrong_dob, x12_env()))).rejections[0].code == "58"

        c = x12_claim()
        c.subscriber.member_id = "NOPE-1"
        ack = parse_277ca(sim.submit_claims(build_837p(c, x12_env())))
        assert not ack.claims[0].accepted and ack.claims[0].category_code == "A3" and ack.claims[0].status_code == "33"
        assert sim.fetch_remittances({"payer_id": "EVGM1", "id": PAYER_EVERGREEN}) == []


class _Resp:
    def __init__(self, text):
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.text.encode()


def test_http_clearinghouse_construction_and_errors(monkeypatch):
    monkeypatch.delenv("BIOVERSE_CLEARINGHOUSE_URL", raising=False)
    with pytest.raises(GatewayError, match="BIOVERSE_CLEARINGHOUSE_URL is not set"):
        HttpClearinghouse()
    with pytest.raises(GatewayError, match="must use https"):
        HttpClearinghouse(url="http://clearinghouse.example")
    with pytest.raises(GatewayError, match="secret name"):
        HttpClearinghouse(url="https://ch.example", secret_name="sk-12345")

    monkeypatch.setenv("BIOVERSE_CLEARINGHOUSE_URL", "https://ch.example/x12/")
    seen = {}

    def ok_opener(req, timeout):
        seen["url"], seen["auth"], seen["type"] = req.full_url, req.get_header("Authorization"), req.get_header("Content-type")
        return _Resp("ISA*...")

    monkeypatch.setenv("CH_TOKEN", "t0ken")
    gw = HttpClearinghouse(secret_name="CH_TOKEN", opener=ok_opener)
    assert gw.eligibility("ISA*270") == "ISA*..."
    assert seen == {"url": "https://ch.example/x12/eligibility", "auth": "Bearer t0ken", "type": "application/edi-x12"}

    monkeypatch.delenv("CH_TOKEN")
    with pytest.raises(GatewayError, match="secret CH_TOKEN is not available"):
        gw.eligibility("ISA*270")

    def refused(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)

    with pytest.raises(GatewayError, match="refused our credentials"):
        HttpClearinghouse(opener=refused).submit_claims("ISA*837")

    def down(req, timeout):
        raise urllib.error.URLError("connection refused")

    with pytest.raises(GatewayError, match="Could not reach the clearinghouse at ch.example"):
        HttpClearinghouse(opener=down).test_connection({"payer_id": "X"})


# --- Jobs -----------------------------------------------------------------------------------------------


def _book(conn, patient_id: str, hours_ahead: int) -> str:
    starts = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    slot = conn.execute(
        "INSERT INTO slots (practitioner_id, starts_at, status) VALUES ('00000000-0000-0000-0000-000000000301', %s, 'booked') "
        "RETURNING id",
        (starts.replace(minute=7, second=0, microsecond=0),),
    ).fetchone()["id"]
    return conn.execute(
        "INSERT INTO appointments (patient_id, practitioner_id, slot_id) VALUES (%s, '00000000-0000-0000-0000-000000000301', %s) "
        "RETURNING id::text",
        (patient_id, slot),
    ).fetchone()["id"]


def test_eligibility_job_rechecks_upcoming_visits_and_flags_staff(client):
    with db() as conn:
        conn.execute("UPDATE appointments SET status = 'cancelled'")      # only our two visits count
        _book(conn, P_MAYA, 30)
        _book(conn, P_PARK, 50)
        conn.commit()
        first = run_job(conn, "insurance_eligibility")
        assert first["status"] == "succeeded", first
        assert first["detail"]["checked"] == 1 and first["detail"]["flagged"] == 1
        second = run_job(conn, "insurance_eligibility")
        assert second["detail"]["checked"] == 0 and second["detail"]["flagged"] == 0
        flags = conn.execute("SELECT title, body, user_id::text FROM notifications WHERE kind = 'insurance_coverage_flag'").fetchall()
        checks = conn.execute("SELECT status, trigger FROM insurance_eligibility_checks WHERE trigger = 'job'").fetchall()
    assert len(flags) == 1 and flags[0]["user_id"] == U_FRONTDESK and "Park" not in flags[0]["body"]
    assert [c["status"] for c in checks] == ["active"]
    desk = client.get("/api/insurance/front-desk", headers=FRONT).json()
    assert len(desk["upcoming"]) == 2


def test_remits_job_pays_accepted_claims(client):
    client.post("/api/insurance/claims/submit", headers=FRONT, json={"claim_id": CL_LIPID_NEW, "diagnosis_codes": ["E78.5"]})
    with db() as conn:
        result = run_job(conn, "insurance_remits")
        assert result["status"] == "succeeded" and result["detail"]["claims_posted"] == 1
        assert run_job(conn, "insurance_remits")["detail"]["claims_posted"] == 0


# --- Front door and FHIR -----------------------------------------------------------------------------


@pytest.mark.parametrize("text,intent", [
    ("show me my insurance card", "insurance"),
    ("am I covered?", "insurance"),
    ("check my benefits", "insurance"),
    ("is my insurance still active", "insurance"),
    ("what's my deductible", "billing"),
    ("is this covered by my insurance", "billing"),
    ("my insurance card is in my bag and I have chest pain", "symptom"),
])
def test_insurance_intents(text, intent):
    assert rules_triage([{"role": "user", "content": text}], {}).intent == intent, text


def test_fhir_coverage_bundle(client):
    b = client.get(f"/api/insurance/fhir/Coverage?patient=Patient/{P_MAYA}", headers=MAYA).json()
    assert b["resourceType"] == "Bundle" and b["total"] == 1
    cov = b["entry"][0]["resource"]
    assert cov["resourceType"] == "Coverage" and cov["subscriberId"] == "NHP-4821-7730"
    assert "C4BB-Coverage" in cov["meta"]["profile"][0]
    assert {c["type"]["coding"][0]["code"] for c in cov["class"]} >= {"group", "plan", "rxbin", "rxpcn", "rxgroup"}
    assert cov["payor"][0]["identifier"]["value"] == "EVGM1"
    assert client.get(f"/api/insurance/fhir/Coverage?patient={P_MAYA}", headers=PARK).status_code == 403
    assert audit_count("fhir_read", P_MAYA) >= 1
