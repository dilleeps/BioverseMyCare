"""Home vitals demo data for Maya Thornton (fictional).

- A connected blood pressure cuff and scale (demo pairing, fictional vendor).
- 30 days of twice-daily home blood pressure with pulse, running slightly high with realistic noise,
  and a daily step count from her phone. Her weekly weigh-ins come from the weight coach seed.
- A home monitoring plan from Dr. Okafor, started at Maya's cardiology visit two days ago: BP twice daily
  for 14 days at 08:00 and 20:00. One reading is missed, so adherence isn't perfect.
- One open sustained-high BP alert in Dr. Okafor's review queue.

Fixed IDs from 9000-9999, ON CONFLICT DO NOTHING, dates relative to ctx.
"""

from __future__ import annotations

import random
from datetime import datetime, time

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import DR_OKAFOR, P_MAYA, U_MAYA, U_OKAFOR, _id
from bioverse.notify import notify
from bioverse.vitals_codes import CODES, interpret

DEV_CUFF, DEV_SCALE = _id(9001), _id(9002)
PLAN_MAYA_BP = _id(9010)
ALERT_MAYA_BP, REVIEW_MAYA_BP = _id(9020), _id(9021)
OBS_BASE, PANEL_BASE = 9100, 9400
DAYS = 30
MISSED = {(-2, "pm")}   # during the plan: one evening reading skipped


def run(conn, ctx: SeedContext) -> None:
    at, days = ctx.at, ctx.days
    cur = conn.cursor()
    cur.executemany(
        """
        INSERT INTO devices (id, patient_id, kind, vendor, model, integration, serial, status, simulated, last_sync,
                             created_at)
        VALUES (%s, %s, %s, %s, %s, 'bluetooth', %s, 'connected', true, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        [
            (DEV_CUFF, P_MAYA, "bp_cuff", "Lumora", "ArmCheck 5 (demo)", "LMR-DEMO-0042",
             at(days(-1), 20, 55), at(days(-DAYS - 1), 18)),
            (DEV_SCALE, P_MAYA, "scale", "Lumora", "Balance Scale (demo)", "LMR-DEMO-0107",
             at(days(-1), 7, 10), at(days(-DAYS - 1), 18, 5)),
        ],
    )

    rng = random.Random(110)
    now = datetime.now(ctx.tz)
    obs = []
    bp_readings = []   # before today: the alert below is built from these

    # Each value has a fixed slot number (8 per day), so a reseed later in the day only adds what's new.
    def add(n, code_key, value, when, source, device=None, device_id=None, panel=None):
        if when > now:
            return
        c = CODES[code_key]
        obs.append((_id(OBS_BASE + n), P_MAYA, c.loinc, c.display, value, c.unit, c.low, c.high,
                    interpret(c, value), when, c.category, source, device, device_id, panel))

    cuff = "Lumora ArmCheck 5 (demo)"
    for i, d in enumerate(range(-DAYS, 1)):
        day = days(d)
        drift = min(1.0, i / (DAYS - 1))                 # 0 -> 1 over the month: a slow upward drift
        for s, (slot, (hh, mm)) in enumerate((("am", (7, 20 + rng.randint(0, 39))), ("pm", (20, rng.randint(0, 50))))):
            skip = (d, slot) in MISSED or (d < -2 and rng.random() < 0.08)
            morning = 3 if slot == "am" else 0
            sys_ = round(min(168, 128 + 9 * drift + morning + rng.gauss(0, 5)))
            dia = round(min(104, 79 + 6 * drift + morning / 2 + rng.gauss(0, 3.5)))
            pulse = round(70 + rng.gauss(0, 4))
            if d == 0 or (d, slot) == (-1, "pm"):
                # The latest readings sit in range. Shared record views (timeline.abnormal_trends) don't yet
                # filter on category, so an out-of-range latest home BP would crowd out lab trends there.
                sys_, dia = 124 + (sys_ % 4), 76 + (dia % 3)
            if skip:
                continue
            when = at(day, hh, mm)
            panel = _id(PANEL_BASE + 2 * i + s)
            base = 8 * i + 3 * s
            add(base, "bp_systolic", sys_, when, "device", cuff, DEV_CUFF, panel)
            add(base + 1, "bp_diastolic", dia, when, "device", cuff, DEV_CUFF, panel)
            add(base + 2, "heart_rate", pulse, when, "device", cuff, DEV_CUFF, panel)
            if d < 0:
                bp_readings.append((when, sys_, dia))
        steps = 3500 + rng.randint(0, 6000)
        if d < 0:
            add(8 * i + 7, "steps", steps, at(day, 23, 30), "import", "Apple Health")

    cur.executemany(
        """
        INSERT INTO observations (id, patient_id, loinc_code, display, value, unit, ref_low, ref_high, interpretation,
                                  effective_at, category, source, device, device_id, panel_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        obs,
    )

    cur.execute(
        """
        INSERT INTO vital_monitoring_plans (id, patient_id, practitioner_id, measure, times, start_on, end_on,
                                            instructions, created_at)
        VALUES (%s, %s, %s, 'bp', %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (PLAN_MAYA_BP, P_MAYA, DR_OKAFOR, [time(8), time(20)], days(-2), days(11),
         "Sit quietly for 5 minutes first, arm supported at heart level. Take two readings a minute apart and "
         "log the second.", at(days(-2), 9, 45)),
    )

    # The last five readings: an open sustained-high alert for Dr. Okafor.
    last5 = bp_readings[-5:]
    high = [r for r in last5 if interpret(CODES["bp_systolic"], r[1]) != "N" or interpret(CODES["bp_diastolic"], r[2]) != "N"]
    avg = f"{round(sum(r[1] for r in last5) / 5)}/{round(sum(r[2] for r in last5) / 5)}"
    title = f"Blood pressure high on {len(high)} of the last 5 readings"
    detail = (f"{len(high)} of the last 5 home blood pressure readings (7 days) were high: "
              f"{', '.join(f'{s}/{d}' for _, s, d in high)} mmHg. Average of those 5: {avg} mmHg.")
    created = last5[-1][0].replace(minute=min(59, last5[-1][0].minute + 1))
    cur.execute(
        """
        INSERT INTO review_items (id, kind, patient_id, practitioner_id, ref_id, title, body, priority, link, created_at)
        VALUES (%s, 'vital_alert', %s, %s, %s, %s, %s, 'routine', %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (REVIEW_MAYA_BP, P_MAYA, DR_OKAFOR, ALERT_MAYA_BP, f"Home vitals · {title}", detail,
         f"/clinician/vitals/{P_MAYA}", created),
    )
    cur.execute(
        """
        INSERT INTO vital_alerts (id, patient_id, measure, kind, severity, title, detail, observation_id, reading_count,
                                  last_reading_at, practitioner_id, review_item_id, created_at)
        VALUES (%s, %s, 'bp', 'sustained_high', 'warning', %s, %s, NULL, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (ALERT_MAYA_BP, P_MAYA, title, detail, 1, last5[-1][0], DR_OKAFOR, REVIEW_MAYA_BP, created),
    )
    notify(conn, user_id=U_OKAFOR, kind="vital_alert", title="Home vitals alert for a patient",
           body=f"Maya Thornton: {title}", link=f"/clinician/vitals/{P_MAYA}", patient_id=P_MAYA,
           due_at=created, dedupe_key=f"vitals:alert:{ALERT_MAYA_BP}", created_by="vitals-rules")
    notify(conn, user_id=U_MAYA, kind="vital_alert", title="Your care team is reviewing your readings",
           body="Several of your recent readings were outside your range. Your care team has been told and will "
                "contact you if anything needs to change. Keep measuring as planned.",
           link="/vitals", patient_id=P_MAYA, due_at=created, dedupe_key=f"vitals:alert:{ALERT_MAYA_BP}",
           created_by="vitals-rules")
