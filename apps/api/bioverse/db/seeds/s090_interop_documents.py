"""Interoperability demo data: the terminology subset, identifiers for matching, and one lab-import log entry.

Idempotent. Adds no clinical data to anyone's record: imports and uploads are created live in the demo.
All identifiers are fictional.
"""

from __future__ import annotations

import json

from bioverse import terminology
from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import (
    DR_ACHEBE, DR_FERREIRA, DR_LINDQVIST, DR_MORI, DR_OKAFOR, DR_RAMAN, DR_WEISS, ORG, P_HADDAD, P_MAYA, P_PARK,
    TEAM_DERM_TELE, U_ADMIN, _id,
)

MRN_SYSTEM = "https://northside.example/fhir/sid/mrn"
STAFF_SYSTEM = "https://northside.example/fhir/sid/staff-id"
HL7_AUTHORITY = "NSH"

# id, patient, MRN
PATIENT_MRNS = [
    (_id(8501), P_MAYA, "NSH-0201"),
    (_id(8502), P_PARK, "NSH-0202"),
    (_id(8503), P_HADDAD, "NSH-0203"),
]

# id, practitioner, staff id (what OBR-16 ordering provider carries)
PRACTITIONER_IDS = [
    (_id(8511), DR_OKAFOR, "D301"),
    (_id(8512), DR_FERREIRA, "D302"),
    (_id(8513), DR_ACHEBE, "D303"),
    (_id(8514), TEAM_DERM_TELE, "D304"),
    (_id(8515), DR_LINDQVIST, "D305"),
    (_id(8516), DR_RAMAN, "D306"),
    (_id(8517), DR_MORI, "D307"),
    (_id(8518), DR_WEISS, "D308"),
]

SAMPLE_REJECTED = "\r".join([
    "MSH|^~\\&|RIVERSIDE-LIS|Riverside Lab|BIOVERSE|NSH|20260901083000||ORU^R01^ORU_R01|RSL-DEMO-0001|P|2.5.1",
    "PID|1||RSL-99812^^^RSL^MR||Example^Jordan||19800101|U",
    "OBR|1||RSL-ACC-1|2345-7^Glucose^LN|||20260901071500",
    "OBX|1|NM|2345-7^Glucose^LN||92|mg/dL^^UCUM|70-99|N|||F",
])


def run(conn, ctx: SeedContext) -> None:
    cur = conn.cursor()
    cur.executemany(
        """
        INSERT INTO code_system_concepts (system, code, display, synonyms, properties)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (system, code) DO UPDATE
          SET display = EXCLUDED.display, synonyms = EXCLUDED.synonyms, properties = EXCLUDED.properties
        """,
        [(s, c, d, syn, json.dumps(p)) for s, c, d, syn, p in terminology.seed_rows()],
    )
    cur.executemany(
        """
        INSERT INTO patient_identifiers (id, patient_id, system, hl7_authority, value, type_code)
        VALUES (%s, %s, %s, %s, %s, 'MR') ON CONFLICT DO NOTHING
        """,
        [(i, p, MRN_SYSTEM, HL7_AUTHORITY, v) for i, p, v in PATIENT_MRNS],
    )
    cur.executemany(
        """
        INSERT INTO practitioner_identifiers (id, practitioner_id, system, hl7_authority, value)
        VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        [(i, p, STAFF_SYSTEM, HL7_AUTHORITY, v) for i, p, v in PRACTITIONER_IDS],
    )
    # One historical rejection so the import log shows what a refused match looks like.
    cur.execute(
        """
        INSERT INTO hl7_inbound_messages (id, received_at, received_by, organization_id, message_type, control_id,
                                          sending_facility, raw, outcome, reason, detail)
        VALUES (%s, %s, %s, %s, 'ORU^R01', 'RSL-DEMO-0001', 'Riverside Lab', %s, 'rejected', %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (
            _id(8601), ctx.at(ctx.days(-3), 8, 30), U_ADMIN, ORG, SAMPLE_REJECTED,
            "No patient matches this identifier, name and date of birth. Nothing was imported.",
            json.dumps({"stage": "patient_match"}),
        ),
    )
