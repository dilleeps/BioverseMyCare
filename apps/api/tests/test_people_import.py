"""Bulk import of people from CSV (dry run, then commit), the template and the CSV export."""

import csv
import io

import psycopg
from psycopg.rows import dict_row

from bioverse.db.seeds.ids import U_FRONTDESK
from tests.conftest import ADMIN, DB, MAYA, as_user

HEADER = "name,email,role,team,specialty,location,birth_date,consult_fee\n"
GOOD = HEADER + (
    "Rae Pharm,rae.pharm@hospital.example,staff,pharmacy,,,,\n"
    "Dee Desk,dee.desk@hospital.example,staff,front_desk,,,,\n"
    "Dr. Ina Card,ina.card@hospital.example,clinician,,Cardiology,East clinic,,75\n"
    "Pat Ient,pat.ient@hospital.example,patient,,,,1980-02-29,\n"
    "Stu Dent,stu.dent@hospital.example,student,,,,,\n"
    "Ada Min,ada.min@hospital.example,admin,,,,,\n"
)


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def run(client, text, headers=ADMIN, **opts):
    return client.post("/api/admin/users/import", headers=headers, json={"csv": text} | opts)


def statuses(report):
    return [r["status"] for r in report["rows"]]


def test_dry_run_changes_nothing_then_commit_creates_each_role_with_its_rows(client):
    r = run(client, GOOD)
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["dry_run"] and not report["committed"]
    assert statuses(report) == ["would_create"] * 6
    assert report["totals"] == {"rows": 6, "create": 6, "update": 0, "skip": 0, "duplicate": 0, "error": 0}
    assert report["rows"][0]["row"] == 2                   # spreadsheet line numbers: the header is line 1
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM users WHERE email LIKE '%%@hospital.example'").fetchone()["n"] == 0

    r = run(client, GOOD, dry_run=False)
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["committed"] and statuses(report) == ["created"] * 6
    ids = {row["email"].split("@")[0]: row["id"] for row in report["rows"]}

    with db() as conn:
        users = {u["email"]: u for u in conn.execute(
            "SELECT id::text, email, role, team FROM users WHERE email LIKE '%%@hospital.example'").fetchall()}
        assert users["rae.pharm@hospital.example"]["team"] == "pharmacy"
        assert conn.execute("SELECT 1 FROM pharmacy_staff WHERE user_id = %s", (ids["rae.pharm"],)).fetchone()
        assert not conn.execute("SELECT 1 FROM pharmacy_staff WHERE user_id = %s", (ids["dee.desk"],)).fetchone()
        doc = conn.execute(
            "SELECT p.specialty, p.location_name, cp.fee_cents FROM practitioners p "
            "JOIN consult_profiles cp ON cp.practitioner_id = p.id WHERE p.user_id = %s", (ids["ina.card"],)).fetchone()
        assert doc == {"specialty": "Cardiology", "location_name": "East clinic", "fee_cents": 7500}
        pat = conn.execute("SELECT name, birth_date::text FROM patients WHERE user_id = %s", (ids["pat.ient"],)).fetchone()
        assert pat == {"name": "Pat Ient", "birth_date": "1980-02-29"}
        assert users["ada.min@hospital.example"]["role"] == "admin"
        assert users["stu.dent@hospital.example"]["role"] == "student"
        events = conn.execute("SELECT detail FROM audit_events WHERE action = 'access.bulk_import'").fetchall()
    assert len(events) == 1
    detail = events[0]["detail"]
    assert detail["created"] == 6 and detail["created_by_role"]["staff"] == 2
    assert "hospital.example" not in str(detail)             # counts only, no personal data

    # The new people can do their jobs.
    assert client.get("/api/pharmacy-orders/staff/queue", headers=as_user(ids["rae.pharm"])).status_code == 200
    assert client.get("/api/pharmacy-orders/staff/queue", headers=as_user(ids["dee.desk"])).status_code == 403
    assert client.get("/api/learning/cases", headers=as_user(ids["stu.dent"])).status_code == 200
    assert client.get("/api/admin/users", headers=as_user(ids["ada.min"])).status_code == 200


def test_row_errors_have_human_messages(client):
    with db() as conn:
        maya_email = conn.execute("SELECT email FROM users WHERE role = 'patient' ORDER BY email LIMIT 1").fetchone()["email"]
    text = HEADER + (
        "Bad Email,not-an-email,staff,front_desk,,,,\n"
        "Who Knows,who@hospital.example,wizard,,,,,\n"
        "Dr. No Spec,nospec@hospital.example,clinician,,,,,\n"
        "No Dob,nodob@hospital.example,patient,,,,,\n"
        "Bad Dob,baddob@hospital.example,patient,,,,17/03/1984,\n"
        "Twice,twice@hospital.example,staff,front_desk,,,,\n"
        "Twice Again,TWICE@hospital.example,staff,pharmacy,,,,\n"
        f"Existing,{maya_email.upper()},patient,,,,1990-01-01,\n"
        "Fine Person,fine@hospital.example,staff,,,,,\n"
        "Wrong Team,team@hospital.example,staff,kitchen,,,,\n"
    )
    report = run(client, text).json()
    by_row = {r["row"]: r for r in report["rows"]}
    assert "doesn't look like an email" in by_row[2]["message"] and by_row[2]["status"] == "error"
    assert "Unknown role 'wizard'" in by_row[3]["message"]
    assert by_row[4]["message"] == "A clinician needs a specialty"
    assert by_row[5]["message"] == "A patient needs a date of birth"
    assert "1984-03-17" in by_row[6]["message"]
    assert by_row[7]["status"] == "would_create"
    assert by_row[8]["status"] == "duplicate" and by_row[8]["message"] == "Same email as row 7"
    assert by_row[9]["status"] == "skip" and "Already has an account" in by_row[9]["message"]
    assert by_row[10]["status"] == "would_create"
    assert "Unknown team 'kitchen'" in by_row[11]["message"]
    assert report["totals"] == {"rows": 10, "create": 2, "update": 0, "skip": 1, "duplicate": 1, "error": 6}
    assert report["blocking"] == 7


def test_commit_is_all_or_nothing_unless_skipping_errors(client):
    text = GOOD + "Broken,broken,staff,,,,,\n"
    r = run(client, text, dry_run=False)
    assert r.status_code == 422
    assert "nobody was imported" in r.json()["detail"]["message"]
    assert r.json()["detail"]["report"]["totals"]["error"] == 1
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM users WHERE email LIKE '%%@hospital.example'").fetchone()["n"] == 0
        assert not conn.execute("SELECT 1 FROM audit_events WHERE action = 'access.bulk_import'").fetchone()

    r = run(client, text, dry_run=False, skip_errors=True)
    assert r.status_code == 200 and r.json()["totals"]["create"] == 6 and r.json()["totals"]["error"] == 1
    assert statuses(r.json())[-1] == "error"
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM users WHERE email LIKE '%%@hospital.example'").fetchone()["n"] == 6


def test_existing_people_are_skipped_or_their_team_updated(client):
    with db() as conn:
        desk_email = conn.execute("SELECT email FROM users WHERE id = %s", (U_FRONTDESK,)).fetchone()["email"]
    text = HEADER + f"Front Desk,{desk_email},staff,pharmacy,,,,\n"
    assert statuses(run(client, text).json()) == ["skip"]
    report = run(client, text, update_existing=True).json()
    assert statuses(report) == ["would_update"] and "front_desk" in report["rows"][0]["message"]
    r = run(client, text, update_existing=True, dry_run=False)
    assert statuses(r.json()) == ["updated"]
    assert client.get("/api/pharmacy-orders/staff/queue", headers=as_user(U_FRONTDESK)).status_code == 200
    # Role changes are never made by an import.
    report = run(client, HEADER + f"Front Desk,{desk_email},admin,,,,,\n", update_existing=True).json()
    assert statuses(report) == ["skip"] and "doesn't change roles" in report["rows"][0]["message"]


def test_headers_are_flexible_and_file_problems_are_explained(client):
    text = ("﻿Full Name;E-mail;Role;Department;Date of Birth;Notes\n"
            "Rx Person;rx2@hospital.example;Pharmacist;;;hello\n"
            "Doc Person;doc2@hospital.example;Doctor;Cardiology;;\n")
    report = run(client, text).json()
    assert report["ignored_columns"] == ["Notes"]
    rows = report["rows"]
    assert rows[0]["role"] == "staff" and rows[0]["team"] == "pharmacy" and rows[0]["status"] == "would_create"
    # "Department" is a team for staff and ignored for other roles; a clinician still needs a specialty column.
    assert rows[1]["role"] == "clinician" and rows[1]["message"] == "A clinician needs a specialty"

    r = run(client, "full name,team\nA,B\n")
    assert r.status_code == 422 and "Missing: email, role" in r.json()["detail"]
    assert run(client, "").status_code == 422
    assert run(client, HEADER).status_code == 422
    too_many = HEADER + "".join(f"P{i},p{i}@hospital.example,student,,,,,\n" for i in range(1001))
    assert run(client, too_many).status_code == 413


def test_import_and_export_are_admin_only(client):
    staff = as_user(U_FRONTDESK)
    assert run(client, GOOD, headers=staff).status_code == 403
    assert run(client, GOOD, headers=MAYA).status_code == 403
    assert client.get("/api/admin/users/export.csv", headers=staff).status_code == 403
    assert client.get("/api/admin/users/import/template", headers=staff).status_code == 403


def test_template_imports_cleanly(client):
    r = client.get("/api/admin/users/import/template", headers=ADMIN)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    report = run(client, r.text).json()
    assert report["totals"]["error"] == 0 and report["totals"]["create"] == report["totals"]["rows"]


def test_export_escapes_formulas(client):
    evil = HEADER + ("\"=HYPERLINK(\"\"http://evil.example\"\",\"\"x\"\")\",evil1@hospital.example,staff,,,,,\n"
                     "+SUM(A1),evil2@hospital.example,student,,,,,\n"
                     "@cmd,evil3@hospital.example,student,,,,,\n"
                     "-2+3,evil4@hospital.example,student,,,,,\n"
                     "Dr. Safe,safe@hospital.example,clinician,,=1+1,,,\n")
    assert run(client, evil, dry_run=False).status_code == 200
    r = client.get("/api/admin/users/export.csv", headers=ADMIN)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿"))))
    assert list(rows[0]) == ["name", "email", "role", "team", "specialty", "disabled", "last_sign_in",
                             "linked_providers"]
    names = {row["email"]: row for row in rows}
    assert names["evil1@hospital.example"]["name"].startswith("'=HYPERLINK")
    assert names["evil2@hospital.example"]["name"] == "'+SUM(A1)"
    assert names["evil3@hospital.example"]["name"] == "'@cmd"
    assert names["evil4@hospital.example"]["name"] == "'-2+3"
    assert names["safe@hospital.example"]["specialty"] == "'=1+1"
    assert names["safe@hospital.example"]["name"] == "Dr. Safe" and names["safe@hospital.example"]["disabled"] == "no"
    with db() as conn:
        assert conn.execute("SELECT 1 FROM audit_events WHERE action = 'access.export'").fetchone()


def test_admin_form_still_reports_errors_the_same_way(client):
    body = {"display_name": "Dr. Form", "email": "form@hospital.example", "role": "clinician"}
    r = client.post("/api/admin/users", headers=ADMIN, json=body)
    assert r.status_code == 422 and r.json()["detail"] == "A clinician needs a specialty"
    r = client.post("/api/admin/users", headers=ADMIN, json=body | {"specialty": "Neurology"})
    assert r.status_code == 201
    r = client.post("/api/admin/users", headers=ADMIN, json=body | {"specialty": "Neurology"})
    assert r.status_code == 409 and r.json()["detail"] == "Someone already uses that email"
    r = client.post("/api/admin/users", headers=ADMIN, json={
        "display_name": "New Patient", "email": "np@hospital.example", "role": "patient", "birth_date": "1970-05-05"})
    assert r.status_code == 201 and r.json()["patient"]["patient_id"]
