"""Billing & Coverage: the patient financial experience (docs/decisions/003).

There is no real payer or payment processor. A **Demo payer** is implemented as rules over our own
tables (coverage benefits, contracted rates, claim adjudication). Payments are recorded in the demo
only: no card or bank data is ever accepted or stored; a real deployment hands payment to the
hospital's own processor. All money is integer cents.

Access: patients reach only their own billing. Organization administrators may read a patient's
billing (with `patient_id`) and decide financial assistance applications. Clinicians have no
billing access: financial data is not needed for care.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from bioverse import audit
from bioverse.auth import Admin, CurrentUser, Patient, User, assert_patient_access
from bioverse.db import DbConn
from bioverse.db.seeds.context import SeedContext

router = APIRouter(prefix="/api/billing", tags=["billing"])

Conn = DbConn

PAYER_LABEL = "Demo payer"
DEMO_NOTICE = (
    "Demo payer: coverage, prices and claims here are simulated by Bioverse rules, not a real insurer."
)
PAYMENT_NOTICE = (
    "Demo payment: no money moves and no card details are collected. In a real deployment, payments go "
    "through the hospital's own payment processor."
)
CATEGORY_LABELS = {
    "primary_care": "primary care visits",
    "specialist": "specialist visits",
    "telehealth": "telehealth visits",
    "imaging": "imaging",
    "lab": "lab tests",
}
# Demo assistance policy: discount by household income relative to the federal poverty level (FPL).
ASSISTANCE_POLICY = {"under_200_fpl": 100, "200_300_fpl": 75, "300_400_fpl": 50, "over_400_fpl": 0}
INCOME_BANDS = {
    "under_200_fpl": "Under 200% of the federal poverty level",
    "200_300_fpl": "200% to 300% of the federal poverty level",
    "300_400_fpl": "300% to 400% of the federal poverty level",
    "over_400_fpl": "Over 400% of the federal poverty level",
}
MIN_INSTALLMENT_CENTS = 500


def clinic_today() -> date:
    return SeedContext().today


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def pct_of(cents: int, pct: int) -> int:
    """pct% of cents, rounded half up, in integer arithmetic."""
    return (cents * pct + 50) // 100


def _valid_id(value: str, what: str = "Record") -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found") from None


def _patient_scope(conn: Connection, user: User, patient_id: str | None) -> str:
    """Patients: themselves. Admins: any patient in their organization (patient_id required)."""
    if patient_id:
        patient_id = _valid_id(patient_id, "Patient")
    if user.role == "patient" and user.patient_id:
        if patient_id and patient_id != user.patient_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your record")
        return user.patient_id
    if user.role == "admin":
        if not patient_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "patient_id is required")
        assert_patient_access(conn, user, patient_id)
        return patient_id
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Billing is available to the patient and organization administrators")


# --- Coverage and eligibility ---------------------------------------------------------------


def _is_eligible(cov: dict, today: date) -> bool:
    return (
        cov["status"] == "active"
        and cov["effective_start"] <= today
        and (cov["effective_end"] is None or cov["effective_end"] >= today)
    )


def _mask(member_id: str) -> str:
    return "•••• " + member_id[-4:]


COVERAGE_COLS = """
    id::text, patient_id::text, payer_name, plan_name, member_id, group_number, status, effective_start,
    effective_end, deductible_cents, deductible_met_cents, oop_max_cents, oop_met_cents, coinsurance_pct,
    oon_coinsurance_pct, copays
"""


def _coverage_out(cov: dict, today: date) -> dict:
    out = {k: v for k, v in cov.items() if k != "member_id"}
    out["member_id_masked"] = _mask(cov["member_id"])
    out["eligible_today"] = _is_eligible(cov, today)
    out["deductible_remaining_cents"] = max(0, cov["deductible_cents"] - cov["deductible_met_cents"])
    out["oop_remaining_cents"] = max(0, cov["oop_max_cents"] - cov["oop_met_cents"])
    out["payer_label"] = cov["payer_name"] or PAYER_LABEL
    return out


def _active_coverage(conn: Connection, patient_id: str, today: date) -> dict | None:
    rows = conn.execute(
        f"SELECT {COVERAGE_COLS} FROM coverages WHERE patient_id = %s ORDER BY effective_start DESC",
        (patient_id,),
    ).fetchall()
    return next((c for c in rows if _is_eligible(c, today)), None)


@router.get("/coverage")
def list_coverage(conn: Conn, user: CurrentUser, patient_id: str | None = None) -> dict:
    pid = _patient_scope(conn, user, patient_id)
    today = clinic_today()
    rows = conn.execute(
        f"SELECT {COVERAGE_COLS} FROM coverages WHERE patient_id = %s ORDER BY effective_start DESC", (pid,)
    ).fetchall()
    for c in rows:
        c["last_check"] = conn.execute(
            """
            SELECT outcome, checked_at FROM coverage_eligibility_responses
            WHERE coverage_id = %s ORDER BY checked_at DESC LIMIT 1
            """,
            (c["id"],),
        ).fetchone()
    audit.record(conn, action="coverage_viewed", entity_type="coverage", actor=user, patient_id=pid)
    return {"notice": DEMO_NOTICE, "coverages": [{**_coverage_out(c, today), "last_check": c["last_check"]} for c in rows]}


def _load_coverage(conn: Connection, user: User, coverage_id: str) -> dict:
    _valid_id(coverage_id, "Coverage")
    cov = conn.execute(f"SELECT {COVERAGE_COLS} FROM coverages WHERE id = %s", (coverage_id,)).fetchone()
    if cov is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Coverage not found")
    _patient_scope(conn, user, cov["patient_id"])
    return cov


@router.get("/coverage/{coverage_id}/member-id")
def reveal_member_id(coverage_id: str, conn: Conn, user: CurrentUser) -> dict:
    """The full member ID, e.g. to read out to a front desk. Audited as a sensitive read."""
    cov = _load_coverage(conn, user, coverage_id)
    audit.record(conn, action="member_id_revealed", entity_type="coverage", entity_id=coverage_id, actor=user,
                 patient_id=cov["patient_id"])
    return {"member_id": cov["member_id"]}


@router.post("/coverage/{coverage_id}/eligibility")
def check_eligibility(coverage_id: str, conn: Conn, user: CurrentUser) -> dict:
    """Eligibility check (CoverageEligibilityRequest) against the demo payer's rules."""
    cov = _load_coverage(conn, user, coverage_id)
    today = clinic_today()
    active = _is_eligible(cov, today)
    out = _coverage_out(cov, today)
    benefits = {
        "plan_name": cov["plan_name"],
        "effective_start": cov["effective_start"].isoformat(),
        "effective_end": cov["effective_end"].isoformat() if cov["effective_end"] else None,
    }
    if active:
        benefits.update({
            "deductible_cents": cov["deductible_cents"],
            "deductible_remaining_cents": out["deductible_remaining_cents"],
            "oop_max_cents": cov["oop_max_cents"],
            "oop_remaining_cents": out["oop_remaining_cents"],
            "coinsurance_pct": cov["coinsurance_pct"],
            "oon_coinsurance_pct": cov["oon_coinsurance_pct"],
            "copays": cov["copays"],
        })
    row = conn.execute(
        """
        INSERT INTO coverage_eligibility_responses (coverage_id, patient_id, outcome, benefits, checked_by)
        VALUES (%s, %s, %s, %s, %s) RETURNING id::text, checked_at
        """,
        (coverage_id, cov["patient_id"], "active" if active else "inactive", Jsonb(benefits), user.id),
    ).fetchone()
    audit.record(conn, action="eligibility_checked", entity_type="coverage", entity_id=coverage_id, actor=user,
                 agent="demo-payer/rules", patient_id=cov["patient_id"], detail={"outcome": "active" if active else "inactive"})
    return {
        "id": row["id"],
        "status": "active" if active else "inactive",
        "checked_at": row["checked_at"],
        "payer": cov["payer_name"] or PAYER_LABEL,
        "benefits": benefits,
        "notice": DEMO_NOTICE,
    }


# --- Price list and cost estimates ----------------------------------------------------------


@router.get("/services")
def list_services(conn: Conn, user: CurrentUser) -> list[dict]:
    return conn.execute(
        """
        SELECT code, name, category, price_cents, allowed_cents FROM service_prices
        WHERE organization_id = %s ORDER BY name
        """,
        (user.organization_id,),
    ).fetchall()


@router.get("/clinicians")
def clinicians_for_estimates(conn: Conn, user: CurrentUser, patient_id: str | None = None) -> list[dict]:
    """Clinicians the estimate tool can check, each marked in or out of network for the patient's plan."""
    pid = _patient_scope(conn, user, patient_id)
    cov = _active_coverage(conn, pid, clinic_today())
    rows = conn.execute(
        """
        SELECT pr.id::text, pr.name, pr.specialty, pr.location_name, pr.accepted_plans
        FROM practitioners pr JOIN patients p ON p.organization_id = pr.organization_id
        WHERE p.id = %s ORDER BY pr.specialty, pr.name
        """,
        (pid,),
    ).fetchall()
    return [
        {"id": r["id"], "name": r["name"], "specialty": r["specialty"], "location_name": r["location_name"],
         "in_network": cov is not None and cov["plan_name"] in r["accepted_plans"]}
        for r in rows
    ]


def calculate_estimate(*,allowed_cents: int, category: str, coverage: dict | None, in_network: bool,
                       price_cents: int | None = None) -> dict[str, Any]:
    """Patient responsibility for one service, with every step spelled out.

    In network with a copay for the category: the copay (deductible does not apply).
    Otherwise: deductible remaining first, then coinsurance on the rest (out-of-network rate when
    out of network). The total is capped by what is left of the out-of-pocket maximum.
    """
    steps: list[str] = []
    if coverage is None:
        charge = price_cents if price_cents is not None else allowed_cents
        steps.append(f"No active coverage was found, so the self-pay price applies: {money(charge)}.")
        return {
            "allowed_cents": charge, "copay_cents": 0, "deductible_cents": 0, "coinsurance_cents": 0,
            "oop_cap_reduction_cents": 0, "patient_cents": charge, "plan_cents": 0, "steps": steps,
        }

    ded_left = max(0, coverage["deductible_cents"] - coverage["deductible_met_cents"])
    oop_left = max(0, coverage["oop_max_cents"] - coverage["oop_met_cents"])
    label = CATEGORY_LABELS.get(category, category)
    steps.append(f"Allowed amount (your insurer's rate for this service): {money(allowed_cents)}.")
    if not in_network:
        steps.append("This clinician is out of network for your plan, so copays don't apply and the "
                     "out-of-network coinsurance rate is used.")

    copay = coverage["copays"].get(category) if in_network else None
    copay_part = ded_part = coins_part = 0
    if copay is not None:
        copay_part = min(int(copay), allowed_cents)
        steps.append(f"Your plan has a {money(int(copay))} copay for {label}. You pay the copay; "
                     "the deductible does not apply.")
        if copay_part < int(copay):
            steps.append(f"The allowed amount is less than the copay, so you pay {money(copay_part)}.")
    else:
        ded_part = min(allowed_cents, ded_left)
        steps.append(f"Deductible left this year: {money(ded_left)}. {money(ded_part)} of this service counts toward it.")
        rest = allowed_cents - ded_part
        pct = coverage["coinsurance_pct"] if in_network else coverage["oon_coinsurance_pct"]
        coins_part = pct_of(rest, pct)
        steps.append(f"Coinsurance: {pct}% of the remaining {money(rest)} = {money(coins_part)}.")

    subtotal = copay_part + ded_part + coins_part
    patient = min(subtotal, oop_left)
    reduction = subtotal - patient
    if reduction:
        steps.append(f"Out-of-pocket maximum left this year: {money(oop_left)}. Your share is capped there, "
                     f"saving {money(reduction)}.")
    else:
        steps.append(f"Out-of-pocket maximum left this year: {money(oop_left)}. Your share of {money(subtotal)} is within it.")
    plan = allowed_cents - patient
    steps.append(f"Estimated you pay {money(patient)}; the plan pays {money(plan)}.")
    if not in_network:
        steps.append("Out-of-network clinicians may also bill you the difference between their charge and the allowed amount.")
    return {
        "allowed_cents": allowed_cents, "copay_cents": copay_part, "deductible_cents": ded_part,
        "coinsurance_cents": coins_part, "oop_cap_reduction_cents": reduction, "patient_cents": patient,
        "plan_cents": plan, "steps": steps,
    }


@router.get("/estimate")
def estimate(conn: Conn, user: CurrentUser, service_code: str, practitioner_id: str | None = None,
             patient_id: str | None = None) -> dict:
    pid = _patient_scope(conn, user, patient_id)
    svc = conn.execute(
        """
        SELECT s.code, s.name, s.category, s.price_cents, s.allowed_cents
        FROM service_prices s JOIN patients p ON p.organization_id = s.organization_id
        WHERE p.id = %s AND s.code = %s
        """,
        (pid, service_code),
    ).fetchone()
    if svc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Service not found")
    cov = _active_coverage(conn, pid, clinic_today())

    in_network = True
    practitioner = None
    if practitioner_id:
        _valid_id(practitioner_id, "Clinician")
        practitioner = conn.execute(
            """
            SELECT pr.id::text, pr.name, pr.specialty, pr.accepted_plans FROM practitioners pr
            JOIN patients p ON p.organization_id = pr.organization_id
            WHERE pr.id = %s AND p.id = %s
            """,
            (practitioner_id, pid),
        ).fetchone()
        if practitioner is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Clinician not found")
        in_network = cov is not None and cov["plan_name"] in practitioner["accepted_plans"]

    result = calculate_estimate(allowed_cents=svc["allowed_cents"], category=svc["category"], coverage=cov,
                                in_network=in_network, price_cents=svc["price_cents"])
    audit.record(conn, action="cost_estimate_viewed", entity_type="service_price", actor=user,
                 agent="demo-payer/rules", patient_id=pid,
                 detail={"service_code": service_code, "practitioner_id": practitioner_id,
                         "patient_cents": result["patient_cents"]})
    return {
        "service": svc,
        "practitioner": {k: practitioner[k] for k in ("id", "name", "specialty")} if practitioner else None,
        "in_network": in_network,
        "network_checked": practitioner is not None,
        "coverage": {"plan_name": cov["plan_name"], "payer": cov["payer_name"] or PAYER_LABEL} if cov else None,
        **result,
        "notice": "Estimate only. " + DEMO_NOTICE,
    }


# --- Claims and explanation of benefits -----------------------------------------------------


CLAIM_SELECT = """
    SELECT c.id::text, c.patient_id::text, c.service_code, c.service_name, c.category, c.service_date,
           c.billed_cents, c.status, c.denial_reason, c.appeal_reason, c.appealed_at, c.submitted_at,
           pr.name AS practitioner_name, cv.plan_name, cv.payer_name,
           e.allowed_cents, e.plan_paid_cents, e.copay_cents, e.deductible_cents, e.coinsurance_cents,
           e.patient_resp_cents, e.adjudicated_at, s.id::text AS statement_id
    FROM claims c
    JOIN coverages cv ON cv.id = c.coverage_id
    LEFT JOIN practitioners pr ON pr.id = c.practitioner_id
    LEFT JOIN explanation_of_benefits e ON e.claim_id = c.id
    LEFT JOIN patient_statements s ON s.claim_id = c.id
"""


def _claim_out(row: dict) -> dict:
    eob_keys = ("allowed_cents", "plan_paid_cents", "copay_cents", "deductible_cents", "coinsurance_cents",
                "patient_resp_cents", "adjudicated_at")
    eob = {k: row[k] for k in eob_keys} if row["adjudicated_at"] else None
    out = {k: v for k, v in row.items() if k not in eob_keys}
    out["eob"] = eob
    out["payer"] = out.pop("payer_name", None) or PAYER_LABEL
    return out


@router.get("/claims")
def list_claims(conn: Conn, user: CurrentUser, patient_id: str | None = None) -> list[dict]:
    pid = _patient_scope(conn, user, patient_id)
    rows = conn.execute(CLAIM_SELECT + " WHERE c.patient_id = %s ORDER BY c.service_date DESC, c.id", (pid,)).fetchall()
    audit.record(conn, action="claims_viewed", entity_type="claim", actor=user, patient_id=pid)
    return [_claim_out(r) for r in rows]


def _load_claim(conn: Connection, user: User, claim_id: str) -> dict:
    _valid_id(claim_id, "Claim")
    row =conn.execute(CLAIM_SELECT + " WHERE c.id = %s", (claim_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Claim not found")
    _patient_scope(conn, user, row["patient_id"])
    return row


@router.get("/claims/{claim_id}")
def get_claim(claim_id: str, conn: Conn, user: CurrentUser) -> dict:
    row = _load_claim(conn, user, claim_id)
    audit.record(conn, action="claim_viewed", entity_type="claim", entity_id=claim_id, actor=user,
                 patient_id=row["patient_id"])
    return _claim_out(row)


class AppealIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=10, max_length=2000)


@router.post("/claims/{claim_id}/appeal")
def appeal_claim(claim_id: str, body: AppealIn, conn: Conn, user: Patient) -> dict:
    row = _load_claim(conn, user, claim_id)
    if row["status"] != "denied":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a denied claim can be appealed")
    conn.execute(
        "UPDATE claims SET status = 'appealed', appeal_reason = %s, appealed_at = now() WHERE id = %s",
        (body.reason.strip(), claim_id),
    )
    audit.record(conn, action="claim_appealed", entity_type="claim", entity_id=claim_id, actor=user,
                 patient_id=row["patient_id"])
    return _claim_out(conn.execute(CLAIM_SELECT + " WHERE c.id = %s", (claim_id,)).fetchone())


# --- Statements, payments, payment plans -----------------------------------------------------


STATEMENT_SELECT = """
    SELECT s.id::text, s.patient_id::text, s.claim_id::text, s.amount_cents, s.issued_on, s.due_on,
           c.service_name, c.service_date, pr.name AS practitioner_name,
           coalesce((SELECT sum(a.amount_cents) FROM statement_adjustments a WHERE a.statement_id = s.id), 0)::int
               AS adjustments_cents,
           coalesce((SELECT sum(p.amount_cents) FROM payments p WHERE p.statement_id = s.id), 0)::int AS paid_cents
    FROM patient_statements s
    JOIN claims c ON c.id = s.claim_id
    LEFT JOIN practitioners pr ON pr.id = c.practitioner_id
"""


def _load_statement(conn: Connection, statement_id: str, lock: bool = False) -> dict | None:
    if lock:
        conn.execute("SELECT 1 FROM patient_statements WHERE id = %s FOR UPDATE", (statement_id,))
    row = conn.execute(STATEMENT_SELECT + " WHERE s.id = %s", (statement_id,)).fetchone()
    if row:
        row["balance_cents"] = row["amount_cents"] - row["adjustments_cents"] - row["paid_cents"]
    return row


def split_installments(total_cents: int, n: int) -> list[int]:
    """Split into n amounts that sum exactly to total; any leftover cents go on the earliest installments."""
    base, rem = divmod(total_cents, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _plan_for(conn: Connection, statement_id: str) -> dict | None:
    plan = conn.execute(
        """
        SELECT id::text, installments, total_cents, status, created_at FROM payment_plans
        WHERE statement_id = %s ORDER BY (status = 'active') DESC, created_at DESC LIMIT 1
        """,
        (statement_id,),
    ).fetchone()
    if plan is None:
        return None
    rows = conn.execute(
        "SELECT id::text, seq, due_on, amount_cents FROM payment_plan_installments WHERE plan_id = %s ORDER BY seq",
        (plan["id"],),
    ).fetchall()
    paid_since = conn.execute(
        "SELECT coalesce(sum(amount_cents), 0)::int AS n FROM payments WHERE statement_id = %s AND created_at >= %s",
        (statement_id, plan["created_at"]),
    ).fetchone()["n"]
    # Payments made since the plan started cover installments in order.
    cum, credit_left = 0, paid_since
    next_due = None
    for r in rows:
        cum += r["amount_cents"]
        r["paid"] = cum <= paid_since
        r["remaining_cents"] = 0 if r["paid"] else r["amount_cents"] - max(0, credit_left)
        credit_left -= r["amount_cents"]
        if not r["paid"] and next_due is None:
            next_due = r
    plan["schedule"] = rows
    plan["paid_since_cents"] = paid_since
    plan["next_installment"] = next_due
    return plan


def _statement_out(conn: Connection, row: dict, today: date) -> dict:
    bal = row["balance_cents"]
    row["status"] = "paid" if bal <= 0 else ("overdue" if row["due_on"] < today else "open")
    row["plan"] = _plan_for(conn, row["id"])
    row["payments"] = conn.execute(
        """
        SELECT id::text, amount_cents, receipt_number, method, created_at FROM payments
        WHERE statement_id = %s ORDER BY created_at
        """,
        (row["id"],),
    ).fetchall()
    row["adjustments"] = conn.execute(
        "SELECT id::text, kind, amount_cents, created_at FROM statement_adjustments WHERE statement_id = %s ORDER BY created_at",
        (row["id"],),
    ).fetchall()
    return row


@router.get("/statements")
def list_statements(conn: Conn, user: CurrentUser, patient_id: str | None = None) -> dict:
    pid = _patient_scope(conn, user, patient_id)
    today = clinic_today()
    rows = conn.execute(STATEMENT_SELECT + " WHERE s.patient_id = %s ORDER BY s.due_on DESC", (pid,)).fetchall()
    out = []
    for r in rows:
        r["balance_cents"] = r["amount_cents"] - r["adjustments_cents"] - r["paid_cents"]
        out.append(_statement_out(conn, r, today))
    audit.record(conn, action="statements_viewed", entity_type="patient_statement", actor=user, patient_id=pid)
    return {
        "statements": out,
        "balance_due_cents": sum(max(0, s["balance_cents"]) for s in out),
        "payment_notice": PAYMENT_NOTICE,
    }


class PaymentIn(BaseModel):
    """Amount only. Any other field (card number, CVV, bank details...) is rejected outright."""

    model_config = ConfigDict(extra="forbid")
    amount_cents: StrictInt = Field(gt=0)


def _own_statement(conn: Connection, user: User, statement_id: str, lock: bool = False) -> dict:
    _valid_id(statement_id, "Bill")
    row =_load_statement(conn, statement_id, lock=lock)
    if row is None or row["patient_id"] != user.patient_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    return row


@router.post("/statements/{statement_id}/payments", status_code=status.HTTP_201_CREATED)
def pay(statement_id: str, body: PaymentIn, conn: Conn, user: Patient) -> dict:
    st = _own_statement(conn, user, statement_id, lock=True)
    if st["balance_cents"] <= 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "This bill is already paid")
    if body.amount_cents > st["balance_cents"]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "exceeds_balance",
             "message": f"The most you can pay on this bill is {money(st['balance_cents'])}."},
        )
    payment = conn.execute(
        """
        INSERT INTO payments (patient_id, statement_id, amount_cents, receipt_number, recorded_by)
        VALUES (%s, %s, %s, 'R-' || to_char(now(), 'YYYY') || '-' || lpad(nextval('payment_receipt_seq')::text, 6, '0'), %s)
        RETURNING id::text, amount_cents, receipt_number, method, created_at
        """,
        (user.patient_id, statement_id, body.amount_cents, user.id),
    ).fetchone()
    balance = st["balance_cents"] - body.amount_cents
    if balance == 0:
        conn.execute("UPDATE payment_plans SET status = 'completed' WHERE statement_id = %s AND status = 'active'",
                     (statement_id,))
    audit.record(conn, action="payment_recorded", entity_type="payment", entity_id=payment["id"], actor=user,
                 patient_id=user.patient_id,
                 detail={"statement_id": statement_id, "amount_cents": body.amount_cents, "method": "demo"})
    return {**payment, "statement_id": statement_id, "balance_cents": balance, "notice": PAYMENT_NOTICE}


RECEIPT_SELECT = """
    SELECT pm.id::text, pm.patient_id::text, pm.statement_id::text, pm.amount_cents, pm.receipt_number,
           pm.method, pm.created_at, pa.name AS patient_name, o.name AS organization_name,
           c.service_name, c.service_date, s.amount_cents AS statement_amount_cents
    FROM payments pm
    JOIN patients pa ON pa.id = pm.patient_id
    JOIN organizations o ON o.id = pa.organization_id
    JOIN patient_statements s ON s.id = pm.statement_id
    JOIN claims c ON c.id = s.claim_id
"""


@router.get("/payments")
def list_payments(conn: Conn, user: CurrentUser, patient_id: str | None = None) -> list[dict]:
    pid = _patient_scope(conn, user, patient_id)
    return conn.execute(RECEIPT_SELECT + " WHERE pm.patient_id = %s ORDER BY pm.created_at DESC", (pid,)).fetchall()


@router.get("/payments/{payment_id}")
def receipt(payment_id: str, conn: Conn, user: CurrentUser) -> dict:
    _valid_id(payment_id, "Receipt")
    row =conn.execute(RECEIPT_SELECT + " WHERE pm.id = %s", (payment_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Receipt not found")
    _patient_scope(conn, user, row["patient_id"])
    after = conn.execute(
        """
        SELECT %(amt)s
               - coalesce((SELECT sum(amount_cents) FROM statement_adjustments
                           WHERE statement_id = %(s)s AND created_at <= %(at)s), 0)
               - coalesce((SELECT sum(amount_cents) FROM payments
                           WHERE statement_id = %(s)s AND created_at <= %(at)s), 0) AS n
        """,
        {"amt": row["statement_amount_cents"], "s": row["statement_id"], "at": row["created_at"]},
    ).fetchone()["n"]
    audit.record(conn, action="receipt_viewed", entity_type="payment", entity_id=payment_id, actor=user,
                 patient_id=row["patient_id"])
    return {**row, "balance_after_cents": int(after), "notice": PAYMENT_NOTICE}


class PlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    installments: StrictInt = Field(ge=2, le=12)


def _write_schedule(conn: Connection, plan_id: str, amounts: list[int], first_due: date, start_seq: int = 1) -> None:
    for i, amount in enumerate(amounts):
        conn.execute(
            "INSERT INTO payment_plan_installments (plan_id, seq, due_on, amount_cents) VALUES (%s, %s, %s, %s)",
            (plan_id, start_seq + i, add_months(first_due, i), amount),
        )


@router.post("/statements/{statement_id}/payment-plan", status_code=status.HTTP_201_CREATED)
def create_plan(statement_id: str, body: PlanIn, conn: Conn, user: Patient) -> dict:
    st = _own_statement(conn, user, statement_id, lock=True)
    balance = st["balance_cents"]
    if balance <= 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "This bill is already paid")
    if conn.execute("SELECT 1 FROM payment_plans WHERE statement_id = %s AND status = 'active'", (statement_id,)).fetchone():
        raise HTTPException(status.HTTP_409_CONFLICT, "This bill already has a payment plan")
    if balance < MIN_INSTALLMENT_CENTS * body.installments:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "installment_too_small",
             "message": f"Each monthly payment must be at least {money(MIN_INSTALLMENT_CENTS)}. "
                        f"Choose {max(1, balance // MIN_INSTALLMENT_CENTS)} or fewer months."},
        )
    today = clinic_today()
    first_due = st["due_on"] if st["due_on"] > today else add_months(today, 1)
    plan = conn.execute(
        """
        INSERT INTO payment_plans (patient_id, statement_id, installments, total_cents)
        VALUES (%s, %s, %s, %s) RETURNING id::text
        """,
        (user.patient_id, statement_id, body.installments, balance),
    ).fetchone()
    _write_schedule(conn, plan["id"], split_installments(balance, body.installments), first_due)
    audit.record(conn, action="payment_plan_created", entity_type="payment_plan", entity_id=plan["id"], actor=user,
                 patient_id=user.patient_id,
                 detail={"statement_id": statement_id, "installments": body.installments, "total_cents": balance})
    return _plan_for(conn, statement_id)


def _rebalance_plan(conn: Connection, statement_id: str, new_balance: int) -> None:
    """After a discount, spread what is still owed over the plan's unpaid installments."""
    plan = _plan_for(conn, statement_id)
    if plan is None or plan["status"] != "active":
        return
    if new_balance <= 0:
        conn.execute("UPDATE payment_plans SET status = 'completed' WHERE id = %s", (plan["id"],))
        return
    unpaid = [r for r in plan["schedule"] if not r["paid"]]
    if not unpaid:
        return
    # Partial credit already paid toward the first unpaid installment stays counted in it.
    partial = unpaid[0]["amount_cents"] - unpaid[0]["remaining_cents"]
    amounts = split_installments(new_balance, len(unpaid))
    amounts[0] += partial
    for r, amount in zip(unpaid, amounts):
        conn.execute("UPDATE payment_plan_installments SET amount_cents = %s WHERE id = %s", (amount, r["id"]))
    paid_total = sum(r["amount_cents"] for r in plan["schedule"] if r["paid"])
    conn.execute("UPDATE payment_plans SET total_cents = %s WHERE id = %s",
                 (paid_total + sum(amounts), plan["id"]))


# --- Financial assistance --------------------------------------------------------------------


class Attestations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    information_accurate: StrictBool
    will_report_changes: StrictBool
    consent_to_verify: StrictBool


class AssistanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    household_size: StrictInt = Field(ge=1, le=20)
    income_band: Literal["under_200_fpl", "200_300_fpl", "300_400_fpl", "over_400_fpl"]
    attestations: Attestations


APPLICATION_SELECT = """
    SELECT f.id::text, f.patient_id::text, f.household_size, f.income_band, f.attestations, f.status,
           f.discount_pct, f.decision_note, f.decided_at, f.created_at, u.display_name AS decided_by_name
    FROM financial_assistance_applications f LEFT JOIN users u ON u.id = f.decided_by
"""


def _application_out(row: dict) -> dict:
    row["income_band_label"] = INCOME_BANDS[row["income_band"]]
    row["suggested_discount_pct"] = ASSISTANCE_POLICY[row["income_band"]]
    return row


@router.get("/assistance-applications")
def my_applications(conn: Conn, user: CurrentUser, patient_id: str | None = None) -> dict:
    pid = _patient_scope(conn, user, patient_id)
    rows = conn.execute(APPLICATION_SELECT + " WHERE f.patient_id = %s ORDER BY f.created_at DESC", (pid,)).fetchall()
    return {"applications": [_application_out(r) for r in rows], "income_bands": INCOME_BANDS}


@router.post("/assistance-applications", status_code=status.HTTP_201_CREATED)
def apply_for_assistance(body: AssistanceIn, conn: Conn, user: Patient) -> dict:
    if not all(body.attestations.model_dump().values()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Please confirm each statement to apply")
    if conn.execute(
        "SELECT 1 FROM financial_assistance_applications WHERE patient_id = %s AND status = 'submitted'",
        (user.patient_id,),
    ).fetchone():
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have an application being reviewed")
    row = conn.execute(
        """
        INSERT INTO financial_assistance_applications (patient_id, household_size, income_band, attestations)
        VALUES (%s, %s, %s, %s) RETURNING id::text
        """,
        (user.patient_id, body.household_size, body.income_band, Jsonb(body.attestations.model_dump())),
    ).fetchone()
    audit.record(conn, action="financial_assistance_applied", entity_type="financial_assistance_application",
                 entity_id=row["id"], actor=user, patient_id=user.patient_id,
                 detail={"household_size": body.household_size, "income_band": body.income_band})
    return _application_out(conn.execute(APPLICATION_SELECT + " WHERE f.id = %s", (row["id"],)).fetchone())


def _open_balances(conn: Connection, patient_id: str) -> list[dict]:
    rows = conn.execute(STATEMENT_SELECT + " WHERE s.patient_id = %s ORDER BY s.due_on", (patient_id,)).fetchall()
    for r in rows:
        r["balance_cents"] = r["amount_cents"] - r["adjustments_cents"] - r["paid_cents"]
    return [r for r in rows if r["balance_cents"] > 0]


@router.get("/admin/assistance-applications")
def admin_applications(conn: Conn, user: Admin, status_filter: Literal["submitted", "approved", "denied", "all"] = "all") -> list[dict]:
    rows = conn.execute(
        """
        SELECT p.name AS patient_name, f.id::text, f.patient_id::text, f.household_size, f.income_band,
               f.attestations, f.status, f.discount_pct, f.decision_note, f.decided_at, f.created_at,
               u.display_name AS decided_by_name
        FROM financial_assistance_applications f
        LEFT JOIN users u ON u.id = f.decided_by
        JOIN patients p ON p.id = f.patient_id
        WHERE p.organization_id = %s AND (%s = 'all' OR f.status = %s)
        ORDER BY (f.status = 'submitted') DESC, f.created_at DESC
        """,
        (user.organization_id, status_filter, status_filter),
    ).fetchall()
    for r in rows:
        _application_out(r)
        r["open_balance_cents"] = sum(s["balance_cents"] for s in _open_balances(conn, r["patient_id"]))
    audit.record(conn, action="assistance_queue_viewed", entity_type="financial_assistance_application", actor=user)
    return rows


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "deny"]
    discount_pct: StrictInt | None = Field(default=None, ge=1, le=100)
    note: str | None = Field(default=None, max_length=1000)


@router.post("/admin/assistance-applications/{application_id}/decision")
def decide_application(application_id: str, body: DecisionIn, conn: Conn, user: Admin) -> dict:
    _valid_id(application_id, "Application")
    app_row =conn.execute(
        "SELECT id::text, patient_id::text, status, income_band FROM financial_assistance_applications WHERE id = %s FOR UPDATE",
        (application_id,),
    ).fetchone()
    if app_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    assert_patient_access(conn, user, app_row["patient_id"])
    if app_row["status"] != "submitted":
        raise HTTPException(status.HTTP_409_CONFLICT, "This application has already been decided")
    note = (body.note or "").strip() or None

    adjustments: list[dict] = []
    if body.decision == "deny":
        if not note:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A denial needs a note for the patient")
        conn.execute(
            """
            UPDATE financial_assistance_applications
            SET status = 'denied', decision_note = %s, decided_by = %s, decided_at = now() WHERE id = %s
            """,
            (note, user.id, application_id),
        )
    else:
        pct = body.discount_pct or ASSISTANCE_POLICY[app_row["income_band"]]
        if not pct:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "This income band has no policy discount. Enter a discount percentage to approve.")
        conn.execute(
            """
            UPDATE financial_assistance_applications
            SET status = 'approved', discount_pct = %s, decision_note = %s, decided_by = %s, decided_at = now()
            WHERE id = %s
            """,
            (pct, note, user.id, application_id),
        )
        for st in _open_balances(conn, app_row["patient_id"]):
            conn.execute("SELECT 1 FROM patient_statements WHERE id = %s FOR UPDATE", (st["id"],))
            discount = min(st["balance_cents"], pct_of(st["balance_cents"], pct))
            if discount <= 0:
                continue
            adj = conn.execute(
                """
                INSERT INTO statement_adjustments (statement_id, patient_id, kind, amount_cents, application_id, created_by)
                VALUES (%s, %s, 'financial_assistance', %s, %s, %s) RETURNING id::text
                """,
                (st["id"], app_row["patient_id"], discount, application_id, user.id),
            ).fetchone()
            _rebalance_plan(conn, st["id"], st["balance_cents"] - discount)
            adjustments.append({"id": adj["id"], "statement_id": st["id"], "amount_cents": discount,
                                "balance_before_cents": st["balance_cents"],
                                "balance_after_cents": st["balance_cents"] - discount})
            audit.record(conn, action="statement_adjusted", entity_type="patient_statement", entity_id=st["id"],
                         actor=user, patient_id=app_row["patient_id"],
                         detail={"kind": "financial_assistance", "amount_cents": discount, "application_id": application_id})

    audit.record(conn, action=f"financial_assistance_{'approved' if body.decision == 'approve' else 'denied'}",
                 entity_type="financial_assistance_application", entity_id=application_id, actor=user,
                 patient_id=app_row["patient_id"],
                 detail={"discount_pct": body.discount_pct, "total_discount_cents": sum(a["amount_cents"] for a in adjustments)})
    out = _application_out(conn.execute(APPLICATION_SELECT + " WHERE f.id = %s", (application_id,)).fetchone())
    out["adjustments"] = adjustments
    return out
