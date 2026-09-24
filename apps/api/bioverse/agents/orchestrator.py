"""The front-door orchestrator.

Owns the conversation and runs every patient turn through the same order:

    1. Deterministic red-flag screen (safety/red_flags.py). Emergencies stop here.
    2. Structured safety check when a screen topic appears (chest, headache).
    3. Triage by the intake agent: Claude when available, rules otherwise.
    4. Route: a care-options card, a link to results / plan / story, or one more question.

Urgency only ever ratchets up. Every step is written to the audit trail.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

from bioverse import audit
from bioverse.agents import llm
from bioverse.agents.triage import URGENCY_RANK, TriageResult, claude_triage, rules_triage
from bioverse.auth import User
from bioverse.safety import red_flags

MAX_FOLLOW_UP_QUESTIONS = 3

TOPIC_PHRASES = {
    "chest": "chest symptoms",
    "headache": "a headache",
}

LINKS = {
    "results": {"to": "/results", "label": "Open my results"},
    "care_plan": {"to": "/plan", "label": "Open my care plan"},
    "health_story": {"to": "/story", "label": "Open my health story"},
}


def _age(birth_date: date) -> int:
    today = date.today()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def _load_patient(conn: Connection, patient_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id::text, name, birth_date, pronouns, preferred_language, allergies FROM patients WHERE id = %s",
        (patient_id,),
    ).fetchone()
    row["age"] = _age(row["birth_date"])
    return row


def _add_message(conn: Connection, conversation_id: str, role: str, content: str, payload: dict | None = None) -> dict:
    return conn.execute(
        """
        INSERT INTO messages (conversation_id, role, content, payload)
        VALUES (%s, %s, %s, %s)
        RETURNING id::text, role, content, payload, created_at
        """,
        (conversation_id, role, content, Jsonb(payload) if payload is not None else None),
    ).fetchone()


def _history(conn: Connection, conversation_id: str) -> list[dict[str, str]]:
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE conversation_id = %s ORDER BY seq",
        (conversation_id,),
    ).fetchall()
    # The API requires the first message to be from the user and roles to alternate;
    # merge consecutive same-role turns.
    merged: list[dict[str, str]] = []
    for row in rows:
        if merged and merged[-1]["role"] == row["role"]:
            merged[-1]["content"] += "\n\n" + row["content"]
        else:
            merged.append({"role": row["role"], "content": row["content"]})
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    return merged


def _set_state(conn: Connection, conversation_id: str, state: dict) -> None:
    conn.execute("UPDATE conversations SET state = %s WHERE id = %s", (Jsonb(state), conversation_id))


def _care_team_practitioner(conn: Connection, patient_id: str, organization_id: str) -> str | None:
    row = conn.execute(
        """
        SELECT practitioner_id::text AS id FROM care_plans
        WHERE patient_id = %s AND status = 'active'
        ORDER BY started_at DESC LIMIT 1
        """,
        (patient_id,),
    ).fetchone()
    if row:
        return row["id"]
    row = conn.execute(
        """
        SELECT id::text FROM practitioners
        WHERE organization_id = %s AND user_id IS NOT NULL
        ORDER BY name LIMIT 1
        """,
        (organization_id,),
    ).fetchone()
    return row["id"] if row else None


def _first_patient_statement(history: list[dict[str, str]]) -> str:
    for turn in history:
        if turn["role"] == "user":
            return turn["content"]
    return ""


def _escalate(
    conn: Connection,
    user: User,
    conversation: dict,
    patient: dict,
    result: red_flags.ScreenResult,
    source: str,
) -> dict:
    history = _history(conn, conversation["id"])
    statement = _first_patient_statement(history)
    flags = result.flags or ["unspecified warning sign"]
    complaint = statement[:120] or "Red flag reported"

    intake = conn.execute(
        """
        INSERT INTO intakes (conversation_id, patient_id, chief_complaint, urgency, red_flags,
                             patient_summary, clinician_summary, status, produced_by)
        VALUES (%s, %s, %s, 'emergency', %s, %s, %s, 'escalated', %s)
        RETURNING id::text
        """,
        (
            conversation["id"],
            patient["id"],
            complaint,
            flags,
            "You reported symptoms that may need emergency care. You were advised to get emergency help now.",
            f"RED FLAG ({', '.join(flags)}). {patient['age']}y. Patient said: \"{statement}\". "
            f"Advised emergency services. Detected by {source}.",
            source,
        ),
    ).fetchone()

    conn.execute("UPDATE conversations SET status = 'escalated', state = '{}'::jsonb WHERE id = %s", (conversation["id"],))

    practitioner_id = _care_team_practitioner(conn, patient["id"], user.organization_id)
    if practitioner_id:
        conn.execute(
            """
            INSERT INTO review_items (kind, patient_id, practitioner_id, ref_id, title, body, priority)
            VALUES ('red_flag', %s, %s, %s, %s, %s, 'urgent')
            """,
            (
                patient["id"],
                practitioner_id,
                intake["id"],
                f"Red flag · {', '.join(flags)}",
                f"Patient was advised to seek emergency care. They said: \"{statement}\"",
            ),
        )

    audit.record(
        conn,
        action="red_flag_escalation",
        entity_type="intake",
        entity_id=intake["id"],
        actor=user,
        agent=source,
        detail={"flags": flags, "level": result.level, "ruleset": result.ruleset},
    )

    payload = {
        "kind": "emergency",
        "level": result.level,
        "flags": flags,
        "emergency_number": red_flags.EMERGENCY_NUMBER,
        "crisis_line": red_flags.CRISIS_LINE if result.level == "crisis" else None,
        "care_team_notified": practitioner_id is not None,
    }
    return _add_message(conn, conversation["id"], "assistant", red_flags.emergency_message(result), payload)


def _run_triage(conn: Connection, patient: dict, history: list[dict[str, str]]) -> tuple[TriageResult, str, str | None]:
    """Returns (result, produced_by, model)."""
    if llm.ai_enabled():
        try:
            outcome = claude_triage(history, patient)
            label = f"intake-agent/claude{'+fallback' if outcome.fell_back else ''}"
            return outcome.output, label, outcome.model
        except llm.LLMUnavailable:
            pass
    return rules_triage(history, patient), "intake-agent/rules", None


def _count_follow_ups(conn: Connection, conversation_id: str) -> int:
    row = conn.execute(
        """
        SELECT count(*) AS n FROM messages
        WHERE conversation_id = %s AND role = 'assistant' AND payload->>'kind' = 'question'
        """,
        (conversation_id,),
    ).fetchone()
    return row["n"]


def _triage_and_route(conn: Connection, user: User, conversation: dict, patient: dict) -> dict:
    history = _history(conn, conversation["id"])
    result, produced_by, model = _run_triage(conn, patient, history)

    audit.record(
        conn,
        action="triage",
        entity_type="conversation",
        entity_id=conversation["id"],
        actor=user,
        agent=produced_by,
        model=model,
        detail={"intent": result.intent, "urgency": result.urgency, "specialty": result.specialty},
    )

    # The model may raise urgency to emergency. It can never lower what the rules decided.
    if result.urgency == "emergency" or result.red_flags:
        screen = red_flags.ScreenResult(level="emergency", flags=result.red_flags or ["flagged by intake agent"])
        return _escalate(conn, user, conversation, patient, screen, produced_by)

    if result.intent in LINKS:
        return _add_message(conn, conversation["id"], "assistant", result.reply, {"kind": "link", **LINKS[result.intent]})

    if (
        result.needs_more_info
        and result.follow_up_question
        and _count_follow_ups(conn, conversation["id"]) < MAX_FOLLOW_UP_QUESTIONS
    ):
        return _add_message(conn, conversation["id"], "assistant", result.follow_up_question, {"kind": "question"})

    specialty = result.specialty or "Primary care"
    statement = _first_patient_statement(history)
    intake = conn.execute(
        """
        INSERT INTO intakes (conversation_id, patient_id, chief_complaint, urgency, red_flags, specialty,
                             patient_summary, clinician_summary, status, produced_by)
        VALUES (%s, %s, %s, %s, '{}', %s, %s, %s, 'routed', %s)
        RETURNING id::text
        """,
        (
            conversation["id"],
            patient["id"],
            result.chief_complaint or statement[:120] or "General concern",
            result.urgency,
            specialty,
            result.patient_summary or f"You were routed to {specialty}.",
            result.clinician_summary or f"Patient report: \"{statement}\". Routed to {specialty}.",
            produced_by,
        ),
    ).fetchone()
    audit.record(
        conn,
        action="intake_created",
        entity_type="intake",
        entity_id=intake["id"],
        actor=user,
        agent=produced_by,
        model=model,
        detail={"specialty": specialty, "urgency": result.urgency},
    )
    payload = {
        "kind": "care_options",
        "specialty": specialty,
        "urgency": result.urgency,
        "intake_id": intake["id"],
    }
    return _add_message(conn, conversation["id"], "assistant", result.reply, payload)


def handle_turn(
    conn: Connection,
    user: User,
    conversation: dict,
    text: str | None,
    safety_answer: list[str] | None,
) -> list[dict]:
    patient = _load_patient(conn, conversation["patient_id"])
    state: dict = conversation.get("state") or {}

    # Record what the patient said or chose.
    if safety_answer is not None:
        topic = state.get("awaiting_safety_check")
        options = {o["id"]: o["label"] for o in red_flags.SAFETY_CHECKS.get(topic, {}).get("options", [])}
        chosen = [options.get(a, a) for a in safety_answer if a != "none"]
        _add_message(conn, conversation["id"], "user", "; ".join(chosen) if chosen else "None of these")
    else:
        _add_message(conn, conversation["id"], "user", text or "")

    # An escalated conversation keeps repeating emergency guidance. It does not drift back to routine care.
    if conversation["status"] == "escalated":
        screen = red_flags.ScreenResult(level="emergency", flags=["previously escalated"])
        reply = _add_message(
            conn,
            conversation["id"],
            "assistant",
            red_flags.emergency_message(screen),
            {"kind": "emergency", "level": "emergency", "flags": [], "emergency_number": red_flags.EMERGENCY_NUMBER,
             "crisis_line": None, "care_team_notified": True},
        )
        return [reply]

    # Answer to a pending safety check.
    if safety_answer is not None:
        topic = state.get("awaiting_safety_check")
        if not topic:
            # No check pending: treat as a normal turn with no text.
            return [_triage_and_route(conn, user, conversation, patient)]
        result = red_flags.evaluate_safety_check(topic, safety_answer)
        audit.record(
            conn,
            action="safety_check_answered",
            entity_type="conversation",
            entity_id=conversation["id"],
            actor=user,
            agent="safety/red-flags",
            detail={"topic": topic, "answer": safety_answer, "level": result.level},
        )
        if result.level == "emergency":
            return [_escalate(conn, user, conversation, patient, result, "safety/red-flags")]
        state = {**state, "awaiting_safety_check": None, "screened_topics": [*state.get("screened_topics", []), topic]}
        _set_state(conn, conversation["id"], state)
        return [_triage_and_route(conn, user, conversation, patient)]

    # A new message: deterministic screen first, always.
    result = red_flags.screen(text or "")
    if result.level in ("emergency", "crisis"):
        return [_escalate(conn, user, conversation, patient, result, "safety/red-flags")]

    if result.level == "screen" and result.topic not in state.get("screened_topics", []):
        check = red_flags.SAFETY_CHECKS[result.topic]
        _set_state(conn, conversation["id"], {**state, "awaiting_safety_check": result.topic})
        audit.record(
            conn,
            action="safety_check_requested",
            entity_type="conversation",
            entity_id=conversation["id"],
            actor=user,
            agent="safety/red-flags",
            detail={"topic": result.topic, "ruleset": result.ruleset},
        )
        lead = (
            f"I want to check a few things first, because {TOPIC_PHRASES[result.topic]} "
            "can sometimes need urgent care."
        )
        payload = {"kind": "safety_check", "topic": result.topic, **check}
        return [_add_message(conn, conversation["id"], "assistant", lead, payload)]

    return [_triage_and_route(conn, user, conversation, patient)]


def to_json(row: dict) -> dict:
    """Serialize a message row for the API."""
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "payload": row["payload"],
        "created_at": row["created_at"].isoformat(),
    }
