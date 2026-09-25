"""Master patient index: scoring, register_patient outcomes, the review queue, merge, and permissions."""

from datetime import date

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse.db.seeds.ids import ORG, P_HADDAD, U_FRONTDESK, U_HADDAD, _id
from bioverse.db.seeds import run_all
from bioverse.patient_match import Person, compare_dob, compare_names, jaro_winkler, norm_phone, score
from bioverse.patient_registry import record_counts, register_patient
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, P_PARK, as_user

FRONT = as_user(U_FRONTDESK)
PHARMACIST = as_user(_id(14001))
RANA_HL7, WEN_DUP, WEN = _id(21001), _id(21002), _id(4105)
MRN = "https://northside.example/fhir/sid/mrn"


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def new_user(conn, email, role="patient"):
    return conn.execute(
        "INSERT INTO users (role, display_name, email, organization_id) VALUES (%s, 'New person', %s, %s) RETURNING id::text",
        (role, email, ORG),
    ).fetchone()["id"]


def register(conn, **kw):
    kw.setdefault("organization_id", ORG)
    kw.setdefault("user_id", None)
    kw.setdefault("source", "test")
    return register_patient(conn, **kw)


def count(conn, sql, *args):
    return conn.execute(sql, args).fetchone()["n"]


# --- Scoring -----------------------------------------------------------------------------------------


def P(name, dob=date(1970, 4, 2), **kw):
    return Person(name=name, birth_date=dob, **kw)


def test_jaro_winkler_and_normalizers():
    assert round(jaro_winkler("martha", "marhta"), 3) == 0.961
    assert jaro_winkler("same", "same") == 1.0 and jaro_winkler("", "x") == 0.0
    assert norm_phone("+1 (555) 010-4417") == norm_phone("555.010.4417") == "5550104417"
    assert norm_phone("12") is None


def test_nickname_swap_accents_and_typos():
    pts, reasons, exact = compare_names("Bill Smith", "William Smith")
    assert not exact and reasons[0]["code"] == "name_nickname" and pts >= 35
    pts, reasons, exact = compare_names("Liz Okoro", "Elizabeth Okoro")
    assert reasons[0]["code"] == "name_nickname"
    _, reasons, exact = compare_names("Thornton Maya", "Maya Thornton")
    assert exact and reasons[0]["code"] == "name_swapped"
    assert compare_names("Thornton, Maya", "Maya Thornton")[2]  # "Family, Given" order
    assert compare_names("JOSÉ  Álvarez-Núñez", "Jose Alvarez Nunez")[2]
    assert compare_names("Maya R. Thornton", "maya thornton")[2]  # middle initial ignored
    pts, reasons, exact = compare_names("Rana Hadad", "Rana Haddad")
    assert not exact and pts == 36 and "typo" in reasons[0]["label"]
    assert compare_names("Ann Lee", "Bob Kim")[0] == 0


def test_dob_exact_transposed_and_conflict():
    assert compare_dob(date(1983, 5, 12), date(1983, 12, 5))[1][0]["code"] == "dob_transposed"
    assert compare_dob(date(1983, 5, 5), date(1983, 5, 5))[2]
    assert compare_dob(date(1983, 5, 13), date(1983, 1, 1))[1][0]["code"] == "dob_differs"


def test_levels():
    assert score(P("Maya Thornton", email="m@x.com"), P("Maya Thornton", email="M@X.com "))[1] == "certain"
    # A phone number is unverified and shared: it adds points but never makes a match certain.
    assert score(P("Maya Thornton", phone="555 010 1234"), P("maya thornton", phone="(555) 010-1234"))[1] == "probable"
    assert score(P("Maya Thornton"), P("Maya Thornton"))[1] == "probable"          # no contact detail: not certain
    assert score(P("Bill Smith", email="b@x.com"), P("William Smith", email="b@x.com"))[1] == "probable"
    assert score(P("Wen Li", date(1983, 5, 12)), P("Wen Li", date(1983, 12, 5)))[1] == "possible"
    assert score(P("Ann Lee"), P("Bob Kim"))[1] == "none"
    # Evidence against: a different sex at birth pulls a certain match down.
    assert score(P("Maya Thornton", email="m@x.com", sex="female"),
                 P("Maya Thornton", email="m@x.com", sex="male"))[1] != "certain"
    # Same household email, different person.
    assert score(P("Leo Thornton", date(2004, 1, 9), email="home@x.com"),
                 P("Maya Thornton", date(1972, 3, 9), email="home@x.com"))[1] == "none"


# --- register_patient ----------------------------------------------------------------------------------


def test_created_stores_contact_and_identifiers(client):
    with db() as conn:
        out = register(conn, name="Ines Carvalho", birth_date=date(1990, 2, 3), email=" Ines@Example.com ",
                       phone="555-010-7788", identifiers=[{"system": MRN, "value": "NSH-9001"},
                                                          {"system": "https://cityhosp.example/id/mrn", "value": "C-1"}])
        assert out["how"] == "created" and out["review_ids"] == []
        row = conn.execute("SELECT email, phone, user_id FROM patients WHERE id = %s", (out["patient_id"],)).fetchone()
        assert row == {"email": "ines@example.com", "phone": "555-010-7788", "user_id": None}
        ids = {r["system"]: r["hl7_authority"] for r in conn.execute(
            "SELECT system, hl7_authority FROM patient_identifiers WHERE patient_id = %s", (out["patient_id"],))}
        assert ids == {MRN: "NSH", "https://cityhosp.example/id/mrn": "CITYHOSP-MRN"}


def test_certain_match_without_login_is_linked(client):
    with db() as conn:
        hl7 = register(conn, name="Tariq Mansour", birth_date=date(1979, 8, 1), phone="555 010 3000",
                       email="Tariq@example.com", identifiers=[{"system": MRN, "value": "NSH-7001"}], source="hl7")
        assert hl7["how"] == "created"
        # Name, date of birth and phone alone never attach a sign-in to a record: review instead.
        uid0 = new_user(conn, "someone@example.com")
        phone_only = register(conn, user_id=uid0, name="Tariq Mansour", birth_date=date(1979, 8, 1),
                              phone="(555) 010-3000", source="self")
        assert phone_only["how"] == "created_pending_review" and phone_only["patient_id"] != hl7["patient_id"]
        before = count(conn, "SELECT count(*) AS n FROM patients")
        uid = new_user(conn, "tariq@example.com")
        out = register(conn, user_id=uid, name="tariq  MANSOUR", birth_date=date(1979, 8, 1),
                       email="tariq@example.com", phone="(555) 010-3000", source="self", actor_id=uid)
        assert out["how"] == "linked" and out["patient_id"] == hl7["patient_id"]
        assert count(conn, "SELECT count(*) AS n FROM patients") == before
        row = conn.execute("SELECT user_id::text, email FROM patients WHERE id = %s", (hl7["patient_id"],)).fetchone()
        assert row == {"user_id": uid, "email": "tariq@example.com"}
        # Identifier alone is enough, and new identifiers are added to the existing record.
        uid2 = new_user(conn, "t2@example.com")
        conn.execute("UPDATE patients SET user_id = NULL WHERE id = %s", (hl7["patient_id"],))
        out = register(conn, user_id=uid2, name="Tariq Mansour", birth_date=date(1979, 8, 1),
                       identifiers=[{"system": MRN, "value": "NSH-7001"}, {"system": "urn:oid:1.2.3", "value": "X9"}])
        assert out["how"] == "linked" and out["patient_id"] == hl7["patient_id"]
        assert out["identifiers"]["added"] == [{"system": "urn:oid:1.2.3", "value": "X9"}]
        assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = 'patient_match.linked'").fetchone()["n"] == 2


def test_certain_match_without_login_passed_returns_existing(client):
    with db() as conn:
        out = register(conn, name="Maya Thornton", birth_date=date(1972, 3, 9),
                       identifiers=[{"system": MRN, "value": "NSH-0201"}], source="import")
        assert out["how"] == "matched_existing" and out["patient_id"] == P_MAYA


def test_certain_match_to_someone_elses_login_is_created_and_flagged(client):
    with db() as conn:
        uid = new_user(conn, "maya.second@example.com")
        out = register(conn, user_id=uid, name="Maya Thornton", birth_date=date(1972, 3, 9), email="maya@example.com")
        assert out["how"] == "created_flagged" and out["patient_id"] != P_MAYA and out["matched_patient_id"] == P_MAYA
        review = conn.execute("SELECT * FROM match_reviews WHERE id = %s", (out["review_ids"][0],)).fetchone()
        assert review["level"] == "certain" and str(review["patient_a"]) == P_MAYA and review["status"] == "open"
        assert conn.execute("SELECT user_id::text FROM patients WHERE id = %s", (P_MAYA,)).fetchone()["user_id"] != uid


def test_probable_and_possible_are_created_pending_review(client):
    with db() as conn:
        out = register(conn, name="Jun Park", birth_date=date(1985, 11, 2))  # no contact details: probable only
        assert out["how"] == "created_pending_review" and out["match"]["level"] == "probable"
        assert count(conn, "SELECT count(*) AS n FROM match_reviews WHERE patient_b = %s AND patient_a = %s",
                     out["patient_id"], P_PARK) == 1
        out = register(conn, name="Rana Haddad", birth_date=date(1961, 6, 18),
                       email="someone.else@example.com", auto_link=True)
        assert out["how"] == "created_pending_review"
        out = register(conn, name="Pat Nobody", birth_date=date(2000, 1, 1))
        assert out["how"] == "created"


def test_identifier_owned_by_someone_with_other_demographics(client):
    with db() as conn:
        out = register(conn, name="Different Person", birth_date=date(1999, 9, 9),
                       identifiers=[{"system": MRN, "value": "NSH-0201"}])
        assert out["how"] == "created_pending_review"
        assert out["identifiers"]["skipped"][0]["value"] == "NSH-0201"
        reasons = conn.execute("SELECT reasons FROM match_reviews WHERE id = %s", (out["review_ids"][0],)).fetchone()
        assert reasons["reasons"][0]["code"] == "identifier_conflict"


# --- Admin create goes through the registry --------------------------------------------------------------


def test_admin_create_reports_how(client):
    res = client.post("/api/admin/users", headers=ADMIN, json={
        "role": "patient", "display_name": "Wen Li", "email": "wen.li@example.com", "birth_date": "1983-12-05"})
    assert res.status_code == 201, res.text
    assert res.json()["patient"]["how"] == "created_pending_review"
    with db() as conn:
        register(conn, name="Omar Farouk", birth_date=date(1966, 10, 20), email="omar@example.com", source="hl7")
    res = client.post("/api/admin/users", headers=ADMIN, json={
        "role": "patient", "display_name": "Omar Farouk", "email": "omar@example.com", "birth_date": "1966-10-20"})
    assert res.json()["patient"]["how"] == "linked"


# --- Review queue, search, permissions ------------------------------------------------------------------


def test_permissions(client):
    for headers in (MAYA, OKAFOR, PHARMACIST):
        assert client.get("/api/patient-matching/reviews", headers=headers).status_code == 403
        assert client.get("/api/patient-matching/search?name=maya", headers=headers).status_code == 403
        assert client.post(f"/api/patient-matching/reviews/{_id(21101)}/not-duplicate", headers=headers).status_code == 403
    assert client.get("/api/patient-matching/reviews", headers=FRONT).status_code == 200
    assert client.get("/api/patient-matching/reviews", headers=ADMIN).status_code == 200


def test_seeded_queue_and_side_by_side(client):
    data = client.get("/api/patient-matching/reviews", headers=FRONT).json()
    assert data["open"] == 2
    by_id = {r["id"]: r for r in data["reviews"]}
    rana = by_id[_id(21101)]
    assert rana["existing"]["id"] == RANA_HL7 and rana["new"]["id"] == P_HADDAD
    assert rana["level"] == "probable" and {r["code"] for r in rana["reasons"]} >= {"dob_exact", "name_similar"}
    assert rana["new"]["has_login"] and not rana["existing"]["has_login"]
    assert rana["existing"]["identifiers"][0]["value"] == "RSL-44120"
    assert rana["new"]["records"]["total"] > 0 and rana["existing"]["records"]["total"] == 0
    assert by_id[_id(21102)]["level"] == "possible"


def test_search(client):
    res = client.get("/api/patient-matching/search", headers=FRONT, params={"name": "Thornton, Maya"}).json()
    assert res["results"][0]["id"] == P_MAYA
    res = client.get("/api/patient-matching/search", headers=FRONT, params={"identifier": "NSH-0202"}).json()
    assert [r["id"] for r in res["results"]] == [P_PARK]
    res = client.get("/api/patient-matching/search", headers=ADMIN,
                     params={"name": "Rana Haddad", "birth_date": "1961-06-18"}).json()
    ids = [r["id"] for r in res["results"]]
    assert ids[:2] == [P_HADDAD, RANA_HL7]
    wen = client.get("/api/patient-matching/search", headers=FRONT, params={"name": "wen li"}).json()["results"]
    assert {r["id"] for r in wen} == {WEN, WEN_DUP} and {(r["level"], r["score"]) for r in wen} == {("strong", 100)}
    assert client.get("/api/patient-matching/search", headers=FRONT).status_code == 422


def test_not_duplicate(client):
    res = client.post(f"/api/patient-matching/reviews/{_id(21102)}/not-duplicate", headers=FRONT)
    assert res.status_code == 200 and res.json()["review"]["status"] == "not_duplicate"
    assert client.post(f"/api/patient-matching/reviews/{_id(21102)}/not-duplicate", headers=FRONT).status_code == 409
    assert client.post(f"/api/patient-matching/reviews/{_id(21102)}/merge", headers=FRONT,
                       json={"survivor": WEN}).status_code == 409
    assert client.get("/api/patient-matching/reviews", headers=FRONT).json()["open"] == 1


# --- Merge -----------------------------------------------------------------------------------------------

def test_merge_moves_everything_and_keeps_retired_record(client):
    """Keep the no-login duplicate; retire Maya's record. Her data and her sign-in move to the survivor."""
    with db() as conn:
        dup = register(conn, name="Maya Thorton", birth_date=date(1972, 3, 9), source="hl7")
        assert dup["how"] == "created_pending_review"
        review_id, survivor = dup["review_ids"][0], dup["patient_id"]
        # A third record queued against both: its review of Maya must follow the merge, not dangle.
        third = register(conn, name="Maya Thornton", birth_date=date(1972, 3, 9), phone="555 010 9999")
        assert len(third["review_ids"]) == 2
        conn.execute(
            """
            INSERT INTO appointments (patient_id, practitioner_id, slot_id, reason)
            SELECT %s, practitioner_id, id, 'Follow-up' FROM slots WHERE status = 'free' LIMIT 1
            """, (P_MAYA,))
        # The survivor already has a consent that Maya also has: a unique conflict that must be handled.
        conn.execute(
            "INSERT INTO consents (patient_id, scope, grantee, status) "
            "SELECT %s, scope, grantee, status FROM consents WHERE patient_id = %s LIMIT 1", (survivor, P_MAYA))
        before = record_counts(conn, P_MAYA)
        assert {"observations", "appointments", "encounters", "medication_requests", "consultations",
                "communications", "nutrition_intakes", "notifications"} <= set(before)
        audit_before = count(conn, "SELECT count(*) AS n FROM audit_events WHERE patient_id = %s", P_MAYA)
        conn.commit()

    res = client.post(f"/api/patient-matching/reviews/{review_id}/merge", headers=ADMIN, json={"survivor": survivor})
    assert res.status_code == 200, res.text
    report = res.json()["report"]
    assert report["login_moved"] and report["kept_on_retired"] == {"consents": 1}
    assert report["moved"]["observations"] == before["observations"] and report["moved"]["appointments"] == 1
    assert res.json()["review"]["status"] == "merged"

    with db() as conn:
        assert record_counts(conn, P_MAYA) == {"consents": 1}
        assert record_counts(conn, survivor) == before
        retired = conn.execute("SELECT merged_into::text, user_id, merged_at FROM patients WHERE id = %s", (P_MAYA,)).fetchone()
        assert retired["merged_into"] == survivor and retired["user_id"] is None and retired["merged_at"]
        s = conn.execute("SELECT user_id::text, allergies FROM patients WHERE id = %s", (survivor,)).fetchone()
        assert s["user_id"] == _id(101) and "Penicillin" in s["allergies"]
        # Audit history stays on the retired record.
        assert count(conn, "SELECT count(*) AS n FROM audit_events WHERE patient_id = %s", P_MAYA) >= audit_before
        assert count(conn, "SELECT count(*) AS n FROM audit_events WHERE action = 'patient_match.merge'") == 1
        assert count(conn, "SELECT count(*) AS n FROM match_reviews WHERE status = 'open' "
                           "AND %s IN (patient_a, patient_b)", P_MAYA) == 0
        assert count(conn, "SELECT count(*) AS n FROM match_reviews WHERE status = 'open' "
                           "AND patient_a = %s AND patient_b = %s", survivor, third["patient_id"]) == 1

    # Maya signs in and lands on the surviving record; the retired one no longer shows up.
    assert client.get("/api/me", headers=MAYA).json()["patient_id"] == survivor
    assert client.get(f"/api/patients/{survivor}/reports", headers=MAYA).status_code == 200
    found = client.get("/api/patient-matching/search", headers=FRONT, params={"name": "Maya Thornton"}).json()
    assert P_MAYA not in [r["id"] for r in found["results"]] and survivor in [r["id"] for r in found["results"]]


def test_merge_refuses_two_logins_and_foreign_survivor(client):
    with db() as conn:
        rid = conn.execute(
            "INSERT INTO match_reviews (organization_id, patient_a, patient_b, level, score) "
            "VALUES (%s, %s, %s, 'possible', 50) RETURNING id::text", (ORG, P_MAYA, P_PARK),
        ).fetchone()["id"]
        conn.commit()
    res = client.post(f"/api/patient-matching/reviews/{rid}/merge", headers=ADMIN, json={"survivor": P_MAYA})
    assert res.status_code == 409 and "sign-in" in res.json()["detail"]
    res = client.post(f"/api/patient-matching/reviews/{rid}/merge", headers=ADMIN, json={"survivor": P_HADDAD})
    assert res.status_code == 422
    with db() as conn:
        assert conn.execute("SELECT merged_into FROM patients WHERE id = %s", (P_PARK,)).fetchone()["merged_into"] is None
        assert conn.execute("SELECT status FROM match_reviews WHERE id = %s", (rid,)).fetchone()["status"] == "open"


def test_seeded_merge_moves_login_less_duplicate(client):
    res = client.post(f"/api/patient-matching/reviews/{_id(21101)}/merge", headers=FRONT, json={"survivor": P_HADDAD})
    assert res.status_code == 200, res.text
    assert res.json()["report"]["moved"] == {"patient_identifiers": 1}
    with db() as conn:
        assert conn.execute("SELECT phone FROM patients WHERE id = %s", (P_HADDAD,)).fetchone()["phone"] == "(555) 010-4417"
        assert conn.execute("SELECT user_id::text FROM patients WHERE id = %s", (P_HADDAD,)).fetchone()["user_id"] == U_HADDAD
    # A later registration with the lab's MRN now resolves to Rana's surviving record.
    with db() as conn:
        out = register(conn, name="Rana Haddad", birth_date=date(1961, 6, 18),
                       identifiers=[{"system": "https://riverside-lab.example/fhir/sid/mrn", "value": "RSL-44120"}])
        assert out["how"] == "matched_existing" and out["patient_id"] == P_HADDAD


def test_seed_is_idempotent(client):
    with db() as conn:
        before = (count(conn, "SELECT count(*) AS n FROM patients"), count(conn, "SELECT count(*) AS n FROM match_reviews"))
    client.post(f"/api/patient-matching/reviews/{_id(21102)}/not-duplicate", headers=ADMIN)
    run_all(DB)
    with db() as conn:
        after = (count(conn, "SELECT count(*) AS n FROM patients"), count(conn, "SELECT count(*) AS n FROM match_reviews"))
        assert after == before
        assert conn.execute("SELECT status FROM match_reviews WHERE id = %s", (_id(21102),)).fetchone()["status"] == "not_duplicate"


@pytest.mark.parametrize("path", ["/api/patient-matching/reviews", "/api/patient-matching/search?name=li"])
def test_retired_records_never_listed(client, path):
    client.post(f"/api/patient-matching/reviews/{_id(21102)}/merge", headers=ADMIN, json={"survivor": WEN})
    body = client.get(path, headers=ADMIN).json()
    assert WEN_DUP not in str(body.get("results", "")) and all(
        r["new"]["id"] != WEN_DUP for r in body.get("reviews", []))
