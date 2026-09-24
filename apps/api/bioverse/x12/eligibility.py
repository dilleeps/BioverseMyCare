"""270 eligibility inquiry and 271 eligibility response (005010X279A1).

    build_270(inquiry, env)   -> X12 text
    parse_270(text)           -> EligibilityInquiry         (used by the simulated clearinghouse)
    build_271(result, inquiry, env) -> X12 text            (used by the simulated clearinghouse)
    parse_271(text)           -> EligibilityResult          (plan status, dates, accumulators, copays...)
"""

from __future__ import annotations

from datetime import datetime

from bioverse.x12 import codes
from bioverse.x12.core import (
    Envelope, Segment, X12Error, amount, build_interchange, cents, clean, d8, el, name_value,
    parse_date_value, percent_from, percent_value, repeats, seg, single_transaction,
)
from bioverse.x12.models import (
    Accumulator, Coinsurance, Copay, EligibilityInquiry, EligibilityResult, Payer, Person, Provider,
    Rejection, Subscriber,
)

VERSION = "005010X279A1"

NOT_FOUND_REASONS = {"15", "58", "72", "73", "75", "76"}


def _person_dmg(p: Person) -> Segment | None:
    if p.birth_date is None:
        return None
    return seg("DMG", "D8", d8(p.birth_date), p.gender)


def _trn(trace: str, npi: str) -> Segment:
    # TRN03: originating company identifier, "9" plus nine digits.
    return seg("TRN", "1", clean(trace), "9" + (npi or "000000000")[:9].ljust(9, "0"))


def validate_inquiry(inq: EligibilityInquiry) -> list[str]:
    errors = []
    if not inq.payer.payer_id.strip():
        errors.append("Payer ID missing")
    if not inq.provider.npi.strip():
        errors.append("Provider NPI missing")
    elif not codes.npi_valid(inq.provider.npi):
        errors.append(f"Provider NPI {inq.provider.npi} is not a valid NPI")
    if not inq.subscriber.member_id.strip():
        errors.append("Subscriber member ID missing")
    if not (inq.subscriber.first_name.strip() and inq.subscriber.last_name.strip()):
        errors.append("Subscriber name missing")
    if inq.relationship == "self" and inq.subscriber.birth_date is None:
        errors.append("Subscriber date of birth missing")
    if inq.relationship != "self":
        if inq.patient is None or not (inq.patient.first_name and inq.patient.last_name):
            errors.append("Patient name missing (the patient is a dependent of the subscriber)")
        elif inq.patient.birth_date is None:
            errors.append("Patient date of birth missing")
    if not inq.service_types:
        errors.append("At least one service type is required")
    return errors


def build_270(inq: EligibilityInquiry, env: Envelope) -> str:
    errors = validate_inquiry(inq)
    if errors:
        raise X12Error(errors)
    dependent = inq.relationship != "self"
    now: datetime = env.timestamp
    body: list[Segment] = [
        seg("BHT", "0022", "13", clean(inq.reference), d8(now.date()), now.strftime("%H%M")),
        seg("HL", "1", "", "20", "1"),
        seg("NM1", "PR", "2", name_value(inq.payer.name), "", "", "", "", "PI", clean(inq.payer.payer_id)),
        seg("HL", "2", "1", "21", "1"),
        seg("NM1", "1P", "2", name_value(inq.provider.name), "", "", "", "", "XX", inq.provider.npi),
        seg("HL", "3", "2", "22", "1" if dependent else "0"),
    ]
    sub = inq.subscriber
    if not dependent:
        body.append(_trn(inq.trace_number, inq.provider.npi))
    body.append(seg("NM1", "IL", "1", name_value(sub.last_name), name_value(sub.first_name), "", "", "", "MI",
                    clean(sub.member_id)))
    if sub.group_number:
        body.append(seg("REF", "6P", clean(sub.group_number)))
    if (dmg := _person_dmg(sub)) is not None:
        body.append(dmg)
    if dependent:
        pat = inq.patient
        assert pat is not None
        body += [seg("HL", "4", "3", "23", "0"), _trn(inq.trace_number, inq.provider.npi),
                 seg("NM1", "03", "1", name_value(pat.last_name), name_value(pat.first_name))]
        if (dmg := _person_dmg(pat)) is not None:
            body.append(dmg)
    body.append(seg("DTP", "291", "D8", d8(inq.date_of_service)))
    body += [seg("EQ", clean(stc)) for stc in inq.service_types]
    return build_interchange(env, transaction_set="270", version=VERSION, bodies=[body])


def parse_270(text: str) -> EligibilityInquiry:
    ic, txn = single_transaction(text, "270")
    payer = Payer(name="", payer_id="")
    provider = Provider()
    subscriber = Subscriber()
    patient: Person | None = None
    reference = trace = ""
    dos = None
    stcs: list[str] = []
    level = ""
    for s in txn.body:
        sid = s[0]
        if sid == "BHT":
            reference = el(s, 3)
        elif sid == "HL":
            level = el(s, 3)
        elif sid == "NM1":
            entity = el(s, 1)
            if entity == "PR":
                payer = Payer(name=el(s, 3), payer_id=el(s, 9))
            elif entity == "1P":
                provider = Provider(name=el(s, 3), npi=el(s, 9))
            elif entity == "IL":
                subscriber = Subscriber(last_name=el(s, 3), first_name=el(s, 4), member_id=el(s, 9))
            elif entity == "03":
                patient = Person(last_name=el(s, 3), first_name=el(s, 4))
        elif sid == "REF" and el(s, 1) == "6P":
            subscriber.group_number = el(s, 2)
        elif sid == "DMG" and el(s, 1) == "D8":
            dob, _ = parse_date_value("D8", el(s, 2), what="DMG02 birth date")
            target = patient if level == "23" and patient is not None else subscriber
            target.birth_date = dob
            target.gender = el(s, 3) if el(s, 3) in ("F", "M", "U") else "U"
        elif sid == "TRN":
            trace = el(s, 2)
        elif sid == "DTP" and el(s, 1) == "291":
            dos, _ = parse_date_value(el(s, 2), el(s, 3), what="DTP03 date of service")
        elif sid == "EQ":
            stcs += repeats(el(s, 1), ic.delimiters)
    if dos is None:
        raise X12Error("The 270 has no date of service (DTP*291)")
    return EligibilityInquiry(
        payer=payer, provider=provider, subscriber=subscriber, patient=patient,
        relationship="child" if patient else "self", service_types=stcs or ["30"], date_of_service=dos,
        trace_number=trace, reference=reference,
    )


# --- 271 ------------------------------------------------------------------------------------------


def _network(flag: bool | None) -> str:
    return "" if flag is None else ("Y" if flag else "N")


def _accumulator_segments(code: str, level: str, acc: Accumulator) -> list[Segment]:
    out = []
    if acc.total_cents is not None:
        out.append(seg("EB", code, level, "30", "", "", "23", amount(acc.total_cents), "", "", "", "", "Y"))
    if acc.remaining_cents is not None:
        out.append(seg("EB", code, level, "30", "", "", "29", amount(acc.remaining_cents), "", "", "", "", "Y"))
    return out


def build_271(result: EligibilityResult, inq: EligibilityInquiry, env: Envelope) -> str:
    """The simulated payer's answer. Echoes the inquiry's trace number and member."""
    now = env.timestamp
    payer = result.payer or inq.payer
    body: list[Segment] = [
        seg("BHT", "0022", "11", clean(inq.reference), d8(now.date()), now.strftime("%H%M")),
        seg("HL", "1", "", "20", "1"),
        seg("NM1", "PR", "2", name_value(payer.name), "", "", "", "", "PI", clean(payer.payer_id)),
    ]
    if payer.phone:
        body.append(seg("PER", "IC", "MEMBER SERVICES", "TE", "".join(c for c in payer.phone if c.isdigit())))
    body += [
        seg("HL", "2", "1", "21", "1"),
        seg("NM1", "1P", "2", name_value(inq.provider.name), "", "", "", "", "XX", inq.provider.npi),
        seg("HL", "3", "2", "22", "0"),
        seg("TRN", "2", clean(inq.trace_number), "9" + inq.provider.npi[:9].ljust(9, "0")),
    ]
    sub = result.subscriber or inq.subscriber
    body.append(seg("NM1", "IL", "1", name_value(sub.last_name), name_value(sub.first_name), "", "", "", "MI",
                    clean(result.member_id or inq.subscriber.member_id)))
    for r in result.rejections:
        body.append(seg("AAA", "N", "", r.code, r.follow_up or "C"))
    if result.status in ("not_found", "error"):
        return build_interchange(env, transaction_set="271", version=VERSION, bodies=[body])

    if result.group_number:
        body.append(seg("REF", "6P", clean(result.group_number)))
    if sub.birth_date:
        body.append(seg("DMG", "D8", d8(sub.birth_date), sub.gender))
    if result.plan_begin:
        body.append(seg("DTP", "346", "D8", d8(result.plan_begin)))
    if result.plan_end:
        body.append(seg("DTP", "347", "D8", d8(result.plan_end)))

    if result.status == "active":
        body.append(seg("EB", "1", "", "30", "", clean(result.plan_name or "")))
    else:
        body.append(seg("EB", "6", "", "30"))
    body += [seg("MSG", clean(m)) for m in result.messages]
    if result.status == "active":
        body += _accumulator_segments("C", "IND", result.deductible_individual)
        body += _accumulator_segments("C", "FAM", result.deductible_family)
        body += _accumulator_segments("G", "IND", result.oop_individual)
        body += _accumulator_segments("G", "FAM", result.oop_family)
        for c in result.copays:
            body.append(seg("EB", "B", "IND", clean(c.service_type), "", "", "27", amount(c.amount_cents),
                            "", "", "", "", _network(c.in_network)))
            if c.note:
                body.append(seg("MSG", clean(c.note)))
        for c in result.coinsurance:
            body.append(seg("EB", "A", "IND", clean(c.service_type), "", "", "", "", percent_value(c.percent),
                            "", "", "", _network(c.in_network)))
    return build_interchange(env, transaction_set="271", version=VERSION, bodies=[body])


def copay_label(service_type: str, note: str | None) -> str:
    n = (note or "").upper()
    for key, label in (("SPECIAL", "Specialist visits"), ("PRIMARY", "Primary care visits"),
                       ("TELE", "Telehealth visits"), ("GENERIC", "Generic prescriptions"),
                       ("BRAND", "Brand-name prescriptions"), ("EMERGENCY", "Emergency room")):
        if key in n:
            return label
    return {"98": "Office visits", "UC": "Urgent care", "88": "Prescriptions", "86": "Emergency room",
            "30": "Covered services"}.get(service_type, codes.service_type_label(service_type))


def coinsurance_label(service_type: str) -> str:
    return "Covered services" if service_type == "30" else codes.service_type_label(service_type)


def _phone(s: Segment) -> str | None:
    for i in (3, 5, 7):
        if el(s, i) == "TE" and el(s, i + 1):
            digits = el(s, i + 1)
            if len(digits) == 10 and digits.isdigit():
                return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
            if len(digits) == 11 and digits.startswith("1") and digits.isdigit():
                return f"1-{digits[1:4]}-{digits[4:7]}-{digits[7:]}"
            return digits
    return None


def parse_271(text: str) -> EligibilityResult:
    ic, txn = single_transaction(text, "271")
    d = ic.delimiters
    payer: Payer | None = None
    member_id = group = plan_name = trace = None
    subscriber = Person()
    plan_begin = plan_end = None
    statuses: list[str] = []
    rejections: list[Rejection] = []
    messages: list[str] = []
    copays: list[Copay] = []
    coins: list[Coinsurance] = []
    accs = {k: {"total": None, "remaining": None, "ytd": None} for k in ("C:IND", "C:FAM", "G:IND", "G:FAM")}
    last_eb_copays: list[Copay] = []
    seen_eb = False

    for s in txn.body:
        sid = s[0]
        if sid == "NM1":
            entity = el(s, 1)
            if entity == "PR":
                payer = Payer(name=el(s, 3), payer_id=el(s, 9))
            elif entity == "IL":
                member_id = el(s, 9) or None
                subscriber = Person(last_name=el(s, 3), first_name=el(s, 4))
        elif sid == "PER" and payer is not None and el(s, 1) == "IC":
            payer.phone = _phone(s)
        elif sid == "TRN":
            trace = el(s, 2)
        elif sid == "AAA":
            code = el(s, 3)
            rejections.append(Rejection(code=code, reason=codes.AAA_REASONS.get(code, f"Reject reason {code}"),
                                        follow_up=el(s, 4) or None))
        elif sid == "REF" and el(s, 1) == "6P":
            group = el(s, 2)
        elif sid == "DMG" and el(s, 1) == "D8":
            subscriber.birth_date, _ = parse_date_value("D8", el(s, 2), what="DMG02 birth date")
            subscriber.gender = el(s, 3) if el(s, 3) in ("F", "M", "U") else "U"
        elif sid == "DTP":
            qual = el(s, 1)
            start, end = parse_date_value(el(s, 2), el(s, 3), what=f"DTP*{qual} date")
            if qual in ("346", "356"):
                plan_begin = start
            elif qual in ("347", "357"):
                plan_end = start
            elif qual == "291":
                plan_begin, plan_end = start, end or plan_end
        elif sid == "EB":
            seen_eb = True
            last_eb_copays = []
            code, level = el(s, 1), el(s, 2) or "IND"
            stcs = repeats(el(s, 3), d) or ["30"]
            network = {"Y": True, "N": False}.get(el(s, 12))
            if code in ("1", "6", "7", "8"):
                statuses.append(code)
                if code == "1" and el(s, 5):
                    plan_name = el(s, 5)
            elif code in ("C", "G"):
                if network is False:
                    continue            # out-of-network accumulators are not shown
                lvl = "FAM" if level == "FAM" else "IND"
                slot = accs[f"{code}:{lvl}"]
                period = el(s, 6)
                value = cents(el(s, 7), what="EB07 amount")
                if period == codes.TIME_REMAINING:
                    slot["remaining"] = value
                elif period == codes.TIME_YEAR_TO_DATE:
                    slot["ytd"] = value
                else:
                    slot["total"] = value
            elif code == "B":
                for stc in stcs:
                    c = Copay(service_type=stc, label="", amount_cents=cents(el(s, 7), what="EB07 copay"),
                              in_network=network)
                    copays.append(c)
                    last_eb_copays.append(c)
            elif code == "A":
                if el(s, 8):
                    for stc in stcs:
                        coins.append(Coinsurance(service_type=stc, label=coinsurance_label(stc),
                                                 percent=percent_from(el(s, 8)), in_network=network))
        elif sid == "MSG":
            if last_eb_copays:
                for c in last_eb_copays:
                    c.note = f"{c.note} {el(s, 1)}".strip() if c.note else el(s, 1)
            elif seen_eb:
                messages.append(el(s, 1))

    for c in copays:
        c.label = copay_label(c.service_type, c.note)

    def acc(key: str) -> Accumulator:
        slot = accs[key]
        remaining = slot["remaining"]
        if remaining is None and slot["ytd"] is not None and slot["total"] is not None:
            remaining = max(0, slot["total"] - slot["ytd"])
        return Accumulator(total_cents=slot["total"], remaining_cents=remaining)

    if rejections:
        status = "not_found" if any(r.code in NOT_FOUND_REASONS for r in rejections) else "error"
    elif "1" in statuses:
        status = "active"
    elif statuses:
        status = "inactive"
    else:
        status = "error"
        messages.append("The payer's response did not include a coverage status.")
    return EligibilityResult(
        status=status, payer=payer, member_id=member_id, subscriber=subscriber, group_number=group,
        plan_name=plan_name, plan_begin=plan_begin, plan_end=plan_end,
        deductible_individual=acc("C:IND"), deductible_family=acc("C:FAM"),
        oop_individual=acc("G:IND"), oop_family=acc("G:FAM"),
        copays=copays, coinsurance=coins, rejections=rejections, messages=messages, trace_number=trace,
    )
