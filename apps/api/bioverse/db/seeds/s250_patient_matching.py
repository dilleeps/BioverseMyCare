"""Duplicate patient records waiting for review, so the demo queue is not empty.

1. Riverside Lab sent results for "Rana Hadad" (one d) weeks before Rana Haddad signed up: the lab feed created
   a record with no sign-in, the lab's MRN and a phone number. Her sign-up created a second record (the
   spelling differs, so it was not linked automatically). Same date of birth -> probable duplicate.
2. The front desk registered "Wen Li" again with day and month of the birth date swapped -> possible duplicate.

Idempotent: fixed ids, ON CONFLICT DO NOTHING. A pair merged or dismissed in the demo stays decided.
The extra records carry no clinical data.
"""

from __future__ import annotations

import json
from datetime import date

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import ORG, P_HADDAD, PLAN, _id
from bioverse.patient_match import Person, score

P_WEN = _id(4105)  # seeded by s040 (front-desk patient, no sign-in)
P_RANA_HL7 = _id(21001)
P_WEN_DUP = _id(21002)

RSL_SYSTEM = "https://riverside-lab.example/fhir/sid/mrn"

# id, name, birth date, phone, pronouns, created days ago (None: now, after the record it duplicates)
DUPLICATES = [
    (P_RANA_HL7, "Rana Hadad", date(1961, 6, 18), "(555) 010-4417", None, 40),
    (P_WEN_DUP, "Wen Li", date(1983, 5, 12), None, "she/her", None),
]

# review id, existing (older) record, newer record, what created the newer record
REVIEWS = [
    (_id(21101), P_RANA_HL7, P_HADDAD, "self"),
    (_id(21102), P_WEN, P_WEN_DUP, "front_desk"),
]


def run(conn, ctx: SeedContext) -> None:
    for pid, name, dob, phone, pronouns, ago in DUPLICATES:
        conn.execute(
            """
            INSERT INTO patients (id, organization_id, name, birth_date, phone, pronouns, insurance_plan, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now())) ON CONFLICT (id) DO NOTHING
            """,
            (pid, ORG, name, dob, phone, pronouns, PLAN, ctx.at(ctx.days(-ago), 10, 15) if ago else None),
        )
    conn.execute(
        """
        INSERT INTO patient_identifiers (id, patient_id, system, hl7_authority, value, type_code)
        VALUES (%s, %s, %s, 'RSL', 'RSL-44120', 'MR') ON CONFLICT DO NOTHING
        """,
        (_id(21011), P_RANA_HL7, RSL_SYSTEM),
    )

    people = {}
    for pid in {p for _, a, b, _ in REVIEWS for p in (a, b)}:
        name, dob, phone, sex = conn.execute(
            "SELECT name, birth_date, phone, sex_at_birth FROM patients WHERE id = %s", (pid,)
        ).fetchone()
        people[pid] = Person(name=name, birth_date=dob, phone=phone, sex=sex)
    for rid, existing, new, source in REVIEWS:
        points, level, reasons = score(people[new], people[existing])
        conn.execute(
            """
            INSERT INTO match_reviews (id, organization_id, patient_a, patient_b, level, score, reasons, source, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, (SELECT created_at FROM patients WHERE id = %s))
            ON CONFLICT DO NOTHING
            """,
            (rid, ORG, existing, new, level if level != "none" else "possible", points, json.dumps(reasons), source, new),
        )
