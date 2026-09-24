"""277CA claim acknowledgment (005010X214): did the payer accept each claim into adjudication?

    build_277ca(ack, env) -> X12 text   (the simulated payer)
    parse_277ca(text)     -> Acknowledgment277
"""

from __future__ import annotations

from bioverse.x12 import codes
from bioverse.x12.core import (
    Envelope, Segment, amount, build_interchange, cents, clean, composite, d8, el, name_value,
    parse_date_value, seg, single_transaction,
)
from bioverse.x12.models import Acknowledgment277, ClaimAcknowledgment, Payer, Person, Provider

VERSION = "005010X214"


def status_message(category: str, status: str, entity: str | None) -> str:
    text = codes.STATUS_CATEGORIES.get(category, f"Status category {category}")
    detail = codes.STATUS_CODES.get(status)
    if detail:
        text += f": {detail}"
    if entity and entity in codes.ENTITIES:
        text += f" ({codes.ENTITIES[entity]})"
    return text


def build_277ca(ack: Acknowledgment277, env: Envelope) -> str:
    now = env.timestamp
    received = ack.received_on or now.date()
    accepted = [c for c in ack.claims if c.accepted]
    rejected = [c for c in ack.claims if not c.accepted]
    body: list[Segment] = [
        seg("BHT", "0085", "08", clean(ack.batch_reference), d8(now.date()), now.strftime("%H%M"), "TH"),
        seg("HL", "1", "", "20", "1"),
        seg("NM1", "PR", "2", name_value(ack.payer.name), "", "", "", "", "PI", clean(ack.payer.payer_id)),
        seg("TRN", "1", f"{env.control_number:09d}"),
        seg("DTP", "050", "D8", d8(received)),
        seg("DTP", "009", "D8", d8(now.date())),
        seg("HL", "2", "1", "21", "1"),
        seg("NM1", "41", "2", name_value(ack.receiver_name), "", "", "", "", "46", clean(ack.receiver_id)),
        seg("TRN", "2", clean(ack.batch_reference)),
        seg("STC", "A1:19:PR", d8(received), "WQ", amount(sum(c.charge_cents for c in ack.claims))),
        seg("QTY", "90", str(len(accepted))),
        seg("QTY", "AA", str(len(rejected))),
        seg("AMT", "YU", amount(sum(c.charge_cents for c in accepted))),
        seg("AMT", "YY", amount(sum(c.charge_cents for c in rejected))),
    ]
    bp = ack.billing_provider or Provider()
    body += [seg("HL", "3", "2", "19", "1"),
             seg("NM1", "85", "2", name_value(bp.name), "", "", "", "", "XX", bp.npi)]
    for i, c in enumerate(ack.claims):
        stc01 = ":".join(p for p in (c.category_code, c.status_code, c.entity_code or "") if p)
        pat = c.patient or Person()
        body += [
            seg("HL", str(4 + i), "3", "PT"),
            seg("NM1", "QC", "1", name_value(pat.last_name), name_value(pat.first_name), "", "", "", "MI",
                clean(c.member_id or "")),
            seg("TRN", "2", clean(c.patient_control_number)),
            seg("STC", stc01, d8(received), "WQ" if c.accepted else "U", amount(c.charge_cents)),
        ]
        if c.payer_claim_number:
            body.append(seg("REF", "1K", clean(c.payer_claim_number)))
        if c.service_date:
            body.append(seg("DTP", "472", "D8", d8(c.service_date)))
    return build_interchange(env, transaction_set="277", version=VERSION, bodies=[body])


def parse_277ca(text: str) -> Acknowledgment277:
    ic, txn = single_transaction(text, "277")
    d = ic.delimiters
    ack = Acknowledgment277(payer=Payer(name="", payer_id=""))
    level = ""
    current: ClaimAcknowledgment | None = None
    pending_patient: Person | None = None
    pending_member: str | None = None
    for s in txn.body:
        sid = s[0]
        if sid == "HL":
            level = el(s, 3)
            current = None
        elif sid == "NM1":
            entity = el(s, 1)
            if entity == "PR":
                ack.payer = Payer(name=el(s, 3), payer_id=el(s, 9))
            elif entity == "41":
                ack.receiver_name, ack.receiver_id = el(s, 3), el(s, 9)
            elif entity == "85":
                ack.billing_provider = Provider(name=el(s, 3), npi=el(s, 9))
            elif entity == "QC":
                pending_patient = Person(last_name=el(s, 3), first_name=el(s, 4))
                pending_member = el(s, 9) or None
        elif sid == "DTP" and el(s, 1) == "050":
            ack.received_on, _ = parse_date_value(el(s, 2), el(s, 3), what="DTP*050 received date")
        elif sid == "TRN" and el(s, 1) == "2":
            if level == "21":
                ack.batch_reference = el(s, 2)
            elif level == "PT":
                current = ClaimAcknowledgment(
                    patient_control_number=el(s, 2), category_code="", status_code="", accepted=False, message="",
                    patient=pending_patient, member_id=pending_member,
                )
                ack.claims.append(current)
        elif sid == "STC" and level == "PT" and current is not None and not current.category_code:
            parts = composite(el(s, 1), d)
            current.category_code = parts[0] if parts else ""
            current.status_code = parts[1] if len(parts) > 1 else ""
            current.entity_code = parts[2] if len(parts) > 2 else None
            current.accepted = current.category_code in codes.ACCEPTED_CATEGORIES
            current.message = status_message(current.category_code, current.status_code, current.entity_code)
            current.charge_cents = cents(el(s, 4), what="STC04 charge")
        elif sid == "REF" and el(s, 1) == "1K" and current is not None:
            current.payer_claim_number = el(s, 2)
        elif sid == "DTP" and el(s, 1) == "472" and current is not None:
            current.service_date, _ = parse_date_value(el(s, 2), el(s, 3), what="DTP*472 service date")
    for c in ack.claims:
        if not c.category_code:
            c.message = "No claim status (STC) was returned for this claim"
    return ack


def claim_status(ack: Acknowledgment277, patient_control_number: str) -> ClaimAcknowledgment | None:
    return next((c for c in ack.claims if c.patient_control_number == patient_control_number), None)

