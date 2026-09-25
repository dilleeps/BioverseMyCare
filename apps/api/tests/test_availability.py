"""My availability: weekly hours generate bookable slots, time off withdraws them, and the consult profile."""

from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse import availability as av
from bioverse.db.seeds.ids import DR_FERREIRA, DR_OKAFOR, U_FRONTDESK
from bioverse.db.seeds.s160_pharmacy_orders import U_PHARMACIST
from bioverse.jobs import run_job
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, as_user

FRONTDESK = as_user(U_FRONTDESK)
PHARMACIST = as_user(U_PHARMACIST)
CHICAGO = ZoneInfo("America/Chicago")
NEW_YORK = ZoneInfo("America/New_York")


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def every_day(start="09:00", end="12:00", minutes=30, mode="in_person", location="Lakeside Clinic"):
    return [{"weekday": d, "start": start, "end": end, "mode": mode, "location": location, "slot_minutes": minutes}
            for d in range(7)]


def new_clinician(client, email="new.doc@northside.example") -> tuple[dict, str]:
    r = client.post("/api/admin/users", headers=ADMIN, json={
        "display_name": "Dr. Nia Castillo", "email": email, "role": "clinician", "specialty": "Dermatology",
        "location_name": "Lakeside Clinic", "consult_fee_dollars": 60,
    })
    assert r.status_code == 201, r.text
    headers = as_user(r.json()["id"])
    pid = client.get("/api/clinician/availability", headers=headers).json()["practitioner"]["id"]
    return headers, pid


def slots_of(pid: str, **where) -> list[dict]:
    extra = "".join(f" AND {k} = %({k})s" for k in where)
    with db() as conn:
        return conn.execute(
            "SELECT id::text, starts_at, duration_min, mode, status, source, location FROM slots "
            "WHERE practitioner_id = %(pid)s" + extra + " ORDER BY starts_at", {"pid": pid, **where},
        ).fetchall()


# --- Template -> slots -> booking -----------------------------------------------------------------


def test_new_clinician_hours_generate_slots_a_patient_can_book(client):
    doc, pid = new_clinician(client)
    empty = client.get("/api/clinician/availability", headers=doc).json()
    assert empty["windows"] == [] and empty["timezone_is_default"] and empty["upcoming"]["free"] == 0

    r = client.put("/api/clinician/availability", headers=doc,
                   json={"timezone": "America/Chicago", "horizon_days": 14, "windows": every_day()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["timezone"] == "America/Chicago" and body["horizon_days"] == 14 and len(body["windows"]) == 7
    assert body["sync"]["created"] >= 13 * 6          # 6 half-hour slots a day; today may be partly over

    generated = slots_of(pid, source="template")
    assert len(generated) == body["sync"]["created"]
    for s in generated:
        local = s["starts_at"].astimezone(CHICAGO)
        assert time(9) <= local.time() < time(12) and local.minute in (0, 30)
        assert s["status"] == "free" and s["duration_min"] == 30 and s["location"] == "Lakeside Clinic"
    last_day = max(s["starts_at"].astimezone(CHICAGO).date() for s in generated)
    assert last_day == datetime.now(CHICAGO).date() + timedelta(days=13)

    # Saving the same hours again changes nothing.
    again = client.put("/api/clinician/availability", headers=doc,
                       json={"timezone": "America/Chicago", "horizon_days": 14, "windows": every_day()}).json()
    assert (again["sync"]["created"], again["sync"]["removed"], again["sync"]["updated"]) == (0, 0, 0)

    # The preview shows what exists; nothing is pending after a save.
    preview = client.get("/api/clinician/availability/preview?days=14", headers=doc).json()
    assert preview["timezone"] == "America/Chicago"
    assert preview["summary"]["pending"] == 0 and preview["summary"]["free"] == len(generated)
    assert preview["slots"][0]["local_time"] in {"09:00", "09:30", "10:00", "10:30", "11:00", "11:30"}

    # A patient in the same organization finds and books one through the existing scheduling path.
    offered = client.get(f"/api/practitioners/{pid}/slots", headers=MAYA).json()
    assert offered and offered[0]["id"] == generated[0]["id"]
    booked = client.post("/api/appointments", headers=MAYA, json={"slot_id": offered[0]["id"], "reason": "Rash"})
    assert booked.status_code == 201, booked.text
    assert booked.json()["practitioner_id"] == pid
    assert slots_of(pid, status="booked")[0]["id"] == offered[0]["id"]

    preview = client.get("/api/clinician/availability/preview?days=14", headers=doc).json()
    mine = [s for s in preview["slots"] if s["status"] == "booked"]
    assert len(mine) == 1 and mine[0]["patient_name"] == "Maya Thornton"

    with db() as conn:
        audit = conn.execute("SELECT count(*) AS n FROM audit_events WHERE action = 'availability.template_saved' "
                             "AND entity_id = %s", (pid,)).fetchone()
    assert audit["n"] == 2


def test_changing_hours_withdraws_free_slots_but_keeps_booked(client):
    doc, pid = new_clinician(client)
    client.put("/api/clinician/availability", headers=doc, json={"windows": every_day("09:00", "12:00", 30)})
    first = slots_of(pid, source="template")[0]
    assert client.post("/api/appointments", headers=MAYA, json={"slot_id": first["id"]}).status_code == 201

    # Afternoons only now, hour-long slots.
    r = client.put("/api/clinician/availability", headers=doc, json={"windows": every_day("14:00", "16:00", 60)}).json()
    assert r["sync"]["removed"] > 0 and r["sync"]["created"] > 0
    tz = ZoneInfo(r["timezone"])
    free = slots_of(pid, status="free")
    assert free and all(s["starts_at"].astimezone(tz).time() in (time(14), time(15)) for s in free)
    assert all(s["duration_min"] == 60 for s in free)
    assert [s["id"] for s in slots_of(pid, status="booked")] == [first["id"]]

    # No hours at all: every free generated slot goes, the booking stays.
    r = client.put("/api/clinician/availability", headers=doc, json={"windows": []}).json()
    assert slots_of(pid, status="free") == [] and len(slots_of(pid, status="booked")) == 1


def test_time_off_removes_free_generated_slots_and_keeps_booked(client):
    doc, pid = new_clinician(client)
    client.put("/api/clinician/availability", headers=doc,
               json={"timezone": "America/Chicago", "windows": every_day("09:00", "12:00", 30)})
    tomorrow = datetime.now(CHICAGO).date() + timedelta(days=1)
    day_slots = [s for s in slots_of(pid) if s["starts_at"].astimezone(CHICAGO).date() == tomorrow]
    assert len(day_slots) == 6
    kept = day_slots[2]
    assert client.post("/api/appointments", headers=MAYA, json={"slot_id": kept["id"]}).status_code == 201

    r = client.post("/api/clinician/availability/time-off", headers=doc,
                    json={"starts_on": str(tomorrow), "ends_on": str(tomorrow + timedelta(days=2)), "reason": "Conference"})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["sync"]["removed"] == 17               # 3 days x 6 slots, less the booked one
    assert [b["patient_name"] for b in out["booked_in_range"]] == ["Maya Thornton"]
    remaining = [s for s in slots_of(pid) if tomorrow <= s["starts_at"].astimezone(CHICAGO).date() <= tomorrow + timedelta(days=2)]
    assert [s["id"] for s in remaining] == [kept["id"]] and remaining[0]["status"] == "booked"

    listing = client.get("/api/clinician/availability", headers=doc).json()["time_off"]
    assert len(listing) == 1 and listing[0]["reason"] == "Conference"
    preview = client.get("/api/clinician/availability/preview?days=7", headers=doc).json()
    assert preview["days_off"][0]["id"] == out["time_off"]["id"]

    # Overlapping time off, backwards ranges and past ranges are refused.
    assert client.post("/api/clinician/availability/time-off", headers=doc,
                       json={"starts_on": str(tomorrow + timedelta(days=1)), "ends_on": str(tomorrow + timedelta(days=5))}).status_code == 409
    assert client.post("/api/clinician/availability/time-off", headers=doc,
                       json={"starts_on": str(tomorrow + timedelta(days=9)), "ends_on": str(tomorrow + timedelta(days=8))}).status_code == 422
    assert client.post("/api/clinician/availability/time-off", headers=doc,
                       json={"starts_on": "2020-01-01", "ends_on": "2020-01-02"}).status_code == 422

    # Back from time off: the slots come back.
    gone = client.delete(f"/api/clinician/availability/time-off/{out['time_off']['id']}", headers=doc)
    assert gone.status_code == 200 and gone.json()["sync"]["created"] == 17
    assert client.delete(f"/api/clinician/availability/time-off/{out['time_off']['id']}", headers=doc).status_code == 404


def test_seeded_slots_are_never_touched(client):
    """Demo clinicians have seeded hours; running the generator keeps every seeded slot and never overlaps one."""
    before = slots_of(DR_OKAFOR, source="manual")
    assert before
    with db() as conn:
        first = run_job(conn, "availability_slots")
        second = run_job(conn, "availability_slots")
    assert first["status"] == "succeeded" and first["detail"]["created"] > 0
    assert (second["detail"]["created"], second["detail"]["removed"], second["detail"]["updated"]) == (0, 0, 0)
    assert slots_of(DR_OKAFOR, source="manual") == before
    spans = [(s["starts_at"], s["starts_at"] + timedelta(minutes=s["duration_min"])) for s in before]
    for s in slots_of(DR_OKAFOR, source="template"):
        end = s["starts_at"] + timedelta(minutes=s["duration_min"])
        assert not any(s["starts_at"] < e and b < end for b, e in spans)

    mine = client.get("/api/clinician/availability", headers=OKAFOR).json()
    assert len(mine["windows"]) == 5 and {w["weekday"] for w in mine["windows"]} == {0, 1, 2, 3, 4}


def test_job_is_idempotent_and_rolls_the_horizon_forward(client):
    doc, pid = new_clinician(client)
    client.put("/api/clinician/availability", headers=doc,
               json={"timezone": "America/Chicago", "horizon_days": 7, "windows": every_day("09:00", "10:00", 60)})
    count = len(slots_of(pid))
    assert count in (6, 7)                              # a week of 09:00 slots, today's only if still ahead
    now = datetime.now(timezone.utc)
    with db() as conn:
        first = run_job(conn, "availability_slots", now)["detail"]      # also opens the demo clinicians' weeks
        assert len(slots_of(pid)) == count
        again = run_job(conn, "availability_slots", now)["detail"]
        assert (again["created"], again["removed"], again["updated"]) == (0, 0, 0)
        assert again["practitioners"] == first["practitioners"] >= 9
        later = run_job(conn, "availability_slots", now + timedelta(days=3))["detail"]
        assert later["removed"] == 0
        assert run_job(conn, "availability_slots", now + timedelta(days=3))["detail"]["created"] == 0
    # Three more days of 09:00 slots; the ones already in the past are left alone.
    assert len(slots_of(pid)) == count + 3


# --- Daylight saving time --------------------------------------------------------------------------


def test_dst_week_keeps_wall_clock_times(client):
    doc, pid = new_clinician(client)
    windows = every_day("09:00", "10:00", 60, location="Lakeside Clinic")
    windows.append({"weekday": 6, "start": "01:00", "end": "02:00", "slot_minutes": 30, "mode": "video"})
    assert client.put("/api/clinician/availability", headers=doc,
                      json={"timezone": "America/New_York", "windows": windows}).status_code == 200

    # New York falls back on Sunday 1 November 2026.
    now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
    with db() as conn:
        av.sync(conn, pid, now)
        conn.commit()
    got = {s["starts_at"] for s in slots_of(pid) if date(2026, 10, 30) <= s["starts_at"].date() <= date(2026, 11, 3)}
    utc = lambda *a: datetime(*a, tzinfo=timezone.utc)  # noqa: E731
    assert utc(2026, 10, 31, 13) in got           # Sat 09:00 EDT (UTC-4)
    assert utc(2026, 11, 1, 14) in got            # Sun 09:00 EST (UTC-5)
    assert utc(2026, 11, 2, 14) in got            # Mon 09:00 EST
    # 01:00 and 01:30 happen twice that night: one slot each, at the first occurrence (EDT).
    assert {utc(2026, 11, 1, 5), utc(2026, 11, 1, 5, 30)} <= got
    assert utc(2026, 11, 1, 6) not in got and utc(2026, 11, 1, 6, 30) not in got
    for s in slots_of(pid):
        local = s["starts_at"].astimezone(NEW_YORK)
        assert local.time() in (time(9), time(1), time(1, 30))

    # Spring forward (Sunday 14 March 2027): 02:00-02:59 doesn't exist, so no slot there.
    sunday = [{"weekday": 6, "start_time": time(1), "end_time": time(4), "slot_minutes": 30, "mode": "video",
               "location": None, "effective_from": None, "effective_until": None}]
    spring = av.candidates(sunday, [], NEW_YORK, date(2027, 3, 14), 1, datetime(2027, 3, 1, tzinfo=timezone.utc))
    assert [c.starts_at.astimezone(NEW_YORK).strftime("%H:%M") for c in spring] == ["01:00", "01:30", "03:00", "03:30"]
    assert spring[2].starts_at - spring[1].starts_at == timedelta(minutes=30)


# --- Validation ------------------------------------------------------------------------------------


def test_template_validation(client):
    doc, _ = new_clinician(client)

    def put(windows, **extra):
        return client.put("/api/clinician/availability", headers=doc, json={"windows": windows, **extra})

    overlap = put([{"weekday": 0, "start": "09:00", "end": "12:00"}, {"weekday": 0, "start": "11:00", "end": "13:00"}])
    assert overlap.status_code == 422 and "overlaps" in overlap.json()["detail"]["message"]
    assert put([{"weekday": 0, "start": "12:00", "end": "09:00"}]).status_code == 422
    assert put([{"weekday": 0, "start": "09:00", "end": "09:00"}]).status_code == 422
    assert put([{"weekday": 0, "start": "09:00", "end": "09:10", "slot_minutes": 20}]).status_code == 422
    assert put([{"weekday": 0, "start": "09:00", "end": "12:00", "slot_minutes": 4}]).status_code == 422
    assert put([{"weekday": 0, "start": "09:00", "end": "12:00", "slot_minutes": 121}]).status_code == 422
    assert put([{"weekday": 7, "start": "09:00", "end": "12:00"}]).status_code == 422
    assert put([{"weekday": 0, "start": "09:00", "end": "12:00", "mode": "phone"}]).status_code == 422
    assert put([], horizon_days=365).status_code == 422
    assert put([], timezone="Mars/Olympus_Mons").status_code == 422
    assert put([{"weekday": 0, "start": "09:00", "end": "12:00", "effective_from": "2026-12-01",
                 "effective_until": "2026-11-01"}]).status_code == 422
    assert client.get("/api/clinician/availability/preview?days=90", headers=doc).status_code == 422

    # Back-to-back windows, and the same hours in different date ranges, are fine.
    ok = put([{"weekday": 0, "start": "09:00", "end": "12:00"}, {"weekday": 0, "start": "12:00", "end": "13:00"},
              {"weekday": 1, "start": "09:00", "end": "12:00", "effective_until": "2026-12-31"},
              {"weekday": 1, "start": "10:00", "end": "13:00", "effective_from": "2027-01-01"}])
    assert ok.status_code == 200, ok.text
    assert [w["start"] for w in ok.json()["windows"]] == ["09:00", "12:00", "09:00", "10:00"]


# --- Who may do what ------------------------------------------------------------------------------


def test_permissions(client):
    doc, pid = new_clinician(client)
    week = {"windows": every_day("09:00", "11:00", 20)}

    # Patients: no.
    assert client.get("/api/clinician/availability", headers=MAYA).status_code == 403
    assert client.put("/api/clinician/availability", headers=MAYA, json=week).status_code == 403
    assert client.get("/api/clinician/consult-profile", headers=MAYA).status_code == 403
    assert client.get(f"/api/admin/practitioners/{pid}/availability", headers=MAYA).status_code == 403
    # Clinicians manage only their own.
    assert client.get(f"/api/admin/practitioners/{pid}/availability", headers=OKAFOR).status_code == 403
    # Pharmacy staff: no.
    assert client.get("/api/admin/availability/practitioners", headers=PHARMACIST).status_code == 403

    # The front desk can edit any clinician in the organization.
    listing = client.get("/api/admin/availability/practitioners", headers=FRONTDESK).json()
    assert pid in {p["id"] for p in listing} and DR_FERREIRA in {p["id"] for p in listing}
    r = client.put(f"/api/admin/practitioners/{pid}/availability", headers=FRONTDESK, json=week)
    assert r.status_code == 200 and r.json()["sync"]["created"] > 0
    assert client.get("/api/clinician/availability", headers=doc).json()["windows"] == r.json()["windows"]
    off = client.post(f"/api/admin/practitioners/{pid}/availability/time-off", headers=FRONTDESK,
                      json={"starts_on": str(date.today() + timedelta(days=3)), "ends_on": str(date.today() + timedelta(days=4))})
    assert off.status_code == 201
    # ... and the clinician sees it, and can remove it.
    assert client.delete(f"/api/clinician/availability/time-off/{off.json()['time_off']['id']}", headers=doc).status_code == 200
    assert client.get(f"/api/admin/practitioners/{pid}/availability/preview?days=7", headers=ADMIN).status_code == 200
    assert client.patch(f"/api/admin/practitioners/{pid}/consult-profile", headers=ADMIN,
                        json={"fee_cents": 9000}).json()["profile"]["fee_cents"] == 9000

    # A clinician can't remove someone else's time off.
    theirs = client.post(f"/api/admin/practitioners/{DR_FERREIRA}/availability/time-off", headers=ADMIN,
                         json={"starts_on": str(date.today() + timedelta(days=3)), "ends_on": str(date.today() + timedelta(days=3))})
    assert theirs.status_code == 201
    assert client.delete(f"/api/clinician/availability/time-off/{theirs.json()['time_off']['id']}", headers=doc).status_code == 404

    # Another organization's clinician doesn't exist, as far as this organization can tell.
    with db() as conn:
        org = conn.execute("INSERT INTO organizations (name) VALUES ('Elsewhere Health') RETURNING id::text").fetchone()["id"]
        other = conn.execute(
            "INSERT INTO practitioners (organization_id, name, specialty, location_name) "
            "VALUES (%s, 'Dr. Other', 'Cardiology', 'Elsewhere') RETURNING id::text", (org,),
        ).fetchone()["id"]
        conn.commit()
    for path in (f"/api/admin/practitioners/{other}/availability", f"/api/admin/practitioners/{other}/consult-profile",
                 f"/api/admin/practitioners/{uuid4()}/availability", "/api/admin/practitioners/not-a-uuid/availability"):
        assert client.get(path, headers=ADMIN).status_code == 404, path
    assert client.put(f"/api/admin/practitioners/{other}/availability", headers=FRONTDESK, json=week).status_code == 404
    assert other not in {p["id"] for p in client.get("/api/admin/availability/practitioners", headers=ADMIN).json()}


# --- Consult profile -------------------------------------------------------------------------------


def test_consult_profile(client):
    doc, pid = new_clinician(client)
    prof = client.get("/api/clinician/consult-profile", headers=doc).json()
    assert prof["exists"] and prof["profile"]["fee_cents"] == 6000 and prof["profile"]["modes"] == ["message", "video"]
    assert not prof["credential"]["credentialed"] and not prof["listed_in_directory"]
    assert next(c for c in prof["listing_checks"] if c["key"] == "license")["ok"] is False
    assert "verified" in prof["directory_note"]

    r = client.patch("/api/clinician/consult-profile", headers=doc, json={
        "fee_cents": 7500, "modes": ["video", "message", "phone"], "bio": "  Skin health for all ages.  ",
        "years_in_practice": 9, "languages": ["English", "Spanish", "spanish"], "accepting": False,
        "reply_hours": 12, "hours": {"mon": ["09:00", "17:00"], "wed": ["13:00", "18:30"], "fri": None},
        "slot_minutes": 20,
    })
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["profile"]["fee_cents"] == 7500 and p["profile"]["modes"] == ["message", "video", "phone"]
    assert p["profile"]["bio"] == "Skin health for all ages." and p["profile"]["accepting"] is False
    assert p["profile"]["hours"] == {"mon": ["09:00", "17:00"], "wed": ["13:00", "18:30"]}
    assert p["languages"] == ["English", "Spanish"] and p["profile"]["reply_hours"] == 12
    assert client.get("/api/clinician/consult-profile", headers=doc).json()["profile"]["years_in_practice"] == 9

    for bad in ({"modes": ["in_person"]}, {"modes": []}, {"fee_cents": -1}, {"hours": {"mon": ["17:00", "09:00"]}},
                {"hours": {"someday": ["09:00", "10:00"]}}, {"hours": {"mon": ["9am"]}}, {"slot_minutes": 5},
                {"accepting": None}, {"nope": 1}):
        assert client.patch("/api/clinician/consult-profile", headers=doc, json=bad).status_code == 422, bad

    with db() as conn:
        events = conn.execute("SELECT detail FROM audit_events WHERE action = 'consult_profile.updated' AND entity_id = %s",
                              (pid,)).fetchall()
    assert len(events) == 1 and "fee_cents" in events[0]["detail"]["fields"]

    # A verified, accepting clinician is listed in the directory.
    okafor = client.get("/api/clinician/consult-profile", headers=OKAFOR).json()
    assert okafor["credential"]["credentialed"] and okafor["listed_in_directory"]
    listed = client.patch("/api/clinician/consult-profile", headers=OKAFOR, json={"accepting": False}).json()
    assert not listed["listed_in_directory"]
    ids = {c["id"] for c in client.get("/api/consultations/clinicians", headers=MAYA).json()["clinicians"]}
    assert DR_OKAFOR not in ids


@pytest.mark.parametrize("weekday,expected", [(0, 3), (6, 2)])
def test_candidates_respect_effective_dates_and_time_off(weekday, expected):
    monday = date(2026, 10, 5)
    template = [{"weekday": weekday, "start_time": time(9), "end_time": time(10), "slot_minutes": 20, "mode": "in_person",
                 "location": None, "effective_from": monday, "effective_until": monday + timedelta(days=21)}]
    off = [{"starts_on": monday + timedelta(days=7), "ends_on": monday + timedelta(days=13)}]
    got = av.candidates(template, off, CHICAGO, monday - timedelta(days=7), 35, datetime(2026, 9, 1, tzinfo=timezone.utc))
    # Mondays 5, 19 and 26 Oct (12 Oct is time off); Sundays 11 and 25 Oct (18 Oct is time off).
    # Nothing before 5 Oct or after 26 Oct.
    assert len({c.starts_at.astimezone(CHICAGO).date() for c in got}) == expected
    assert len(got) == expected * 3


def test_a_cancelled_slot_can_be_booked_again(client):
    doc, pid = new_clinician(client, "rebook.doc@northside.example")
    client.put("/api/clinician/availability", headers=doc, json={"windows": every_day("09:00", "10:00", 30)})
    slot = client.get(f"/api/practitioners/{pid}/slots", headers=MAYA).json()[0]["id"]
    first = client.post("/api/appointments", headers=MAYA, json={"slot_id": slot})
    assert first.status_code == 201, first.text
    assert client.post(f"/api/appointments/{first.json()['id']}/cancel", headers=MAYA).status_code == 200
    again = client.post("/api/appointments", headers=MAYA, json={"slot_id": slot})
    assert again.status_code == 201, again.text
    # Still only one active booking per slot.
    assert client.post("/api/appointments", headers=MAYA, json={"slot_id": slot}).status_code in (404, 409)
