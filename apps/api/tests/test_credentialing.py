"""Credentialing: NPI check digits, the verification queue, the directory gate, and the expiry job."""

from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse.db.seeds.s120_consultations import (
    CR_BENALI, CR_CASTELLANO, CR_MENSAH, CR_WHITFIELD, DR_BENALI, DR_CASTELLANO, DR_MENSAH, DR_WHITFIELD,
    U_BENALI, U_CASTELLANO, U_MENSAH, U_WHITFIELD,
)
from bioverse.jobs import run_job
from bioverse.routers.credentialing import luhn_ok, npi_check_digit, npi_is_valid, npi_problem
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, as_user

CASTELLANO = as_user(U_CASTELLANO)
BENALI = as_user(U_BENALI)
MENSAH = as_user(U_MENSAH)


# --- NPI ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("npi", ["1234567893", "1000000012", "1000000087", "1245319599"])
def test_valid_npis(npi):
    assert npi_is_valid(npi) and npi_problem(npi) is None


@pytest.mark.parametrize("npi,problem", [
    ("1234567890", "check digit"),     # one digit off the CMS example
    ("1234567839", "check digit"),     # transposed digits
    ("123456789", "10 digits"),
    ("12345678930", "10 digits"),
    ("12345678a3", "10 digits"),
    ("3234567893", "starts with 1"),
    ("", "10 digits"),
])
def test_invalid_npis(npi, problem):
    assert not npi_is_valid(npi)
    assert problem in npi_problem(npi)


def test_check_digit_uses_the_80840_prefix():
    # CMS example: 123456789 -> 3. Plain Luhn over the nine digits alone would give 7.
    assert npi_check_digit("123456789") == 3
    assert luhn_ok("808401234567893") and not luhn_ok("1234567893")
    for stem in ("100000001", "187654321", "155555555", "299999999"):
        npi = stem + str(npi_check_digit(stem))
        assert npi_is_valid(npi)
        wrong = stem + str((npi_check_digit(stem) + 1) % 10)
        assert not npi_is_valid(wrong)


def test_npi_endpoint(client):
    assert client.get("/api/credentialing/npi/1234567893", headers=ADMIN).json()["valid"] is True
    bad = client.get("/api/credentialing/npi/1234567890", headers=OKAFOR).json()
    assert bad["valid"] is False and "check digit" in bad["problem"]
    assert client.get("/api/credentialing/npi/1234567893", headers=MAYA).status_code == 403


# --- Queue and decisions -------------------------------------------------------------------------


def directory_ids(client, **params):
    r = client.get("/api/consultations/clinicians", headers=MAYA, params=params)
    assert r.status_code == 200, r.text
    return {c["id"] for c in r.json()["clinicians"]}


def test_admin_queue_shows_pending_and_expiring(client):
    pending = client.get("/api/credentialing/credentials?filter=pending", headers=ADMIN).json()["credentials"]
    assert [c["id"] for c in pending] == [CR_CASTELLANO]
    assert pending[0]["npi_valid"] is True
    expiring = client.get("/api/credentialing/credentials?filter=expiring", headers=ADMIN).json()["credentials"]
    ids = [c["id"] for c in expiring]
    assert CR_WHITFIELD in ids and CR_MENSAH in ids
    whit = next(c for c in expiring if c["id"] == CR_WHITFIELD)
    assert whit["expiring_soon"] and whit["days_to_expiry"] == 20
    assert next(c for c in expiring if c["id"] == CR_MENSAH)["lapsed"] is True
    summary = client.get("/api/credentialing/summary", headers=ADMIN).json()
    assert summary["pending"] == 1 and summary["attention"] >= 1
    assert "simulated" in summary["notice"]


def test_only_admins_run_the_queue(client):
    for who in (MAYA, OKAFOR):
        assert client.get("/api/credentialing/credentials", headers=who).status_code == 403
        assert client.post(f"/api/credentialing/credentials/{CR_CASTELLANO}/verify", headers=who, json={}).status_code == 403
        assert client.post(f"/api/credentialing/credentials/{CR_CASTELLANO}/reject", headers=who,
                           json={"reason": "no"}).status_code == 403


def test_verify_adds_clinician_to_directory_and_is_audited(client):
    assert DR_CASTELLANO not in directory_ids(client)
    r = client.post(f"/api/credentialing/credentials/{CR_CASTELLANO}/verify", headers=ADMIN, json={"notes": "Checked"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "verified" and body["verified_by_name"] == "Northside Operations"
    demo = [c for c in body["verification_checks"] if c["demo"]]
    assert demo and all("simulated" in c["detail"] for c in demo)
    assert DR_CASTELLANO in directory_ids(client, specialty="Psychiatry")
    # Already decided
    assert client.post(f"/api/credentialing/credentials/{CR_CASTELLANO}/verify", headers=ADMIN, json={}).status_code == 409
    with psycopg.connect(DB) as conn:
        n = conn.execute("SELECT count(*) FROM audit_events WHERE action = 'credential_verified' AND entity_id = %s",
                         (CR_CASTELLANO,)).fetchone()[0]
    assert n == 1


def test_reject_needs_a_reason(client):
    url = f"/api/credentialing/credentials/{CR_CASTELLANO}/reject"
    assert client.post(url, headers=ADMIN, json={"reason": ""}).status_code == 422
    r = client.post(url, headers=ADMIN, json={"reason": "License number not found on the state board"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert r.json()["decision_reason"].startswith("License number")
    assert DR_CASTELLANO not in directory_ids(client)
    with psycopg.connect(DB) as conn:
        detail = conn.execute("SELECT detail FROM audit_events WHERE action = 'credential_rejected'").fetchone()[0]
    assert detail["reason"].startswith("License number")


def test_cannot_verify_an_expired_license(client):
    with psycopg.connect(DB) as conn:
        conn.execute("UPDATE practitioner_credentials SET expires_on = current_date - 3, issued_on = NULL WHERE id = %s",
                     (CR_CASTELLANO,))
    r = client.post(f"/api/credentialing/credentials/{CR_CASTELLANO}/verify", headers=ADMIN, json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "checks_failed"


def test_suspension_removes_clinician_immediately(client):
    assert DR_BENALI in directory_ids(client)
    r = client.post(f"/api/credentialing/credentials/{CR_BENALI}/suspend", headers=ADMIN,
                    json={"reason": "Board inquiry pending"})
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    assert DR_BENALI not in directory_ids(client)
    assert client.get(f"/api/consultations/clinicians/{DR_BENALI}", headers=MAYA).status_code == 404
    mine = client.get("/api/credentialing/mine", headers=BENALI).json()
    assert mine["credentialed"] is False and "suspended" in mine["message"]


def test_clinician_submits_own_license(client):
    body = {"license_number": "md-demo 99", "jurisdiction": "ny", "license_type": "MD", "npi": "1234567890",
            "expires_on": "2030-01-01"}
    bad = client.post("/api/credentialing/mine", headers=MENSAH, json=body)
    assert bad.status_code == 422 and "check digit" in bad.text
    body["npi"] = "1234567893"
    r = client.post("/api/credentialing/mine", headers=MENSAH, json=body)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending" and r.json()["jurisdiction"] == "NY" and r.json()["license_number"] == "MD-DEMO99"
    assert client.post("/api/credentialing/mine", headers=MENSAH, json=body).status_code == 409   # duplicate
    past = {**body, "license_number": "MD-OLD-1", "expires_on": "2020-01-01"}
    assert client.post("/api/credentialing/mine", headers=MENSAH, json=past).status_code == 422
    # Pending does not credential: still out of the directory until an admin verifies it.
    assert DR_MENSAH not in directory_ids(client)
    assert client.post("/api/credentialing/mine", headers=MAYA, json=body).status_code == 403


# --- Expiry job ---------------------------------------------------------------------------------


def notes_for(conn, key_like):
    return conn.execute(
        "SELECT user_id::text, title, dedupe_key FROM notifications WHERE dedupe_key LIKE %s ORDER BY dedupe_key",
        (key_like,),
    ).fetchall()


def test_expiry_job_warns_and_expires(client):
    with psycopg.connect(DB, row_factory=dict_row) as conn:
        now = datetime.now(timezone.utc)
        res = run_job(conn, "credential_expiry", now)
        assert res["status"] == "succeeded", res
        assert res["detail"]["expired"] == 1
        st = conn.execute("SELECT status FROM practitioner_credentials WHERE id = %s", (CR_MENSAH,)).fetchone()["status"]
        assert st == "expired"
        # Whitfield: 20 days out gets the 30-day notice only (admin and the clinician).
        whit = notes_for(conn, f"credential:{CR_WHITFIELD}:%")
        assert {n["dedupe_key"].rsplit(":", 1)[1] for n in whit} == {"30d"}
        assert {n["user_id"] for n in whit} >= {U_WHITFIELD}
        assert any(n["title"].startswith("License expiring") for n in whit)
        # Idempotent
        again = run_job(conn, "credential_expiry", now)
        assert again["detail"] == {"warned": 0, "expired": 0}
        assert len(notes_for(conn, f"credential:{CR_WHITFIELD}:%")) == len(whit)
        # Two weeks later: the 7-day notice.
        later = run_job(conn, "credential_expiry", now + timedelta(days=14))
        assert later["detail"]["warned"] == 1
        keys = {n["dedupe_key"].rsplit(":", 1)[1] for n in notes_for(conn, f"credential:{CR_WHITFIELD}:%")}
        assert keys == {"30d", "7d"}
        # And after the date it is expired and gone from the directory.
        run_job(conn, "credential_expiry", now + timedelta(days=22))
        st = conn.execute("SELECT status FROM practitioner_credentials WHERE id = %s", (CR_WHITFIELD,)).fetchone()["status"]
        assert st == "expired"
    assert DR_WHITFIELD not in directory_ids(client)


def test_sixty_day_notice(client):
    with psycopg.connect(DB, row_factory=dict_row) as conn:
        conn.execute("UPDATE practitioner_credentials SET expires_on = current_date + 45 WHERE id = %s", (CR_BENALI,))
        conn.commit()
        run_job(conn, "credential_expiry", datetime.now(timezone.utc))
        keys = {n["dedupe_key"].rsplit(":", 1)[1] for n in notes_for(conn, f"credential:{CR_BENALI}:%")}
    assert keys == {"60d"}
