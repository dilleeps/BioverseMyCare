"""Companion dose-time derivation: directions to parts of the day, preferred times, time zones and DST."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from bioverse import companion
from bioverse.companion import Med, parse_frequency

NY = ZoneInfo("America/New_York")
LA = ZoneInfo("America/Los_Angeles")
UTC = timezone.utc
DEFAULTS = companion.DEFAULT_SETTINGS


def med(sig: str, start: datetime, rx: str = "rx1") -> Med:
    return Med(id=rx, patient_id="p", drug_code="x", drug_name="Testamine", strength="5 mg", sig=sig, status="active",
               prescriber_id="pr", authored_at=start, start=start, freq=parse_frequency(sig))


def day_doses(m: Med, tz, d: date, settings=DEFAULTS):
    return companion.doses_on(m, settings, tz, d)


@pytest.mark.parametrize("sig,slots,per_day", [
    ("Take 1 tablet by mouth once daily in the evening.", ("evening",), 1),
    ("Take 1 tablet by mouth once daily.", ("morning",), 1),
    ("Take 1 tablet by mouth once daily in the morning.", ("morning",), 1),
    ("Take one capsule twice daily", ("morning", "evening"), 2),
    ("1 tab PO BID", ("morning", "evening"), 2),
    ("Take 1 tablet every 12 hours", ("morning", "evening"), 2),
    ("Take three times a day with meals", ("morning", "midday", "evening"), 3),
    ("Take 1 tablet four times daily", ("morning", "midday", "evening", "bedtime"), 4),
    ("Take 1 tablet at bedtime", ("bedtime",), 1),
    ("Take 1 tablet nightly", ("bedtime",), 1),
    ("Take once daily with dinner", ("evening",), 1),
])
def test_frequency_to_parts_of_day(sig, slots, per_day):
    f = parse_frequency(sig)
    assert (f.slots, f.per_day, f.as_needed, f.understood) == (slots, per_day, False, True)


def test_frequency_special_cases():
    prn = parse_frequency("Take 1 tablet every 6 hours as needed for pain")
    assert prn.as_needed and prn.slots == () and companion.dose_times(prn, DEFAULTS, "rx") == []
    weekly = parse_frequency("Take 1 tablet once a week")
    assert weekly.weekly and weekly.slots == ("morning",)
    course = parse_frequency("Take 2 tablets on day 1, then 1 tablet daily for 4 days.")
    assert course.course_days == 5 and course.per_day == 1
    unknown = parse_frequency("Use as directed")
    assert not unknown.understood and companion.dose_times(unknown, DEFAULTS, "rx") == []


def test_default_times_and_patient_overrides():
    f = parse_frequency("twice daily")
    assert companion.dose_times(f, DEFAULTS, "rx1") == [time(8), time(20)]
    prefs = {**DEFAULTS, "dose_times": {"evening": "21:30"}}
    assert companion.dose_times(f, prefs, "rx1") == [time(8), time(21, 30)]
    per_med = {**prefs, "medication_times": {"rx1": ["07:15", "19:00", "07:15"]}}
    assert companion.dose_times(f, per_med, "rx1") == [time(7, 15), time(19)]
    assert companion.dose_times(f, per_med, "other") == [time(8), time(21, 30)]
    with pytest.raises(ValueError):
        companion.parse_hhmm("25:00")


def test_doses_follow_the_patients_time_zone():
    start = datetime(2026, 9, 1, 12, tzinfo=UTC)
    m = med("once daily in the evening", start)
    ny = day_doses(m, NY, date(2026, 9, 24))
    la = day_doses(m, LA, date(2026, 9, 24))
    assert [d.local for d in ny] == [datetime(2026, 9, 24, 20, 0)] == [d.local for d in la]
    assert ny[0].at == datetime(2026, 9, 25, 0, 0, tzinfo=UTC)          # EDT, UTC-4
    assert la[0].at == datetime(2026, 9, 25, 3, 0, tzinfo=UTC)          # PDT, UTC-7
    assert ny[0].key == "med:rx1:2026-09-24T20:00"


def test_spring_forward_keeps_the_wall_clock_time():
    m = med("once daily in the evening", datetime(2026, 3, 1, tzinfo=UTC))
    before = day_doses(m, NY, date(2026, 3, 7))[0]
    on = day_doses(m, NY, date(2026, 3, 8))[0]      # clocks go forward at 02:00 on 8 March 2026
    assert before.at == datetime(2026, 3, 8, 1, 0, tzinfo=UTC)          # 20:00 EST
    assert on.at == datetime(2026, 3, 9, 0, 0, tzinfo=UTC)              # 20:00 EDT: 23 hours later
    assert (on.at - before.at) == timedelta(hours=23)
    # A dose time that doesn't exist that night (02:30) happens at the same instant as 03:30 EDT.
    night = {**DEFAULTS, "medication_times": {"rx1": ["02:30"]}}
    skipped_hour = day_doses(m, NY, date(2026, 3, 8), night)
    assert len(skipped_hour) == 1
    assert skipped_hour[0].at == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
    assert skipped_hour[0].at.astimezone(NY).time() == time(3, 30)


def test_fall_back_gives_one_dose_not_two():
    m = med("once daily", datetime(2026, 10, 1, tzinfo=UTC))
    night = {**DEFAULTS, "medication_times": {"rx1": ["01:30"]}}   # 01:30 happens twice on 1 Nov 2026
    doses = day_doses(m, NY, date(2026, 11, 1), night)
    assert len(doses) == 1 and doses[0].at == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)   # the first (EDT) 01:30
    week = companion.scheduled_doses(m, DEFAULTS, NY, datetime(2026, 10, 29, tzinfo=UTC), datetime(2026, 11, 4, tzinfo=UTC))
    assert [d.local.time() for d in week] == [time(8)] * len(week)
    assert len({d.local.date() for d in week}) == len(week) == 6


def test_start_course_and_weekly_limits():
    start = datetime(2026, 9, 10, 21, 0, tzinfo=UTC)            # 17:00 in New York
    m = med("twice daily", start)
    first = day_doses(m, NY, date(2026, 9, 10))
    assert [d.local.time() for d in first] == [time(20)]         # the 08:00 dose was before pickup
    course = med("Take 2 tablets on day 1, then 1 tablet daily for 4 days.", datetime(2026, 9, 1, 11, tzinfo=UTC))
    days = companion.scheduled_doses(course, DEFAULTS, NY, datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 20, tzinfo=UTC))
    assert [d.local.date().day for d in days] == [1, 2, 3, 4, 5]
    weekly = med("once weekly", datetime(2026, 9, 2, 11, tzinfo=UTC))   # a Wednesday
    w = companion.scheduled_doses(weekly, DEFAULTS, NY, datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 30, tzinfo=UTC))
    assert {d.local.weekday() for d in w} == {2} and len(w) == 4
    waiting = Med(id="rx", patient_id="p", drug_code="x", drug_name="X", strength="", sig="daily", status="active",
                  prescriber_id="pr", authored_at=start, start=None, freq=parse_frequency("daily"))
    assert day_doses(waiting, NY, date(2026, 9, 11)) == []


def test_reminder_titles_are_generic():
    assert companion.reminder_title(time(8)) == "Time for your morning medicine"
    assert companion.reminder_title(time(13)) == "Time for your afternoon medicine"
    assert companion.reminder_title(time(20)) == "Time for your evening medicine"
    assert companion.reminder_title(time(22)) == "Time for your bedtime medicine"
    assert "medicine" in companion.REMINDER_BODY and "Testamine" not in companion.REMINDER_BODY


def test_checkin_wording_guard():
    facts = {"first_name": "Maya", "medicine": "Atorvastatin"}
    assert companion.wording_is_safe("Hi Maya, how are things going since you started Atorvastatin?", facts)
    assert not companion.wording_is_safe("Hi Maya, you should take it with food. How are you?", facts)
    assert not companion.wording_is_safe("Hi Maya, any side effects from your 20 mg dose?", facts)
    assert not companion.wording_is_safe("Hi Maya, hope you're well.", facts)          # doesn't ask
    assert companion.template_prompt("new_medication", facts).startswith("Hi Maya, you started Atorvastatin")
