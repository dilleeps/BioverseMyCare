"""X12 5010 builders and parsers: envelopes, 270/271, 837P, 277CA, 835. Pure functions, no database."""

from datetime import date, datetime

import pytest

from bioverse.x12 import (
    Envelope, X12Error, build_270, build_271, build_277ca, build_835, build_837p, parse_270, parse_271,
    parse_277ca, parse_835, parse_837p, parse_interchange, validate_837p,
)
from bioverse.x12 import codes
from bioverse.x12.core import amount, cents, split_segments
from bioverse.x12.models import (
    Accumulator, Acknowledgment277, Address, Adjustment, ClaimAcknowledgment, Coinsurance, Copay,
    EligibilityInquiry, EligibilityResult, Payer, Person, ProfessionalClaim, Provider, ProviderAdjustment,
    RemitClaim, RemitServiceLine, Remittance, ServiceLine, Subscriber,
)


def npi(first9: str) -> str:
    return first9 + codes.npi_check_digit(first9)


BILLING_NPI = npi("192837465")
RENDERING_NPI = npi("165432198")
PAYER = Payer(name="Evergreen Mutual Health", payer_id="EVGM1", phone="1-800-555-0142")
ADDRESS = Address(line1="14 Alder Lane", city="Springfield", state="IL", zip="62704")


def env(n: int = 1) -> Envelope:
    return Envelope(sender_id="NSH0001", receiver_id="BVSIMCH", control_number=n,
                    timestamp=datetime(2026, 9, 24, 10, 30))


def inquiry(**kw) -> EligibilityInquiry:
    base = dict(
        payer=PAYER,
        provider=Provider(name="Northside Health", npi=BILLING_NPI),
        subscriber=Subscriber(first_name="Maya", last_name="Thornton", birth_date=date(1972, 3, 9), gender="F",
                              member_id="NHP-4821-7730", group_number="NS-1001"),
        date_of_service=date(2026, 9, 24), trace_number="TRC000123", reference="EL000123",
    )
    base.update(kw)
    return EligibilityInquiry(**base)


def claim(**kw) -> ProfessionalClaim:
    base = dict(
        patient_control_number="BV00000042",
        submitter=Provider(name="Northside Health", tax_id="NSH0001"),
        submitter_phone="555-010-4410",
        receiver=Provider(name="Bioverse Simulated Clearinghouse", tax_id="BVSIMCH"),
        billing_provider=Provider(name="Northside Health", npi=BILLING_NPI, tax_id="99-1234567",
                                  taxonomy="261QM1300X", address=Address(line1="200 Northside Avenue",
                                                                         city="Springfield", state="IL", zip="62701")),
        payer=PAYER,
        subscriber=Subscriber(first_name="Maya", last_name="Thornton", birth_date=date(1972, 3, 9), gender="F",
                              member_id="NHP-4821-7730", group_number="NS-1001", address=ADDRESS),
        diagnosis_codes=["R07.9", "E78.5"],
        rendering_provider=Provider(name="Okafor", first_name="Adaeze", npi=RENDERING_NPI, taxonomy="207RC0000X"),
        service_lines=[
            ServiceLine(procedure_code="99214", charge_cents=38000, service_date=date(2026, 9, 22), diagnosis_pointers=[1, 2]),
            ServiceLine(procedure_code="80061", charge_cents=9500, service_date=date(2026, 9, 22), diagnosis_pointers=[2]),
        ],
        reference="B000042",
    )
    base.update(kw)
    return ProfessionalClaim(**base)


# --- Envelope -------------------------------------------------------------------------------------


def test_envelope_structure_counts_and_control_numbers():
    text = build_270(inquiry(), env(123456789))
    segments, d = split_segments(text)
    assert (d.element, d.sub, d.repetition, d.segment) == ("*", ":", "^", "~")
    isa = text.split("\n")[0]
    assert len(isa) == 106 and isa.endswith(":~")
    assert segments[0][13] == "123456789" and segments[-1] == ["IEA", "1", "123456789"]
    gs = segments[1]
    assert gs[1] == "HS" and gs[8] == "005010X279A1" and segments[-2] == ["GE", "1", gs[6]]
    st = segments[2]
    se = segments[-3]
    assert st[:3] == ["ST", "270", "0001"] and se[0] == "SE" and se[2] == "0001"
    assert int(se[1]) == len(segments) - 4       # ST through SE inclusive, excluding ISA, GS, GE, IEA

    ic = parse_interchange(text)
    assert ic.control == "123456789" and ic.usage == "T" and ic.transactions("270")[0].control == "0001"


def test_envelope_rejects_wrong_counts_and_mismatched_control_numbers():
    text = build_270(inquiry(), env(7))
    bad_se = text.replace("SE*", "SE*9", 1)
    with pytest.raises(X12Error) as e:
        parse_interchange(bad_se)
    assert any("SE01" in m for m in e.value.errors)

    bad_iea = text.replace("IEA*1*000000007", "IEA*1*000000008")
    with pytest.raises(X12Error) as e:
        parse_interchange(bad_iea)
    assert any("IEA02" in m and "ISA13" in m for m in e.value.errors)

    bad_ge = text.replace("GE*1*7", "GE*2*7")
    with pytest.raises(X12Error) as e:
        parse_interchange(bad_ge)
    assert any("GE01" in m for m in e.value.errors)

    with pytest.raises(X12Error, match="must start with an ISA"):
        parse_interchange("GS*HS*A*B~")


def test_parser_reads_other_delimiters():
    text = build_270(inquiry(), env(3))
    swapped = text.replace("*", "|").replace("~", "'")
    ic = parse_interchange(swapped)
    assert ic.delimiters.element == "|" and ic.delimiters.segment == "'"
    assert parse_270(swapped).subscriber.member_id == "NHP-4821-7730"


def test_values_and_identifiers():
    assert amount(38000) == "380" and amount(21050) == "210.5" and amount(-125) == "-1.25" and amount(7) == "0.07"
    assert cents("380") == 38000 and cents("210.5") == 21050 and cents("-1.25") == -125
    assert codes.npi_valid("1234567893") and not codes.npi_valid("1234567890")
    assert codes.icd10_x12("E78.5") == "E785" and codes.icd10_display("E785") == "E78.5"
    assert codes.icd10_valid("R07.9") and not codes.icd10_valid("hello")


# --- 270 / 271 ------------------------------------------------------------------------------------


def test_270_round_trip_and_validation():
    text = build_270(inquiry(service_types=["30", "98", "UC", "88"]), env(11))
    assert "EQ*98~" in text and "DMG*D8*19720309*F~" in text and "NM1*IL*1*THORNTON*MAYA****MI*NHP-4821-7730~" in text
    back = parse_270(text)
    assert back.subscriber.member_id == "NHP-4821-7730" and back.subscriber.birth_date == date(1972, 3, 9)
    assert back.service_types == ["30", "98", "UC", "88"] and back.trace_number == "TRC000123"
    assert back.payer.payer_id == "EVGM1" and back.date_of_service == date(2026, 9, 24)

    with pytest.raises(X12Error) as e:
        build_270(inquiry(subscriber=Subscriber(first_name="Maya", last_name="Thornton")), env())
    assert "Subscriber member ID missing" in e.value.errors
    assert "Subscriber date of birth missing" in e.value.errors


def test_270_dependent_loop():
    text = build_270(inquiry(relationship="child", patient=Person(first_name="Eli", last_name="Thornton",
                                                                  birth_date=date(2012, 5, 1), gender="M")), env())
    assert "HL*4*3*23*0~" in text and "NM1*03*1*THORNTON*ELI~" in text
    back = parse_270(text)
    assert back.patient.first_name == "ELI" and back.patient.birth_date == date(2012, 5, 1)


FULL_RESULT = EligibilityResult(
    status="active", payer=PAYER, member_id="NHP-4821-7730",
    subscriber=Person(first_name="MAYA", last_name="THORNTON", birth_date=date(1972, 3, 9), gender="F"),
    group_number="NS-1001", plan_name="Northside Health Plus PPO",
    plan_begin=date(2026, 1, 1), plan_end=date(2026, 12, 31),
    deductible_individual=Accumulator(total_cents=150000, remaining_cents=68000),
    deductible_family=Accumulator(total_cents=300000, remaining_cents=240000),
    oop_individual=Accumulator(total_cents=400000, remaining_cents=338500),
    oop_family=Accumulator(total_cents=800000, remaining_cents=720500),
    copays=[
        Copay(service_type="98", label="", amount_cents=2500, note="PRIMARY CARE PHYSICIAN"),
        Copay(service_type="98", label="", amount_cents=4000, note="SPECIALIST"),
        Copay(service_type="UC", label="", amount_cents=7500),
        Copay(service_type="88", label="", amount_cents=1000, note="GENERIC DRUGS"),
    ],
    coinsurance=[Coinsurance(service_type="30", label="", percent=20, in_network=True),
                 Coinsurance(service_type="30", label="", percent=40, in_network=False)],
)


def test_271_benefit_extraction():
    text = build_271(FULL_RESULT, inquiry(), env(12))
    assert "EB*C*IND*30***23*1500*****Y~" in text and "EB*C*IND*30***29*680*****Y~" in text
    assert "EB*B*IND*98***27*40*****Y~\nMSG*SPECIALIST~" in text
    assert "EB*A*IND*30*****.2****Y~" in text
    r = parse_271(text)
    assert r.status == "active" and r.plan_name == "Northside Health Plus PPO"
    assert (r.plan_begin, r.plan_end) == (date(2026, 1, 1), date(2026, 12, 31))
    assert r.deductible_individual.total_cents == 150000 and r.deductible_individual.met_cents == 82000
    assert r.deductible_family.met_cents == 60000
    assert r.oop_individual.remaining_cents == 338500 and r.oop_family.total_cents == 800000
    labels = {c.label: c.amount_cents for c in r.copays}
    assert labels == {"Primary care visits": 2500, "Specialist visits": 4000, "Urgent care": 7500,
                      "Generic prescriptions": 1000}
    assert [(c.percent, c.in_network) for c in r.coinsurance] == [(20, True), (40, False)]
    assert r.payer.phone == "800-555-0142" or r.payer.phone.endswith("555-0142")
    assert r.trace_number == "TRC000123" and r.group_number == "NS-1001"


def test_271_year_to_date_repeated_service_types_and_out_of_network_accumulators():
    text = build_271(EligibilityResult(status="active", plan_name="P"), inquiry(), env())
    # Hand-edit in payer variations: a year-to-date deductible, a repeated service type, an OON total.
    text = text.replace("EB*1**30**P~", "EB*1**30**P~\nEB*C*IND*30***23*1000*****Y~\nEB*C*IND*30***24*250*****Y~\n"
                        "EB*C*IND*30***23*5000*****N~\nEB*B*IND*98^UC***27*30*****Y~")
    lines = text.strip().split("\n")
    se_index = next(i for i, s in enumerate(lines) if s.startswith("SE*"))
    st_index = next(i for i, s in enumerate(lines) if s.startswith("ST*"))
    lines[se_index] = f"SE*{se_index - st_index + 1}*0001~"
    r = parse_271("\n".join(lines))
    assert r.deductible_individual.total_cents == 100000 and r.deductible_individual.remaining_cents == 75000
    assert sorted(c.service_type for c in r.copays) == ["98", "UC"]


def test_271_inactive_and_not_found():
    inactive = parse_271(build_271(EligibilityResult(status="inactive", plan_end=date(2026, 8, 25)), inquiry(), env()))
    assert inactive.status == "inactive" and inactive.plan_end == date(2026, 8, 25)
    from bioverse.x12.models import Rejection
    nf = EligibilityResult(status="not_found", rejections=[Rejection(code="75", reason="")])
    text = build_271(nf, inquiry(), env())
    assert "AAA*N**75*C~" in text
    r = parse_271(text)
    assert r.status == "not_found" and r.rejections[0].reason == "Subscriber or insured not found"


# --- 837P ----------------------------------------------------------------------------------------


def test_837p_structure_and_round_trip():
    c = claim(prior_authorization="EVG-PA-0042")
    text = build_837p(c, env(42))
    for fragment in (
        f"NM1*85*2*NORTHSIDE HEALTH*****XX*{BILLING_NPI}~", "REF*EI*991234567~", "SBR*P*18*NS-1001******CI~",
        "NM1*IL*1*THORNTON*MAYA****MI*NHP-4821-7730~", "CLM*BV00000042*475***11:B:1*Y*A*Y*Y~",
        "REF*G1*EVG-PA-0042~", "HI*ABK:R079*ABF:E785~", f"NM1*82*1*OKAFOR*ADAEZE****XX*{RENDERING_NPI}~",
        "SV1*HC:99214*380*UN*1***1:2~", "DTP*472*D8*20260922~", "NM1*PR*2*EVERGREEN MUTUAL HEALTH*****PI*EVGM1~",
    ):
        assert fragment in text, fragment
    ic = parse_interchange(text)
    assert ic.groups[0].functional_id == "HC" and ic.groups[0].version == "005010X222A1"

    [back] = parse_837p(text)
    assert back.patient_control_number == "BV00000042" and back.total_charge_cents == 47500
    assert back.diagnosis_codes == ["R07.9", "E78.5"] and back.prior_authorization == "EVG-PA-0042"
    assert back.subscriber.member_id == "NHP-4821-7730" and back.subscriber.address.city == "SPRINGFIELD"
    assert back.rendering_provider.npi == RENDERING_NPI and back.rendering_provider.taxonomy == "207RC0000X"
    assert [(s.procedure_code, s.charge_cents, s.diagnosis_pointers) for s in back.service_lines] == [
        ("99214", 38000, [1, 2]), ("80061", 9500, [2])]
    assert back.service_lines[0].service_date == date(2026, 9, 22)
    assert back.billing_provider.tax_id == "991234567"


def test_837p_required_field_validation():
    bad = claim(
        subscriber=Subscriber(first_name="Maya", last_name="Thornton", birth_date=date(1972, 3, 9)),
        diagnosis_codes=["not-a-code"],
        billing_provider=Provider(name="Northside Health", npi="1234567890", tax_id="99-1234567",
                                  address=ADDRESS),
        service_lines=[ServiceLine(procedure_code="", charge_cents=0, service_date=date(2026, 9, 22),
                                   diagnosis_pointers=[3])],
    )
    errors = validate_837p(bad)
    assert "Subscriber member ID missing" in errors
    assert "Subscriber address missing (required when the patient is the subscriber)" in errors
    assert any(e.startswith("Billing provider NPI 1234567890 is not a valid NPI") for e in errors)
    assert "Diagnosis code 'not-a-code' is not in ICD-10-CM format (for example E78.5)" in errors
    assert "Service line 1: procedure code missing" in errors
    assert "Service line 1: charge must be more than $0" in errors
    assert "Service line 1: diagnosis pointer 3 has no matching diagnosis code" in errors
    with pytest.raises(X12Error) as e:
        build_837p(bad, env())
    assert e.value.errors == errors
    assert "At least one diagnosis code is required" in validate_837p(claim(diagnosis_codes=[]))


def test_837p_dependent_patient():
    c = claim(relationship="child", patient=Person(first_name="Eli", last_name="Thornton",
                                                   birth_date=date(2012, 5, 1), gender="M"), patient_address=ADDRESS)
    text = build_837p(c, env())
    assert "SBR*P**NS-1001******CI~" in text and "PAT*19~" in text and "NM1*QC*1*THORNTON*ELI~" in text
    [back] = parse_837p(text)
    assert back.relationship == "child" and back.patient.birth_date == date(2012, 5, 1)


# --- 277CA ---------------------------------------------------------------------------------------


def test_277ca_round_trip():
    ack = Acknowledgment277(
        payer=PAYER, receiver_name="Northside Health", receiver_id="NSH0001",
        billing_provider=Provider(name="Northside Health", npi=BILLING_NPI), batch_reference="B000042",
        received_on=date(2026, 9, 24),
        claims=[
            ClaimAcknowledgment(patient_control_number="BV00000042", category_code="A2", status_code="20",
                                accepted=True, message="", payer_claim_number="EVG2609240001", charge_cents=47500,
                                service_date=date(2026, 9, 22), patient=Person(first_name="Maya", last_name="Thornton"),
                                member_id="NHP-4821-7730"),
            ClaimAcknowledgment(patient_control_number="BV00000043", category_code="A7", status_code="562",
                                entity_code="85", accepted=False, message="", charge_cents=9500),
        ],
    )
    text = build_277ca(ack, env(77))
    assert "STC*A2:20*20260924*WQ*475~" in text and "STC*A7:562:85*20260924*U*95~" in text
    back = parse_277ca(text)
    assert back.batch_reference == "B000042" and back.payer.payer_id == "EVGM1"
    ok, rejected = back.claims
    assert ok.accepted and ok.payer_claim_number == "EVG2609240001" and ok.message == "Accepted into adjudication: Accepted for processing"
    assert not rejected.accepted
    assert rejected.message == ("Rejected for invalid information: Entity's National Provider Identifier (NPI) "
                                "(billing provider)")


# --- 835 ------------------------------------------------------------------------------------------


def remittance() -> Remittance:
    return Remittance(
        payer=PAYER, payee=Provider(name="Northside Health", npi=BILLING_NPI), payment_cents=21000 - 1500 + 125,
        payment_method="ACH", payment_date=date(2026, 9, 30), trace_number="EFT0000931",
        claims=[
            RemitClaim(
                patient_control_number="BV00000042", status_code="1", charge_cents=47500, paid_cents=21000,
                patient_resp_cents=9500, payer_claim_number="EVG2609240001",
                patient=Person(first_name="Maya", last_name="Thornton"), member_id="NHP-4821-7730",
                service_date=date(2026, 9, 22),
                service_lines=[
                    RemitServiceLine(procedure_code="99214", charge_cents=38000, paid_cents=21000, allowed_cents=26000,
                                     service_date=date(2026, 9, 22),
                                     adjustments=[Adjustment(group="CO", reason_code="45", amount_cents=12000),
                                                  Adjustment(group="PR", reason_code="3", amount_cents=5000)]),
                    RemitServiceLine(procedure_code="80061", charge_cents=9500, paid_cents=0, allowed_cents=4500,
                                     service_date=date(2026, 9, 22),
                                     adjustments=[Adjustment(group="CO", reason_code="45", amount_cents=5000),
                                                  Adjustment(group="PR", reason_code="1", amount_cents=4500)]),
                ],
            ),
            RemitClaim(patient_control_number="BV00000044", status_code="4", charge_cents=180000, paid_cents=0,
                       payer_claim_number="EVG2609240002",
                       adjustments=[Adjustment(group="CO", reason_code="197", amount_cents=180000)]),
        ],
        provider_adjustments=[
            ProviderAdjustment(provider_id=BILLING_NPI, fiscal_date=date(2026, 12, 31), reason_code="WO",
                               reference="EVG2601010009", amount_cents=1500),
            ProviderAdjustment(provider_id=BILLING_NPI, fiscal_date=date(2026, 12, 31), reason_code="L6",
                               amount_cents=-125),
        ],
    )


def test_835_round_trip_with_cas_and_plb():
    text = build_835(remittance(), env(835))
    assert "BPR*I*196.25*C*ACH************20260930~" in text
    assert "CLP*BV00000042*1*475*210*95*CI*EVG2609240001*11*1~" in text
    assert "CAS*CO*45*120~\nCAS*PR*3*50~" in text and "CAS*CO*197*1800~" in text
    assert f"PLB*{BILLING_NPI}*20261231*WO:EVG2601010009*15*L6*-1.25~" in text
    r = parse_835(text)
    assert r.payment_cents == 19625 and r.trace_number == "EFT0000931" and r.payer.payer_id == "EVGM1"
    paid, denied = r.claims
    assert paid.patient_resp_by_reason("3") == 5000 and paid.patient_resp_by_reason("1") == 4500
    assert paid.service_lines[0].allowed_cents == 26000 and paid.member_id == "NHP-4821-7730"
    assert [(a.group, a.reason_code, a.amount_cents) for a in paid.service_lines[1].adjustments] == [
        ("CO", "45", 5000), ("PR", "1", 4500)]
    assert denied.status_code == "4" and denied.adjustments[0].reason_code == "197"
    assert [(p.reason_code, p.reference, p.amount_cents) for p in r.provider_adjustments] == [
        ("WO", "EVG2601010009", 1500), ("L6", None, -125)]


def test_835_balancing_errors_are_readable():
    text = build_835(remittance(), env()).replace("CAS*PR*3*50~", "CAS*PR*3*40~")
    with pytest.raises(X12Error) as e:
        parse_835(text)
    msgs = " | ".join(e.value.errors)
    assert "Claim BV00000042: charge 475 minus paid 210 does not equal its adjustments 255" in msgs
    assert "line 1 (99214)" in msgs

    bad_total = build_835(remittance(), env()).replace("BPR*I*196.25", "BPR*I*200")
    with pytest.raises(X12Error, match="Payment 200 does not equal"):
        parse_835(bad_total)


def test_carc_plain_language():
    assert "prior authorization" in codes.carc_text("197")
    assert codes.carc_text("45").startswith("The charge is more than")
    assert codes.carc_text("9999") == "Adjustment reason code 9999."
    assert codes.adjustment_label("PR", "3").startswith("PR-3 (Patient responsibility)")
