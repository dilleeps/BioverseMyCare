"""Insurance services shared by the insurance router and its scheduled jobs.

- Eligibility: coverage -> 270 -> gateway -> 271 -> stored check with plain-language benefits.
- Claims: billing claim (or completed encounter) -> 837P -> gateway -> 277CA -> stored submission.
- Remittances: 835 -> parsed and balanced -> posted to billing (claim status, explanation_of_benefits,
  patient_statements, coverage accumulators) using billing's existing columns only. Provider-level
  adjustments (PLB) and the raw 835 stay in this module's own tables.

All functions expect a connection whose rows are dicts (every request and job connection is).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

from bioverse import audit
from bioverse.config import clinic_tz
from bioverse.notify import notify, patient_user
from bioverse.payers.gateway import GatewayError, build_gateway, gateway_for
from bioverse.x12 import X12Error, build_270, build_837p, codes, parse_271, parse_277ca, parse_835
from bioverse.x12.ack import claim_status
from bioverse.x12.core import Envelope
from bioverse.x12.models import (
    Address, EligibilityInquiry, EligibilityResult, Payer, Person, ProfessionalClaim, Provider, ServiceLine,
    Subscriber,
)

SIM_RECEIVER = "BVSIMCH"
ELIGIBILITY_SERVICE_TYPES = ["30", "98", "UC", "88"]

# Billing's service codes as billable procedures (CPT) with modifiers.
SERVICE_CPT = {
    "PCP_VISIT": ("99213", []),
    "SPEC_VISIT": ("99214", []),
    "ECHO": ("93306", []),
    "LIPID": ("80061", []),
    "TELEHEALTH": ("99213", ["95"]),
}
# Suggested diagnoses per service when the visit record doesn't carry coded diagnoses. Staff confirm them.
DEFAULT_DIAGNOSES = {
    "SPEC_VISIT": ["R07.9", "E78.5"],
    "LIPID": ["E78.5"],
    "ECHO": ["R07.9"],
    "PCP_VISIT": ["Z00.00"],
    "TELEHEALTH": ["Z71.89"],
}
GENDER = {"female": "F", "male": "M"}


class ServiceError(Exception):
    """A readable failure with an HTTP status for the router: 422 for bad data, 502 for the payer side."""

    def __init__(self, message: str, *, errors: list[str] | None = None, status: int = 422):
        self.errors = errors or [message]
        self.status = status
        super().__init__(message)


# --- Small helpers ------------------------------------------------------------------------------


def clinic_now() -> datetime:
    return datetime.now(clinic_tz())


def money_plain(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    if cents % 100 == 0:
        return f"{sign}${cents // 100:,}"
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def split_name(full: str) -> tuple[str, str]:
    parts = (full or "").replace("Dr.", "").split()
    if not parts:
        return "", ""
    return parts[0], parts[-1]


def envelope(conn: Connection, sender: str, receiver: str = SIM_RECEIVER) -> Envelope:
    n = conn.execute("SELECT nextval('insurance_control_seq') AS n").fetchone()["n"] % 999_999_999 or 1
    return Envelope(sender_id=sender, receiver_id=receiver, control_number=n,
                    timestamp=clinic_now().replace(tzinfo=None))


PAYER_COLS = """id::text, name, payer_id, connection_type, transactions, fhir_base_url, fhir_profiles,
                member_phone, provider_phone, claims_address, auth_required_procedures, fictional"""


def get_payer(conn: Connection, payer_ref: str | None) -> dict[str, Any] | None:
    if not payer_ref:
        return None
    return conn.execute(f"SELECT {PAYER_COLS} FROM payers WHERE id = %s", (payer_ref,)).fetchone()


def billing_provider(conn: Connection, organization_id: str) -> dict[str, Any] | None:
    return conn.execute("SELECT * FROM insurance_billing_providers WHERE organization_id = %s",
                        (organization_id,)).fetchone()


def coverage_context(conn: Connection, coverage_id: str) -> dict[str, Any] | None:
    """A billing coverage with this module's details, the patient, and the registered payer."""
    return conn.execute(
        """
        SELECT c.id::text, c.patient_id::text, c.payer_name, c.plan_name, c.member_id, c.group_number, c.status,
               c.effective_start, c.effective_end, c.copays,
               p.name AS patient_name, p.birth_date, p.sex_at_birth, p.organization_id::text,
               d.payer_ref::text, d.relationship, d.subscriber_name, d.subscriber_birth_date,
               d.address_line, d.city, d.state, d.zip, d.rx_bin, d.rx_pcn, d.rx_group
        FROM coverages c
        JOIN patients p ON p.id = c.patient_id
        LEFT JOIN coverage_details d ON d.coverage_id = c.id
        WHERE c.id = %s
        """,
        (coverage_id,),
    ).fetchone()


def _patient_person(ctx: dict[str, Any]) -> Person:
    first, last = split_name(ctx["patient_name"])
    return Person(first_name=first, last_name=last, birth_date=ctx["birth_date"],
                  gender=GENDER.get(ctx.get("sex_at_birth") or "", "U"))


def _subscriber(ctx: dict[str, Any], member_id: str, group: str | None) -> tuple[Subscriber, Person | None, str]:
    relationship = ctx.get("relationship") or "self"
    address = None
    if ctx.get("address_line"):
        address = Address(line1=ctx["address_line"], city=ctx["city"] or "", state=ctx["state"] or "", zip=ctx["zip"] or "")
    if relationship == "self":
        p = _patient_person(ctx)
        return Subscriber(**p.model_dump(), member_id=member_id, group_number=group, address=address), None, relationship
    first, last = split_name(ctx.get("subscriber_name") or "")
    sub = Subscriber(first_name=first, last_name=last, birth_date=ctx.get("subscriber_birth_date"),
                     member_id=member_id, group_number=group, address=address)
    return sub, _patient_person(ctx), relationship


# --- Eligibility --------------------------------------------------------------------------------


def plain_summary(result: EligibilityResult | None, payer_name: str, error: str | None = None) -> list[str]:
    """What the 271 means, in sentences a patient can act on."""
    if result is None or result.status == "error":
        reason = error or "; ".join(r.reason for r in (result.rejections if result else [])) or "the payer didn't answer"
        return [f"We couldn't check this coverage right now: {reason}. Please try again later or call the number on your card."]
    if result.status == "not_found":
        reason = "; ".join(r.reason for r in result.rejections)
        return [f"{payer_name} couldn't find a member with these details ({reason.lower()}). "
                "Check the member ID, name and date of birth against your card."]
    if result.status == "inactive":
        when = f" It ended on {result.plan_end:%B %-d, %Y}." if result.plan_end and result.plan_end < clinic_now().date() else ""
        return [f"{payer_name} reports this coverage is not active.{when} Please check with your employer or plan, "
                "or add a new card."]
    lines = [f"Your coverage with {payer_name}{f' ({result.plan_name})' if result.plan_name else ''} is active."]
    ded = result.deductible_individual
    if ded.total_cents is not None and ded.met_cents is not None:
        if ded.remaining_cents == 0:
            lines.append(f"You've met your {money_plain(ded.total_cents)} deductible for this plan year.")
        else:
            lines.append(f"You've met {money_plain(ded.met_cents)} of your {money_plain(ded.total_cents)} deductible.")
    fam = result.deductible_family
    if fam.total_cents is not None and fam.met_cents is not None:
        lines.append(f"Your family has met {money_plain(fam.met_cents)} of its {money_plain(fam.total_cents)} deductible.")
    oop = result.oop_individual
    if oop.total_cents is not None and oop.met_cents is not None:
        lines.append(f"You've paid {money_plain(oop.met_cents)} toward your {money_plain(oop.total_cents)} "
                     "out-of-pocket maximum. After that, the plan pays in full for covered care.")
    for c in result.copays:
        if c.in_network is not False:
            lines.append(f"{c.label}: {money_plain(c.amount_cents)} copay.")
    in_net = next((c for c in result.coinsurance if c.in_network is not False), None)
    out_net = next((c for c in result.coinsurance if c.in_network is False), None)
    if in_net:
        tail = f" ({out_net.percent}% out of network)" if out_net else ""
        lines.append(f"For other covered care, after your deductible you pay {in_net.percent}% in network{tail}.")
    return lines


def benefits_view(benefits: dict[str, Any]) -> dict[str, Any]:
    """Stored 271 benefits with `met_cents` filled in on each accumulator, for screens."""
    out = dict(benefits)
    for key in ("deductible_individual", "deductible_family", "oop_individual", "oop_family"):
        acc = dict(out.get(key) or {})
        if acc.get("total_cents") is not None and acc.get("remaining_cents") is not None:
            acc["met_cents"] = max(0, acc["total_cents"] - acc["remaining_cents"])
        out[key] = acc
    return out


CHECK_COLS = """ch.id::text, ch.patient_id::text, ch.coverage_id::text, ch.reported_coverage_id::text,
                ch.appointment_id::text, ch.trigger, ch.status, ch.benefits, ch.summary, ch.error, ch.simulated,
                ch.checked_at, y.name AS payer_name"""


def check_out(row: dict[str, Any], *, include_x12: bool = False, x12: dict | None = None) -> dict[str, Any]:
    out = {k: v for k, v in row.items() if k not in ("request_x12", "response_x12")}
    out["benefits"] = benefits_view(row.get("benefits") or {})
    if include_x12 and x12:
        out["request_x12"], out["response_x12"] = x12.get("request_x12"), x12.get("response_x12")
    return out


def _run_eligibility(conn: Connection, *, organization_id: str, patient_id: str, payer: dict[str, Any] | None,
                     subscriber: Subscriber, patient: Person | None, relationship: str, trigger: str,
                     actor: Any, coverage_id: str | None = None, reported_id: str | None = None,
                     appointment_id: str | None = None, date_of_service: date | None = None) -> dict[str, Any]:
    result: EligibilityResult | None = None
    error: str | None = None
    request = response = None
    simulated = True
    payer_name = payer["name"] if payer else "The payer"
    try:
        if payer is None:
            raise ServiceError("This coverage isn't linked to a payer in the registry, so it can't be checked electronically.")
        bp = billing_provider(conn, organization_id)
        if bp is None:
            raise ServiceError("The organization's billing NPI isn't set up yet.")
        seq = conn.execute("SELECT nextval('insurance_control_seq') AS n").fetchone()["n"]
        inq = EligibilityInquiry(
            payer=Payer(name=payer["name"], payer_id=payer["payer_id"]),
            provider=Provider(name=bp["name"], npi=bp["npi"]),
            subscriber=subscriber, patient=patient, relationship=relationship,
            service_types=ELIGIBILITY_SERVICE_TYPES, date_of_service=date_of_service or clinic_now().date(),
            trace_number=f"BV{seq:010d}", reference=f"EL{seq:08d}",
        )
        request = build_270(inq, envelope(conn, bp["submitter_id"]))
        gateway = gateway_for(conn, organization_id, payer)
        simulated = gateway.simulated
        response = gateway.eligibility(request)
        result = parse_271(response)
        status = result.status
    except X12Error as exc:
        status, error = "error", "; ".join(exc.errors)
    except (GatewayError, ServiceError) as exc:
        status, error = "error", str(exc)
    summary = plain_summary(result, payer_name, error)
    row = conn.execute(
        """
        INSERT INTO insurance_eligibility_checks
            (patient_id, coverage_id, reported_coverage_id, payer_ref, appointment_id, trigger, status, benefits,
             summary, error, request_x12, response_x12, simulated, requested_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id::text
        """,
        (patient_id, coverage_id, reported_id, payer["id"] if payer else None, appointment_id, trigger, status,
         Jsonb(result.model_dump(mode="json") if result else {}), summary, error, request, response, simulated,
         actor.id if actor else None),
    ).fetchone()
    if coverage_id and status in ("active", "inactive") and result is not None:
        # Billing's own eligibility history shows the latest check too ("Last checked ...").
        conn.execute(
            """
            INSERT INTO coverage_eligibility_responses (coverage_id, patient_id, outcome, benefits, checked_by)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (coverage_id, patient_id, status,
             Jsonb({"source": "x12_271", "check_id": row["id"], "plan_name": result.plan_name, "summary": summary}),
             actor.id if actor else None),
        )
    audit.record(conn, action="insurance_eligibility_checked", entity_type="coverage", entity_id=coverage_id or reported_id,
                 actor=actor, agent="simulated-clearinghouse" if simulated else "http-clearinghouse",
                 patient_id=patient_id, detail={"status": status, "trigger": trigger, "check_id": row["id"]})
    return conn.execute(
        f"SELECT {CHECK_COLS} FROM insurance_eligibility_checks ch LEFT JOIN payers y ON y.id = ch.payer_ref "
        "WHERE ch.id = %s",
        (row["id"],),
    ).fetchone()


def check_coverage(conn: Connection, coverage_id: str, *, trigger: str, actor: Any = None,
                   appointment_id: str | None = None, date_of_service: date | None = None) -> dict[str, Any]:
    ctx = coverage_context(conn, coverage_id)
    if ctx is None:
        raise ServiceError("Coverage not found", status=404)
    subscriber, patient, relationship = _subscriber(ctx, ctx["member_id"], ctx["group_number"])
    return _run_eligibility(
        conn, organization_id=ctx["organization_id"], patient_id=ctx["patient_id"],
        payer=get_payer(conn, ctx["payer_ref"]), subscriber=subscriber, patient=patient, relationship=relationship,
        trigger=trigger, actor=actor, coverage_id=coverage_id, appointment_id=appointment_id,
        date_of_service=date_of_service,
    )


def verify_reported(conn: Connection, reported: dict[str, Any], *, actor: Any) -> dict[str, Any]:
    """Check a patient-reported card with the payer. An active answer makes it a billing coverage."""
    ctx = conn.execute(
        "SELECT name AS patient_name, birth_date, sex_at_birth, organization_id::text FROM patients WHERE id = %s",
        (reported["patient_id"],),
    ).fetchone()
    ctx["relationship"] = "self"
    subscriber, patient, relationship = _subscriber(ctx, reported["member_id"], reported["group_number"])
    payer = get_payer(conn, reported["payer_ref"])
    check = _run_eligibility(
        conn, organization_id=ctx["organization_id"], patient_id=reported["patient_id"], payer=payer,
        subscriber=subscriber, patient=patient, relationship=relationship, trigger="verification", actor=actor,
        reported_id=reported["id"],
    )
    coverage_id = None
    if check["status"] == "active":
        b = check["benefits"]
        copays = {}
        for c in b.get("copays", []):
            key = {"Primary care visits": "primary_care", "Specialist visits": "specialist",
                   "Telehealth visits": "telehealth"}.get(c["label"])
            if key and c.get("in_network") is not False:
                copays[key] = c["amount_cents"]
        coins = {c["in_network"]: c["percent"] for c in b.get("coinsurance", [])}
        ded, oop = b.get("deductible_individual") or {}, b.get("oop_individual") or {}
        ded_total, oop_total = ded.get("total_cents") or 0, oop.get("total_cents") or 0
        today = clinic_now().date()
        # A new plan replaces what it overlaps: billing picks the newest active coverage.
        cov = conn.execute(
            """
            INSERT INTO coverages (patient_id, payer_name, plan_name, member_id, group_number, status, effective_start,
                                   effective_end, deductible_cents, deductible_met_cents, oop_max_cents, oop_met_cents,
                                   coinsurance_pct, oon_coinsurance_pct, copays)
            VALUES (%s, %s, %s, %s, %s, 'active', %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id::text
            """,
            (reported["patient_id"], payer["name"], b.get("plan_name") or reported["plan_name"] or payer["name"],
             reported["member_id"], b.get("group_number") or reported["group_number"],
             b.get("plan_begin") or today, b.get("plan_end"), ded_total,
             max(0, ded_total - (ded.get("remaining_cents") if ded.get("remaining_cents") is not None else ded_total)),
             oop_total,
             max(0, oop_total - (oop.get("remaining_cents") if oop.get("remaining_cents") is not None else oop_total)),
             coins.get(True, 0), coins.get(False, coins.get(True, 0)), Jsonb(copays)),
        ).fetchone()
        coverage_id = cov["id"]
        conn.execute(
            """
            INSERT INTO coverage_details (coverage_id, patient_id, payer_ref, relationship, rx_bin, rx_pcn, rx_group, source)
            VALUES (%s, %s, %s, 'self', %s, %s, %s, 'card_scan')
            """,
            (coverage_id, reported["patient_id"], payer["id"], reported["rx_bin"], reported["rx_pcn"],
             reported["rx_group"]),
        )
        conn.execute("UPDATE insurance_eligibility_checks SET coverage_id = %s WHERE id = %s", (coverage_id, check["id"]))
        audit.record(conn, action="coverage_created_from_card", entity_type="coverage", entity_id=coverage_id,
                     actor=actor, patient_id=reported["patient_id"], detail={"reported_coverage_id": reported["id"]})
    status = {"active": "verified", "inactive": "inactive", "not_found": "not_found"}.get(check["status"], "error")
    conn.execute(
        """
        UPDATE reported_coverages SET status = %s, status_message = %s, coverage_id = %s,
               verified_at = CASE WHEN %s = 'verified' THEN now() ELSE verified_at END
        WHERE id = %s
        """,
        (status, " ".join(check["summary"]), coverage_id, status, reported["id"]),
    )
    return {"check": check_out(check), "status": status, "coverage_id": coverage_id}


# --- Claims -------------------------------------------------------------------------------------


def _active_coverage_on(conn: Connection, patient_id: str, day: date) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT id::text FROM coverages WHERE patient_id = %s AND status = 'active' AND effective_start <= %s
          AND (effective_end IS NULL OR effective_end >= %s) ORDER BY effective_start DESC LIMIT 1
        """,
        (patient_id, day, day),
    ).fetchone()


def _service_for_encounter(enc: dict[str, Any]) -> str:
    kind = (enc["kind"] or "").lower()
    if "video" in kind or "tele" in kind:
        return "TELEHEALTH"
    return "PCP_VISIT" if (enc["specialty"] or "").lower() == "primary care" else "SPEC_VISIT"


def _prior_auth_for(conn: Connection, patient_id: str, coverage_id: str, procedure_codes: list[str],
                    day: date) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT id::text, status, payer_reference, procedure_code FROM prior_authorizations
        WHERE patient_id = %s AND coverage_id = %s AND procedure_code = ANY(%s) AND status = 'approved'
          AND (valid_from IS NULL OR valid_from <= %s) AND (valid_to IS NULL OR valid_to >= %s)
        ORDER BY decided_at DESC NULLS LAST LIMIT 1
        """,
        (patient_id, coverage_id, procedure_codes, day, day),
    ).fetchone()


def claim_draft(conn: Connection, organization_id: str, *, claim_id: str | None = None,
                encounter_id: str | None = None) -> dict[str, Any]:
    """Everything needed to build an 837P for one billing claim or completed encounter."""
    if claim_id:
        src = conn.execute(
            """
            SELECT c.id::text AS claim_id, c.patient_id::text, c.coverage_id::text, c.practitioner_id::text,
                   c.service_code, c.service_name, c.category, c.service_date, c.billed_cents, c.status,
                   p.name AS patient_name, p.organization_id::text
            FROM claims c JOIN patients p ON p.id = c.patient_id WHERE c.id = %s
            """,
            (claim_id,),
        ).fetchone()
        if src is None or src["organization_id"] != organization_id:
            raise ServiceError("Claim not found", status=404)
        src["encounter_id"] = None
    elif encounter_id:
        enc = conn.execute(
            """
            SELECT e.id::text, e.patient_id::text, e.practitioner_id::text, e.occurred_at, e.kind,
                   pr.specialty, p.name AS patient_name, p.organization_id::text
            FROM encounters e JOIN patients p ON p.id = e.patient_id LEFT JOIN practitioners pr ON pr.id = e.practitioner_id
            WHERE e.id = %s
            """,
            (encounter_id,),
        ).fetchone()
        if enc is None or enc["organization_id"] != organization_id:
            raise ServiceError("Visit not found", status=404)
        day = enc["occurred_at"].astimezone(clinic_tz()).date()
        code = _service_for_encounter(enc)
        price = conn.execute(
            "SELECT name, category, price_cents FROM service_prices WHERE organization_id = %s AND code = %s",
            (organization_id, code),
        ).fetchone()
        if price is None:
            raise ServiceError(f"The price list has no {code} service.")
        cov = _active_coverage_on(conn, enc["patient_id"], day)
        src = {"claim_id": None, "encounter_id": enc["id"], "patient_id": enc["patient_id"],
               "coverage_id": cov["id"] if cov else None, "practitioner_id": enc["practitioner_id"],
               "service_code": code, "service_name": f"{enc['kind']} ({price['name'].lower()})",
               "category": price["category"], "service_date": day, "billed_cents": price["price_cents"],
               "status": None, "patient_name": enc["patient_name"], "organization_id": organization_id}
    else:
        raise ServiceError("Choose a claim or a visit to bill")

    problems: list[str] = []
    ctx = coverage_context(conn, src["coverage_id"]) if src["coverage_id"] else None
    if ctx is None:
        problems.append("No active coverage on the date of service")
    payer = get_payer(conn, ctx["payer_ref"]) if ctx else None
    if ctx is not None and payer is None:
        problems.append("The coverage isn't linked to a registered payer")
    cpt, modifiers = SERVICE_CPT.get(src["service_code"], ("", []))
    if not cpt:
        problems.append(f"Service {src['service_code']} has no procedure code mapping")
    line = {"procedure_code": cpt, "modifiers": modifiers, "charge_cents": src["billed_cents"], "units": 1,
            "service_date": src["service_date"].isoformat(), "diagnosis_pointers": [1],
            "description": src["service_name"], "place_of_service": "10" if "95" in modifiers else None}
    pa = _prior_auth_for(conn, src["patient_id"], src["coverage_id"], [cpt], src["service_date"]) if ctx else None
    needs_auth = bool(payer and cpt in (payer["auth_required_procedures"] or []))
    return {
        **{k: src[k] for k in ("claim_id", "encounter_id", "patient_id", "patient_name", "coverage_id",
                               "practitioner_id", "service_code", "service_name", "category", "billed_cents")},
        "service_date": src["service_date"].isoformat(),
        "payer": {"id": payer["id"], "name": payer["name"], "payer_id": payer["payer_id"]} if payer else None,
        "member_id": ctx["member_id"] if ctx else None,
        "diagnosis_codes": DEFAULT_DIAGNOSES.get(src["service_code"], []),
        "service_lines": [line],
        "prior_authorization": pa,
        "prior_authorization_required": needs_auth,
        "problems": problems,
    }


def build_professional_claim(conn: Connection, organization_id: str, draft: dict[str, Any], diagnosis_codes: list[str],
                             pcn: str, *, service_lines: list[dict[str, Any]] | None = None) -> ProfessionalClaim:
    if draft["problems"]:
        raise ServiceError("This claim can't be built yet", errors=draft["problems"])
    bp = billing_provider(conn, organization_id)
    if bp is None:
        raise ServiceError("Billing provider NPI missing")
    ctx = coverage_context(conn, draft["coverage_id"])
    subscriber, patient, relationship = _subscriber(ctx, ctx["member_id"], ctx["group_number"])
    rendering = None
    if draft["practitioner_id"]:
        pr = conn.execute(
            """
            SELECT pr.name, n.npi, n.taxonomy FROM practitioners pr
            LEFT JOIN insurance_provider_numbers n ON n.practitioner_id = pr.id WHERE pr.id = %s
            """,
            (draft["practitioner_id"],),
        ).fetchone()
        first, last = split_name(pr["name"])
        rendering = Provider(name=last, first_name=first, npi=pr["npi"] or "", taxonomy=pr["taxonomy"])
    address = Address(line1=bp["address_line"], city=bp["city"], state=bp["state"], zip=bp["zip"])
    lines = [ServiceLine(**{k: v for k, v in line.items() if k in ServiceLine.model_fields})
             for line in (service_lines or draft["service_lines"])]
    return ProfessionalClaim(
        patient_control_number=pcn,
        submitter=Provider(name=bp["name"], tax_id=bp["submitter_id"]),
        submitter_phone=bp["phone"] or "",
        receiver=Provider(name="Bioverse Simulated Clearinghouse", tax_id=SIM_RECEIVER),
        billing_provider=Provider(name=bp["name"], npi=bp["npi"], tax_id=bp["tax_id"], taxonomy=bp["taxonomy"],
                                  address=address),
        payer=Payer(name=draft["payer"]["name"], payer_id=draft["payer"]["payer_id"]),
        subscriber=subscriber, relationship=relationship, patient=patient,
        patient_address=subscriber.address if patient else None,
        diagnosis_codes=[c.strip().upper() for c in diagnosis_codes if c.strip()],
        prior_authorization=(draft["prior_authorization"] or {}).get("payer_reference"),
        rendering_provider=rendering, service_lines=lines, reference=pcn,
    )


SUBMISSION_COLS = """s.id::text, s.patient_id::text, s.claim_id::text, s.encounter_id::text, s.coverage_id::text,
    s.patient_control_number, s.diagnosis_codes, s.service_lines, s.total_charge_cents, s.status, s.ack_category,
    s.ack_status_code, s.ack_message, s.payer_claim_number, s.simulated, s.submitted_at, s.acknowledged_at,
    s.remitted_at, s.interchange_control, p.name AS patient_name, y.name AS payer_name, c.service_name,
    c.service_date, c.status AS billing_status, c.denial_reason"""
SUBMISSION_FROM = """insurance_claim_submissions s JOIN patients p ON p.id = s.patient_id
    JOIN payers y ON y.id = s.payer_ref JOIN claims c ON c.id = s.claim_id"""


def submit_claim(conn: Connection, user: Any, organization_id: str, *, claim_id: str | None, encounter_id: str | None,
                 diagnosis_codes: list[str], dry_run: bool = False) -> dict[str, Any]:
    draft = claim_draft(conn, organization_id, claim_id=claim_id, encounter_id=encounter_id)
    if draft["claim_id"] and conn.execute(
        "SELECT 1 FROM insurance_claim_submissions WHERE claim_id = %s AND status <> 'rejected'", (draft["claim_id"],)
    ).fetchone():
        raise ServiceError("This claim has already been sent", status=409)
    if dry_run:
        pcn = "BVPREVIEW"
    else:
        seq = conn.execute("SELECT nextval('insurance_claim_number_seq') AS n").fetchone()["n"]
        pcn = f"BV{seq:08d}"
    model = build_professional_claim(conn, organization_id, draft, diagnosis_codes, pcn)
    bp = billing_provider(conn, organization_id)
    try:
        x837 = build_837p(model, envelope(conn, bp["submitter_id"]))
    except X12Error as exc:
        raise ServiceError("The claim is missing required information", errors=exc.errors) from None
    if dry_run:
        return {"x12_837": x837, "patient_control_number": pcn, "total_charge_cents": model.total_charge_cents,
                "draft": draft}

    payer = get_payer(conn, draft["payer"]["id"])
    try:
        gateway = gateway_for(conn, organization_id, payer)
        x277 = gateway.submit_claims(x837)
        ack = parse_277ca(x277)
    except GatewayError as exc:
        raise ServiceError(str(exc), status=502) from None
    except X12Error as exc:
        raise ServiceError("The clearinghouse's acknowledgment could not be read", errors=exc.errors, status=502) from None
    result = claim_status(ack, pcn)
    if result is None:
        raise ServiceError("The acknowledgment did not mention this claim", status=502)

    billing_claim_id = draft["claim_id"]
    if billing_claim_id is None:
        # A completed visit without a billing claim: create billing's claim record (existing columns only).
        billing_claim_id = conn.execute(
            """
            INSERT INTO claims (patient_id, coverage_id, practitioner_id, service_code, service_name, category,
                                service_date, billed_cents, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'submitted') RETURNING id::text
            """,
            (draft["patient_id"], draft["coverage_id"], draft["practitioner_id"], draft["service_code"],
             draft["service_name"], draft["category"], draft["service_date"], draft["billed_cents"]),
        ).fetchone()["id"]
    status = "accepted" if result.accepted else "rejected"
    row = conn.execute(
        """
        INSERT INTO insurance_claim_submissions
            (organization_id, patient_id, claim_id, encounter_id, coverage_id, payer_ref, prior_authorization_id,
             patient_control_number, diagnosis_codes, service_lines, total_charge_cents, status, x12_837,
             interchange_control, x12_277ca, ack_category, ack_status_code, ack_message, payer_claim_number,
             simulated, submitted_by, acknowledged_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, clock_timestamp())
        RETURNING id::text
        """,
        (organization_id, draft["patient_id"], billing_claim_id, draft["encounter_id"], draft["coverage_id"],
         payer["id"], (draft["prior_authorization"] or {}).get("id"), pcn, model.diagnosis_codes,
         Jsonb([line.model_dump(mode="json") for line in model.service_lines]), model.total_charge_cents, status,
         x837, x837.split("*", 14)[13], x277, result.category_code, result.status_code, result.message,
         result.payer_claim_number, gateway.simulated, user.id if user else None),
    ).fetchone()
    if result.accepted:
        conn.execute("UPDATE claims SET status = 'in_review' WHERE id = %s AND status = 'submitted'", (billing_claim_id,))
    audit.record(conn, action="insurance_claim_submitted", entity_type="claim", entity_id=billing_claim_id, actor=user,
                 agent=gateway.label, patient_id=draft["patient_id"],
                 detail={"submission_id": row["id"], "patient_control_number": pcn, "status": status,
                         "ack": f"{result.category_code}:{result.status_code}"})
    return get_submission(conn, row["id"])


def get_submission(conn: Connection, submission_id: str) -> dict[str, Any] | None:
    row = conn.execute(f"SELECT {SUBMISSION_COLS}, s.organization_id::text FROM {SUBMISSION_FROM} WHERE s.id = %s",
                       (submission_id,)).fetchone()
    if row is None:
        return None
    row["remits"] = conn.execute(
        """
        SELECT rc.id::text, rc.status_code, rc.charge_cents, rc.paid_cents, rc.patient_resp_cents, rc.adjustments,
               rc.posting_status, rc.posting_note, rc.posted_at, r.trace_number, r.payment_date, r.source
        FROM insurance_remittance_claims rc JOIN insurance_remittances r ON r.id = rc.remittance_id
        WHERE rc.submission_id = %s ORDER BY rc.posted_at
        """,
        (submission_id,),
    ).fetchall()
    return row


# --- Remittance posting -------------------------------------------------------------------------


def adjustment_view(a: dict[str, Any]) -> dict[str, Any]:
    return {**a, "label": codes.adjustment_label(a["group"], a["reason_code"]),
            "plain": codes.carc_text(a["reason_code"]),
            "group_label": codes.GROUP_CODES.get(a["group"], a["group"]).split(":")[0]}


def denial_text(adjustments: list[dict[str, Any]]) -> str:
    reasons = [a for a in adjustments if not (a["group"] == "CO" and a["reason_code"] == "45") and a["group"] != "PR"]
    if not reasons:
        return "The plan denied this claim."
    first = reasons[0]
    return f"{codes.carc_text(first['reason_code'])} (Reason code {first['group']}-{first['reason_code']}.)"


def post_remittance(conn: Connection, text: str, *, source: str, actor: Any = None,
                    organization_id: str | None = None) -> dict[str, Any]:
    try:
        remit = parse_835(text)
    except X12Error as exc:
        raise ServiceError("This 835 could not be read", errors=exc.errors) from None
    bp = conn.execute("SELECT organization_id::text FROM insurance_billing_providers WHERE npi = %s",
                      (remit.payee.npi,)).fetchone()
    org = bp["organization_id"] if bp else organization_id
    if org is None:
        raise ServiceError(f"No organization in Bioverse bills under NPI {remit.payee.npi or '(none)'}")
    if organization_id and org != organization_id:
        raise ServiceError("This remittance is addressed to another organization's NPI", status=403)
    payer = conn.execute(f"SELECT {PAYER_COLS} FROM payers WHERE payer_id = %s", (remit.payer.payer_id,)).fetchone()
    payer_name = payer["name"] if payer else remit.payer.name
    existing = conn.execute(
        "SELECT id::text FROM insurance_remittances WHERE organization_id = %s AND payer_name = %s AND trace_number = %s",
        (org, payer_name, remit.trace_number),
    ).fetchone()
    if existing:
        return {"remittance_id": existing["id"], "duplicate": True, "claims": []}
    plb_total = sum(p.amount_cents for p in remit.provider_adjustments)
    rem = conn.execute(
        """
        INSERT INTO insurance_remittances (organization_id, payer_ref, payer_name, trace_number, payment_cents,
                                           payment_method, payment_date, provider_adjustments,
                                           provider_adjustment_cents, x12_835, source, received_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text
        """,
        (org, payer["id"] if payer else None, payer_name, remit.trace_number, remit.payment_cents,
         remit.payment_method, remit.payment_date,
         Jsonb([{**p.model_dump(mode="json"), "label": codes.PLB_REASONS.get(p.reason_code, p.reason_code)}
                for p in remit.provider_adjustments]),
         plb_total, text, source, actor.id if actor else None),
    ).fetchone()
    results = []
    for c in remit.claims:
        results.append(_post_claim(conn, org, rem["id"], c, actor))
    audit.record(conn, action="insurance_remittance_received", entity_type="insurance_remittance",
                 entity_id=rem["id"], actor=actor, agent=f"{source}-835",
                 detail={"trace_number": remit.trace_number, "payment_cents": remit.payment_cents,
                         "claims": len(remit.claims), "provider_adjustment_cents": plb_total})
    return {"remittance_id": rem["id"], "duplicate": False, "claims": results}


def _post_claim(conn: Connection, org: str, remittance_id: str, c: Any, actor: Any) -> dict[str, Any]:
    adjustments = [a.model_dump() for a in c.all_adjustments()]
    sub = conn.execute(
        """
        SELECT s.id::text, s.claim_id::text, s.patient_id::text, s.coverage_id::text, cl.status AS claim_status
        FROM insurance_claim_submissions s JOIN claims cl ON cl.id = s.claim_id
        WHERE s.organization_id = %s AND s.patient_control_number = %s
        ORDER BY s.submitted_at DESC LIMIT 1
        """,
        (org, c.patient_control_number),
    ).fetchone()
    posting, note = "unmatched", "No claim we sent has this patient control number."
    patient_id = claim_id = None
    if sub is not None:
        patient_id, claim_id = sub["patient_id"], sub["claim_id"]
        if c.status_code in codes.PAID_STATUSES:
            posting, note = _post_payment(conn, sub, c)
        elif c.status_code == "4":
            text = denial_text(adjustments)
            conn.execute("UPDATE claims SET status = 'denied', denial_reason = %s WHERE id = %s", (text, claim_id))
            conn.execute("UPDATE insurance_claim_submissions SET status = 'denied', remitted_at = clock_timestamp() "
                         "WHERE id = %s", (sub["id"],))
            posting, note = "posted", f"Denied. {text}"
            _tell_patient(conn, patient_id, claim_id, denied=True)
        else:
            posting = "needs_review"
            note = (f"{codes.CLAIM_PAYMENT_STATUS.get(c.status_code, 'Status ' + c.status_code)}: "
                    "billing staff must post this by hand.")
    row = conn.execute(
        """
        INSERT INTO insurance_remittance_claims
            (remittance_id, submission_id, claim_id, patient_id, patient_control_number, status_code, charge_cents,
             paid_cents, patient_resp_cents, payer_claim_number, adjustments, service_lines, posting_status, posting_note)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text
        """,
        (remittance_id, sub["id"] if sub else None, claim_id, patient_id, c.patient_control_number, c.status_code,
         c.charge_cents, c.paid_cents, c.patient_resp_cents, c.payer_claim_number, Jsonb(adjustments),
         Jsonb([line.model_dump(mode="json") for line in c.service_lines]), posting, note),
    ).fetchone()
    if patient_id:
        audit.record(conn, action="insurance_remittance_posted", entity_type="claim", entity_id=claim_id, actor=actor,
                     patient_id=patient_id, detail={"remittance_claim_id": row["id"], "posting": posting,
                                                    "paid_cents": c.paid_cents, "status_code": c.status_code})
    return {"id": row["id"], "patient_control_number": c.patient_control_number, "posting_status": posting,
            "note": note, "paid_cents": c.paid_cents, "patient_resp_cents": c.patient_resp_cents}


def _post_payment(conn: Connection, sub: dict[str, Any], c: Any) -> tuple[str, str]:
    """Write the payer's adjudication into billing: EOB, claim status, statement, accumulators."""
    deductible = c.patient_resp_by_reason("1")
    coinsurance = c.patient_resp_by_reason("2")
    copay = c.patient_resp_by_reason("3")
    allowed = c.paid_cents + c.patient_resp_cents
    eob = conn.execute(
        """
        INSERT INTO explanation_of_benefits (claim_id, patient_id, allowed_cents, plan_paid_cents, copay_cents,
                                             deductible_cents, coinsurance_cents, patient_resp_cents)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (claim_id) DO NOTHING RETURNING id
        """,
        (sub["claim_id"], sub["patient_id"], allowed, c.paid_cents, copay, deductible, coinsurance,
         c.patient_resp_cents),
    ).fetchone()
    conn.execute("UPDATE insurance_claim_submissions SET status = 'paid', remitted_at = clock_timestamp() WHERE id = %s",
                 (sub["id"],))
    if eob is None:
        return "already_posted", "Billing already had an explanation of benefits for this claim; nothing changed."
    conn.execute("UPDATE claims SET status = 'paid', denial_reason = NULL WHERE id = %s", (sub["claim_id"],))
    today = clinic_now().date()
    if c.patient_resp_cents > 0:
        conn.execute(
            """
            INSERT INTO patient_statements (patient_id, claim_id, amount_cents, issued_on, due_on)
            VALUES (%s, %s, %s, %s, %s) ON CONFLICT (claim_id) DO NOTHING
            """,
            (sub["patient_id"], sub["claim_id"], c.patient_resp_cents, today, today + timedelta(days=30)),
        )
    conn.execute(
        """
        UPDATE coverages SET deductible_met_cents = least(deductible_cents, deductible_met_cents + %s),
                             oop_met_cents = least(oop_max_cents, oop_met_cents + %s)
        WHERE id = %s
        """,
        (deductible, c.patient_resp_cents, sub["coverage_id"]),
    )
    _tell_patient(conn, sub["patient_id"], sub["claim_id"], denied=False)
    return "posted", (f"Paid {money_plain(c.paid_cents)}; patient responsibility {money_plain(c.patient_resp_cents)}"
                      f" (deductible {money_plain(deductible)}, coinsurance {money_plain(coinsurance)}, "
                      f"copay {money_plain(copay)}).")


def _tell_patient(conn: Connection, patient_id: str, claim_id: str, *, denied: bool) -> None:
    uid = patient_user(conn, patient_id)
    if uid:
        notify(conn, user_id=uid, kind="insurance_claim_processed", patient_id=patient_id, link="/billing",
               title="Your insurance processed a claim",
               body="Open Bills & coverage to see what the plan paid and what, if anything, you owe."
               if not denied else "Open Bills & coverage to see why the plan didn't pay and what happens next.",
               dedupe_key=f"insurance-claim:{claim_id}:{'denied' if denied else 'paid'}")


def fetch_remittances(conn: Connection, *, organization_id: str | None = None, actor: Any = None) -> dict[str, Any]:
    """Ask every connected payer for waiting 835s and post them."""
    rows = conn.execute(
        """
        SELECT DISTINCT ON (y.id, pc.gateway) y.id::text AS id, y.name, y.payer_id, y.connection_type,
               y.fhir_base_url, y.auth_required_procedures, pc.gateway, pc.credentials_secret_name
        FROM payer_connections pc JOIN payers y ON y.id = pc.payer_ref
        WHERE pc.status = 'connected' AND (%s::uuid IS NULL OR pc.organization_id = %s::uuid)
        ORDER BY y.id, pc.gateway
        """,
        (organization_id, organization_id),
    ).fetchall()
    summary = {"remittances": 0, "claims_posted": 0, "errors": []}
    for payer in rows:
        try:
            gateway = build_gateway(conn, payer["gateway"], payer["credentials_secret_name"])
            texts = gateway.fetch_remittances(payer)
        except GatewayError as exc:
            summary["errors"].append(f"{payer['name']}: {exc}")
            continue
        for text in texts:
            try:
                posted = post_remittance(conn, text, source="simulated" if gateway.simulated else "imported", actor=actor)
            except ServiceError as exc:
                summary["errors"].append(f"{payer['name']}: {'; '.join(exc.errors)}")
                continue
            summary["remittances"] += 0 if posted["duplicate"] else 1
            summary["claims_posted"] += sum(1 for c in posted["claims"] if c["posting_status"] == "posted")
    return summary
