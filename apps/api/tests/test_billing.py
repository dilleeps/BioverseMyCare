"""Billing & Coverage: estimate math, eligibility, claims, payments, plans and financial assistance."""

import psycopg
import pytest

from bioverse.agents.triage import rules_triage
from bioverse.db.seed import P_HADDAD, U_HADDAD
from bioverse.db.seeds.s050_billing_pharmacy import (
    CL_LIPID_OLD, CL_PHYSICAL, COV_MAYA, COV_PARK, FA_HADDAD, ST_CARDIO, ST_HADDAD_ECHO, ST_HADDAD_VISIT,
)
from bioverse.routers.billing import calculate_estimate, split_installments
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, PARK, as_user

HADDAD = as_user(U_HADDAD)

COV = {
    "deductible_cents": 150000, "deductible_met_cents": 42000,
    "oop_max_cents": 400000, "oop_met_cents": 61500,
    "coinsurance_pct": 20, "oon_coinsurance_pct": 40,
    "copays": {"primary_care": 2500, "specialist": 5000, "telehealth": 1500},
}


def cov(**over):
    return {**COV, **over}


def est(allowed, category, coverage=COV, in_network=True, price=None):
    return calculate_estimate(allowed_cents=allowed, category=category, coverage=coverage,
                              in_network=in_network, price_cents=price)


# --- Estimate math -----------------------------------------------------------------------------


def test_copay_applies_and_skips_deductible():
    r = est(26000, "specialist")
    assert (r["copay_cents"], r["deductible_cents"], r["coinsurance_cents"]) == (5000, 0, 0)
    assert r["patient_cents"] == 5000 and r["plan_cents"] == 21000
    assert any("copay" in s for s in r["steps"])


def test_copay_never_exceeds_allowed_amount():
    r = est(1000, "telehealth")
    assert r["patient_cents"] == 1000 and r["plan_cents"] == 0


def test_service_fully_inside_remaining_deductible():
    r = est(90000, "imaging")  # 108000 deductible left
    assert r["deductible_cents"] == 90000 and r["coinsurance_cents"] == 0 and r["patient_cents"] == 90000


def test_deductible_partly_left_then_coinsurance():
    r = est(90000, "imaging", cov(deductible_met_cents=120000))  # 30000 left
    assert r["deductible_cents"] == 30000
    assert r["coinsurance_cents"] == 12000  # 20% of 60000
    assert r["patient_cents"] == 42000 and r["plan_cents"] == 48000


def test_deductible_met_only_coinsurance_rounded_half_up():
    r = est(4503, "lab", cov(deductible_met_cents=150000))
    assert r["deductible_cents"] == 0
    assert r["coinsurance_cents"] == 901  # 20% of 4503 = 900.6 -> 901
    assert r["patient_cents"] + r["plan_cents"] == 4503


def test_out_of_pocket_maximum_caps_share():
    r = est(90000, "imaging", cov(oop_met_cents=380000))  # 20000 OOP left
    assert r["deductible_cents"] + r["coinsurance_cents"] == 90000
    assert r["patient_cents"] == 20000 and r["oop_cap_reduction_cents"] == 70000
    assert r["plan_cents"] == 70000


def test_out_of_pocket_maximum_caps_copay_too():
    r = est(26000, "specialist", cov(oop_met_cents=398000))
    assert r["patient_cents"] == 2000


def test_out_of_pocket_met_means_zero():
    r = est(90000, "imaging", cov(oop_met_cents=400000))
    assert r["patient_cents"] == 0 and r["plan_cents"] == 90000


def test_out_of_network_ignores_copay_and_uses_oon_rate():
    r = est(26000, "specialist", cov(deductible_met_cents=150000), in_network=False)
    assert r["copay_cents"] == 0
    assert r["coinsurance_cents"] == 10400  # 40% of 26000
    assert any("out of network" in s for s in r["steps"])


def test_no_coverage_is_self_pay_price():
    r = est(26000, "specialist", coverage=None, price=38000)
    assert r["patient_cents"] == 38000 and r["plan_cents"] == 0


def test_estimate_endpoint_and_network_check(client):
    r = client.get("/api/billing/estimate?service_code=SPEC_VISIT", headers=MAYA).json()
    assert r["patient_cents"] == 5000 and r["in_network"] and r["coverage"]["payer"] == "Evergreen Mutual Health"
    echo = client.get("/api/billing/estimate?service_code=ECHO", headers=MAYA).json()
    assert echo["patient_cents"] == 90000 and echo["steps"]

    with psycopg.connect(DB) as conn:
        oon = conn.execute(
            """
            INSERT INTO practitioners (organization_id, name, specialty, location_name, accepted_plans)
            SELECT organization_id, 'Dr. Out Of Network', 'Cardiology', 'Elsewhere', '{}' FROM patients WHERE id = %s
            RETURNING id::text
            """,
            (P_MAYA,),
        ).fetchone()[0]
    r = client.get(f"/api/billing/estimate?service_code=SPEC_VISIT&practitioner_id={oon}", headers=MAYA).json()
    assert r["in_network"] is False and r["copay_cents"] == 0
    # 26000 all within the 108000 deductible left.
    assert r["patient_cents"] == 26000

    assert client.get("/api/billing/estimate?service_code=NOPE", headers=MAYA).status_code == 404
    # Park's coverage ended: self-pay price.
    park = client.get("/api/billing/estimate?service_code=SPEC_VISIT", headers=PARK).json()
    assert park["coverage"] is None and park["patient_cents"] == 38000


# --- Coverage and eligibility ---------------------------------------------------------------------


def test_coverage_masks_member_id_and_reveal_is_audited(client):
    body = client.get("/api/billing/coverage", headers=MAYA).json()
    c = body["coverages"][0]
    assert "member_id" not in c and c["member_id_masked"].endswith("7730")
    assert c["deductible_remaining_cents"] == 108000 and c["oop_remaining_cents"] == 338500
    assert "Demo payer" in body["notice"]

    full = client.get(f"/api/billing/coverage/{COV_MAYA}/member-id", headers=MAYA).json()
    assert full["member_id"] == "NHP-4821-7730"
    with psycopg.connect(DB) as conn:
        n = conn.execute(
            "SELECT count(*) FROM audit_events WHERE action = 'member_id_revealed' AND patient_id = %s", (P_MAYA,)
        ).fetchone()[0]
    assert n == 1


def test_eligibility_check_active_and_inactive(client):
    r = client.post(f"/api/billing/coverage/{COV_MAYA}/eligibility", headers=MAYA)
    assert r.status_code == 200
    assert r.json()["status"] == "active" and r.json()["benefits"]["copays"]["specialist"] == 5000
    assert r.json()["payer"] == "Evergreen Mutual Health"

    park = client.post(f"/api/billing/coverage/{COV_PARK}/eligibility", headers=PARK).json()
    assert park["status"] == "inactive" and "copays" not in park["benefits"]

    # Not your coverage.
    assert client.post(f"/api/billing/coverage/{COV_PARK}/eligibility", headers=MAYA).status_code == 403
    with psycopg.connect(DB) as conn:
        n = conn.execute(
            "SELECT count(*) FROM audit_events WHERE action = 'eligibility_checked' AND patient_id = %s", (P_MAYA,)
        ).fetchone()[0]
    assert n == 1
    last = client.get("/api/billing/coverage", headers=MAYA).json()["coverages"][0]["last_check"]
    assert last["outcome"] == "active"


# --- Claims -------------------------------------------------------------------------------------


def test_claims_with_eob_and_appeal(client):
    claims = client.get("/api/billing/claims", headers=MAYA).json()
    statuses = {c["status"] for c in claims}
    assert {"paid", "denied", "in_review"} <= statuses
    physical = next(c for c in claims if c["id"] == CL_PHYSICAL)
    eob = physical["eob"]
    assert eob["allowed_cents"] == eob["plan_paid_cents"] + eob["patient_resp_cents"]
    assert next(c for c in claims if c["status"] == "in_review")["eob"] is None

    assert client.post(f"/api/billing/claims/{CL_PHYSICAL}/appeal", headers=MAYA,
                       json={"reason": "I think this was billed wrongly."}).status_code == 409
    r = client.post(f"/api/billing/claims/{CL_LIPID_OLD}/appeal", headers=MAYA,
                    json={"reason": "My doctor ordered this test for a known condition."})
    assert r.status_code == 200 and r.json()["status"] == "appealed"
    assert client.get(f"/api/billing/claims/{CL_PHYSICAL}", headers=PARK).status_code == 403


# --- Payments -----------------------------------------------------------------------------------


def balance(client, statement_id, headers=MAYA):
    body = client.get("/api/billing/statements", headers=headers).json()
    return next(s for s in body["statements"] if s["id"] == statement_id)


def test_payment_cannot_exceed_balance_and_rejects_card_fields(client):
    url = f"/api/billing/statements/{ST_CARDIO}/payments"
    assert balance(client, ST_CARDIO)["balance_cents"] == 5000

    over = client.post(url, headers=MAYA, json={"amount_cents": 5001})
    assert over.status_code == 422 and over.json()["detail"]["code"] == "exceeds_balance"

    for extra in ({"card_number": "4242424242424242"}, {"cvv": "123"}, {"card": {"number": "4242"}},
                  {"expiry": "12/30"}, {"bank_account": "000123"}):
        r = client.post(url, headers=MAYA, json={"amount_cents": 100, **extra})
        assert r.status_code == 422, extra
    for bad in ({"amount_cents": 10.5}, {"amount_cents": "100"}, {"amount_cents": 0}, {"amount_cents": -5}, {}):
        assert client.post(url, headers=MAYA, json=bad).status_code == 422, bad
    assert balance(client, ST_CARDIO)["balance_cents"] == 5000, "rejected requests must not record anything"

    ok = client.post(url, headers=MAYA, json={"amount_cents": 2000})
    assert ok.status_code == 201 and ok.json()["balance_cents"] == 3000
    assert ok.json()["receipt_number"].startswith("R-")
    rest = client.post(url, headers=MAYA, json={"amount_cents": 3000})
    assert rest.status_code == 201 and rest.json()["balance_cents"] == 0
    assert balance(client, ST_CARDIO)["status"] == "paid"
    assert client.post(url, headers=MAYA, json={"amount_cents": 1}).status_code == 409

    receipt = client.get(f"/api/billing/payments/{ok.json()['id']}", headers=MAYA).json()
    assert receipt["amount_cents"] == 2000 and receipt["balance_after_cents"] == 3000
    assert "no card details" in receipt["notice"]
    assert client.get(f"/api/billing/payments/{ok.json()['id']}", headers=PARK).status_code == 403

    with psycopg.connect(DB) as conn:
        cols = [r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'payments'"
        ).fetchall()]
        audited = conn.execute(
            "SELECT count(*) FROM audit_events WHERE action = 'payment_recorded' AND patient_id = %s", (P_MAYA,)
        ).fetchone()[0]
    assert not [c for c in cols if any(w in c for w in ("card", "cvv", "pan", "expir", "bank", "token"))]
    assert audited == 2


def test_payment_role_and_ownership_denials(client):
    url = f"/api/billing/statements/{ST_CARDIO}/payments"
    assert client.post(url, headers=OKAFOR, json={"amount_cents": 100}).status_code == 403
    assert client.post(url, headers=ADMIN, json={"amount_cents": 100}).status_code == 403
    assert client.post(url, headers=PARK, json={"amount_cents": 100}).status_code == 404
    assert client.post("/api/billing/statements/not-a-uuid/payments", headers=MAYA,
                       json={"amount_cents": 100}).status_code == 404
    # Clinicians have no billing access at all; admins read with patient_id.
    assert client.get("/api/billing/statements", headers=OKAFOR).status_code == 403
    assert client.get(f"/api/billing/statements?patient_id={P_MAYA}", headers=ADMIN).status_code == 200
    assert client.get(f"/api/billing/statements?patient_id={P_HADDAD}", headers=MAYA).status_code == 403


# --- Payment plans ------------------------------------------------------------------------------


@pytest.mark.parametrize("total,n", [(5000, 3), (42000, 12), (100, 3), (99999, 7), (47001, 2)])
def test_split_installments_sums_exactly(total, n):
    parts = split_installments(total, n)
    assert len(parts) == n and sum(parts) == total and max(parts) - min(parts) <= 1


def test_payment_plan_schedule_and_installment_payments(client):
    url = f"/api/billing/statements/{ST_CARDIO}/payment-plan"
    assert client.post(url, headers=MAYA, json={"installments": 12}).status_code == 422  # under $5 each
    assert client.post(url, headers=MAYA, json={"installments": 1}).status_code == 422
    assert client.post(url, headers=MAYA, json={"installments": 3, "card_number": "4242"}).status_code == 422

    plan = client.post(url, headers=MAYA, json={"installments": 3})
    assert plan.status_code == 201
    sched = plan.json()["schedule"]
    assert [s["amount_cents"] for s in sched] == [1667, 1667, 1666]
    assert sum(s["amount_cents"] for s in sched) == 5000
    dues = [s["due_on"] for s in sched]
    assert dues == sorted(dues) and len(set(dues)) == 3
    assert client.post(url, headers=MAYA, json={"installments": 2}).status_code == 409

    pay = client.post(f"/api/billing/statements/{ST_CARDIO}/payments", headers=MAYA, json={"amount_cents": 1667})
    assert pay.status_code == 201
    st = balance(client, ST_CARDIO)
    assert [s["paid"] for s in st["plan"]["schedule"]] == [True, False, False]
    assert st["plan"]["next_installment"]["remaining_cents"] == 1667
    client.post(f"/api/billing/statements/{ST_CARDIO}/payments", headers=MAYA, json={"amount_cents": 3333})
    assert balance(client, ST_CARDIO)["plan"]["status"] == "completed"


# --- Financial assistance -----------------------------------------------------------------------


GOOD_APPLICATION = {
    "household_size": 3,
    "income_band": "300_400_fpl",
    "attestations": {"information_accurate": True, "will_report_changes": True, "consent_to_verify": True},
}


def test_assistance_application_validation(client):
    url = "/api/billing/assistance-applications"
    missing = {**GOOD_APPLICATION, "attestations": {**GOOD_APPLICATION["attestations"], "consent_to_verify": False}}
    assert client.post(url, headers=MAYA, json=missing).status_code == 422
    assert client.post(url, headers=MAYA, json={**GOOD_APPLICATION, "ssn": "000-00-0000"}).status_code == 422
    assert client.post(url, headers=MAYA, json={**GOOD_APPLICATION, "income_band": "rich"}).status_code == 422
    assert client.post(url, headers=OKAFOR, json=GOOD_APPLICATION).status_code == 403
    r = client.post(url, headers=MAYA, json=GOOD_APPLICATION)
    assert r.status_code == 201 and r.json()["status"] == "submitted" and r.json()["suggested_discount_pct"] == 50
    assert client.post(url, headers=MAYA, json=GOOD_APPLICATION).status_code == 409


def test_assistance_approval_applies_discount_and_rebalances_plan(client):
    client.post(f"/api/billing/statements/{ST_CARDIO}/payment-plan", headers=MAYA, json={"installments": 2})
    client.post(f"/api/billing/statements/{ST_CARDIO}/payments", headers=MAYA, json={"amount_cents": 1000})
    app_id = client.post("/api/billing/assistance-applications", headers=MAYA, json=GOOD_APPLICATION).json()["id"]

    queue = client.get("/api/billing/admin/assistance-applications?status_filter=submitted", headers=ADMIN).json()
    assert {a["id"] for a in queue} >= {app_id, FA_HADDAD}
    assert client.get("/api/billing/admin/assistance-applications", headers=MAYA).status_code == 403
    assert client.get("/api/billing/admin/assistance-applications", headers=OKAFOR).status_code == 403

    url = f"/api/billing/admin/assistance-applications/{app_id}/decision"
    assert client.post(url, headers=MAYA, json={"decision": "approve"}).status_code == 403
    r = client.post(url, headers=ADMIN, json={"decision": "approve", "discount_pct": 50})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert r.json()["adjustments"] == [{**r.json()["adjustments"][0], "amount_cents": 2000,
                                        "balance_before_cents": 4000, "balance_after_cents": 2000}]
    st = balance(client, ST_CARDIO)
    assert st["balance_cents"] == 2000
    plan = st["plan"]
    remaining = sum(s["remaining_cents"] for s in plan["schedule"] if not s["paid"])
    assert remaining == 2000
    assert sum(s["amount_cents"] for s in plan["schedule"]) == plan["paid_since_cents"] + 2000
    assert client.post(url, headers=ADMIN, json={"decision": "deny", "note": "x"}).status_code == 409

    mine = client.get("/api/billing/assistance-applications", headers=MAYA).json()["applications"][0]
    assert mine["status"] == "approved" and mine["discount_pct"] == 50
    with psycopg.connect(DB) as conn:
        actions = {r[0] for r in conn.execute(
            "SELECT action FROM audit_events WHERE patient_id = %s", (P_MAYA,)
        ).fetchall()}
    assert {"financial_assistance_applied", "financial_assistance_approved", "statement_adjusted"} <= actions


def test_assistance_policy_discount_and_denial(client):
    url = f"/api/billing/admin/assistance-applications/{FA_HADDAD}/decision"
    r = client.post(url, headers=ADMIN, json={"decision": "approve"})  # 200-300% FPL -> 75% by policy
    assert r.status_code == 200 and r.json()["discount_pct"] == 75
    assert balance(client, ST_HADDAD_VISIT, HADDAD)["balance_cents"] == 1250
    assert balance(client, ST_HADDAD_ECHO, HADDAD)["balance_cents"] == 10500

    maya_app = client.post("/api/billing/assistance-applications", headers=MAYA, json=GOOD_APPLICATION).json()["id"]
    deny_url = f"/api/billing/admin/assistance-applications/{maya_app}/decision"
    assert client.post(deny_url, headers=ADMIN, json={"decision": "deny"}).status_code == 422
    d = client.post(deny_url, headers=ADMIN, json={"decision": "deny", "note": "Income is above the policy limit."})
    assert d.status_code == 200 and d.json()["status"] == "denied" and d.json()["adjustments"] == []
    assert balance(client, ST_CARDIO)["balance_cents"] == 5000


# --- Front door ---------------------------------------------------------------------------------


@pytest.mark.parametrize("text,intent", [
    ("How much will my echocardiogram cost?", "billing"),
    ("I got a bill from my visit", "billing"),
    ("what's my deductible", "billing"),
    ("is this covered by my insurance", "billing"),
    ("what's the status of my claim", "billing"),
    ("my insurance won't cover my chest pain visit", "symptom"),
])
def test_billing_intent_routing(text, intent):
    result = rules_triage([{"role": "user", "content": text}], {})
    assert result.intent == intent, text


def test_dosing_question_is_not_a_billing_question():
    assert rules_triage([{"role": "user", "content": "how much atorvastatin should I take"}], {}).intent != "billing"
