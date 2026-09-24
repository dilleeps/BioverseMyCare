"""Clinician workspace: patient list, pre-visit brief, review queue, Doctor Agent configuration."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from bioverse import audit
from bioverse.auth import Clinician, assert_patient_access
from bioverse.db import DbConn
from bioverse.services import timeline
from bioverse.config import clinic_today

router = APIRouter(prefix="/api/clinician", tags=["clinician"])

Conn = DbConn


@router.get("/patients")
def my_patients(conn: Conn, user: Clinician) -> list[dict]:
    """Patients with an active care plan or an upcoming appointment with this clinician."""
    rows = conn.execute(
        """
        WITH mine AS (
            SELECT patient_id FROM care_plans WHERE practitioner_id = %(pr)s AND status = 'active'
            UNION
            SELECT a.patient_id FROM appointments a JOIN slots s ON s.id = a.slot_id
            WHERE a.practitioner_id = %(pr)s AND a.status = 'booked' AND s.starts_at > now()
            UNION
            SELECT patient_id FROM review_items WHERE practitioner_id = %(pr)s AND status = 'open'
        )
        SELECT p.id::text, p.name, p.birth_date, p.pronouns,
               (SELECT min(s.starts_at) FROM appointments a JOIN slots s ON s.id = a.slot_id
                 WHERE a.patient_id = p.id AND a.practitioner_id = %(pr)s AND a.status = 'booked' AND s.starts_at > now()
               ) AS next_appointment,
               (SELECT count(*) FROM review_items r WHERE r.patient_id = p.id AND r.practitioner_id = %(pr)s
                 AND r.status = 'open') AS open_items
        FROM patients p JOIN mine m ON m.patient_id = p.id
        ORDER BY next_appointment NULLS LAST, p.name
        """,
        {"pr": user.practitioner_id},
    ).fetchall()
    for r in rows:
        r["age"] = timeline.age(r.pop("birth_date"))
    return rows


@router.get("/patients/{patient_id}/brief")
def previsit_brief(patient_id: str, conn: Conn, user: Clinician) -> dict:
    """Assembled from the record, with a source for every line. The clinician accepts or edits it."""
    assert_patient_access(conn, user, patient_id)
    header = timeline.patient_header(conn, patient_id)
    bullets: list[dict[str, Any]] = []
    flags: list[str] = []

    intake = conn.execute(
        """
        SELECT id::text, chief_complaint, urgency, red_flags, specialty, clinician_summary, created_at
        FROM intakes WHERE patient_id = %s ORDER BY created_at DESC LIMIT 1
        """,
        (patient_id,),
    ).fetchone()
    if intake:
        screen = ("RED FLAG: " + ", ".join(intake["red_flags"])) if intake["urgency"] == "emergency" else "red-flag screen negative"
        bullets.append({
            "text": f"Intake on {intake['created_at']:%d %b}: {intake['chief_complaint'].lower()}; {screen}. {intake['clinician_summary']}",
            "source": {"type": "intake", "id": intake["id"]},
        })
        if intake["urgency"] == "emergency":
            flags.append("Red flag at last intake")

    for t in timeline.abnormal_trends(conn, patient_id):
        hist = t["history"] or []
        trend = ""
        if len(hist) >= 2:
            first, last = hist[0], hist[-1]
            direction = "rising" if last["value"] > first["value"] else "falling"
            trend = f", {direction} across {len(hist)} results"
        label = "high" if t["interpretation"] == "H" else "low"
        bullets.append({
            "text": f"{t['display']} {t['value']:g} {t['unit']} ({label}){trend}.",
            "source": {"type": "observation", "loinc": t["loinc_code"]},
        })

    today = clinic_today()
    tasks = conn.execute(
        """
        SELECT t.id::text, t.kind, t.title, t.due_on, t.status, c.id::text AS plan_id
        FROM care_plan_tasks t JOIN care_plans c ON c.id = t.care_plan_id
        WHERE c.patient_id = %s AND c.status = 'active' AND t.status = 'todo'
        ORDER BY t.position
        """,
        (patient_id,),
    ).fetchall()
    for t in tasks:
        if t["kind"] == "medication" and t["due_on"] and t["due_on"] <= today:
            bullets.append({"text": f"{t['title']}: not yet marked started by the patient.",
                            "source": {"type": "care_plan_task", "id": t["id"]}})
            flags.append("Medication not started")
        elif t["kind"] == "referral":
            state = "overdue" if t["due_on"] and t["due_on"] < today else "not yet scheduled"
            bullets.append({"text": f"{t['title']}: {state}.", "source": {"type": "care_plan_task", "id": t["id"]}})
            flags.append("Referral pending")

    for g in conn.execute(
        "SELECT id::text, title, detail FROM care_gaps WHERE patient_id = %s AND status = 'open'", (patient_id,)
    ).fetchall():
        bullets.append({"text": f"{g['title']}. {g['detail']}", "source": {"type": "care_gap", "id": g["id"]}})

    # Lines contributed by modules (bioverse/briefs/).
    from bioverse import briefs

    for b in briefs.collect(conn, patient_id, user.practitioner_id):
        bullets.append({"text": b["text"], "source": b["source"]})
        if b.get("flag"):
            flags.append(b["flag"])

    questions_row = conn.execute(
        """
        SELECT x.questions FROM result_explanations x JOIN diagnostic_reports r ON r.id = x.report_id
        WHERE r.patient_id = %s AND x.status = 'approved' AND jsonb_array_length(x.questions) > 0
        ORDER BY r.collected_at DESC LIMIT 1
        """,
        (patient_id,),
    ).fetchone()
    questions = questions_row["questions"] if questions_row else []

    next_visit = conn.execute(
        """
        SELECT s.starts_at, s.mode FROM appointments a JOIN slots s ON s.id = a.slot_id
        WHERE a.patient_id = %s AND a.practitioner_id = %s AND a.status = 'booked' AND s.starts_at > now()
        ORDER BY s.starts_at LIMIT 1
        """,
        (patient_id, user.practitioner_id),
    ).fetchone()

    audit.record(conn, action="brief_viewed", entity_type="patient", entity_id=patient_id, actor=user,
                 agent="doctor-agent/rules", patient_id=patient_id)
    accepted = conn.execute(
        """
        SELECT occurred_at FROM audit_events
        WHERE action = 'brief_accepted' AND entity_id = %s AND actor_user_id = %s
          AND occurred_at > now() - interval '24 hours'
        ORDER BY occurred_at DESC LIMIT 1
        """,
        (patient_id, user.id),
    ).fetchone()
    return {
        "accepted_at": accepted["occurred_at"] if accepted else None,
        "patient": header,
        "next_visit": next_visit,
        "bullets": bullets,
        "attention_flags": sorted(set(flags)),
        "patient_questions": questions,
        "produced_by": "doctor-agent/rules",
        "timeline": timeline.events(conn, patient_id, limit=12),
    }


@router.post("/patients/{patient_id}/brief/accept")
def accept_brief(patient_id: str, conn: Conn, user: Clinician) -> dict:
    """The clinician has reviewed the drafted brief. Recorded as provenance for the visit."""
    assert_patient_access(conn, user, patient_id)
    audit.record(conn, action="brief_accepted", entity_type="patient", entity_id=patient_id, actor=user,
                 agent="doctor-agent/rules", patient_id=patient_id)
    row = conn.execute("SELECT now() AS at").fetchone()
    return {"accepted_at": row["at"]}


@router.get("/review-queue")
def review_queue(conn: Conn, user: Clinician) -> list[dict]:
    return conn.execute(
        """
        SELECT r.id::text, r.kind, r.title, r.body, r.priority, r.created_at, r.link,
               p.id::text AS patient_id, p.name AS patient_name
        FROM review_items r JOIN patients p ON p.id = r.patient_id
        WHERE r.practitioner_id = %s AND r.status = 'open'
        ORDER BY (r.priority = 'urgent') DESC, r.created_at
        """,
        (user.practitioner_id,),
    ).fetchall()


ALLOWED_ACTIONS = {
    "result_explanation": {"approve", "reject"},
    "agent_escalation": {"reply", "forward_to_staff"},
    "red_flag": {"acknowledge"},
}


class ResolveIn(BaseModel):
    action: Literal["approve", "reject", "reply", "forward_to_staff", "acknowledge"]
    text: str | None = Field(default=None, max_length=4000)


@router.post("/review-items/{item_id}/resolve")
def resolve(item_id: str, body: ResolveIn, conn: Conn, user: Clinician) -> dict:
    item = conn.execute(
        """
        SELECT id::text, kind, ref_id::text, patient_id::text, status, link
        FROM review_items WHERE id = %s AND practitioner_id = %s FOR UPDATE
        """,
        (item_id, user.practitioner_id),
    ).fetchone()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review item not found")
    if item["status"] != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "Already resolved")
    # Kinds owned by modules resolve in their own screens. Those with a link must be decided there;
    # acknowledging them here would close the item and leave the decision (a refill, a referral) undone.
    if item["kind"] not in ALLOWED_ACTIONS and item["link"]:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Decide this in its own screen: {item['link']}")
    if body.action not in ALLOWED_ACTIONS.get(item["kind"], {"acknowledge"}):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'{body.action}' is not valid for {item['kind']}")
    if body.action == "reply" and not (body.text and body.text.strip()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A reply needs text")

    if item["kind"] == "result_explanation":
        if body.action == "approve":
            # AI Draft -> Clinician Review -> Clinician Edit -> Approve -> Publish.
            conn.execute(
                """
                UPDATE result_explanations
                SET status = 'approved', final_text = coalesce(nullif(%s, ''), draft_text),
                    reviewed_by = %s, reviewed_at = now()
                WHERE id = %s
                """,
                ((body.text or "").strip(), user.id, item["ref_id"]),
            )
        else:
            conn.execute(
                "UPDATE result_explanations SET status = 'rejected', reviewed_by = %s, reviewed_at = now() WHERE id = %s",
                (user.id, item["ref_id"]),
            )

    resolution = body.action + (f": {body.text.strip()}" if body.text and body.text.strip() else "")
    conn.execute(
        "UPDATE review_items SET status = 'resolved', resolution = %s, resolved_by = %s, resolved_at = now() WHERE id = %s",
        (resolution, user.id, item_id),
    )
    audit.record(
        conn,
        action=f"review_{body.action}",
        entity_type="review_item",
        entity_id=item_id,
        actor=user,
        patient_id=item["patient_id"],
        detail={"kind": item["kind"], "edited": bool(body.text and body.text.strip())},
    )
    return {"id": item_id, "status": "resolved", "resolution": resolution}


# --- Doctor Agent configuration ------------------------------------------------------------------


class Question(BaseModel):
    id: str
    text: str = Field(min_length=3, max_length=300)
    source: Literal["specialty", "clinician"]
    enabled: bool


class FollowUpStep(BaseModel):
    day: int = Field(ge=0, le=365)
    action: str = Field(min_length=3, max_length=200)


class EscalationRule(BaseModel):
    id: str
    label: str
    action: str
    route_to: str
    locked: bool


class ApprovalRequirement(BaseModel):
    id: str
    label: str
    required: bool
    locked: bool


class AgentConfig(BaseModel):
    active: bool
    previsit_questions: list[Question] = Field(max_length=20)
    followup_protocol: list[FollowUpStep] = Field(max_length=20)
    escalation_rules: list[EscalationRule]
    approval_requirements: list[ApprovalRequirement]


ACTION_CHOICES = {
    "new_symptom": ("gather_then_escalate", "escalate_immediately"),
    "side_effect": ("answer_from_approved_content", "escalate"),
    "logistics": ("handle_via_scheduling", "escalate"),
}
ROUTE_CHOICES = {
    "new_symptom": ("clinician_same_day", "nurse_triage"),
    "side_effect": ("staff_if_unresolved", "clinician"),
    "logistics": ("front_desk", "clinician"),
}


# Starting point for a clinician who hasn't set up their agent yet. The red-flag rule and the two review
# requirements are organization policy, so they are locked exactly as for everyone else.
DEFAULT_CONFIG = {
    "previsit_questions": [
        {"id": "q1", "text": "What would you like to talk about at this visit?", "source": "specialty", "enabled": True},
        {"id": "q2", "text": "Current medications and any missed doses this week", "source": "specialty", "enabled": True},
    ],
    "followup_protocol": [
        {"day": 1, "action": "Check the plan from the visit is clear"},
        {"day": 7, "action": "Ask how things are going and about side effects"},
    ],
    "escalation_rules": [
        {"id": "red_flag", "label": "Red-flag symptom", "action": "emergency_guidance", "route_to": "clinician_and_team_now", "locked": True},
        {"id": "new_symptom", "label": "New or worsening symptom", "action": "gather_then_escalate", "route_to": "clinician_same_day", "locked": False},
        {"id": "side_effect", "label": "Side-effect question", "action": "answer_from_approved_content", "route_to": "staff_if_unresolved", "locked": False},
        {"id": "logistics", "label": "Appointment or logistics", "action": "handle_via_scheduling", "route_to": "front_desk", "locked": False},
    ],
    "approval_requirements": [
        {"id": "abnormal_results", "label": "Abnormal result explanations", "required": True, "locked": True},
        {"id": "medication_instructions", "label": "Medication instructions", "required": True, "locked": True},
        {"id": "normal_results", "label": "Normal result explanations", "required": True, "locked": False},
        {"id": "routine_education", "label": "Routine education from my approved handouts", "required": False, "locked": False},
    ],
}


def _load_config(conn: Connection, practitioner_id: str) -> dict:
    sql = """
        SELECT active, previsit_questions, followup_protocol, escalation_rules, approval_requirements, updated_at
        FROM doctor_agent_configs WHERE practitioner_id = %s
    """
    row = conn.execute(sql, (practitioner_id,)).fetchone()
    if row is None:
        conn.execute(
            """
            INSERT INTO doctor_agent_configs (practitioner_id, previsit_questions, followup_protocol,
                                              escalation_rules, approval_requirements)
            VALUES (%s, %s, %s, %s, %s) ON CONFLICT (practitioner_id) DO NOTHING
            """,
            (practitioner_id, *(Jsonb(DEFAULT_CONFIG[k]) for k in
                                ("previsit_questions", "followup_protocol", "escalation_rules", "approval_requirements"))),
        )
        row = conn.execute(sql, (practitioner_id,)).fetchone()
    return row


@router.get("/agent-config")
def get_agent_config(conn: Conn, user: Clinician) -> dict:
    config = _load_config(conn, user.practitioner_id)
    patients = conn.execute(
        "SELECT count(DISTINCT patient_id) AS n FROM care_plans WHERE practitioner_id = %s AND status = 'active'",
        (user.practitioner_id,),
    ).fetchone()
    return {**config, "active_patients": patients["n"], "choices": {"actions": ACTION_CHOICES, "routes": ROUTE_CHOICES}}


@router.put("/agent-config")
def put_agent_config(body: AgentConfig, conn: Conn, user: Clinician) -> dict:
    current = _load_config(conn, user.practitioner_id)

    # Organization-locked rules are enforced here, not just greyed out in the UI.
    cur_rules = {r["id"]: r for r in current["escalation_rules"]}
    new_rules = {r.id: r.model_dump() for r in body.escalation_rules}
    if set(cur_rules) != set(new_rules):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Escalation rules cannot be added or removed")
    for rid, rule in cur_rules.items():
        new = new_rules[rid]
        if rule["locked"] and new != rule:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'{rule['label']}' is locked by your organization")
        if not rule["locked"]:
            if new["locked"] or new["label"] != rule["label"]:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Rule labels and lock state are not editable")
            if new["action"] not in ACTION_CHOICES.get(rid, ()) or new["route_to"] not in ROUTE_CHOICES.get(rid, ()):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Invalid choice for '{rule['label']}'")

    cur_appr = {a["id"]: a for a in current["approval_requirements"]}
    new_appr = {a.id: a.model_dump() for a in body.approval_requirements}
    if set(cur_appr) != set(new_appr):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Approval requirements cannot be added or removed")
    for aid, req in cur_appr.items():
        new = new_appr[aid]
        if req["locked"] and new != req:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'{req['label']}' is required by your organization")
        if new["locked"] != req["locked"] or new["label"] != req["label"]:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Requirement labels and lock state are not editable")

    # Specialty questions come from the organization's library; clinicians may toggle them but not rewrite them.
    cur_q = {q["id"]: q for q in current["previsit_questions"]}
    for q in body.previsit_questions:
        prior = cur_q.get(q.id)
        if q.source == "specialty" and (prior is None or prior["text"] != q.text):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Specialty questions can be switched on or off, not edited")

    row = conn.execute(
        """
        UPDATE doctor_agent_configs
        SET active = %s, previsit_questions = %s, followup_protocol = %s,
            escalation_rules = %s, approval_requirements = %s, updated_at = now()
        WHERE practitioner_id = %s
        RETURNING active, previsit_questions, followup_protocol, escalation_rules, approval_requirements, updated_at
        """,
        (
            body.active,
            Jsonb([q.model_dump() for q in body.previsit_questions]),
            Jsonb(sorted((s.model_dump() for s in body.followup_protocol), key=lambda s: s["day"])),
            Jsonb([r.model_dump() for r in body.escalation_rules]),
            Jsonb([a.model_dump() for a in body.approval_requirements]),
            user.practitioner_id,
        ),
    ).fetchone()
    audit.record(conn, action="agent_config_updated", entity_type="practitioner", entity_id=user.practitioner_id, actor=user)
    return row
