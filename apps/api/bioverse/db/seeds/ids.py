"""Fixed demo IDs. Stable across reseeds so the web app's demo identities never change.

Each module seeds inside its own reserved range to avoid collisions:

    1 - 999       core (this file)
    1000 - 1999   platform (admin user, caregiver identity)
    2000 - 2999   visits and referrals
    3000 - 3999   messaging and the Doctor Agent runtime
    4000 - 4999   hospital operations, organization, analytics
    5000 - 5999   billing, coverage, pharmacy
    6000 - 6999   wellness, prevention, family and caregivers, personal health AI
    7000 - 7999   research, clinical trials, evidence
    8000 - 8999   trust and safety, interoperability, AI platform
"""


def _id(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


ORG = _id(1)

# Users
U_MAYA, U_OKAFOR, U_PARK, U_HADDAD, U_FRONTDESK = _id(101), _id(102), _id(103), _id(104), _id(105)
U_ADMIN = _id(1001)

# Patients
P_MAYA, P_PARK, P_HADDAD = _id(201), _id(202), _id(203)

# Practitioners
DR_OKAFOR, DR_FERREIRA, DR_ACHEBE, TEAM_DERM_TELE = _id(301), _id(302), _id(303), _id(304)
DR_LINDQVIST, DR_RAMAN, DR_MORI, DR_WEISS = _id(305), _id(306), _id(307), _id(308)

PLAN = "Northside Health Plus"
