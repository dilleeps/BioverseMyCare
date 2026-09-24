"""Doctor Agent runtime (module 8) and the patient-message pipeline for secure messaging (module 12).

Every patient message in a thread runs through `handle_patient_message`, in this order:

    1. Store the message.
    2. Deterministic red-flag screen (safety/red_flags.py). An emergency or crisis stops everything:
       emergency guidance in the thread, the thread is flagged, and an urgent `red_flag` review item goes to
       the care-team clinician. This runs whether or not AI or the Doctor Agent is on.
    3. A pre-visit interview answer is stored as a structured response and the next question is asked.
    4. Triage (agents/message_triage.py): category + priority, rules always, Claude when allowed.
    5. If the addressed clinician's Doctor Agent is active, apply their escalation rules. Otherwise route by
       category (logistics and billing to the front desk, everything else to the clinician).

The Doctor Agent never exceeds its configuration and never writes clinical content of its own: it asks
information-gathering questions, shares approved education content verbatim, hands off, and escalates.
Anything clinical beyond approved content waits for the clinician (a draft plus a review item).

Every automated message is labelled "<Dr. Name>'s assistant (automated)" and audited with the agent name and
model. Follow-up check-ins and pre-visit interviews live here too.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from psycopg import Connection
from psycopg.types.json import Jsonb

from bioverse import audit, consent
from bioverse.agents import message_triage
from bioverse.agents.message_triage import CATEGORY_LABELS, CLINICAL, NON_CLINICAL, TriageOutcome
from bioverse.auth import User
from bioverse.db.seeds.context import SeedContext
from bioverse.safety import red_flags

AGENT = "doctor-agent/rules"
SAFETY_LABEL = "Bioverse safety (automated)"
NOTICE_LABEL = "Bioverse (automated)"
MAX_CLARIFYING_QUESTIONS = 2

CLARIFYING_QUESTIONS = [
    "Thanks for letting us know. When did this start, and is it getting better, worse, or staying the same?",
    "How much is it affecting your day, from 0 (not at all) to 10 (the worst)? Is anything making it better or worse?",
]

CLINICIAN_ROUTES = {"clinician", "clinician_same_day", "clinician_and_team_now"}
STAFF_ROUTES = {"nurse_triage", "staff_if_unresolved"}


def today() -> date:
    """The clinic's today, matching the seed's dates."""
    return SeedContext().today


def short_name(name: str | None) -> str:
    if not name:
        return "your care team"
    if name.startswith("Dr"):
        return f"Dr. {name.split()[-1]}"
    return name


def agent_label(practitioner_name: str | None) -> str:
    return f"{short_name(practitioner_name)}'s assistant (automated)"


def link_for(thread_id: str) -> str:
    return f"/clinician/inbox?thread={thread_id}"


# ---------------------------------------------------------------------------------------------
# Thread store
# ---------------------------------------------------------------------------------------------

THREAD_COLUMNS = """
    t.id::text, t.patient_id::text, t.organization_id::text, t.subject, t.kind, t.practitioner_id::text,
    pr.name AS practitioner_name, pr.user_id::text AS practitioner_user_id,
    t.appointment_id::text, t.care_plan_id::text, t.category, t.priority, t.triage_reason, t.flagged, t.flag_reason,
    t.flag_acknowledged_at, t.assigned_to, t.status, t.awaiting_since, t.agent_state, t.created_at, t.last_message_at,
    p.name AS patient_name, p.user_id::text AS patient_user_id
"""


def load_thread(conn: Connection, thread_id: str, *, for_update: bool = False) -> dict | None:
    if for_update:
        conn.execute("SELECT 1 FROM communication_threads WHERE id = %s FOR UPDATE", (thread_id,))
    return conn.execute(
        f"""
        SELECT {THREAD_COLUMNS}
        FROM communication_threads t
        JOIN patients p ON p.id = t.patient_id
        LEFT JOIN practitioners pr ON pr.id = t.practitioner_id
        WHERE t.id = %s
        """,
        (thread_id,),
    ).fetchone()


def add_participant(conn: Connection, thread_id: str, user_id: str | None, role: str) -> None:
    if not user_id:
        return
    conn.execute(
        """
        INSERT INTO communication_participants (thread_id, user_id, role) VALUES (%s, %s, %s)
        ON CONFLICT (thread_id, user_id) DO NOTHING
        """,
        (thread_id, user_id, role),
    )


def add_message(
    conn: Connection,
    thread: dict,
    *,
    author_kind: str,
    author_label: str,
    body: str,
    actor: User | None,
    author_user_id: str | None = None,
    payload: dict | None = None,
    produced_by: str | None = None,
    model: str | None = None,
) -> dict:
    row = conn.execute(
        """
        INSERT INTO communications (thread_id, patient_id, author_user_id, author_kind, author_label, body, payload,
                                    produced_by, model)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id::text, seq, author_kind, author_label, author_user_id::text, body, payload, category, priority,
                  triage_reason, produced_by, model, created_at
        """,
        (thread["id"], thread["patient_id"], author_user_id, author_kind, author_label, body,
         Jsonb(payload) if payload is not None else None, produced_by, model),
    ).fetchone()
    conn.execute("UPDATE communication_threads SET last_message_at = now() WHERE id = %s", (thread["id"],))
    if author_user_id:
        # Writing a message means you have read everything up to it.
        conn.execute(
            """
            UPDATE communication_participants SET last_read_seq = greatest(last_read_seq, %s), last_read_at = now()
            WHERE thread_id = %s AND user_id = %s
            """,
            (row["seq"], thread["id"], author_user_id),
        )
    audit.record(
        conn,
        action=f"message_{author_kind}",
        entity_type="communication",
        entity_id=row["id"],
        actor=actor,
        agent=produced_by if author_kind in ("agent", "system") else None,
        model=model,
        patient_id=thread["patient_id"],
        detail={"thread_id": thread["id"], "kind": (payload or {}).get("kind")},
    )
    return row


def care_team_practitioner(conn: Connection, patient_id: str, organization_id: str) -> str | None:
    """Practitioner of the patient's active care plan; else their most recent clinician with an account;
    else primary care with an account; else any clinician with an account in the organization."""
    row = conn.execute(
        """
        SELECT practitioner_id::text AS id FROM care_plans
        WHERE patient_id = %s AND status = 'active' ORDER BY started_at DESC LIMIT 1
        """,
        (patient_id,),
    ).fetchone()
    if row:
        return row["id"]
    row = conn.execute(
        """
        SELECT pr.id::text FROM (
            SELECT practitioner_id, created_at AS at FROM appointments WHERE patient_id = %(p)s AND status = 'booked'
            UNION ALL
            SELECT practitioner_id, occurred_at FROM encounters WHERE patient_id = %(p)s AND practitioner_id IS NOT NULL
        ) x JOIN practitioners pr ON pr.id = x.practitioner_id
        WHERE pr.user_id IS NOT NULL
        ORDER BY x.at DESC LIMIT 1
        """,
        {"p": patient_id},
    ).fetchone()
    if row:
        return row["id"]
    row = conn.execute(
        """
        SELECT id::text FROM practitioners WHERE organization_id = %s AND user_id IS NOT NULL
        ORDER BY (specialty = 'Primary care') DESC, name LIMIT 1
        """,
        (organization_id,),
    ).fetchone()
    return row["id"] if row else None


def create_thread(
    conn: Connection,
    *,
    patient_id: str,
    subject: str,
    kind: str = "care_team",
    practitioner_id: str | None = None,
    appointment_id: str | None = None,
    care_plan_id: str | None = None,
    agent_state: dict | None = None,
) -> dict:
    org = conn.execute("SELECT organization_id::text FROM patients WHERE id = %s", (patient_id,)).fetchone()["organization_id"]
    if practitioner_id is None:
        practitioner_id = care_team_practitioner(conn, patient_id, org)
    row = conn.execute(
        """
        INSERT INTO communication_threads (patient_id, organization_id, subject, kind, practitioner_id, appointment_id,
                                           care_plan_id, agent_state)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text
        """,
        (patient_id, org, subject, kind, practitioner_id, appointment_id, care_plan_id, Jsonb(agent_state or {})),
    ).fetchone()
    thread = load_thread(conn, row["id"])
    add_participant(conn, thread["id"], thread["patient_user_id"], "patient")
    add_participant(conn, thread["id"], thread["practitioner_user_id"], "clinician")
    return thread


def assign(conn: Connection, thread: dict, to: str) -> None:
    """Hand the thread to the clinician, the front desk, or the nurse-triage pool (staff)."""
    conn.execute("UPDATE communication_threads SET assigned_to = %s WHERE id = %s", (to, thread["id"]))
    thread["assigned_to"] = to
    if to in ("front_desk", "nurse_triage"):
        for staff in conn.execute(
            "SELECT id::text FROM users WHERE organization_id = %s AND role = 'staff'", (thread["organization_id"],)
        ).fetchall():
            add_participant(conn, thread["id"], staff["id"], "staff")


def set_state(conn: Connection, thread: dict, state: dict) -> None:
    conn.execute("UPDATE communication_threads SET agent_state = %s WHERE id = %s", (Jsonb(state), thread["id"]))
    thread["agent_state"] = state


def load_config(conn: Connection, practitioner_id: str | None) -> dict | None:
    if not practitioner_id:
        return None
    return conn.execute(
        """
        SELECT active, previsit_questions, followup_protocol, escalation_rules, approval_requirements
        FROM doctor_agent_configs WHERE practitioner_id = %s
        """,
        (practitioner_id,),
    ).fetchone()


def rule_for(config: dict, rule_id: str) -> dict | None:
    return next((r for r in config["escalation_rules"] if r["id"] == rule_id), None)


def approval_required(config: dict, requirement_id: str) -> bool:
    """Unknown requirements count as required: conservative by default."""
    req = next((a for a in config["approval_requirements"] if a["id"] == requirement_id), None)
    return True if req is None else bool(req["required"])


def _review_item(
    conn: Connection, thread: dict, *, kind: str, title: str, body: str, priority: str, practitioner_id: str | None = None
) -> str | None:
    """One open review item per thread and kind. Returns its id, or None when no clinician can receive it."""
    practitioner_id = practitioner_id or thread["practitioner_id"] or care_team_practitioner(
        conn, thread["patient_id"], thread["organization_id"])
    if not practitioner_id:
        return None
    link = link_for(thread["id"])
    existing = conn.execute(
        "SELECT id::text FROM review_items WHERE kind = %s AND link = %s AND status = 'open' AND practitioner_id = %s",
        (kind, link, practitioner_id),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE review_items SET body = body || E'\\n\\n' || %s,
                   priority = CASE WHEN %s = 'urgent' THEN 'urgent' ELSE priority END
            WHERE id = %s
            """,
            (body, priority, existing["id"]),
        )
        return existing["id"]
    row = conn.execute(
        """
        INSERT INTO review_items (kind, patient_id, practitioner_id, ref_id, title, body, priority, link)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text
        """,
        (kind, thread["patient_id"], practitioner_id, thread["id"], title, body, priority, link),
    ).fetchone()
    return row["id"]


# ---------------------------------------------------------------------------------------------
# Red flags
# ---------------------------------------------------------------------------------------------


def escalate_red_flag(
    conn: Connection, user: User | None, thread: dict, screen: red_flags.ScreenResult, statement: str,
    source: str = "safety/red-flags", model: str | None = None,
) -> dict:
    flags = screen.flags or ["unspecified warning sign"]
    item_id = _review_item(
        conn, thread, kind="red_flag", priority="urgent",
        title=f"Red flag in message · {', '.join(flags)}",
        body=f"Patient was shown emergency guidance in secure messaging. They wrote: \"{statement}\"",
    )
    conn.execute(
        """
        UPDATE communication_threads
        SET flagged = true, flag_reason = %s, priority = 'urgent', assigned_to = 'clinician',
            flag_acknowledged_at = NULL, flag_acknowledged_by = NULL,
            awaiting_since = coalesce(awaiting_since, now())
        WHERE id = %s
        """,
        (", ".join(flags), thread["id"]),
    )
    thread.update(flagged=True, priority="urgent", assigned_to="clinician")
    state = dict(thread["agent_state"] or {})
    changed = False
    if state.get("gathering"):
        state.pop("gathering")
        changed = True
    if state.get("previsit") and state["previsit"].get("status") == "in_progress":
        state["previsit"] = {**state["previsit"], "status": "stopped_red_flag"}
        changed = True
    if changed:
        set_state(conn, thread, state)
    audit.record(
        conn, action="red_flag_escalation", entity_type="communication_thread", entity_id=thread["id"], actor=user,
        patient_id=thread["patient_id"], agent=source, model=model,
        detail={"flags": flags, "level": screen.level, "ruleset": screen.ruleset, "review_item": item_id},
    )
    payload = {
        "kind": "emergency",
        "level": screen.level,
        "flags": flags,
        "emergency_number": red_flags.EMERGENCY_NUMBER,
        "crisis_line": red_flags.CRISIS_LINE if screen.level == "crisis" else None,
        "care_team_notified": item_id is not None,
    }
    return add_message(conn, thread, author_kind="system", author_label=SAFETY_LABEL,
                       body=red_flags.emergency_message(screen), actor=user, payload=payload, produced_by=source,
                       model=model)


# ---------------------------------------------------------------------------------------------
# Approved education content
# ---------------------------------------------------------------------------------------------


def patient_medications(conn: Connection, patient_id: str) -> str:
    """Medications on the patient's active care plans, lowercased, for content matching."""
    rows = conn.execute(
        """
        SELECT t.title, coalesce(t.detail, '') AS detail FROM care_plan_tasks t JOIN care_plans c ON c.id = t.care_plan_id
        WHERE c.patient_id = %s AND c.status = 'active' AND t.kind = 'medication'
        """,
        (patient_id,),
    ).fetchall()
    return " ".join(f"{r['title']} {r['detail']}" for r in rows).lower()


def _stem_found(stems: list[str], text: str) -> bool:
    if not stems:
        return False
    pattern = re.compile(r"\b(" + "|".join(re.escape(s) for s in stems) + r")", re.I)
    return message_triage.found(pattern, text)


def match_content(conn: Connection, organization_id: str, text: str, medications_on_record: str) -> dict | None:
    """The approved side-effect item whose symptoms appear in the message and whose medication is named in the
    message or is on the patient's active care plan. Deterministic: the agent never paraphrases content."""
    for item in conn.execute(
        """
        SELECT id::text, title, body, medications, symptoms FROM education_content
        WHERE organization_id = %s AND status = 'approved' AND topic = 'side_effect' ORDER BY title
        """,
        (organization_id,),
    ).fetchall():
        med_hit = any(m.lower() in text.lower() or m.lower() in medications_on_record for m in item["medications"])
        if med_hit and _stem_found(item["symptoms"], text):
            return item
    return None


def general_safety_content(conn: Connection, organization_id: str) -> dict | None:
    return conn.execute(
        """
        SELECT id::text, title, body FROM education_content
        WHERE organization_id = %s AND status = 'approved' AND topic = 'general' ORDER BY title LIMIT 1
        """,
        (organization_id,),
    ).fetchone()


# ---------------------------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------------------------


def handle_patient_message(conn: Connection, user: User, thread: dict, body: str) -> list[dict]:
    """Store a patient message and run it through safety, triage and the Doctor Agent. Returns new messages."""
    out = [add_message(conn, thread, author_kind="patient", author_label=thread["patient_name"], body=body,
                       actor=user, author_user_id=user.id)]
    conn.execute(
        "UPDATE communication_threads SET awaiting_since = coalesce(awaiting_since, now()), status = 'open' WHERE id = %s",
        (thread["id"],),
    )

    # 1. Safety first, always, with or without AI.
    screen = red_flags.screen(body)
    if screen.level in ("emergency", "crisis"):
        category = "other" if screen.level == "crisis" else "new_symptom"
        _record_triage(conn, out[0], TriageOutcome(category, "urgent", f"Red flag: {', '.join(screen.flags)}.",
                                                    "safety/red-flags"), thread)
        out.append(escalate_red_flag(conn, user, thread, screen, body))
        return out

    state = dict(thread["agent_state"] or {})

    # 2. Pre-visit interview answers are data for the clinician, not new requests.
    if state.get("previsit", {}).get("status") == "in_progress":
        out.extend(_previsit_answer(conn, user, thread, out[0], body, screen))
        return out

    # 3. Triage. The model may raise priority, never lower it.
    triage = message_triage.classify(body, screen_level=screen.level, ai_allowed=consent.ai_allowed(conn, thread["patient_id"]))
    if thread["kind"] == "followup" and triage.category == "new_symptom":
        # A symptom reported in reply to a medication check-in is a possible side effect of that medication.
        triage.category = "side_effect"
        triage.reason += " Reported in reply to a medication check-in."
    _record_triage(conn, out[0], triage, thread)
    audit.record(conn, action="message_triaged", entity_type="communication", entity_id=out[0]["id"], actor=user,
                 patient_id=thread["patient_id"], agent=triage.produced_by, model=triage.model,
                 detail={"category": triage.category, "priority": triage.priority})
    if triage.possible_emergency:
        flagged = red_flags.ScreenResult(level="emergency", flags=["flagged by message triage"])
        out.append(escalate_red_flag(conn, user, thread, flagged, body, source=triage.produced_by, model=triage.model))
        return out

    # 4. Doctor Agent, if the addressed clinician has it switched on.
    config = load_config(conn, thread["practitioner_id"])
    if not (config and config["active"]):
        assign(conn, thread, "front_desk" if triage.category in NON_CLINICAL else "clinician")
        return out
    out.extend(_apply_rules(conn, user, thread, config, out[0], body, triage, state))
    return out


def _record_triage(conn: Connection, message: dict, triage: TriageOutcome, thread: dict) -> None:
    conn.execute(
        "UPDATE communications SET category = %s, priority = %s, triage_reason = %s WHERE id = %s",
        (triage.category, triage.priority, triage.reason, message["id"]),
    )
    message.update(category=triage.category, priority=triage.priority, triage_reason=triage.reason)
    # A thread stays urgent until a human has answered it.
    conn.execute(
        """
        UPDATE communication_threads
        SET category = %s, triage_reason = %s,
            priority = CASE WHEN %s = 'urgent' OR (priority = 'urgent' AND awaiting_since IS NOT NULL) THEN 'urgent'
                            ELSE 'routine' END
        WHERE id = %s
        """,
        (triage.category, triage.reason, triage.priority, thread["id"]),
    )
    thread.update(category=triage.category)


def _agent_say(conn: Connection, user: User, thread: dict, body: str, payload: dict) -> dict:
    return add_message(conn, thread, author_kind="agent", author_label=agent_label(thread["practitioner_name"]),
                       body=body, actor=user, payload=payload, produced_by=AGENT)


def _apply_rules(
    conn: Connection, user: User, thread: dict, config: dict, message: dict, body: str, triage: TriageOutcome, state: dict
) -> list[dict]:
    category = triage.category

    # Continue gathering details for a symptom: one question per turn, then escalate.
    gathering = state.get("gathering")
    if gathering:
        gathering = {**gathering, "answers": [*gathering.get("answers", []), body]}
        if gathering["asked"] < MAX_CLARIFYING_QUESTIONS:
            gathering["asked"] += 1
            set_state(conn, thread, {**state, "gathering": gathering})
            return [_agent_say(conn, user, thread, CLARIFYING_QUESTIONS[gathering["asked"] - 1],
                               {"kind": "clarifying_question", "n": gathering["asked"]})]
        set_state(conn, thread, {k: v for k, v in state.items() if k != "gathering"})
        details = [f"Q: {q} A: \"{a}\"" for q, a in zip(CLARIFYING_QUESTIONS, gathering["answers"], strict=False)]
        return _escalate(conn, user, thread, gathering["category"], gathering["route"],
                         gathering["first"], details, "urgent" if triage.priority == "urgent" else gathering["priority"])

    # After an education answer, a further clinical message means it was not resolved.
    if state.get("education_given") and category in CLINICAL:
        set_state(conn, thread, {k: v for k, v in state.items() if k != "education_given"})
        rule = rule_for(config, "side_effect") or {"route_to": "clinician"}
        return _escalate(conn, user, thread, category, rule["route_to"], body,
                         ["Patient replied after receiving approved education content."], triage.priority)

    if category in ("new_symptom", "worsening_symptom"):
        rule = rule_for(config, "new_symptom") or {"action": "escalate_immediately", "route_to": "clinician"}
        if rule["action"] == "gather_then_escalate":
            set_state(conn, thread, {**state, "gathering": {
                "asked": 1, "route": rule["route_to"], "category": category, "first": body, "answers": [],
                "priority": triage.priority,
            }})
            return [_agent_say(conn, user, thread, CLARIFYING_QUESTIONS[0], {"kind": "clarifying_question", "n": 1})]
        return _escalate(conn, user, thread, category, rule["route_to"], body, [], triage.priority)

    if category == "side_effect":
        rule = rule_for(config, "side_effect") or {"action": "escalate", "route_to": "clinician"}
        if rule["action"] == "answer_from_approved_content":
            item = match_content(conn, thread["organization_id"], body, patient_medications(conn, thread["patient_id"]))
            if item:
                return _answer_from_content(conn, user, thread, config, item, body, state)
            return _escalate(conn, user, thread, category, rule["route_to"], body,
                             ["No approved education content matched."], triage.priority)
        return _escalate(conn, user, thread, category, rule["route_to"], body, [], triage.priority)

    if category == "logistics":
        rule = rule_for(config, "logistics") or {"route_to": "front_desk"}
        return _escalate(conn, user, thread, category, rule["route_to"], body, [], "routine")

    if category == "billing":
        return _escalate(conn, user, thread, category, "front_desk", body, [], "routine")

    # Medication and results questions, and anything else: outside the agent's configured scope.
    return _escalate(conn, user, thread, category, "clinician", body,
                     ["Outside the Doctor Agent's configured scope."], triage.priority)


def _escalate(
    conn: Connection, user: User, thread: dict, category: str, route: str, statement: str, details: list[str],
    priority: str,
) -> list[dict]:
    doctor = short_name(thread["practitioner_name"])
    label = CATEGORY_LABELS.get(category, "Message").lower()
    safety = f" If things get worse or you feel unsafe, call {red_flags.EMERGENCY_NUMBER}."
    if route in ("front_desk",):
        assign(conn, thread, "front_desk")
        text = "I've passed your message to the front desk team. They'll reply here, usually within one working day."
        payload = {"kind": "handoff", "to": "front_desk"}
    elif route in STAFF_ROUTES:
        assign(conn, thread, "nurse_triage")
        text = f"I've passed your message to {doctor}'s nursing team. They'll reply here.{safety}"
        payload = {"kind": "handoff", "to": "nurse_triage"}
    else:
        assign(conn, thread, "clinician")
        same_day = route == "clinician_same_day"
        review_priority = "urgent" if same_day or priority == "urgent" else "routine"
        body = f"\"{statement}\"" + ("\n" + "\n".join(details) if details else "")
        item_id = _review_item(conn, thread, kind="agent_escalation", priority=review_priority,
                               title=f"Doctor Agent escalation · {label}", body=body)
        if same_day or review_priority == "urgent":
            conn.execute("UPDATE communication_threads SET priority = 'urgent' WHERE id = %s", (thread["id"],))
        text = (f"I've passed your message to {doctor}{' to look at today' if same_day else ''}. "
                f"You'll get a reply here from the care team.{safety}")
        payload = {"kind": "handoff", "to": "clinician", "review_item": item_id}
    audit.record(conn, action="agent_escalation", entity_type="communication_thread", entity_id=thread["id"],
                 actor=user, patient_id=thread["patient_id"], agent=AGENT,
                 detail={"category": category, "route": route, "details": details})
    return [_agent_say(conn, user, thread, text, payload)]


def _answer_from_content(
    conn: Connection, user: User, thread: dict, config: dict, item: dict, statement: str, state: dict
) -> list[dict]:
    doctor = short_name(thread["practitioner_name"])
    general = general_safety_content(conn, thread["organization_id"])
    answer = item["body"] + (f"\n\n{general['body']}" if general else "")
    content_ids = [item["id"]] + ([general["id"]] if general else [])

    if approval_required(config, "routine_education"):
        # The clinician wants to approve even routine education: hold it as a draft for them.
        conn.execute(
            """
            INSERT INTO communication_drafts (thread_id, patient_id, source, body, grounding, produced_by)
            VALUES (%s, %s, 'agent_pending_approval', %s, %s, %s)
            """,
            (thread["id"], thread["patient_id"], answer, Jsonb([{"type": "education_content", "id": c} for c in content_ids]), AGENT),
        )
        assign(conn, thread, "clinician")
        _review_item(conn, thread, kind="doctor_agent_approval", priority="routine",
                     title=f"Approve Doctor Agent answer · {item['title']}",
                     body=f"Patient asked: \"{statement}\". The agent drafted an answer from \"{item['title']}\".")
        audit.record(conn, action="agent_answer_held_for_approval", entity_type="communication_thread",
                     entity_id=thread["id"], actor=user, patient_id=thread["patient_id"], agent=AGENT,
                     detail={"content_ids": content_ids})
        return [_agent_say(conn, user, thread,
                           f"I've found information {doctor} has approved about this. The care team will check it "
                           f"before it's sent to you here. If things get worse, call {red_flags.EMERGENCY_NUMBER}.",
                           {"kind": "handoff", "to": "clinician_approval"})]

    set_state(conn, thread, {**state, "education_given": content_ids})
    # Answered from approved content: nobody is left waiting on this message.
    conn.execute("UPDATE communication_threads SET awaiting_since = NULL, priority = 'routine' WHERE id = %s", (thread["id"],))
    audit.record(conn, action="agent_answer_from_content", entity_type="communication_thread", entity_id=thread["id"],
                 actor=user, patient_id=thread["patient_id"], agent=AGENT, detail={"content_ids": content_ids})
    closing = f"\n\nIf this doesn't answer your question, reply here and I'll pass it to {doctor}'s team."
    return [_agent_say(conn, user, thread, answer + closing,
                       {"kind": "education", "title": item["title"], "content_ids": content_ids})]


# ---------------------------------------------------------------------------------------------
# Pre-visit interview
# ---------------------------------------------------------------------------------------------


def start_previsit(conn: Connection, user: User, appointment: dict) -> dict:
    """Idempotent: returns the existing interview thread for this appointment if there is one."""
    existing = conn.execute(
        "SELECT id::text FROM communication_threads WHERE appointment_id = %s AND kind = 'previsit'",
        (appointment["id"],),
    ).fetchone()
    if existing:
        return load_thread(conn, existing["id"])
    config = load_config(conn, appointment["practitioner_id"])
    questions = [{"id": q["id"], "text": q["text"]} for q in (config or {}).get("previsit_questions", []) if q["enabled"]]
    thread = create_thread(
        conn, patient_id=appointment["patient_id"], practitioner_id=appointment["practitioner_id"],
        appointment_id=appointment["id"], kind="previsit",
        subject=f"Before your visit on {appointment['starts_at']:%a %d %b}",
        agent_state={"previsit": {"status": "in_progress", "index": 0, "questions": questions}},
    )
    doctor = short_name(thread["practitioner_name"])
    _agent_say(conn, user, thread,
               f"Hi {thread['patient_name'].split()[0]}, {doctor} has {len(questions)} short question"
               f"{'s' if len(questions) != 1 else ''} before your visit. Your answers go to {doctor} ahead of the "
               "visit. Answer in your own words; there are no wrong answers.",
               {"kind": "previsit_intro"})
    _agent_say(conn, user, thread, questions[0]["text"],
               {"kind": "previsit_question", "question_id": questions[0]["id"], "n": 1, "of": len(questions)})
    audit.record(conn, action="previsit_started", entity_type="appointment", entity_id=appointment["id"], actor=user,
                 patient_id=appointment["patient_id"], agent=AGENT, detail={"thread_id": thread["id"]})
    return load_thread(conn, thread["id"])


def _previsit_answer(
    conn: Connection, user: User, thread: dict, message: dict, body: str, screen: red_flags.ScreenResult
) -> list[dict]:
    state = dict(thread["agent_state"])
    pv = dict(state["previsit"])
    questions = pv["questions"]
    q = questions[pv["index"]]
    symptoms = message_triage.mentions_symptoms(body) or screen.level != "none"
    conn.execute(
        """
        INSERT INTO questionnaire_responses (patient_id, practitioner_id, appointment_id, thread_id, question_id,
                                             question_text, answer_text, communication_id, mentions_symptoms, screen_level)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (appointment_id, question_id) DO UPDATE
          SET answer_text = EXCLUDED.answer_text, communication_id = EXCLUDED.communication_id,
              mentions_symptoms = EXCLUDED.mentions_symptoms, screen_level = EXCLUDED.screen_level
        """,
        (thread["patient_id"], thread["practitioner_id"], thread["appointment_id"], thread["id"], q["id"], q["text"],
         body, message["id"], symptoms, screen.level),
    )
    audit.record(conn, action="previsit_answer", entity_type="appointment", entity_id=thread["appointment_id"],
                 actor=user, patient_id=thread["patient_id"], agent=AGENT,
                 detail={"question_id": q["id"], "mentions_symptoms": symptoms})
    pv["index"] += 1
    if pv["index"] < len(questions):
        set_state(conn, thread, {**state, "previsit": pv})
        nxt = questions[pv["index"]]
        return [_agent_say(conn, user, thread, nxt["text"],
                           {"kind": "previsit_question", "question_id": nxt["id"], "n": pv["index"] + 1, "of": len(questions)})]
    pv["status"] = "complete"
    set_state(conn, thread, {**state, "previsit": pv})
    conn.execute("UPDATE communication_threads SET awaiting_since = NULL WHERE id = %s", (thread["id"],))
    doctor = short_name(thread["practitioner_name"])
    closing = (f"Thank you. {doctor} will see your answers before your visit."
               + (" You mentioned symptoms, so they've been highlighted for the care team. If anything gets worse "
                  f"before your visit, call {red_flags.EMERGENCY_NUMBER} or message us here." if _any_symptoms(conn, thread) else ""))
    return [_agent_say(conn, user, thread, closing, {"kind": "previsit_complete"})]


def _any_symptoms(conn: Connection, thread: dict) -> bool:
    return conn.execute(
        "SELECT 1 FROM questionnaire_responses WHERE thread_id = %s AND mentions_symptoms", (thread["id"],)
    ).fetchone() is not None


# ---------------------------------------------------------------------------------------------
# Follow-up protocol check-ins
# ---------------------------------------------------------------------------------------------


def _checkin_text(first_name: str, doctor: str, medication: str, day: int, action: str) -> str:
    lower = action.lower()
    med = re.sub(r"^start\s+", "", medication, flags=re.I).split(",")[0]
    if "first dose" in lower:
        ask = f"Have you taken your first dose of {med}? Just reply here to let us know."
    elif "side effect" in lower:
        examples = action.split(":", 1)[1].strip() if ":" in action else ""
        ask = (f"Have you noticed any side effects since starting {med}"
               + (f", such as {examples.replace(', ', ' or ')}" if examples else "") + "? Reply here and tell us how you're feeling.")
    elif "adherence" in lower:
        ask = f"How is taking {med} going? Have you been able to take it every day?"
        if "lipid" in lower or "recheck" in lower:
            ask += " It's also time to book your cholesterol recheck."
    else:
        ask = f"{action}. Reply here to let us know how things are going."
    return f"Hi {first_name}, this is your day {day} check-in from {doctor}'s care team. {ask}"


def materialize_followups(conn: Connection, *, patient_ids: list[str], actor: User | None) -> int:
    """Create scheduled check-ins from each clinician's follow-up protocol and send the ones that are due.

    There are no background workers, so this runs when a patient opens their messages or a clinician opens the
    inbox. It is idempotent: rows are unique per (task, day), and each row is sent at most once.
    """
    if not patient_ids:
        return 0
    plans = conn.execute(
        """
        SELECT c.id::text AS care_plan_id, c.patient_id::text, c.practitioner_id::text, c.started_at,
               t.id::text AS task_id, t.title, t.completed_at, d.followup_protocol
        FROM care_plans c
        JOIN care_plan_tasks t ON t.care_plan_id = c.id AND t.kind = 'medication'
        JOIN doctor_agent_configs d ON d.practitioner_id = c.practitioner_id AND d.active
        WHERE c.status = 'active' AND c.patient_id = ANY(%s::uuid[])
        """,
        (patient_ids,),
    ).fetchall()
    for plan in plans:
        base = (plan["completed_at"] or plan["started_at"]).date()
        for step in plan["followup_protocol"]:
            conn.execute(
                """
                INSERT INTO communication_requests (patient_id, practitioner_id, care_plan_id, task_id, step_day, action, due_on)
                VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (task_id, step_day) DO NOTHING
                """,
                (plan["patient_id"], plan["practitioner_id"], plan["care_plan_id"], plan["task_id"], step["day"],
                 step["action"], base + timedelta(days=step["day"])),
            )

    due = conn.execute(
        """
        SELECT r.id::text, r.patient_id::text, r.practitioner_id::text, r.care_plan_id::text, r.task_id::text,
               r.step_day, r.action, r.due_on, t.title AS task_title
        FROM communication_requests r
        JOIN care_plan_tasks t ON t.id = r.task_id
        JOIN care_plans c ON c.id = r.care_plan_id AND c.status = 'active'
        JOIN doctor_agent_configs d ON d.practitioner_id = r.practitioner_id AND d.active
        WHERE r.status = 'scheduled' AND r.due_on <= %s AND r.patient_id = ANY(%s::uuid[])
        ORDER BY r.task_id, r.step_day
        FOR UPDATE OF r SKIP LOCKED
        """,
        (today(), patient_ids),
    ).fetchall()
    # When several steps are overdue for one task, send only the latest; the earlier ones are stale.
    latest: dict[str, dict] = {}
    for r in due:
        latest[r["task_id"]] = r
    sent = 0
    for r in due:
        if latest[r["task_id"]] is not r:
            conn.execute("UPDATE communication_requests SET status = 'skipped' WHERE id = %s", (r["id"],))
            continue
        thread_row = conn.execute(
            "SELECT id::text FROM communication_threads WHERE care_plan_id = %s AND kind = 'followup'",
            (r["care_plan_id"],),
        ).fetchone()
        if thread_row:
            thread = load_thread(conn, thread_row["id"])
        else:
            med = re.sub(r"^start\s+", "", r["task_title"], flags=re.I).split(",")[0]
            thread = create_thread(conn, patient_id=r["patient_id"], practitioner_id=r["practitioner_id"],
                                   care_plan_id=r["care_plan_id"], kind="followup", subject=f"Check-ins: {med}")
        body = _checkin_text(thread["patient_name"].split()[0], short_name(thread["practitioner_name"]),
                             r["task_title"], r["step_day"], r["action"])
        msg = add_message(conn, thread, author_kind="agent", author_label=agent_label(thread["practitioner_name"]),
                          body=body, actor=actor, produced_by=AGENT,
                          payload={"kind": "checkin", "day": r["step_day"], "request_id": r["id"]})
        conn.execute(
            "UPDATE communication_requests SET status = 'sent', communication_id = %s, sent_at = now() WHERE id = %s",
            (msg["id"], r["id"]),
        )
        sent += 1
    return sent
