"""Secure messaging between patients and their care team (module 12).

Patients see only their own threads. Clinicians and staff see threads they take part in, and threads of
patients in their organization; the inbox lists the ones addressed to them (clinicians: their own threads;
staff: threads handed to the front desk or nurse triage). Admins do not read messages.

Messages are text only. Attachments and document sharing are out of scope for this module.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from bioverse import audit, consent
from bioverse.agents import doctor_agent as agent
from bioverse.agents import llm, message_triage
from bioverse.auth import CurrentUser, User, assert_patient_access
from bioverse.db import DbConn
from bioverse.safety import red_flags

router = APIRouter(prefix="/api/messages", tags=["messaging"])

Conn = DbConn
WORKFORCE = ("clinician", "staff")
STAFF_POOLS = ("front_desk", "nurse_triage")


# ---------------------------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------------------------


def _uuid_ok(value: str | None) -> bool:
    try:
        UUID(value or "")
        return True
    except ValueError:
        return False


def _require_messaging_role(user: User) -> None:
    if user.role == "patient" and user.patient_id:
        return
    if user.role in WORKFORCE:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Messaging is for patients and their care team")


def _is_participant(conn: Connection, thread_id: str, user_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM communication_participants WHERE thread_id = %s AND user_id = %s", (thread_id, user_id)
    ).fetchone() is not None


def _thread_for(conn: Connection, user: User, thread_id: str, *, for_update: bool = False) -> dict:
    """Load a thread the user may see, or 404 (never reveal that someone else's thread exists)."""
    _require_messaging_role(user)
    thread = agent.load_thread(conn, thread_id, for_update=for_update) if _uuid_ok(thread_id) else None
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    if user.role == "patient":
        if thread["patient_id"] != user.patient_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
        return thread
    if _is_participant(conn, thread_id, user.id):
        return thread
    if thread["organization_id"] != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    return thread


def _can_reply(conn: Connection, user: User, thread: dict) -> bool:
    if user.role == "patient":
        return thread["patient_id"] == user.patient_id
    if user.role == "clinician":
        return True
    # Front desk and nurse-triage staff answer what was handed to them, not clinical threads.
    return thread["assigned_to"] in STAFF_POOLS


def _require_reply(conn: Connection, user: User, thread: dict) -> None:
    if not _can_reply(conn, user, thread):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This thread is with the clinician, not the front desk")


# ---------------------------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------------------------

SUMMARY_SQL = f"""
    SELECT {agent.THREAD_COLUMNS},
           lm.body AS last_body, lm.author_label AS last_author, lm.author_kind AS last_author_kind,
           me.last_read_seq,
           (SELECT count(*) FROM communications c
             WHERE c.thread_id = t.id AND me.user_id IS NOT NULL AND c.seq > me.last_read_seq
               AND c.author_user_id IS DISTINCT FROM %(uid)s) AS unread
    FROM communication_threads t
    JOIN patients p ON p.id = t.patient_id
    LEFT JOIN practitioners pr ON pr.id = t.practitioner_id
    LEFT JOIN communication_participants me ON me.thread_id = t.id AND me.user_id = %(uid)s
    LEFT JOIN LATERAL (
        SELECT body, author_label, author_kind FROM communications c WHERE c.thread_id = t.id ORDER BY seq DESC LIMIT 1
    ) lm ON true
"""

INBOX_ORDER = """
    ORDER BY (t.flagged AND t.flag_acknowledged_at IS NULL) DESC,
             (t.priority = 'urgent' AND t.awaiting_since IS NOT NULL) DESC,
             (t.awaiting_since IS NOT NULL) DESC,
             t.awaiting_since ASC NULLS LAST,
             t.last_message_at DESC
"""


def _summary(row: dict, user: User) -> dict:
    workforce = user.role in WORKFORCE
    out = {
        "id": row["id"],
        "subject": row["subject"],
        "kind": row["kind"],
        "patient": {"id": row["patient_id"], "name": row["patient_name"]},
        "practitioner": {"id": row["practitioner_id"], "name": row["practitioner_name"]} if row["practitioner_id"] else None,
        "care_team_label": agent.short_name(row["practitioner_name"]) if row["practitioner_id"] else "My care team",
        "status": row["status"],
        "flagged": row["flagged"],
        "last_message_at": row["last_message_at"],
        "last_message": (
            {"body": (row["last_body"] or "")[:160], "author": row["last_author"],
             "automated": row["last_author_kind"] in ("agent", "system")}
            if row.get("last_body") is not None else None
        ),
        "unread": row.get("unread") or 0,
    }
    if workforce:
        out.update(
            category=row["category"],
            category_label=message_triage.CATEGORY_LABELS.get(row["category"]) if row["category"] else None,
            priority=row["priority"],
            triage_reason=row["triage_reason"],
            flag_reason=row["flag_reason"],
            flag_acknowledged=row["flag_acknowledged_at"] is not None,
            assigned_to=row["assigned_to"],
            awaiting_since=row["awaiting_since"],
        )
    return out


def _message_json(row: dict, user: User) -> dict:
    out = {
        "id": row["id"],
        "seq": row["seq"],
        "author_kind": row["author_kind"],
        "author_label": row["author_label"],
        "author_user_id": row["author_user_id"],
        "automated": row["author_kind"] in ("agent", "system"),
        "body": row["body"],
        "payload": row["payload"],
        "created_at": row["created_at"],
    }
    if user.role in WORKFORCE:
        out.update(category=row["category"], priority=row["priority"], triage_reason=row["triage_reason"],
                   produced_by=row["produced_by"], model=row["model"])
    return out


def _detail(conn: Connection, user: User, thread_id: str) -> dict:
    row = conn.execute(SUMMARY_SQL + " WHERE t.id = %(tid)s", {"uid": user.id, "tid": thread_id}).fetchone()
    messages = conn.execute(
        """
        SELECT id::text, seq, author_kind, author_label, author_user_id::text, body, payload, category, priority,
               triage_reason, produced_by, model, created_at
        FROM communications WHERE thread_id = %s ORDER BY seq
        """,
        (thread_id,),
    ).fetchall()
    participants = conn.execute(
        """
        SELECT cp.user_id::text, u.display_name AS name, cp.role, cp.last_read_seq, cp.last_read_at
        FROM communication_participants cp JOIN users u ON u.id = cp.user_id
        WHERE cp.thread_id = %s ORDER BY cp.joined_at, u.display_name
        """,
        (thread_id,),
    ).fetchall()
    out = _summary(row, user)
    out["messages"] = [_message_json(m, user) for m in messages]
    out["participants"] = participants
    out["can_reply"] = _can_reply(conn, user, row)
    out["attachments_supported"] = False
    if user.role in WORKFORCE:
        # Drafts are for the care team only. They never appear in a patient's view.
        out["drafts"] = conn.execute(
            """
            SELECT id::text, source, body, grounding, produced_by, model, created_at
            FROM communication_drafts WHERE thread_id = %s AND status = 'draft' ORDER BY created_at
            """,
            (thread_id,),
        ).fetchall()
        prev = conn.execute(
            """
            SELECT question_text, answer_text, mentions_symptoms FROM questionnaire_responses
            WHERE thread_id = %s ORDER BY created_at
            """,
            (thread_id,),
        ).fetchall()
        out["previsit_answers"] = prev
        out["agent_state"] = row["agent_state"]
    return out


def _mark_read(conn: Connection, user: User, thread_id: str) -> None:
    conn.execute(
        """
        UPDATE communication_participants
        SET last_read_seq = coalesce((SELECT max(seq) FROM communications WHERE thread_id = %s), 0), last_read_at = now()
        WHERE thread_id = %s AND user_id = %s
        """,
        (thread_id, thread_id, user.id),
    )


# ---------------------------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------------------------


def _materialize_for(conn: Connection, user: User) -> None:
    """Send any follow-up check-ins that have come due (no background workers)."""
    if user.role == "patient":
        agent.materialize_followups(conn, patient_ids=[user.patient_id], actor=user)
    elif user.role == "clinician":
        rows = conn.execute(
            "SELECT DISTINCT patient_id::text FROM care_plans WHERE practitioner_id = %s AND status = 'active'",
            (user.practitioner_id,),
        ).fetchall()
        agent.materialize_followups(conn, patient_ids=[r["patient_id"] for r in rows], actor=user)


@router.get("/threads")
def list_threads(conn: Conn, user: CurrentUser) -> list[dict]:
    _require_messaging_role(user)
    _materialize_for(conn, user)
    if user.role == "patient":
        rows = conn.execute(
            SUMMARY_SQL + " WHERE t.patient_id = %(pid)s ORDER BY t.last_message_at DESC",
            {"uid": user.id, "pid": user.patient_id},
        ).fetchall()
    elif user.role == "clinician":
        rows = conn.execute(
            SUMMARY_SQL
            + """ WHERE t.organization_id = %(org)s
                    AND (t.practitioner_id = %(pr)s OR me.user_id IS NOT NULL)
                    AND NOT (t.assigned_to IN ('front_desk', 'nurse_triage') AND t.practitioner_id IS DISTINCT FROM %(pr)s
                             AND NOT t.flagged)
              """ + INBOX_ORDER,
            {"uid": user.id, "org": user.organization_id, "pr": user.practitioner_id},
        ).fetchall()
    else:
        rows = conn.execute(
            SUMMARY_SQL
            + """ WHERE t.organization_id = %(org)s
                    AND (t.assigned_to IN ('front_desk', 'nurse_triage') OR me.user_id IS NOT NULL)
              """ + INBOX_ORDER,
            {"uid": user.id, "org": user.organization_id},
        ).fetchall()
    return [_summary(r, user) for r in rows]


class NewThreadIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    subject: str | None = Field(default=None, max_length=120)
    patient_id: str | None = None  # care team starting a thread with a patient


def _subject_from(body: str) -> str:
    first = body.strip().split("\n")[0]
    return first if len(first) <= 60 else first[:57].rstrip() + "..."


@router.post("/threads", status_code=status.HTTP_201_CREATED)
def start_thread(body: NewThreadIn, conn: Conn, user: CurrentUser) -> dict:
    _require_messaging_role(user)
    text = body.body.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A message needs text")
    subject = (body.subject or "").strip() or _subject_from(text)

    if user.role == "patient":
        # "My care team": the practitioner of the active care plan, else primary care.
        thread = agent.create_thread(conn, patient_id=user.patient_id, subject=subject)
        audit.record(conn, action="thread_started", entity_type="communication_thread", entity_id=thread["id"],
                     actor=user, patient_id=user.patient_id)
        agent.handle_patient_message(conn, user, thread, text)
    else:
        if not body.patient_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose the patient to message")
        assert_patient_access(conn, user, body.patient_id)
        thread = agent.create_thread(conn, patient_id=body.patient_id, subject=subject,
                                     practitioner_id=user.practitioner_id if user.role == "clinician" else None)
        agent.add_participant(conn, thread["id"], user.id, user.role)
        if user.role == "staff":
            agent.assign(conn, thread, "front_desk")
        audit.record(conn, action="thread_started", entity_type="communication_thread", entity_id=thread["id"],
                     actor=user, patient_id=body.patient_id)
        agent.add_message(conn, thread, author_kind=user.role, author_label=user.display_name, body=text,
                          actor=user, author_user_id=user.id)
    _mark_read(conn, user, thread["id"])
    return _detail(conn, user, thread["id"])


@router.get("/threads/{thread_id}")
def get_thread(thread_id: str, conn: Conn, user: CurrentUser) -> dict:
    thread = _thread_for(conn, user, thread_id)
    _mark_read(conn, user, thread_id)
    if user.role in WORKFORCE:
        audit.record(conn, action="thread_viewed", entity_type="communication_thread", entity_id=thread_id,
                     actor=user, patient_id=thread["patient_id"])
    return _detail(conn, user, thread_id)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    draft_id: str | None = None


@router.post("/threads/{thread_id}/messages")
def send_message(thread_id: str, body: MessageIn, conn: Conn, user: CurrentUser) -> dict:
    # Lock the thread so two concurrent messages cannot interleave agent state.
    thread = _thread_for(conn, user, thread_id, for_update=True)
    _require_reply(conn, user, thread)
    text = body.body.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A message needs text")

    if user.role == "patient":
        if body.draft_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Patients do not send drafts")
        agent.handle_patient_message(conn, user, thread, text)
        _mark_read(conn, user, thread_id)  # the sender has seen the instant automated reply too
        return _detail(conn, user, thread_id)

    agent.add_participant(conn, thread_id, user.id, user.role)
    draft = None
    if body.draft_id:
        if not _uuid_ok(body.draft_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found or already used")
        draft = conn.execute(
            "SELECT id::text, body, source, produced_by FROM communication_drafts WHERE id = %s AND thread_id = %s AND status = 'draft' FOR UPDATE",
            (body.draft_id, thread_id),
        ).fetchone()
        if draft is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found or already used")
    msg = agent.add_message(conn, thread, author_kind=user.role, author_label=user.display_name, body=text,
                            actor=user, author_user_id=user.id,
                            payload={"kind": "reply", "from_draft": draft["source"]} if draft else None)
    if draft:
        conn.execute(
            """
            UPDATE communication_drafts SET status = 'sent', sent_communication_id = %s, decided_by = %s, decided_at = now()
            WHERE id = %s
            """,
            (msg["id"], user.id, draft["id"]),
        )
        audit.record(conn, action="draft_sent", entity_type="communication_draft", entity_id=draft["id"], actor=user,
                     patient_id=thread["patient_id"], agent=draft["produced_by"],
                     detail={"edited": draft["body"].strip() != text, "source": draft["source"]})

    # A human has answered: nobody is waiting, and the agent stops gathering on this thread.
    state = {k: v for k, v in (thread["agent_state"] or {}).items() if k not in ("gathering", "education_given")}
    conn.execute(
        """
        UPDATE communication_threads
        SET awaiting_since = NULL, agent_state = %s,
            priority = CASE WHEN flagged AND flag_acknowledged_at IS NULL THEN 'urgent' ELSE 'routine' END
        WHERE id = %s
        """,
        (Jsonb(state), thread_id),
    )
    if user.role == "clinician":
        resolved = conn.execute(
            """
            UPDATE review_items SET status = 'resolved', resolution = %s, resolved_by = %s, resolved_at = now()
            WHERE link = %s AND practitioner_id = %s AND status = 'open'
              AND kind IN ('agent_escalation', 'doctor_agent_approval')
            RETURNING id::text
            """,
            (f"reply: {text[:200]}", user.id, agent.link_for(thread_id), user.practitioner_id),
        ).fetchall()
        for r in resolved:
            audit.record(conn, action="review_reply", entity_type="review_item", entity_id=r["id"], actor=user,
                         patient_id=thread["patient_id"], detail={"thread_id": thread_id})
    _mark_read(conn, user, thread_id)
    return _detail(conn, user, thread_id)


# ---------------------------------------------------------------------------------------------
# AI-drafted replies
# ---------------------------------------------------------------------------------------------


def record_facts(conn: Connection, patient_id: str) -> list[str]:
    """Approved facts a draft may rely on. No diagnoses: only allergies, the active plan, approved result
    explanations and upcoming visits."""
    facts: list[str] = []
    p = conn.execute("SELECT allergies FROM patients WHERE id = %s", (patient_id,)).fetchone()
    facts.append("Allergies: " + (", ".join(p["allergies"]) or "none recorded"))
    for t in conn.execute(
        """
        SELECT c.title AS plan, t.title, t.status, t.due_on FROM care_plan_tasks t JOIN care_plans c ON c.id = t.care_plan_id
        WHERE c.patient_id = %s AND c.status = 'active' ORDER BY t.position
        """,
        (patient_id,),
    ).fetchall():
        facts.append(f"Care plan '{t['plan']}': {t['title']} ({'done' if t['status'] == 'done' else 'to do'}"
                     + (f", due {t['due_on']:%d %b}" if t["due_on"] and t["status"] != "done" else "") + ")")
    for x in conn.execute(
        """
        SELECT r.name, r.collected_at, x.final_text FROM result_explanations x JOIN diagnostic_reports r ON r.id = x.report_id
        WHERE r.patient_id = %s AND x.status = 'approved' ORDER BY r.collected_at DESC LIMIT 2
        """,
        (patient_id,),
    ).fetchall():
        facts.append(f"Approved explanation of {x['name']} ({x['collected_at']:%d %b %Y}): {x['final_text']}")
    for a in conn.execute(
        """
        SELECT s.starts_at, pr.name FROM appointments a JOIN slots s ON s.id = a.slot_id
        JOIN practitioners pr ON pr.id = a.practitioner_id
        WHERE a.patient_id = %s AND a.status = 'booked' AND s.starts_at > now() ORDER BY s.starts_at LIMIT 3
        """,
        (patient_id,),
    ).fetchall():
        facts.append(f"Upcoming visit: {a['name']} on {a['starts_at']:%a %d %b at %H:%M}")
    return facts


@router.post("/threads/{thread_id}/draft", status_code=status.HTTP_201_CREATED)
def draft_reply(thread_id: str, conn: Conn, user: CurrentUser) -> dict:
    """An AI-drafted reply for the clinician or staff member to edit. It is never sent automatically."""
    thread = _thread_for(conn, user, thread_id)
    if user.role not in WORKFORCE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Drafts are for the care team")
    _require_reply(conn, user, thread)

    messages = conn.execute(
        "SELECT author_label, body FROM communications WHERE thread_id = %s ORDER BY seq DESC LIMIT 30", (thread_id,)
    ).fetchall()[::-1]
    facts = record_facts(conn, thread["patient_id"])
    first_name = thread["patient_name"].split()[0]
    produced_by, model, grounding = "reply-drafter/rules", None, []
    body = None
    if llm.ai_enabled() and consent.ai_allowed(conn, thread["patient_id"]):
        try:
            result = message_triage.claude_draft(messages=messages, facts=facts, sender=user.display_name,
                                                 patient_first_name=first_name, emergency=red_flags.EMERGENCY_NUMBER)
            body = result.output.body.strip()
            grounding = [{"type": "record_fact", "text": f} for f in result.output.facts_used]
            produced_by = f"reply-drafter/claude{'+fallback' if result.fell_back else ''}"
            model = result.model
        except llm.LLMUnavailable:
            body = None
    if not body:
        body = message_triage.template_draft(category=thread["category"], sender=user.display_name,
                                             patient_first_name=first_name, emergency=red_flags.EMERGENCY_NUMBER)
        produced_by, model, grounding = "reply-drafter/rules", None, []
    grounding = [{"type": "thread", "id": thread_id}, *grounding]
    row = conn.execute(
        """
        INSERT INTO communication_drafts (thread_id, patient_id, requested_by, source, body, grounding, produced_by, model)
        VALUES (%s, %s, %s, 'ai_draft', %s, %s, %s, %s)
        RETURNING id::text, source, body, grounding, produced_by, model, created_at
        """,
        (thread_id, thread["patient_id"], user.id, body, Jsonb(grounding), produced_by, model),
    ).fetchone()
    audit.record(conn, action="draft_created", entity_type="communication_draft", entity_id=row["id"], actor=user,
                 patient_id=thread["patient_id"], agent=produced_by, model=model, detail={"thread_id": thread_id})
    return row


@router.post("/drafts/{draft_id}/discard")
def discard_draft(draft_id: str, conn: Conn, user: CurrentUser) -> dict:
    if user.role not in WORKFORCE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Drafts are for the care team")
    row = conn.execute(
        "SELECT id::text, thread_id::text, status FROM communication_drafts WHERE id = %s", (draft_id,)
    ).fetchone() if _uuid_ok(draft_id) else None
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    thread = _thread_for(conn, user, row["thread_id"])
    _require_reply(conn, user, thread)
    if row["status"] != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "Draft already used or discarded")
    conn.execute(
        "UPDATE communication_drafts SET status = 'discarded', decided_by = %s, decided_at = now() WHERE id = %s",
        (user.id, draft_id),
    )
    audit.record(conn, action="draft_discarded", entity_type="communication_draft", entity_id=draft_id, actor=user,
                 patient_id=thread["patient_id"])
    return {"id": draft_id, "status": "discarded"}


# ---------------------------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------------------------


@router.post("/threads/{thread_id}/acknowledge-flag")
def acknowledge_flag(thread_id: str, conn: Conn, user: CurrentUser) -> dict:
    """The clinician has seen the red flag. Resolves the thread's red-flag review item."""
    thread = _thread_for(conn, user, thread_id, for_update=True)
    if user.role != "clinician":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Clinician access required")
    if not thread["flagged"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "This thread is not flagged")
    conn.execute(
        "UPDATE communication_threads SET flag_acknowledged_at = now(), flag_acknowledged_by = %s WHERE id = %s",
        (user.id, thread_id),
    )
    conn.execute(
        """
        UPDATE review_items SET status = 'resolved', resolution = 'acknowledge', resolved_by = %s, resolved_at = now()
        WHERE link = %s AND kind = 'red_flag' AND status = 'open' AND practitioner_id = %s
        """,
        (user.id, agent.link_for(thread_id), user.practitioner_id),
    )
    audit.record(conn, action="red_flag_acknowledged", entity_type="communication_thread", entity_id=thread_id,
                 actor=user, patient_id=thread["patient_id"])
    return _detail(conn, user, thread_id)


class AssignIn(BaseModel):
    to: Literal["clinician", "front_desk", "nurse_triage"]


@router.post("/threads/{thread_id}/assign")
def assign_thread(thread_id: str, body: AssignIn, conn: Conn, user: CurrentUser) -> dict:
    """Hand a thread between the clinician and the front desk or nurse-triage pool."""
    thread = _thread_for(conn, user, thread_id, for_update=True)
    if user.role not in WORKFORCE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Care team access required")
    _require_reply(conn, user, thread)
    if thread["flagged"] and body.to != "clinician":
        raise HTTPException(status.HTTP_409_CONFLICT, "A red-flag thread stays with the clinician")
    agent.assign(conn, thread, body.to)
    agent.add_participant(conn, thread_id, user.id, user.role)
    audit.record(conn, action="thread_assigned", entity_type="communication_thread", entity_id=thread_id, actor=user,
                 patient_id=thread["patient_id"], detail={"to": body.to})
    return _detail(conn, user, thread_id)
