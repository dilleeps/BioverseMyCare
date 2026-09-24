"""835 health care claim payment/advice (005010X221A1).

    build_835(remit, env) -> X12 text     (the simulated payer)
    parse_835(text)       -> Remittance, checked against the 835 balancing rules:
        - per claim:  CLP03 charge - CLP04 paid = every CAS adjustment on the claim and its lines
        - per line:   SVC02 charge - SVC03 paid = the line's CAS adjustments
        - per claim:  CLP05 patient responsibility = the PR adjustments
        - payment:    BPR02 = sum of CLP04 - sum of PLB adjustments
"""

from __future__ import annotations

from bioverse.x12.core import (
    Envelope, Segment, X12Error, amount, build_interchange, cents, clean, composite, d8, el, name_value,
    parse_date_value, seg, single_transaction,
)
from bioverse.x12.models import (
    Adjustment, Payer, Person, Provider, ProviderAdjustment, RemitClaim, RemitServiceLine, Remittance,
)

VERSION = "005010X221A1"


def _cas_segments(adjustments: list[Adjustment]) -> list[Segment]:
    """One CAS per group code, up to six reason/amount/quantity triples each."""
    out: list[Segment] = []
    groups: dict[str, list[Adjustment]] = {}
    for a in adjustments:
        groups.setdefault(a.group, []).append(a)
    for group, items in groups.items():
        for start in range(0, len(items), 6):
            elements: list[str] = [group]
            for a in items[start:start + 6]:
                elements += [clean(a.reason_code), amount(a.amount_cents), a.quantity or ""]
            out.append(seg("CAS", *elements))
    return out


def build_835(r: Remittance, env: Envelope) -> str:
    handling = "I" if r.payment_cents > 0 else "H"
    method = r.payment_method if r.payment_cents > 0 else "NON"
    body: list[Segment] = [
        seg("BPR", handling, amount(r.payment_cents), r.credit_debit, method, "", "", "", "", "", "", "", "", "",
            "", "", d8(r.payment_date)),
        seg("TRN", "1", clean(r.trace_number), "1" + "".join(ch for ch in r.payer.payer_id if ch.isalnum())[:9].ljust(9, "0")),
        seg("DTM", "405", d8(r.payment_date)),
        seg("N1", "PR", name_value(r.payer.name)),
        seg("REF", "2U", clean(r.payer.payer_id)),
        seg("N1", "PE", name_value(r.payee.name), "XX", r.payee.npi),
    ]
    if r.claims:
        body.append(seg("LX", "1"))
    for c in r.claims:
        body.append(seg("CLP", clean(c.patient_control_number), c.status_code, amount(c.charge_cents),
                        amount(c.paid_cents), amount(c.patient_resp_cents), clean(c.filing_indicator),
                        clean(c.payer_claim_number), "11", "1"))
        body += _cas_segments(c.adjustments)
        pat = c.patient or Person()
        body.append(seg("NM1", "QC", "1", name_value(pat.last_name), name_value(pat.first_name), "", "", "", "MI",
                        clean(c.member_id or "")))
        if c.service_date:
            body.append(seg("DTM", "232", d8(c.service_date)))
        for line in c.service_lines:
            proc = ":".join(["HC", clean(line.procedure_code), *[clean(m) for m in line.modifiers]])
            body.append(seg("SVC", proc, amount(line.charge_cents), amount(line.paid_cents), "", str(line.units)))
            if line.service_date:
                body.append(seg("DTM", "472", d8(line.service_date)))
            body += _cas_segments(line.adjustments)
            if line.allowed_cents is not None:
                body.append(seg("AMT", "B6", amount(line.allowed_cents)))
    by_provider: dict[tuple[str, str], list[ProviderAdjustment]] = {}
    for p in r.provider_adjustments:
        by_provider.setdefault((p.provider_id, d8(p.fiscal_date)), []).append(p)
    for (provider_id, fiscal), items in by_provider.items():
        for start in range(0, len(items), 6):
            elements: list[str] = [clean(provider_id), fiscal]
            for p in items[start:start + 6]:
                code = p.reason_code + (f":{clean(p.reference)}" if p.reference else "")
                elements += [code, amount(p.amount_cents)]
            body.append(seg("PLB", *elements))
    return build_interchange(env, transaction_set="835", version=VERSION, bodies=[body])


def _parse_cas(s: Segment) -> list[Adjustment]:
    group = el(s, 1)
    out = []
    for i in range(2, 20, 3):
        code = el(s, i)
        if not code:
            continue
        out.append(Adjustment(group=group, reason_code=code, amount_cents=cents(el(s, i + 1), what=f"CAS {group}-{code} amount"),
                              quantity=el(s, i + 2) or None))
    return out


def balance_errors(r: Remittance) -> list[str]:
    errors: list[str] = []
    for c in r.claims:
        adj = sum(a.amount_cents for a in c.all_adjustments())
        if c.charge_cents - c.paid_cents != adj:
            errors.append(
                f"Claim {c.patient_control_number}: charge {amount(c.charge_cents)} minus paid {amount(c.paid_cents)} "
                f"does not equal its adjustments {amount(adj)}"
            )
        pr = sum(a.amount_cents for a in c.all_adjustments() if a.group == "PR")
        if pr != c.patient_resp_cents:
            errors.append(
                f"Claim {c.patient_control_number}: patient responsibility {amount(c.patient_resp_cents)} does not "
                f"equal its PR adjustments {amount(pr)}"
            )
        for i, line in enumerate(c.service_lines, start=1):
            ladj = sum(a.amount_cents for a in line.adjustments)
            if line.charge_cents - line.paid_cents != ladj:
                errors.append(
                    f"Claim {c.patient_control_number}, line {i} ({line.procedure_code}): charge "
                    f"{amount(line.charge_cents)} minus paid {amount(line.paid_cents)} does not equal its "
                    f"adjustments {amount(ladj)}"
                )
    expected = sum(c.paid_cents for c in r.claims) - sum(p.amount_cents for p in r.provider_adjustments)
    if expected != r.payment_cents:
        errors.append(f"Payment {amount(r.payment_cents)} does not equal claim payments minus provider "
                      f"adjustments ({amount(expected)})")
    return errors


def parse_835(text: str, *, check_balance: bool = True) -> Remittance:
    ic, txn = single_transaction(text, "835")
    d = ic.delimiters
    payment = 0
    credit_debit, method, pay_date, trace = "C", "ACH", None, ""
    payer = Payer(name="", payer_id="")
    payee = Provider()
    claims: list[RemitClaim] = []
    plbs: list[ProviderAdjustment] = []
    claim: RemitClaim | None = None
    line: RemitServiceLine | None = None
    n1 = ""
    for s in txn.body:
        sid = s[0]
        if sid == "BPR":
            payment = cents(el(s, 2), what="BPR02 payment amount")
            credit_debit, method = el(s, 3) or "C", el(s, 4) or "ACH"
            if el(s, 16):
                pay_date, _ = parse_date_value("D8", el(s, 16), what="BPR16 payment date")
        elif sid == "TRN" and el(s, 1) == "1":
            trace = el(s, 2)
        elif sid == "DTM" and el(s, 1) == "405" and pay_date is None:
            pay_date, _ = parse_date_value("D8", el(s, 2), what="DTM*405 production date")
        elif sid == "N1":
            n1 = el(s, 1)
            if n1 == "PR":
                payer = Payer(name=el(s, 2), payer_id=el(s, 4) if el(s, 3) == "XV" else payer.payer_id)
            elif n1 == "PE":
                payee = Provider(name=el(s, 2), npi=el(s, 4) if el(s, 3) == "XX" else "")
        elif sid == "REF" and el(s, 1) == "2U" and n1 == "PR" and claim is None:
            payer.payer_id = el(s, 2)
        elif sid == "CLP":
            line = None
            claim = RemitClaim(
                patient_control_number=el(s, 1), status_code=el(s, 2),
                charge_cents=cents(el(s, 3), what="CLP03 charge"), paid_cents=cents(el(s, 4), what="CLP04 paid"),
                patient_resp_cents=cents(el(s, 5), what="CLP05 patient responsibility"),
                filing_indicator=el(s, 6) or "CI", payer_claim_number=el(s, 7),
            )
            claims.append(claim)
        elif sid == "CAS" and claim is not None:
            (line.adjustments if line is not None else claim.adjustments).extend(_parse_cas(s))
        elif sid == "NM1" and el(s, 1) == "QC" and claim is not None:
            claim.patient = Person(last_name=el(s, 3), first_name=el(s, 4))
            claim.member_id = el(s, 9) or None
        elif sid == "DTM" and claim is not None and el(s, 1) in ("232", "050", "472"):
            value, _ = parse_date_value("D8", el(s, 2), what=f"DTM*{el(s, 1)} date")
            if el(s, 1) == "472" and line is not None:
                line.service_date = value
            elif el(s, 1) == "232":
                claim.service_date = value
        elif sid == "SVC" and claim is not None:
            proc = composite(el(s, 1), d)
            line = RemitServiceLine(
                procedure_code=proc[1] if len(proc) > 1 else "", modifiers=proc[2:6],
                charge_cents=cents(el(s, 2), what="SVC02 charge"), paid_cents=cents(el(s, 3), what="SVC03 paid"),
                units=int(float(el(s, 5) or "1")),
            )
            claim.service_lines.append(line)
        elif sid == "AMT" and el(s, 1) == "B6" and line is not None:
            line.allowed_cents = cents(el(s, 2), what="AMT*B6 allowed amount")
        elif sid == "PLB":
            fiscal, _ = parse_date_value("D8", el(s, 2), what="PLB02 fiscal period date")
            for i in range(3, 15, 2):
                if not el(s, i):
                    continue
                parts = composite(el(s, i), d)
                plbs.append(ProviderAdjustment(provider_id=el(s, 1), fiscal_date=fiscal, reason_code=parts[0],
                                               reference=parts[1] if len(parts) > 1 else None,
                                               amount_cents=cents(el(s, i + 1), what="PLB amount")))
    if pay_date is None:
        raise X12Error("The 835 has no payment date (BPR16)")
    if not trace:
        raise X12Error("The 835 has no check or EFT trace number (TRN02)")
    remit = Remittance(payer=payer, payee=payee, payment_cents=payment, credit_debit=credit_debit,
                       payment_method=method, payment_date=pay_date, trace_number=trace, claims=claims,
                       provider_adjustments=plbs)
    if check_balance and (errors := balance_errors(remit)):
        raise X12Error(errors)
    return remit
