"""SimulatedClearinghouse: a stand-in for a clearinghouse and the payers behind it. DEMO ONLY.

It speaks real X12 in both directions, so everything upstream (building, sending, parsing, posting)
runs exactly as it would against a real clearinghouse. Answers are deterministic and come from the
fictional payer-side tables `payer_sim_members` and `payer_sim_claims`:

- 270 -> 271: looks the member up by payer ID and member ID, checks name and date of birth, and
  returns plan dates, deductible and out-of-pocket accumulators, copays and coinsurance.
- 837 -> 277CA: accepts claims for known members (A2) and rejects unknown ones (A3, subscriber not found).
- 835 later: `fetch_remittances` adjudicates accepted claims with the same benefit rules billing's
  estimates use, updates the member's accumulators, and returns one 835 per billing provider.
  Denials: coverage not active on the date of service (CARC 27); prior authorization required but
  absent (CARC 197).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from bioverse.config import clinic_tz
from bioverse.payers.gateway import ConnectionTest, GatewayError, PayerGateway
from bioverse.x12 import (
    Envelope, X12Error, build_271, build_277ca, build_835, parse_270, parse_271, parse_837p,
)
from bioverse.x12.core import d8
from bioverse.x12.models import (
    Accumulator, Acknowledgment277, Adjustment, ClaimAcknowledgment, Coinsurance, Copay, EligibilityInquiry,
    EligibilityResult, Payer, Person, ProfessionalClaim, Provider, Rejection, RemitClaim, RemitServiceLine,
    Remittance, Subscriber,
)

SENDER_ID = "BVSIMCH"
SENDER_NAME = "Bioverse Simulated Clearinghouse"

# The simulated payers' fee schedule (allowed amount per unit), matching billing's demo contracted rates.
FEE_SCHEDULE = {"99213": 15000, "99214": 26000, "99204": 26000, "93306": 90000, "80061": 4500}
PRIMARY_CARE_TAXONOMIES = {"207Q00000X", "207R00000X", "208D00000X", "261QP2300X"}

COPAY_ROWS = [
    # member copay key, service type, MSG text
    ("primary_care", "98", "PRIMARY CARE PHYSICIAN"),
    ("specialist", "98", "SPECIALIST"),
    ("telehealth", "98", "TELEHEALTH VISIT"),
    ("urgent_care", "UC", None),
    ("generic_rx", "88", "GENERIC DRUGS"),
]


def _q(conn: Connection, sql: str, params: Any = None):
    """Dict rows whatever the connection's default row factory (seeds use tuples, requests dicts)."""
    return conn.cursor(row_factory=dict_row).execute(sql, params)


def _now() -> datetime:
    return datetime.now(clinic_tz())


def _find_payer(conn: Connection, payer_id: str) -> dict[str, Any] | None:
    return _q(conn, 
        "SELECT id::text, name, payer_id, member_phone, auth_required_procedures FROM payers WHERE payer_id = %s",
        (payer_id.strip(),),
    ).fetchone()


def _find_member(conn: Connection, payer_ref: str, member_id: str) -> dict[str, Any] | None:
    return _q(conn, 
        "SELECT * FROM payer_sim_members WHERE payer_ref = %s AND upper(member_id) = upper(%s)",
        (payer_ref, member_id.strip()),
    ).fetchone()


def _active_on(member: dict[str, Any], day: date) -> bool:
    return member["plan_begin"] <= day and (member["plan_end"] is None or member["plan_end"] >= day)


def category_for(procedure: str, modifiers: list[str], pos: str | None, rendering_taxonomy: str | None) -> str:
    """Billing's service category for a procedure code, so copays apply the way the plan defines them."""
    if procedure.startswith("992"):
        if "95" in modifiers or pos in ("02", "10"):
            return "telehealth"
        return "primary_care" if rendering_taxonomy in PRIMARY_CARE_TAXONOMIES else "specialist"
    if procedure.startswith("7") or procedure.startswith("93"):
        return "imaging"
    if procedure.startswith("8"):
        return "lab"
    return "other"


class SimulatedClearinghouse(PayerGateway):
    simulated = True
    label = "simulated-clearinghouse"

    def __init__(self, conn: Connection):
        self.conn = conn

    def _env(self, receiver: str) -> Envelope:
        n = _q(self.conn, "SELECT nextval('insurance_control_seq') AS n").fetchone()["n"] % 999_999_999 or 1
        return Envelope(sender_id=SENDER_ID, receiver_id=receiver or "UNKNOWN", control_number=n,
                        timestamp=_now().replace(tzinfo=None))

    # --- Connection test ----------------------------------------------------------------------

    def test_connection(self, payer: dict[str, Any]) -> ConnectionTest:
        from bioverse.x12 import build_270

        probe = EligibilityInquiry(
            payer=Payer(name=payer["name"], payer_id=payer["payer_id"]),
            provider=Provider(name="CONNECTION TEST", npi="1234567893"),
            subscriber=Subscriber(first_name="TEST", last_name="PROBE", birth_date=date(1970, 1, 1),
                                  member_id="CONNECTION-TEST"),
            date_of_service=_now().date(), trace_number="PING", reference="PING",
        )
        reply = parse_271(self.eligibility(build_270(probe, self._env(payer["payer_id"]))))
        if reply.status not in ("not_found", "active", "inactive"):
            return ConnectionTest(False, "The simulated clearinghouse did not return a usable 271.")
        msg = f"Simulated clearinghouse answered a test 270 for {payer['name']} with a valid 271. Demo: no real payer was contacted."
        if payer.get("connection_type") == "fhir_payer_api" and payer.get("fhir_base_url"):
            msg += f" A live connection would also read {payer['fhir_base_url']}/metadata."
        return ConnectionTest(True, msg)

    # --- 270 -> 271 -----------------------------------------------------------------------------

    def benefits_for(self, member: dict[str, Any], payer: dict[str, Any], dos: date) -> EligibilityResult:
        person = Person(first_name=member["first_name"], last_name=member["last_name"],
                        birth_date=member["birth_date"], gender=member["gender"])
        base = dict(
            payer=Payer(name=payer["name"], payer_id=payer["payer_id"], phone=payer["member_phone"]),
            member_id=member["member_id"], subscriber=person, group_number=member["group_number"],
            plan_name=member["plan_name"], plan_begin=member["plan_begin"], plan_end=member["plan_end"],
        )
        if not _active_on(member, dos):
            return EligibilityResult(status="inactive", **base)

        def acc(total: int | None, met: int) -> Accumulator:
            return Accumulator() if total is None else Accumulator(total_cents=total, remaining_cents=max(0, total - met))

        copays = [Copay(service_type=stc, label="", amount_cents=int(member["copays"][key]), note=note)
                  for key, stc, note in COPAY_ROWS if key in (member["copays"] or {})]
        return EligibilityResult(
            status="active", **base,
            deductible_individual=acc(member["deductible_cents"], member["deductible_met_cents"]),
            deductible_family=acc(member["family_deductible_cents"], member["family_deductible_met_cents"]),
            oop_individual=acc(member["oop_max_cents"], member["oop_met_cents"]),
            oop_family=acc(member["family_oop_max_cents"], member["family_oop_met_cents"]),
            copays=copays,
            coinsurance=[Coinsurance(service_type="30", label="", percent=member["coinsurance_pct"], in_network=True),
                         Coinsurance(service_type="30", label="", percent=member["oon_coinsurance_pct"], in_network=False)],
        )

    def eligibility(self, x12_270: str) -> str:
        try:
            inq = parse_270(x12_270)
        except X12Error as exc:
            raise GatewayError(f"The simulated clearinghouse could not read the 270: {exc}") from None
        payer = _find_payer(self.conn, inq.payer.payer_id)
        if payer is None:
            result = EligibilityResult(status="error", rejections=[Rejection(code="41", reason="")])
        else:
            member = _find_member(self.conn, payer["id"], inq.subscriber.member_id)
            if member is None:
                result = EligibilityResult(status="not_found", rejections=[Rejection(code="75", reason="")])
            elif member["last_name"].upper() != inq.subscriber.last_name.upper():
                result = EligibilityResult(status="not_found", rejections=[Rejection(code="73", reason="")])
            elif inq.relationship == "self" and inq.subscriber.birth_date not in (None, member["birth_date"]):
                result = EligibilityResult(status="not_found", rejections=[Rejection(code="58", reason="")])
            else:
                result = self.benefits_for(member, payer, inq.date_of_service)
        return build_271(result, inq, self._env(inq.provider.npi))

    # --- 837 -> 277CA ---------------------------------------------------------------------------

    def submit_claims(self, x12_837: str) -> str:
        try:
            claims = parse_837p(x12_837)
        except X12Error as exc:
            raise GatewayError(f"The simulated clearinghouse could not read the 837: {exc}") from None
        if not claims:
            raise GatewayError("The 837 held no claims.")
        first = claims[0]
        payer = _find_payer(self.conn, first.payer.payer_id)
        acks: list[ClaimAcknowledgment] = []
        for c in claims:
            base = dict(patient_control_number=c.patient_control_number, charge_cents=c.total_charge_cents,
                        service_date=min(line.service_date for line in c.service_lines),
                        patient=Person(first_name=c.subscriber.first_name, last_name=c.subscriber.last_name),
                        member_id=c.subscriber.member_id, message="")
            member = _find_member(self.conn, payer["id"], c.subscriber.member_id) if payer else None
            if payer is None:
                acks.append(ClaimAcknowledgment(category_code="A3", status_code="116", entity_code="PR",
                                                accepted=False, **base))
                continue
            if member is None:
                acks.append(ClaimAcknowledgment(category_code="A3", status_code="33", entity_code="IL",
                                                accepted=False, **base))
                continue
            seq = _q(self.conn, "SELECT nextval('insurance_control_seq') AS n").fetchone()["n"]
            number = f"{payer['payer_id'][:3]}{_now():%y%m%d}{seq:06d}"
            _q(self.conn, 
                """
                INSERT INTO payer_sim_claims (payer_ref, patient_control_number, payer_claim_number, claim, status)
                VALUES (%s, %s, %s, %s, 'accepted')
                """,
                (payer["id"], c.patient_control_number, number, c.model_dump_json()),
            )
            acks.append(ClaimAcknowledgment(category_code="A2", status_code="20", accepted=True,
                                            payer_claim_number=number, **base))
        ack = Acknowledgment277(
            payer=Payer(name=payer["name"] if payer else first.payer.name, payer_id=first.payer.payer_id),
            receiver_name=first.submitter.name, receiver_id=first.submitter.tax_id or "",
            billing_provider=first.billing_provider, batch_reference=first.reference, received_on=_now().date(),
            claims=acks,
        )
        return build_277ca(ack, self._env(first.submitter.tax_id or ""))

    # --- 835 ------------------------------------------------------------------------------------

    def adjudicate(self, claim: ProfessionalClaim, payer: dict[str, Any], payer_claim_number: str) -> RemitClaim:
        from bioverse.routers.billing import calculate_estimate   # the same benefit rules billing estimates use

        member = _find_member(self.conn, payer["id"], claim.subscriber.member_id)
        dos = min(line.service_date for line in claim.service_lines)
        base = dict(patient_control_number=claim.patient_control_number, charge_cents=claim.total_charge_cents,
                    payer_claim_number=payer_claim_number, filing_indicator=claim.claim_filing_indicator,
                    patient=Person(first_name=claim.subscriber.first_name, last_name=claim.subscriber.last_name),
                    member_id=claim.subscriber.member_id, service_date=dos)

        def deny(code: str) -> RemitClaim:
            return RemitClaim(status_code="4", paid_cents=0, patient_resp_cents=0,
                              adjustments=[Adjustment(group="CO", reason_code=code, amount_cents=claim.total_charge_cents)],
                              **base)

        if member is None or not _active_on(member, dos):
            return deny("27")
        needs_auth = set(payer["auth_required_procedures"] or [])
        if needs_auth & {line.procedure_code for line in claim.service_lines} and not claim.prior_authorization:
            return deny("197")

        lines: list[RemitServiceLine] = []
        taxonomy = claim.rendering_provider.taxonomy if claim.rendering_provider else claim.billing_provider.taxonomy
        for line in claim.service_lines:
            per_unit = FEE_SCHEDULE.get(line.procedure_code, line.charge_cents * 60 // 100 // max(1, line.units))
            allowed = min(line.charge_cents, per_unit * line.units)
            category = category_for(line.procedure_code, line.modifiers, line.place_of_service or claim.place_of_service,
                                    taxonomy)
            est = calculate_estimate(allowed_cents=allowed, category=category, coverage=member, in_network=True)
            copay, ded, coins = est["copay_cents"], est["deductible_cents"], est["coinsurance_cents"]
            cut = est["oop_cap_reduction_cents"]
            for_part = min(cut, coins)
            coins, cut = coins - for_part, cut - for_part
            for_part = min(cut, ded)
            ded, cut = ded - for_part, cut - for_part
            copay -= min(cut, copay)
            patient = copay + ded + coins
            adjustments = []
            if line.charge_cents > allowed:
                adjustments.append(Adjustment(group="CO", reason_code="45", amount_cents=line.charge_cents - allowed))
            for code, value in (("1", ded), ("2", coins), ("3", copay)):
                if value:
                    adjustments.append(Adjustment(group="PR", reason_code=code, amount_cents=value))
            lines.append(RemitServiceLine(procedure_code=line.procedure_code, modifiers=line.modifiers,
                                          charge_cents=line.charge_cents, paid_cents=allowed - patient,
                                          units=line.units, service_date=line.service_date, allowed_cents=allowed,
                                          adjustments=adjustments))
            # The payer's accumulators move with every adjudicated line.
            member["deductible_met_cents"] += ded
            member["oop_met_cents"] += patient
            member["family_deductible_met_cents"] += ded
            member["family_oop_met_cents"] += patient
            _q(self.conn, 
                """
                UPDATE payer_sim_members SET deductible_met_cents = %s, oop_met_cents = %s,
                       family_deductible_met_cents = %s, family_oop_met_cents = %s WHERE id = %s
                """,
                (member["deductible_met_cents"], member["oop_met_cents"], member["family_deductible_met_cents"],
                 member["family_oop_met_cents"], member["id"]),
            )
        paid = sum(line.paid_cents for line in lines)
        patient_resp = sum(a.amount_cents for line in lines for a in line.adjustments if a.group == "PR")
        return RemitClaim(status_code="1", paid_cents=paid, patient_resp_cents=patient_resp, service_lines=lines, **base)

    def fetch_remittances(self, payer: dict[str, Any]) -> list[str]:
        payer = _find_payer(self.conn, payer["payer_id"]) or payer
        pending = _q(self.conn, 
            """
            SELECT id::text, payer_claim_number, claim FROM payer_sim_claims
            WHERE payer_ref = %s AND status = 'accepted' ORDER BY received_at FOR UPDATE SKIP LOCKED
            """,
            (payer["id"],),
        ).fetchall()
        if not pending:
            return []
        by_payee: dict[str, list[tuple[str, ProfessionalClaim, RemitClaim]]] = {}
        payees: dict[str, Provider] = {}
        for row in pending:
            raw = row["claim"] if isinstance(row["claim"], dict) else json.loads(row["claim"])
            claim = ProfessionalClaim.model_validate(raw)
            remit = self.adjudicate(claim, payer, row["payer_claim_number"])
            npi = claim.billing_provider.npi
            payees[npi] = claim.billing_provider
            by_payee.setdefault(npi, []).append((row["id"], claim, remit))
        texts = []
        today = _now().date()
        for i, (npi, items) in enumerate(sorted(by_payee.items())):
            seq = _q(self.conn, "SELECT nextval('insurance_control_seq') AS n").fetchone()["n"]
            trace = f"SIM{payer['payer_id']}{d8(today)}{seq:06d}"
            remittance = Remittance(
                payer=Payer(name=payer["name"], payer_id=payer["payer_id"]),
                payee=Provider(name=payees[npi].name, npi=npi),
                payment_cents=sum(r.paid_cents for _, _, r in items),
                payment_method="ACH", payment_date=today, trace_number=trace,
                claims=[r for _, _, r in items],
            )
            submitter = items[0][1].submitter.tax_id or ""
            texts.append(build_835(remittance, self._env(submitter)))
            for sim_id, _, _ in items:
                _q(self.conn, 
                    "UPDATE payer_sim_claims SET status = 'adjudicated', adjudicated_at = clock_timestamp(), "
                    "remit_trace = %s WHERE id = %s",
                    (trace, sim_id),
                )
        return texts
