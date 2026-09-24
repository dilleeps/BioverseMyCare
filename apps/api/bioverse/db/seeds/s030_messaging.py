"""Messaging and Doctor Agent demo data (IDs 3000-3999). Idempotent: fixed IDs and ON CONFLICT DO NOTHING.

- Approved education content library (statin muscle aches, amlodipine dizziness, when to call).
- Maya <-> Dr. Okafor thread with a short history, and her statin check-in thread. The day-1 check-in was sent
  yesterday; the day-7 check-in is set due today for the demo (the core story started the statin two days ago),
  so it is sent when Maya opens her messages or Dr. Okafor opens the inbox.
- Rana Haddad's "Is dizziness normal with the new tablet?" thread, linked to the core agent_escalation review item.
- Rana's upcoming visit with Dr. Okafor and a pre-visit interview in progress (one answer given).
- Jun Park's logistics thread for the front desk.
- The front desk user joins the demo identity switcher.
"""

from __future__ import annotations

import json

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import (
    DR_OKAFOR, ORG, P_HADDAD, P_MAYA, P_PARK, U_FRONTDESK, U_HADDAD, U_MAYA, U_OKAFOR, U_PARK, _id,
)

EDU_STATIN, EDU_AMLODIPINE, EDU_WHEN_TO_CALL = _id(3001), _id(3002), _id(3003)
T_MAYA, T_MAYA_FOLLOWUP, T_RANA, T_RANA_PREVISIT, T_JUN = _id(3100), _id(3110), _id(3130), _id(3140), _id(3160)
APPT_RANA = _id(3300)

AGENT_LABEL = "Dr. Okafor's assistant (automated)"
AGENT = "doctor-agent/rules"


def _thread(conn, tid, patient_id, subject, *, kind="care_team", category=None, priority="routine", assigned_to="clinician",
            awaiting_since=None, agent_state=None, appointment_id=None, care_plan_id=None, created_at=None,
            practitioner_id=DR_OKAFOR):
    conn.execute(
        """
        INSERT INTO communication_threads (id, patient_id, organization_id, subject, kind, practitioner_id, appointment_id,
                                           care_plan_id, category, priority, assigned_to, awaiting_since, agent_state,
                                           created_at, last_message_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (tid, patient_id, ORG, subject, kind, practitioner_id, appointment_id, care_plan_id, category, priority,
         assigned_to, awaiting_since, json.dumps(agent_state or {}), created_at, created_at),
    )


def _participants(conn, tid, members):
    for user_id, role in members:
        conn.execute(
            """
            INSERT INTO communication_participants (thread_id, user_id, role) VALUES (%s, %s, %s)
            ON CONFLICT (thread_id, user_id) DO NOTHING
            """,
            (tid, user_id, role),
        )


def _messages(conn, tid, patient_id, rows, *, read_by=()):
    """rows: (n, at, author_kind, author_user_id, author_label, body, payload, category)."""
    for n, at, kind, uid, label, body, payload, category in rows:
        conn.execute(
            """
            INSERT INTO communications (id, thread_id, patient_id, author_user_id, author_kind, author_label, body, payload,
                                        category, priority, produced_by, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (_id(n), tid, patient_id, uid, kind, label, body, json.dumps(payload) if payload else None, category,
             "routine" if category else None, AGENT if kind == "agent" else None, at),
        )
    last = rows[-1][1]
    conn.execute("UPDATE communication_threads SET last_message_at = greatest(last_message_at, %s) WHERE id = %s", (last, tid))
    for user_id in read_by:
        conn.execute(
            """
            UPDATE communication_participants
            SET last_read_seq = greatest(last_read_seq, (SELECT max(seq) FROM communications WHERE thread_id = %s)),
                last_read_at = coalesce(last_read_at, %s)
            WHERE thread_id = %s AND user_id = %s
            """,
            (tid, last, tid, user_id),
        )


def run(conn, ctx: SeedContext) -> None:
    at, days = ctx.at, ctx.days

    conn.execute("UPDATE users SET demo_label = 'Front desk', demo_order = 40 WHERE id = %s", (U_FRONTDESK,))

    # Approved education content -----------------------------------------------------------------
    content = [
        (EDU_STATIN, "side_effect", "Statins and muscle aches",
         "Mild muscle aches can happen in the first weeks of taking a statin such as atorvastatin, and they often "
         "settle on their own. Keep taking your tablet unless your care team tells you otherwise. Let us know if the "
         "aches are severe, keep getting worse, or come with weakness, or if your urine turns dark brown: that needs "
         "a same-day call to the clinic.",
         ["atorvastatin", "simvastatin", "rosuvastatin", "pravastatin", "statin"], ["muscle", "ache", "aching", "cramp", "sore"]),
        (EDU_AMLODIPINE, "side_effect", "Amlodipine and dizziness",
         "Feeling a little dizzy or light-headed, especially when standing up quickly, can happen in the first weeks "
         "of taking amlodipine. Stand up slowly, sit down if you feel dizzy, and drink enough fluids. Keep taking "
         "your tablet unless your care team tells you otherwise. Tell us if the dizziness does not improve, or if "
         "you faint or fall.",
         ["amlodipine"], ["dizz", "light-headed", "lightheaded", "unsteady"]),
        (EDU_WHEN_TO_CALL, "general", "When to call",
         "Call 911 straight away for chest pain that spreads or comes with breathlessness or sweating, trouble "
         "breathing, fainting, or signs of a stroke such as a drooping face or slurred speech. For anything that is "
         "worrying you but is not an emergency, message us here or call the clinic.",
         [], []),
    ]
    for cid, topic, title, body, meds, symptoms in content:
        conn.execute(
            """
            INSERT INTO education_content (id, organization_id, topic, title, body, medications, symptoms, approved_by, approved_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING
            """,
            (cid, ORG, topic, title, body, meds, symptoms, U_OKAFOR, at(days(-30), 9)),
        )

    # Maya <-> Dr. Okafor -------------------------------------------------------------------------
    _thread(conn, T_MAYA, P_MAYA, "Morning or evening for atorvastatin?", category="medication_question",
            created_at=at(days(-2), 18, 5))
    _participants(conn, T_MAYA, [(U_MAYA, "patient"), (U_OKAFOR, "clinician")])
    _messages(conn, T_MAYA, P_MAYA, [
        (3101, at(days(-2), 18, 5), "patient", U_MAYA, "Maya Thornton",
         "Hi Dr. Okafor, should I take the atorvastatin in the morning or the evening?", None, "medication_question"),
        (3102, at(days(-2), 18, 5), "agent", None, AGENT_LABEL,
         "I've passed your message to Dr. Okafor. You'll get a reply here from the care team. If things get worse "
         "or you feel unsafe, call 911.", {"kind": "handoff", "to": "clinician"}, None),
        (3103, at(days(-1), 8, 40), "clinician", U_OKAFOR, "Dr. Adaeze Okafor",
         "Hi Maya, the evening is best, as on your care plan. If you miss a dose, take the next one at the usual "
         "time; don't double up.\n\nDr. Okafor", None, None),
        (3104, at(days(-1), 9, 2), "patient", U_MAYA, "Maya Thornton", "Thank you, that's clear.", None, "other"),
    ], read_by=(U_MAYA, U_OKAFOR))

    # Maya's statin check-ins ---------------------------------------------------------------------
    task = conn.execute(
        """
        SELECT t.id::text AS task_id, c.id::text AS plan_id FROM care_plan_tasks t JOIN care_plans c ON c.id = t.care_plan_id
        WHERE c.patient_id = %s AND c.practitioner_id = %s AND t.kind = 'medication' ORDER BY t.position LIMIT 1
        """,
        (P_MAYA, DR_OKAFOR),
    ).fetchone()
    if task:
        task_id, plan_id = task  # seed connections return tuples
        _thread(conn, T_MAYA_FOLLOWUP, P_MAYA, "Check-ins: atorvastatin 20 mg", kind="followup",
                care_plan_id=plan_id, created_at=at(days(-1), 9))
        _participants(conn, T_MAYA_FOLLOWUP, [(U_MAYA, "patient"), (U_OKAFOR, "clinician")])
        _messages(conn, T_MAYA_FOLLOWUP, P_MAYA, [
            (3111, at(days(-1), 9), "agent", None, AGENT_LABEL,
             "Hi Maya, this is your day 1 check-in from Dr. Okafor's care team. Have you taken your first dose of "
             "atorvastatin 20 mg? Just reply here to let us know.", {"kind": "checkin", "day": 1}, None),
            (3112, at(days(-1), 20, 15), "patient", U_MAYA, "Maya Thornton",
             "Yes, I took the first one this evening. All fine so far.", None, "medication_question"),
        ], read_by=(U_MAYA, U_OKAFOR))
        steps = [
            (3120, 1, "Confirm first dose taken", days(-1), "sent", _id(3111)),
            # Set due today for the demo, so the day-7 statin check-in is sent on the next visit to messages.
            (3121, 7, "Side effects check: muscle pain, fatigue", days(0), "scheduled", None),
            (3122, 30, "Adherence check and prompt lipid recheck booking", days(28), "scheduled", None),
        ]
        for rid, day, action, due, status, comm in steps:
            conn.execute(
                """
                INSERT INTO communication_requests (id, patient_id, practitioner_id, care_plan_id, task_id, step_day, action,
                                                    due_on, status, communication_id, sent_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (_id(rid), P_MAYA, DR_OKAFOR, plan_id, task_id, day, action, due, status, comm,
                 at(days(-1), 9) if status == "sent" else None),
            )

    # Rana: the side-effect question behind the core agent_escalation review item ----------------
    _thread(conn, T_RANA, P_HADDAD, "Is dizziness normal with the new tablet?", category="side_effect",
            awaiting_since=at(days(0), 6, 40), created_at=at(days(0), 6, 40))
    _participants(conn, T_RANA, [(U_HADDAD, "patient"), (U_OKAFOR, "clinician")])
    _messages(conn, T_RANA, P_HADDAD, [
        (3131, at(days(0), 6, 40), "patient", U_HADDAD, "Rana Haddad", "Is dizziness normal with the new tablet?", None, "side_effect"),
        (3132, at(days(0), 6, 40), "agent", None, AGENT_LABEL,
         "Thanks for letting us know. When did this start, and is it getting better, worse, or staying the same?",
         {"kind": "clarifying_question", "n": 1}, None),
        (3133, at(days(0), 6, 50), "patient", U_HADDAD, "Rana Haddad",
         "Since I started the amlodipine 5 mg eight days ago. Mostly when I stand up. I haven't fallen and there's "
         "no chest pain.", None, "side_effect"),
        (3134, at(days(0), 6, 55), "agent", None, AGENT_LABEL,
         "I've passed your message to Dr. Okafor. You'll get a reply here from the care team. If things get worse "
         "or you feel unsafe, call 911.", {"kind": "handoff", "to": "clinician"}, None),
    ], read_by=(U_HADDAD,))
    conn.execute(
        """
        UPDATE review_items SET link = %s, ref_id = %s
        WHERE kind = 'agent_escalation' AND patient_id = %s AND practitioner_id = %s AND link IS NULL
          AND title = 'Doctor Agent escalation · side effect'
        """,
        (f"/clinician/inbox?thread={T_RANA}", T_RANA, P_HADDAD, DR_OKAFOR),
    )

    # Rana's upcoming visit and a pre-visit interview in progress ---------------------------------
    if conn.execute("SELECT 1 FROM appointments WHERE id = %s", (APPT_RANA,)).fetchone() is None:
        slot = conn.execute(
            """
            SELECT id FROM slots WHERE practitioner_id = %s AND status = 'free' AND starts_at > now() + interval '1 day'
            ORDER BY starts_at LIMIT 1
            """,
            (DR_OKAFOR,),
        ).fetchone()
        if slot:
            conn.execute("UPDATE slots SET status = 'booked' WHERE id = %s", (slot[0],))
            conn.execute(
                """
                INSERT INTO appointments (id, patient_id, practitioner_id, slot_id, reason, created_at)
                VALUES (%s, %s, %s, %s, 'Blood pressure follow-up', %s)
                """,
                (APPT_RANA, P_HADDAD, DR_OKAFOR, slot[0], at(days(-8), 10)),
            )
    if conn.execute("SELECT 1 FROM appointments WHERE id = %s", (APPT_RANA,)).fetchone():
        questions = conn.execute(
            "SELECT previsit_questions FROM doctor_agent_configs WHERE practitioner_id = %s", (DR_OKAFOR,)
        ).fetchone()[0]
        enabled = [{"id": q["id"], "text": q["text"]} for q in questions if q["enabled"]]
        if len(enabled) >= 2:
            state = {"previsit": {"status": "in_progress", "index": 1, "questions": enabled}}
            _thread(conn, T_RANA_PREVISIT, P_HADDAD, "Before your visit with Dr. Okafor", kind="previsit",
                    appointment_id=APPT_RANA, agent_state=state, created_at=at(days(0), 7, 10))
            _participants(conn, T_RANA_PREVISIT, [(U_HADDAD, "patient"), (U_OKAFOR, "clinician")])
            answer = "No chest pain. I do get dizzy when I stand up since the new tablet."
            _messages(conn, T_RANA_PREVISIT, P_HADDAD, [
                (3141, at(days(0), 7, 10), "agent", None, AGENT_LABEL,
                 f"Hi Rana, Dr. Okafor has {len(enabled)} short questions before your visit. Your answers go to "
                 "Dr. Okafor ahead of the visit. Answer in your own words; there are no wrong answers.",
                 {"kind": "previsit_intro"}, None),
                (3142, at(days(0), 7, 10), "agent", None, AGENT_LABEL, enabled[0]["text"],
                 {"kind": "previsit_question", "question_id": enabled[0]["id"], "n": 1, "of": len(enabled)}, None),
                (3143, at(days(0), 7, 22), "patient", U_HADDAD, "Rana Haddad", answer, None, None),
                (3144, at(days(0), 7, 22), "agent", None, AGENT_LABEL, enabled[1]["text"],
                 {"kind": "previsit_question", "question_id": enabled[1]["id"], "n": 2, "of": len(enabled)}, None),
            ], read_by=(U_HADDAD,))
            conn.execute(
                """
                INSERT INTO questionnaire_responses (id, patient_id, practitioner_id, appointment_id, thread_id, question_id,
                                                     question_text, answer_text, communication_id, mentions_symptoms,
                                                     screen_level, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true, 'none', %s) ON CONFLICT DO NOTHING
                """,
                (_id(3150), P_HADDAD, DR_OKAFOR, APPT_RANA, T_RANA_PREVISIT, enabled[0]["id"], enabled[0]["text"],
                 answer, _id(3143), at(days(0), 7, 22)),
            )

    # Jun: a logistics question for the front desk ----------------------------------------------------
    _thread(conn, T_JUN, P_PARK, "Letter for my employer", category="logistics", assigned_to="front_desk",
            awaiting_since=at(days(0), 8, 5), created_at=at(days(0), 8, 5))
    _participants(conn, T_JUN, [(U_PARK, "patient"), (U_OKAFOR, "clinician"), (U_FRONTDESK, "staff")])
    _messages(conn, T_JUN, P_PARK, [
        (3161, at(days(0), 8, 5), "patient", U_PARK, "Jun Park",
         "Hi, I need a letter confirming my blood test appointment yesterday for my employer. Who can help with that?",
         None, "logistics"),
        (3162, at(days(0), 8, 5), "agent", None, AGENT_LABEL,
         "I've passed your message to the front desk team. They'll reply here, usually within one working day.",
         {"kind": "handoff", "to": "front_desk"}, None),
    ], read_by=(U_PARK,))
