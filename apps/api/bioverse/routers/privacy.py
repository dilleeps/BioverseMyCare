"""Patient Privacy Center (Trust and Safety): my consents, who accessed my record, my privacy export.

Patients only, and only their own record. Consent changes go through `bioverse.consent`, which audits
every change with the patient's id.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
from psycopg import Connection
from pydantic import BaseModel

from bioverse import audit, consent
from bioverse.auth import Patient
from bioverse.db import DbConn

router = APIRouter(prefix="/api/privacy", tags=["privacy"])

# Scopes a patient may change here. Caregiver access is owned by the Family module (/family).
SELF_SERVICE = ("ai_processing", "research_matching")

SCOPES: dict[str, dict[str, str]] = {
    "ai_processing": {
        "title": "Let AI help with my messages",
        "on": "Bioverse's AI reads what you write so it can ask better questions, summarize what you said for "
              "your care team, and point you to the right care.",
        "off": "Bioverse uses fixed rules only. It still checks every message for warning signs and still routes "
               "you to care, but replies are simpler and summaries are shorter. No AI model sees your messages.",
        "always": "Warning-sign checks always run, and clinicians review anything clinical before you see it.",
    },
    "research_matching": {
        "title": "Tell me about research studies I may qualify for",
        "on": "Bioverse may compare your record with open research studies and let you know when one could fit. "
              "Nobody from a study contacts you unless you agree to that study separately.",
        "off": "Your record is not matched to research studies and nobody contacts you about research.",
        "always": "Joining a study always needs its own separate agreement.",
    },
    "caregiver_access": {
        "title": "Someone who can help with my care",
        "on": "This person can see or do the things listed below on your behalf.",
        "off": "This person no longer has access to your record.",
        "always": "Manage who can help you in Family and caregivers.",
    },
}

# Plain-language descriptions of audit actions, for "who accessed my record".
ACTIONS = {
    "report_viewed": "Opened one of your lab reports",
    "brief_viewed": "Opened your pre-visit summary",
    "brief_accepted": "Reviewed your pre-visit summary",
    "triage": "Sorted your request and chose where to send it",
    "intake_created": "Wrote a summary of what you told Bioverse for your care team",
    "red_flag_escalation": "Flagged a possible emergency and alerted your care team",
    "safety_check_requested": "Asked you safety questions about a symptom",
    "safety_check_answered": "Recorded your answers to safety questions",
    "conversation_started": "Started a conversation with Bioverse",
    "appointment_booked": "Booked an appointment",
    "appointment_cancelled": "Cancelled an appointment",
    "task_updated": "Updated a task in your care plan",
    "review_approve": "Approved an explanation of your results",
    "review_reject": "Sent an explanation of your results back for changes",
    "review_reply": "Replied to your question",
    "review_acknowledge": "Acknowledged an alert about you",
    "review_forward_to_staff": "Passed your question to the care team",
    "explanation_drafted": "Drafted an explanation of your results for your doctor to check",
    "consent_granted": "Turned a privacy choice on",
    "consent_denied": "Turned a privacy choice off",
    "consent_revoked": "Withdrew a permission",
    "break_glass": "Opened your record under emergency access",
    "incident_reported": "Reported a safety or privacy concern involving your record",
    "incident_updated": "Updated a safety or privacy concern involving your record",
    "privacy_export": "Downloaded your privacy report",
    "ai_trace_viewed": "Reviewed how Bioverse's AI handled one of your requests",
}

ROLE_LABELS = {"patient": "Patient", "clinician": "Clinician", "staff": "Staff", "admin": "Administrator",
               "system": "Bioverse system"}

AGENT_LABELS = {
    "intake-agent": "Bioverse intake assistant",
    "safety/red-flags": "Bioverse safety check",
    "doctor-agent": "Doctor Agent",
    "results-agent": "Bioverse results assistant",
    "scheduling-agent": "Bioverse scheduling",
}


def humanize_action(action: str) -> str:
    if action in ACTIONS:
        return ACTIONS[action]
    words = action.replace("_", " ").replace("-", " ").strip()
    return words[:1].upper() + words[1:] if words else action


def agent_label(agent: str | None) -> str | None:
    if not agent:
        return None
    for prefix, label in AGENT_LABELS.items():
        if agent == prefix or agent.startswith(prefix + "/"):
            return label
    return agent


def _consents(conn: Connection, patient_id: str) -> dict[str, Any]:
    rows = {(r["scope"], r["grantee"]): r for r in consent.list_for(conn, patient_id)}
    choices = []
    for scope in SELF_SERVICE:
        row = rows.get((scope, ""))
        granted = consent.is_granted(conn, patient_id, scope)
        info = SCOPES[scope]
        choices.append({
            "scope": scope,
            "title": info["title"],
            "granted": granted,
            "explanation": info["on"] if granted else info["off"],
            "when_on": info["on"],
            "when_off": info["off"],
            "always": info["always"],
            "is_default": row is None,
            "status": row["status"] if row else None,
            "updated_at": row["updated_at"] if row else None,
        })

    caregivers = []
    grantee_ids = [g for (s, g) in rows if s == "caregiver_access" and g]
    names: dict[str, str] = {}
    if grantee_ids:
        valid = []
        for g in grantee_ids:
            try:
                valid.append(str(UUID(g)))
            except ValueError:
                continue
        if valid:
            names = {
                r["id"]: r["display_name"]
                for r in conn.execute(
                    "SELECT id::text, display_name FROM users WHERE id = ANY(%s::uuid[])", (valid,)
                ).fetchall()
            }
    for (scope, grantee), row in rows.items():
        if scope != "caregiver_access":
            continue
        caregivers.append({
            "grantee": grantee,
            "name": names.get(grantee, "A person you named"),
            "granted": consent.is_granted(conn, patient_id, scope, grantee),
            "status": row["status"],
            "permissions": (row["detail"] or {}).get("permissions", []),
            "expires_at": row["expires_at"],
            "updated_at": row["updated_at"],
        })

    other = [
        {"scope": r["scope"], "grantee": r["grantee"] or None, "status": r["status"], "updated_at": r["updated_at"]}
        for (scope, _), r in rows.items()
        if scope not in SCOPES
    ]
    return {"choices": choices, "caregivers": caregivers, "other": other,
            "ai_allowed": consent.ai_allowed(conn, patient_id)}


@router.get("/consents")
def my_consents(conn: DbConn, user: Patient) -> dict:
    return _consents(conn, user.patient_id)


class ConsentIn(BaseModel):
    granted: bool


@router.put("/consents/{scope}")
def set_consent(scope: str, body: ConsentIn, conn: DbConn, user: Patient) -> dict:
    if scope not in SELF_SERVICE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This permission can't be changed here")
    # consent.set_status writes the audit event (consent_granted / consent_denied) with patient_id.
    consent.set_status(
        conn,
        patient_id=user.patient_id,
        scope=scope,
        status="granted" if body.granted else "denied",
        actor=user,
        detail={"source": "privacy_center"},
    )
    return _consents(conn, user.patient_id)


def _access_log(conn: Connection, patient_id: str, user_id: str, include_mine: bool, before_id: int | None,
                limit: int) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT e.id, e.occurred_at, e.action, e.entity_type, e.agent, e.actor_role,
               e.actor_user_id::text AS actor_id, u.display_name AS actor_name, u.role AS user_role,
               e.detail->>'reason' AS reason
        FROM audit_events e LEFT JOIN users u ON u.id = e.actor_user_id
        WHERE e.patient_id = %(p)s
          AND (%(mine)s OR e.actor_user_id IS DISTINCT FROM %(me)s::uuid)
          AND (%(before)s::bigint IS NULL OR e.id < %(before)s::bigint)
        ORDER BY e.id DESC
        LIMIT %(limit)s
        """,
        {"p": patient_id, "mine": include_mine, "me": user_id, "before": before_id, "limit": limit + 1},
    ).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    items = []
    for r in rows:
        is_me = r["actor_id"] == user_id
        role = r["user_role"] or r["actor_role"] or "system"
        if is_me:
            who = "You"
        elif r["actor_name"]:
            who = r["actor_name"]
        else:
            who = agent_label(r["agent"]) or "Bioverse system"
        items.append({
            "id": r["id"],
            "at": r["occurred_at"],
            "who": who,
            "role": "You" if is_me else ROLE_LABELS.get(role, role.title()),
            "what": humanize_action(r["action"]),
            "action": r["action"],
            "via": agent_label(r["agent"]) if r["agent"] and r["actor_name"] else None,
            "is_me": is_me,
            "emergency_access": r["action"] == "break_glass",
            "reason": r["reason"] if r["action"] == "break_glass" else None,
        })
    return {"items": items, "next_before_id": rows[-1]["id"] if more and rows else None}


@router.get("/access-log")
def access_log(
    conn: DbConn,
    user: Patient,
    include_mine: bool = False,
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Audit events about me. By default leaves out what I did myself."""
    return _access_log(conn, user.patient_id, user.id, include_mine, before_id, limit)


@router.get("/export")
def export(conn: DbConn, user: Patient) -> Response:
    """My consents and my complete access log, as a JSON file."""
    items: list[dict[str, Any]] = []
    before = None
    while True:
        page = _access_log(conn, user.patient_id, user.id, True, before, 200)
        items += page["items"]
        before = page["next_before_id"]
        if before is None or len(items) >= 20000:
            break
    body = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "patient_id": user.patient_id,
        "name": user.display_name,
        "about": "Your Bioverse privacy report: the permissions you have given and every recorded access "
                 "to your record. Your health record itself is exported from Records.",
        "consents": _consents(conn, user.patient_id),
        "access_log": items,
    }
    audit.record(conn, action="privacy_export", entity_type="patient", entity_id=user.patient_id, actor=user,
                 patient_id=user.patient_id, detail={"events": len(items)})
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(
        content=json.dumps(body, default=str, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="bioverse-privacy-{stamp}.json"'},
    )
