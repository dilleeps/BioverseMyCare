"""837P professional claim (005010X222A1): validate, build, and parse (the simulated payer reads it).

    validate_837p(claim) -> list of readable problems ("Subscriber member ID missing")
    build_837p(claim, env) -> X12 text, or X12Error listing every problem
    parse_837p(text)       -> list[ProfessionalClaim]
"""

from __future__ import annotations

import re
from datetime import date

from bioverse.x12 import codes
from bioverse.x12.core import (
    Envelope, Segment, X12Error, amount, build_interchange, cents, clean, composite, d8, el, name_value,
    parse_date_value, parse_interchange, seg,
)
from bioverse.x12.models import (
    RELATIONSHIP_CODES, RELATIONSHIP_FROM_CODE, Address, Payer, Person, ProfessionalClaim, Provider,
    ServiceLine, Subscriber,
)

VERSION = "005010X222A1"
MAX_DIAGNOSES = 12
MAX_LINES = 50


def _npi_problem(label: str, npi: str | None) -> str | None:
    if not npi:
        return f"{label} NPI missing"
    if not codes.npi_valid(npi):
        return f"{label} NPI {npi} is not a valid NPI (10 digits with a correct check digit)"
    return None


def validate_837p(c: ProfessionalClaim) -> list[str]:
    errors: list[str] = []
    if not c.patient_control_number.strip():
        errors.append("Patient control number missing")
    elif len(c.patient_control_number) > 20:
        errors.append("Patient control number must be 20 characters or fewer")
    if not c.submitter.npi and not c.submitter.tax_id and not c.submitter.name:
        errors.append("Submitter missing")
    if not c.receiver.tax_id:
        errors.append("Receiver (clearinghouse) ID missing")

    bp = c.billing_provider
    if not bp.name.strip():
        errors.append("Billing provider name missing")
    if p := _npi_problem("Billing provider", bp.npi):
        errors.append(p)
    if not bp.tax_id or not re.fullmatch(r"\d{9}", bp.tax_id.replace("-", "")):
        errors.append("Billing provider tax ID (EIN, 9 digits) missing")
    if bp.address is None or not bp.address.complete():
        errors.append("Billing provider address missing")

    if not c.payer.payer_id.strip():
        errors.append("Payer ID missing")
    if not c.payer.name.strip():
        errors.append("Payer name missing")

    sub = c.subscriber
    if not sub.member_id.strip():
        errors.append("Subscriber member ID missing")
    if not (sub.first_name.strip() and sub.last_name.strip()):
        errors.append("Subscriber name missing")
    if c.relationship == "self":
        if sub.birth_date is None:
            errors.append("Subscriber date of birth missing")
        if sub.address is None or not sub.address.complete():
            errors.append("Subscriber address missing (required when the patient is the subscriber)")
    else:
        if c.patient is None or not (c.patient.first_name and c.patient.last_name):
            errors.append("Patient name missing (the patient is a dependent of the subscriber)")
        elif c.patient.birth_date is None:
            errors.append("Patient date of birth missing")
        if c.patient_address is None or not c.patient_address.complete():
            errors.append("Patient address missing")

    if c.rendering_provider is not None and (p := _npi_problem("Rendering provider", c.rendering_provider.npi)):
        errors.append(p)

    if not c.diagnosis_codes:
        errors.append("At least one diagnosis code is required")
    if len(c.diagnosis_codes) > MAX_DIAGNOSES:
        errors.append(f"At most {MAX_DIAGNOSES} diagnosis codes fit on a professional claim")
    for code in c.diagnosis_codes:
        if not codes.icd10_valid(code):
            errors.append(f"Diagnosis code '{code}' is not in ICD-10-CM format (for example E78.5)")

    if not c.service_lines:
        errors.append("At least one service line is required")
    if len(c.service_lines) > MAX_LINES:
        errors.append(f"At most {MAX_LINES} service lines fit on a professional claim")
    for i, line in enumerate(c.service_lines, start=1):
        if not line.procedure_code.strip():
            errors.append(f"Service line {i}: procedure code missing")
        elif not codes.PROCEDURE_PATTERN.match(line.procedure_code.strip().upper()):
            errors.append(f"Service line {i}: procedure code '{line.procedure_code}' must be a 5-character CPT or HCPCS code")
        if len(line.modifiers) > 4:
            errors.append(f"Service line {i}: at most 4 modifiers")
        if line.charge_cents <= 0:
            errors.append(f"Service line {i}: charge must be more than $0")
        if line.units < 1:
            errors.append(f"Service line {i}: units must be at least 1")
        if not line.diagnosis_pointers:
            errors.append(f"Service line {i}: needs at least one diagnosis pointer")
        for ptr in line.diagnosis_pointers:
            if not 1 <= ptr <= min(len(c.diagnosis_codes), 12) or ptr > 12:
                errors.append(f"Service line {i}: diagnosis pointer {ptr} has no matching diagnosis code")
        if len(line.diagnosis_pointers) > 4:
            errors.append(f"Service line {i}: at most 4 diagnosis pointers")
    return errors


def _address(a: Address) -> list[Segment]:
    return [seg("N3", name_value(a.line1)),
            seg("N4", name_value(a.city), clean(a.state).upper(), clean(a.zip).replace("-", ""))]


def _dmg(p: Person) -> Segment:
    assert p.birth_date is not None
    return seg("DMG", "D8", d8(p.birth_date), p.gender)


def build_837p(c: ProfessionalClaim, env: Envelope) -> str:
    errors = validate_837p(c)
    if errors:
        raise X12Error(errors)
    now = env.timestamp
    sub, bp = c.subscriber, c.billing_provider
    is_self = c.relationship == "self"
    body: list[Segment] = [
        seg("BHT", "0019", "00", clean(c.reference or c.patient_control_number), d8(now.date()),
            now.strftime("%H%M"), "CH"),
        seg("NM1", "41", "2", name_value(c.submitter.name), "", "", "", "", "46",
            clean(c.submitter.tax_id or c.submitter.npi)),
        seg("PER", "IC", name_value(c.submitter_contact), "TE", "".join(ch for ch in c.submitter_phone if ch.isdigit())),
        seg("NM1", "40", "2", name_value(c.receiver.name), "", "", "", "", "46", clean(c.receiver.tax_id)),
        seg("HL", "1", "", "20", "1"),
    ]
    if bp.taxonomy:
        body.append(seg("PRV", "BI", "PXC", clean(bp.taxonomy)))
    body.append(seg("NM1", "85", "2", name_value(bp.name), "", "", "", "", "XX", bp.npi))
    assert bp.address is not None
    body += _address(bp.address)
    body.append(seg("REF", "EI", (bp.tax_id or "").replace("-", "")))

    body += [
        seg("HL", "2", "1", "22", "0" if is_self else "1"),
        seg("SBR", "P", "18" if is_self else "", clean(sub.group_number or ""), "", "", "", "", "",
            clean(c.claim_filing_indicator)),
        seg("NM1", "IL", "1", name_value(sub.last_name), name_value(sub.first_name), "", "", "", "MI",
            clean(sub.member_id)),
    ]
    if is_self:
        assert sub.address is not None
        body += _address(sub.address)
        body.append(_dmg(sub))
    body.append(seg("NM1", "PR", "2", name_value(c.payer.name), "", "", "", "", "PI", clean(c.payer.payer_id)))
    if not is_self:
        assert c.patient is not None and c.patient_address is not None
        body += [seg("HL", "3", "2", "23", "0"), seg("PAT", RELATIONSHIP_CODES[c.relationship]),
                 seg("NM1", "QC", "1", name_value(c.patient.last_name), name_value(c.patient.first_name)),
                 *_address(c.patient_address), _dmg(c.patient)]

    body.append(seg("CLM", clean(c.patient_control_number), amount(c.total_charge_cents), "", "",
                    f"{c.place_of_service}:B:{c.frequency_code}", "Y", "A", "Y", "Y"))
    if c.prior_authorization:
        body.append(seg("REF", "G1", clean(c.prior_authorization)))
    hi = [f"{'ABK' if i == 0 else 'ABF'}:{codes.icd10_x12(code)}" for i, code in enumerate(c.diagnosis_codes)]
    body.append(seg("HI", *hi))
    rp = c.rendering_provider
    if rp is not None:
        body.append(seg("NM1", "82", "1", name_value(rp.name), name_value(rp.first_name or ""), "", "", "", "XX", rp.npi))
        if rp.taxonomy:
            body.append(seg("PRV", "PE", "PXC", clean(rp.taxonomy)))
    for i, line in enumerate(c.service_lines, start=1):
        proc = ":".join(["HC", clean(line.procedure_code).upper(), *[clean(m).upper() for m in line.modifiers]])
        pos = line.place_of_service if line.place_of_service and line.place_of_service != c.place_of_service else ""
        body += [
            seg("LX", str(i)),
            seg("SV1", proc, amount(line.charge_cents), "UN", str(line.units), pos, "",
                ":".join(str(p) for p in line.diagnosis_pointers)),
            seg("DTP", "472", "D8", d8(line.service_date)),
        ]
    return build_interchange(env, transaction_set="837", version=VERSION, bodies=[body])


def _parse_address(pending: dict, s: Segment) -> None:
    if s[0] == "N3":
        pending["line1"] = el(s, 1)
    else:
        pending.update(city=el(s, 1), state=el(s, 2), zip=el(s, 3))


def parse_837p(text: str) -> list[ProfessionalClaim]:
    """Every claim in every 837 transaction. Addresses and names come back upper-cased, as sent."""
    ic = parse_interchange(text)
    d = ic.delimiters
    txns = ic.transactions("837")
    if not txns:
        raise X12Error("Expected an 837 transaction set")
    claims: list[ProfessionalClaim] = []
    declared: dict[str, int] = {}
    for txn in txns:
        reference = ""
        submitter = Provider()
        receiver = Provider()
        contact, phone = "", ""
        billing = Provider()
        payer = Payer(name="", payer_id="")
        subscriber = Subscriber()
        patient: Person | None = None
        patient_addr: Address | None = None
        relationship = "self"
        filing = "CI"
        current: ProfessionalClaim | None = None
        addr_target = None
        addr: dict = {}
        line: ServiceLine | None = None

        def flush_addr() -> None:
            nonlocal addr, addr_target, patient_addr
            if addr_target is not None and addr:
                a = Address(**{k: addr.get(k, "") for k in ("line1", "city", "state", "zip")})
                if addr_target == "85":
                    billing.address = a
                elif addr_target == "IL":
                    subscriber.address = a
                elif addr_target == "QC":
                    patient_addr = a
            addr, addr_target = {}, None

        for s in txn.body:
            sid = s[0]
            if sid in ("N3", "N4"):
                _parse_address(addr, s)
                continue
            flush_addr()
            if sid == "BHT":
                reference = el(s, 3)
            elif sid == "PER" and el(s, 1) == "IC":
                contact, phone = el(s, 2), el(s, 4)
            elif sid == "PRV" and el(s, 1) == "BI":
                billing.taxonomy = el(s, 3)
            elif sid == "PRV" and el(s, 1) == "PE" and current is not None and current.rendering_provider:
                current.rendering_provider.taxonomy = el(s, 3)
            elif sid == "NM1":
                entity = el(s, 1)
                if entity == "41":
                    submitter = Provider(name=el(s, 3), tax_id=el(s, 9))
                elif entity == "40":
                    receiver = Provider(name=el(s, 3), tax_id=el(s, 9))
                elif entity == "85":
                    billing.name, billing.npi, addr_target = el(s, 3), el(s, 9), "85"
                elif entity == "IL":
                    subscriber.last_name, subscriber.first_name, subscriber.member_id = el(s, 3), el(s, 4), el(s, 9)
                    addr_target = "IL"
                elif entity == "PR":
                    payer = Payer(name=el(s, 3), payer_id=el(s, 9))
                elif entity == "QC":
                    patient = Person(last_name=el(s, 3), first_name=el(s, 4))
                    addr_target = "QC"
                elif entity == "82" and current is not None:
                    current.rendering_provider = Provider(name=el(s, 3), first_name=el(s, 4) or None, npi=el(s, 9))
            elif sid == "REF" and el(s, 1) == "EI":
                billing.tax_id = el(s, 2)
            elif sid == "REF" and el(s, 1) == "G1" and current is not None:
                current.prior_authorization = el(s, 2)
            elif sid == "SBR":
                subscriber.group_number = el(s, 3) or None
                filing = el(s, 9) or "CI"
            elif sid == "PAT":
                relationship = RELATIONSHIP_FROM_CODE.get(el(s, 1), "other")
            elif sid == "DMG" and el(s, 1) == "D8":
                dob, _ = parse_date_value("D8", el(s, 2), what="DMG02 birth date")
                target = patient if patient is not None else subscriber
                target.birth_date = dob
                target.gender = el(s, 3) if el(s, 3) in ("F", "M", "U") else "U"
            elif sid == "CLM":
                pos = composite(el(s, 5), d)
                current = ProfessionalClaim(
                    patient_control_number=el(s, 1), submitter=submitter, submitter_contact=contact,
                    submitter_phone=phone, receiver=receiver, billing_provider=billing, payer=payer,
                    subscriber=subscriber, relationship=relationship, patient=patient, patient_address=patient_addr,
                    claim_filing_indicator=filing, place_of_service=pos[0] if pos else "11",
                    frequency_code=pos[2] if len(pos) > 2 else "1", reference=reference,
                )
                declared[current.patient_control_number] = cents(el(s, 2), what="CLM02 total charge")
                claims.append(current)
            elif sid == "HI" and current is not None:
                for element in s[1:]:
                    parts = composite(element, d)
                    if len(parts) >= 2:
                        current.diagnosis_codes.append(codes.icd10_display(parts[1]))
            elif sid == "SV1" and current is not None:
                proc = composite(el(s, 1), d)
                line = ServiceLine(
                    procedure_code=proc[1] if len(proc) > 1 else "", modifiers=proc[2:6],
                    charge_cents=cents(el(s, 2), what="SV102 charge"), units=int(float(el(s, 4) or "1")),
                    service_date=date.min,  # replaced by the line's DTP*472
                    diagnosis_pointers=[int(p) for p in composite(el(s, 7), d) if p.isdigit()],
                    place_of_service=el(s, 5) or None,
                )
                current.service_lines.append(line)
            elif sid == "DTP" and el(s, 1) == "472" and line is not None:
                line.service_date, _ = parse_date_value(el(s, 2), el(s, 3), what="DTP*472 service date")
        flush_addr()
    for c in claims:
        total = declared.get(c.patient_control_number)
        if total is not None and total != c.total_charge_cents:
            raise X12Error(f"Claim {c.patient_control_number}: CLM02 total {amount(total)} does not equal "
                           f"the service lines' total {amount(c.total_charge_cents)}")
        for i, line in enumerate(c.service_lines, start=1):
            if line.service_date == date.min:
                raise X12Error(f"Claim {c.patient_control_number}, service line {i}: date of service (DTP*472) missing")
    return claims
