"""Health companion demo data for Maya Thornton. Idempotent.

Maya has taken amlodipine 5 mg each morning for about two weeks (prescribed by Dr. Lindqvist, her primary care
clinician; the cardiology after-visit summary tells her to "keep taking your other medicines as usual"). Her
dose history is realistic: 13 of 15 doses taken, one skipped while away from home, one not recorded. She
answered "Better" to the check-in three days after starting it, and the check-in about her cardiology visit
is still open. Atorvastatin, started at that visit, gets reminders once she picks it up.
"""

from __future__ import annotations

import json
from datetime import timedelta

from psycopg.types.json import Jsonb

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import DR_LINDQVIST, DR_OKAFOR, P_MAYA, U_MAYA, _id
from bioverse.notify import notify

RX_MAYA_AMLO = _id(12001)
DISP_AMLO_MAYA = _id(12002)
CHECKIN_AMLO = _id(12301)
CHECKIN_VISIT = _id(12302)
PH_RIVERSIDE = _id(5501)

DOSE_DAYS = range(15, 0, -1)            # days ago: 15 .. 1
SKIPPED = {10: "away_from_home"}        # days ago -> reason
NOT_RECORDED = {4}


def run(conn, ctx: SeedContext) -> None:
    at, days = ctx.at, ctx.days
    cur = conn.cursor()
    if cur.execute("SELECT 1 FROM patients WHERE id = %s", (P_MAYA,)).fetchone() is None:
        return

    # A medicine Maya has taken for two weeks, filled and picked up at her usual pharmacy.
    cur.execute(
        """
        INSERT INTO medication_requests (id, patient_id, prescriber_id, drug_code, drug_name, strength, sig, quantity,
                                         refills_authorized, refills_remaining, status, pharmacy_id, authored_at)
        VALUES (%s, %s, %s, 'amlodipine', 'Amlodipine', '5 mg', 'Take 1 tablet by mouth once daily in the morning.',
                30, 2, 2, 'active', %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (RX_MAYA_AMLO, P_MAYA, DR_LINDQVIST, PH_RIVERSIDE, at(days(-16), 9, 50)),
    )
    cur.execute(
        """
        INSERT INTO medication_dispenses (id, medication_request_id, patient_id, pharmacy_id, fill_number, status,
                                          sent_at, ready_at, picked_up_at)
        VALUES (%s, %s, %s, %s, 1, 'picked_up', %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        (DISP_AMLO_MAYA, RX_MAYA_AMLO, P_MAYA, PH_RIVERSIDE, at(days(-16), 9, 52), at(days(-16), 14, 0),
         at(days(-16), 17, 40)),
    )

    cur.execute(
        """
        INSERT INTO companion_settings (patient_id, daily_brief, daily_brief_time, dose_times, updated_by, updated_at)
        VALUES (%s, true, '07:30', %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        (P_MAYA, Jsonb({"morning": "08:00", "evening": "21:00"}), U_MAYA, at(days(-15), 19, 5)),
    )

    # Dose history: one morning dose a day since pickup.
    doses, logs = [], []
    for i, ago in enumerate(DOSE_DAYS):
        if ago in NOT_RECORDED:
            continue
        day = days(-ago)
        scheduled = at(day, 8, 0)
        status = "skipped" if ago in SKIPPED else "taken"
        recorded = scheduled + timedelta(minutes=(7 * ago) % 45 + 3)
        doses.append((_id(12100 + i), P_MAYA, RX_MAYA_AMLO, scheduled, scheduled.replace(tzinfo=None), status,
                      SKIPPED.get(ago), U_MAYA, recorded))
        if status == "taken":
            logs.append((_id(12200 + i), RX_MAYA_AMLO, P_MAYA, day, recorded))
    cur.executemany(
        """
        INSERT INTO medication_doses (id, patient_id, medication_request_id, scheduled_at, scheduled_local, status,
                                      reason, recorded_by, recorded_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        doses,
    )
    # The pharmacy page's daily log mirrors taken doses of a once-a-day medicine.
    cur.executemany(
        """
        INSERT INTO medication_adherence_logs (id, medication_request_id, patient_id, taken_on, logged_at)
        VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        logs,
    )

    # Check-in three days after starting amlodipine: answered "Better".
    cur.execute(
        """
        INSERT INTO companion_checkins (id, patient_id, kind, ref_id, subject, practitioner_id, prompt, produced_by,
                                        status, response, screen_level, due_at, answered_at, created_at)
        VALUES (%s, %s, 'new_medication', %s, 'Amlodipine 5 mg', %s, %s, 'companion/rules', 'answered', 'better',
                'none', %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (CHECKIN_AMLO, P_MAYA, RX_MAYA_AMLO, DR_LINDQVIST,
         "Hi Maya, you started Amlodipine a few days ago. How are you feeling?",
         at(days(-13), 10), at(days(-13), 12, 20), at(days(-13), 10)),
    )
    notify(conn, user_id=U_MAYA, patient_id=P_MAYA, kind="companion", title="How are you feeling today?",
           body="A quick check-in from Bioverse One. It takes a few seconds.",
           link=f"/companion?checkin={CHECKIN_AMLO}", due_at=at(days(-13), 10), dedupe_key=f"checkin:{CHECKIN_AMLO}")
    cur.execute(
        "UPDATE notifications SET status = 'sent', read_at = coalesce(read_at, %s) WHERE user_id = %s AND dedupe_key = %s",
        (at(days(-13), 12, 20), U_MAYA, f"checkin:{CHECKIN_AMLO}"),
    )

    # The day after her cardiology visit: still waiting for an answer.
    enc = cur.execute(
        """
        SELECT id FROM encounters WHERE patient_id = %s AND practitioner_id = %s ORDER BY occurred_at DESC LIMIT 1
        """,
        (P_MAYA, DR_OKAFOR),
    ).fetchone()
    if enc is not None:
        inserted = cur.execute(
            """
            INSERT INTO companion_checkins (id, patient_id, kind, ref_id, subject, practitioner_id, prompt, produced_by,
                                            due_at, created_at)
            VALUES (%s, %s, 'post_visit', %s, 'your visit with Dr. Adaeze Okafor', %s, %s, 'companion/rules', %s, %s)
            ON CONFLICT DO NOTHING RETURNING id
            """,
            (CHECKIN_VISIT, P_MAYA, enc[0], DR_OKAFOR,
             "Hi Maya, how are you feeling after your recent visit with Dr. Adaeze Okafor?",
             at(days(-1), 10), at(days(-1), 10)),
        ).fetchone()
        if inserted:
            notify(conn, user_id=U_MAYA, patient_id=P_MAYA, kind="companion", title="How are you feeling today?",
                   body="A quick check-in from Bioverse One. It takes a few seconds.",
                   link=f"/companion?checkin={CHECKIN_VISIT}", due_at=at(days(-1), 10),
                   dedupe_key=f"checkin:{CHECKIN_VISIT}")

    if cur.execute("SELECT 1 FROM audit_events WHERE action = 'companion_seeded'").fetchone() is None:
        cur.execute(
            """
            INSERT INTO audit_events (actor_role, agent, action, entity_type, patient_id, detail)
            VALUES ('system', 'seed', 'companion_seeded', 'patient', %s, %s)
            """,
            (P_MAYA, json.dumps({"doses": len(doses)})),
        )
