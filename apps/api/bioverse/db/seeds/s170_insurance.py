"""Insurance connections demo data. Idempotent: fixed IDs 15000-15999, ON CONFLICT DO NOTHING.

Everything is fictional: three made-up payers, made-up NPIs (valid check digits, not assigned to anyone),
and a SIMULATED clearinghouse whose payer-side member records mirror billing's demo coverages.

- Maya Thornton: Evergreen Mutual Health, deductible partly met, one stored eligibility check, and one
  full claim cycle for her cardiology visit (837P sent, 277CA accepted, 835 paid with a copay as the
  patient-responsibility adjustment). The 835 matches the explanation of benefits billing already holds.
- A pending prior authorization for Maya's echocardiogram.
- Jun Park: his Evergreen plan ended; a new Summit Crest plan exists on the payer side for him to add
  from his card.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from psycopg.rows import dict_row

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import (
    DR_ACHEBE, DR_FERREIRA, DR_LINDQVIST, DR_MORI, DR_OKAFOR, DR_RAMAN, DR_WEISS, ORG, P_HADDAD, P_MAYA, P_PARK,
    PLAN, TEAM_DERM_TELE, _id,
)
from bioverse.x12 import build_270, build_277ca, build_835, build_837p
from bioverse.x12.codes import npi_check_digit
from bioverse.x12.core import Envelope
from bioverse.x12.models import (
    Acknowledgment277, Address, Adjustment, ClaimAcknowledgment, EligibilityInquiry, Payer, Person,
    ProfessionalClaim, Provider, RemitClaim, RemitServiceLine, Remittance, ServiceLine, Subscriber,
)

# Billing's seeded rows this module builds on (s050_billing_pharmacy.py).
COV_MAYA, COV_PARK, COV_HADDAD = _id(5001), _id(5002), _id(5003)
CL_CARDIO = _id(5104)

PAYER_EVERGREEN, PAYER_HARBORLINE, PAYER_SUMMIT = _id(15001), _id(15002), _id(15003)
CONN_EVERGREEN, CONN_HARBORLINE, CONN_SUMMIT = _id(15011), _id(15012), _id(15013)
SIM_MAYA, SIM_PARK_OLD, SIM_HADDAD, SIM_PARK_NEW = _id(15021), _id(15022), _id(15023), _id(15024)
CHECK_MAYA = _id(15101)
SUB_CARDIO, SIM_CLAIM_CARDIO = _id(15201), _id(15202)
REMIT_CARDIO, REMIT_CLAIM_CARDIO = _id(15301), _id(15302)
PA_MAYA_ECHO = _id(15401)

PARK_NEW_MEMBER_ID = "SCB-771204-02"


def npi(first9: str) -> str:
    return first9 + npi_check_digit(first9)


ORG_NPI = npi("192837465")
SUBMITTER_ID = "NSH0001"
PROVIDER_NUMBERS = [
    # practitioner, NPI, taxonomy (NUCC)
    (DR_OKAFOR, npi("165432101"), "207RC0000X"),       # cardiovascular disease
    (DR_FERREIRA, npi("165432102"), "207N00000X"),     # dermatology
    (DR_ACHEBE, npi("165432103"), "207N00000X"),
    (TEAM_DERM_TELE, npi("165432104"), "207N00000X"),
    (DR_LINDQVIST, npi("165432105"), "207Q00000X"),    # family medicine
    (DR_RAMAN, npi("165432106"), "207RC0000X"),
    (DR_MORI, npi("165432107"), "207Q00000X"),
    (DR_WEISS, npi("165432108"), "2084N0400X"),        # neurology
]
OKAFOR_NPI = PROVIDER_NUMBERS[0][1]

PAYERS = [
    # id, name, payer id, type, transactions, fhir base, profiles, member phone, provider phone, claims address, auth codes
    (PAYER_EVERGREEN, "Evergreen Mutual Health", "EVGM1", "x12_clearinghouse",
     ["270/271", "837P", "277CA", "835"], None, [], "1-800-555-0142", "1-800-555-0143",
     "PO Box 4100, Springfield, IL 62701", ["93306"]),
    (PAYER_HARBORLINE, "Harborline Health Plan", "HRBL2", "fhir_payer_api",
     ["270/271", "837P", "277CA", "835", "FHIR Coverage", "FHIR ExplanationOfBenefit"],
     "https://fhir.harborline.example/r4", ["CARIN Blue Button", "Da Vinci PDex"], "1-800-555-0177",
     "1-800-555-0178", "PO Box 900, Riverton, IL 62561", []),
    (PAYER_SUMMIT, "Summit Crest Benefits", "SMCB3", "x12_clearinghouse",
     ["270/271", "837P", "277CA", "835"], None, [], "1-800-555-0199", "1-800-555-0198",
     "PO Box 77, Summit, IL 60501", ["93306"]),
]

MAYA_ADDRESS = ("14 Alder Lane", "Springfield", "IL", "62704")
PARK_ADDRESS = ("88 Birchwood Court", "Springfield", "IL", "62702")
HADDAD_ADDRESS = ("5 Quarry Road", "Chatham", "IL", "62629")
COPAYS = {"primary_care": 2500, "specialist": 5000, "telehealth": 1500, "urgent_care": 7500, "generic_rx": 1000}


def _env(n: int, ts: datetime, sender: str = SUBMITTER_ID, receiver: str = "BVSIMCH") -> Envelope:
    return Envelope(sender_id=sender, receiver_id=receiver, control_number=n, timestamp=ts.replace(tzinfo=None))


def run(conn, ctx: SeedContext) -> None:
    at, days = ctx.at, ctx.days
    cur = conn.cursor(row_factory=dict_row)
    plan_start = date(ctx.today.year - 2, 1, 1)

    cur.executemany(
        """
        INSERT INTO payers (id, name, payer_id, connection_type, transactions, fhir_base_url, fhir_profiles,
                            member_phone, provider_phone, claims_address, auth_required_procedures)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        PAYERS,
    )
    cur.executemany(
        """
        INSERT INTO payer_connections (id, organization_id, payer_ref, status, gateway, credentials_secret_name,
                                       last_tested_at, last_test_ok, last_test_message)
        VALUES (%s, %s, %s, %s, 'simulated', %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [
            (CONN_EVERGREEN, ORG, PAYER_EVERGREEN, "connected", "EVERGREEN_CLEARINGHOUSE_TOKEN", at(days(-7), 9),
             True, "Simulated clearinghouse answered a test 270 with a valid 271. Demo: no real payer was contacted."),
            (CONN_HARBORLINE, ORG, PAYER_HARBORLINE, "disconnected", None, None, None, None),
            (CONN_SUMMIT, ORG, PAYER_SUMMIT, "connected", None, at(days(-7), 9), True,
             "Simulated clearinghouse answered a test 270 with a valid 271. Demo: no real payer was contacted."),
        ],
    )
    cur.execute(
        """
        INSERT INTO insurance_billing_providers (organization_id, name, npi, tax_id, taxonomy, address_line, city,
                                                 state, zip, phone, submitter_id)
        VALUES (%s, 'Northside Health', %s, '99-1234567', '261QM1300X', '200 Northside Avenue', 'Springfield',
                'IL', '62701', '555-010-4410', %s) ON CONFLICT DO NOTHING
        """,
        (ORG, ORG_NPI, SUBMITTER_ID),
    )
    cur.executemany(
        "INSERT INTO insurance_provider_numbers (practitioner_id, npi, taxonomy) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        PROVIDER_NUMBERS,
    )
    cur.executemany(
        """
        INSERT INTO coverage_details (coverage_id, patient_id, payer_ref, address_line, city, state, zip,
                                      rx_bin, rx_pcn, rx_group)
        VALUES (%s, %s, %s, %s, %s, %s, %s, '999123', 'BVDEMO', 'EVGRX01') ON CONFLICT DO NOTHING
        """,
        [(COV_MAYA, P_MAYA, PAYER_EVERGREEN, *MAYA_ADDRESS), (COV_PARK, P_PARK, PAYER_EVERGREEN, *PARK_ADDRESS),
         (COV_HADDAD, P_HADDAD, PAYER_EVERGREEN, *HADDAD_ADDRESS)],
    )

    # --- Simulated payer side: members mirror billing's demo coverages --------------------------
    members = [
        # id, payer, member id, first, last, dob, gender, group, plan, begin, end, ded, ded met, fam ded, fam met,
        # oop, oop met, fam oop, fam oop met, coins, oon, copays
        (SIM_MAYA, PAYER_EVERGREEN, "NHP-4821-7730", "Maya", "Thornton", date(1972, 3, 9), "F", "NS-1001", PLAN,
         plan_start, None, 150000, 42000, 300000, 60000, 400000, 61500, 800000, 79500, 20, 40, COPAYS),
        (SIM_PARK_OLD, PAYER_EVERGREEN, "NHP-5530-1189", "Jun", "Park", date(1985, 11, 2), "M", "NS-1001", PLAN,
         plan_start, days(-30), 150000, 0, 300000, 0, 400000, 0, 800000, 0, 20, 40, COPAYS),
        (SIM_HADDAD, PAYER_EVERGREEN, "NHP-3307-2254", "Rana", "Haddad", date(1961, 6, 18), "F", "NS-1001", PLAN,
         plan_start, None, 100000, 100000, None, 0, 300000, 147000, None, 0, 20, 40, COPAYS),
        (SIM_PARK_NEW, PAYER_SUMMIT, PARK_NEW_MEMBER_ID, "Jun", "Park", date(1985, 11, 2), "M", "SC-2207",
         "Summit Crest Silver PPO", days(-29), None, 250000, 0, 500000, 0, 600000, 0, 1200000, 0, 30, 50,
         {"primary_care": 3500, "specialist": 6000, "telehealth": 2000, "urgent_care": 9000, "generic_rx": 1500}),
    ]
    cur.executemany(
        """
        INSERT INTO payer_sim_members (id, payer_ref, member_id, first_name, last_name, birth_date, gender,
            group_number, plan_name, plan_begin, plan_end, deductible_cents, deductible_met_cents,
            family_deductible_cents, family_deductible_met_cents, oop_max_cents, oop_met_cents,
            family_oop_max_cents, family_oop_met_cents, coinsurance_pct, oon_coinsurance_pct, copays)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        [(*m[:-1], json.dumps(m[-1])) for m in members],
    )

    # --- Prior authorization: Maya's echocardiogram, pended by the payer --------------------------
    cur.execute(
        """
        INSERT INTO prior_authorizations (id, patient_id, coverage_id, payer_ref, practitioner_id, procedure_code,
                                          description, diagnosis_codes, status, payer_reference, note, submitted_at,
                                          updated_at)
        VALUES (%s, %s, %s, %s, %s, '93306', 'Echocardiogram (transthoracic, complete)', '{R07.9}', 'pended',
                'EVG-PA-26-00417', %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        (PA_MAYA_ECHO, P_MAYA, COV_MAYA, PAYER_EVERGREEN, DR_OKAFOR,
         "Evergreen asked for the most recent cardiology note. Sent; waiting for their review.",
         at(days(-2), 10, 5), at(days(-1), 15, 20)),
    )

    _seed_eligibility_check(cur, ctx)
    _seed_claim_cycle(cur, ctx)


def _seed_eligibility_check(cur, ctx: SeedContext) -> None:
    if cur.execute("SELECT 1 FROM insurance_eligibility_checks WHERE id = %s", (CHECK_MAYA,)).fetchone():
        return
    from bioverse.payers.services import plain_summary
    from bioverse.payers.simulated import SimulatedClearinghouse
    from bioverse.x12 import parse_271

    when = ctx.at(ctx.days(-3), 8, 12)
    inq = EligibilityInquiry(
        payer=Payer(name="Evergreen Mutual Health", payer_id="EVGM1"),
        provider=Provider(name="Northside Health", npi=ORG_NPI),
        subscriber=Subscriber(first_name="Maya", last_name="Thornton", birth_date=date(1972, 3, 9), gender="F",
                              member_id="NHP-4821-7730", group_number="NS-1001"),
        service_types=["30", "98", "UC", "88"], date_of_service=when.date(), trace_number="BV0000015101",
        reference="EL00015101",
    )
    request = build_270(inq, _env(15101, when))
    response = SimulatedClearinghouse(cur.connection).eligibility(request)
    result = parse_271(response)
    cur.execute(
        """
        INSERT INTO insurance_eligibility_checks (id, patient_id, coverage_id, payer_ref, trigger, status, benefits,
            summary, request_x12, response_x12, simulated, checked_at)
        VALUES (%s, %s, %s, %s, 'seed', %s, %s, %s, %s, %s, true, %s) ON CONFLICT DO NOTHING
        """,
        (CHECK_MAYA, P_MAYA, COV_MAYA, PAYER_EVERGREEN, result.status, json.dumps(result.model_dump(mode="json")),
         plain_summary(result, "Evergreen Mutual Health"), request, response, when),
    )


def _seed_claim_cycle(cur, ctx: SeedContext) -> None:
    """Maya's cardiology visit two days ago: 837P, accepted 277CA, and the 835 behind billing's EOB."""
    if cur.execute("SELECT 1 FROM insurance_claim_submissions WHERE id = %s", (SUB_CARDIO,)).fetchone():
        return
    service_day = ctx.days(-2)
    sent = ctx.at(ctx.days(-1), 9, 0)
    acked = ctx.at(ctx.days(-1), 9, 4)
    paid_on = ctx.days(-1)
    pcn, payer_claim = "BV00000901", f"EVG{service_day:%y%m%d}000901"
    payer = Payer(name="Evergreen Mutual Health", payer_id="EVGM1")
    billing = Provider(name="Northside Health", npi=ORG_NPI, tax_id="99-1234567", taxonomy="261QM1300X",
                       address=Address(line1="200 Northside Avenue", city="Springfield", state="IL", zip="62701"))
    line = ServiceLine(procedure_code="99214", charge_cents=38000, service_date=service_day, diagnosis_pointers=[1, 2])
    claim = ProfessionalClaim(
        patient_control_number=pcn, submitter=Provider(name="Northside Health", tax_id=SUBMITTER_ID),
        submitter_phone="555-010-4410", receiver=Provider(name="Bioverse Simulated Clearinghouse", tax_id="BVSIMCH"),
        billing_provider=billing, payer=payer,
        subscriber=Subscriber(first_name="Maya", last_name="Thornton", birth_date=date(1972, 3, 9), gender="F",
                              member_id="NHP-4821-7730", group_number="NS-1001",
                              address=Address(line1=MAYA_ADDRESS[0], city=MAYA_ADDRESS[1], state=MAYA_ADDRESS[2],
                                              zip=MAYA_ADDRESS[3])),
        diagnosis_codes=["R07.9", "E78.5"],
        rendering_provider=Provider(name="Okafor", first_name="Adaeze", npi=OKAFOR_NPI, taxonomy="207RC0000X"),
        service_lines=[line], reference=pcn,
    )
    x837 = build_837p(claim, _env(15201, sent))
    x277 = build_277ca(Acknowledgment277(
        payer=payer, receiver_name="Northside Health", receiver_id=SUBMITTER_ID,
        billing_provider=Provider(name="Northside Health", npi=ORG_NPI), batch_reference=pcn, received_on=sent.date(),
        claims=[ClaimAcknowledgment(patient_control_number=pcn, category_code="A2", status_code="20", accepted=True,
                                    message="", payer_claim_number=payer_claim, charge_cents=38000,
                                    service_date=service_day, patient=Person(first_name="Maya", last_name="Thornton"),
                                    member_id="NHP-4821-7730")],
    ), _env(15202, acked, sender="BVSIMCH", receiver=SUBMITTER_ID))
    adjustments = [Adjustment(group="CO", reason_code="45", amount_cents=12000),
                   Adjustment(group="PR", reason_code="3", amount_cents=5000)]
    remit_claim = RemitClaim(
        patient_control_number=pcn, status_code="1", charge_cents=38000, paid_cents=21000, patient_resp_cents=5000,
        payer_claim_number=payer_claim, patient=Person(first_name="Maya", last_name="Thornton"),
        member_id="NHP-4821-7730", service_date=service_day,
        service_lines=[RemitServiceLine(procedure_code="99214", charge_cents=38000, paid_cents=21000,
                                        service_date=service_day, allowed_cents=26000, adjustments=adjustments)],
    )
    trace = "SIMEVGM1" + f"{paid_on:%Y%m%d}" + "000901"
    x835 = build_835(Remittance(payer=payer, payee=Provider(name="Northside Health", npi=ORG_NPI),
                                payment_cents=21000, payment_date=paid_on, trace_number=trace, claims=[remit_claim]),
                     _env(15301, ctx.at(paid_on, 10), sender="BVSIMCH", receiver=SUBMITTER_ID))

    cur.execute(
        """
        INSERT INTO insurance_claim_submissions
            (id, organization_id, patient_id, claim_id, coverage_id, payer_ref, patient_control_number,
             diagnosis_codes, service_lines, total_charge_cents, status, x12_837, interchange_control, x12_277ca,
             ack_category, ack_status_code, ack_message, payer_claim_number, simulated, submitted_at,
             acknowledged_at, remitted_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 38000, 'paid', %s, '000015201', %s, 'A2', '20',
                'Accepted into adjudication: Accepted for processing', %s, true, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (SUB_CARDIO, ORG, P_MAYA, CL_CARDIO, COV_MAYA, PAYER_EVERGREEN, pcn, ["R07.9", "E78.5"],
         json.dumps([line.model_dump(mode="json")]), x837, x277, payer_claim, sent, acked, ctx.at(paid_on, 10)),
    )
    cur.execute(
        """
        INSERT INTO payer_sim_claims (id, payer_ref, patient_control_number, payer_claim_number, claim, status,
                                      received_at, adjudicated_at, remit_trace)
        VALUES (%s, %s, %s, %s, %s, 'adjudicated', %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        (SIM_CLAIM_CARDIO, PAYER_EVERGREEN, pcn, payer_claim, claim.model_dump_json(), sent, ctx.at(paid_on, 10), trace),
    )
    cur.execute(
        """
        INSERT INTO insurance_remittances (id, organization_id, payer_ref, payer_name, trace_number, payment_cents,
                                           payment_method, payment_date, x12_835, source, received_at)
        VALUES (%s, %s, %s, 'Evergreen Mutual Health', %s, 21000, 'ACH', %s, %s, 'seed', %s) ON CONFLICT DO NOTHING
        """,
        (REMIT_CARDIO, ORG, PAYER_EVERGREEN, trace, paid_on, x835, ctx.at(paid_on, 10)),
    )
    cur.execute(
        """
        INSERT INTO insurance_remittance_claims
            (id, remittance_id, submission_id, claim_id, patient_id, patient_control_number, status_code,
             charge_cents, paid_cents, patient_resp_cents, payer_claim_number, adjustments, service_lines,
             posting_status, posting_note, posted_at)
        VALUES (%s, %s, %s, %s, %s, %s, '1', 38000, 21000, 5000, %s, %s, %s, 'posted', %s, %s) ON CONFLICT DO NOTHING
        """,
        (REMIT_CLAIM_CARDIO, REMIT_CARDIO, SUB_CARDIO, CL_CARDIO, P_MAYA, pcn, payer_claim,
         json.dumps([a.model_dump() for a in adjustments]),
         json.dumps([remit_claim.service_lines[0].model_dump(mode="json")]),
         "Paid $210; patient responsibility $50 (deductible $0, coinsurance $0, copay $50).", ctx.at(paid_on, 10)),
    )
