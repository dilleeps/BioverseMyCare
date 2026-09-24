"""AI Platform governance console (admin): agent registry, AI activity log with traceability,
evaluations, model monitoring and the clinical review matrix.

Everything here reads the platform's own records (audit_events, review_items, result_explanations,
messages). Opening the trace of a patient-facing AI event reads patient data, so it is audited with
the patient's id.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from psycopg import Connection
from pydantic import BaseModel

from bioverse import ai_registry, audit, evals
from bioverse.auth import Admin
from bioverse.db import DbConn

router = APIRouter(prefix="/api/ai", tags=["ai-platform"])

ORG_SCOPE = """(u.organization_id = %(org)s OR p.organization_id = %(org)s
                OR (e.actor_user_id IS NULL AND e.patient_id IS NULL))"""
NOT_AI = ("seed",)  # agent labels that are not AI or rules agents


def _clinic_tz() -> str:
    return os.getenv("BIOVERSE_CLINIC_TZ", "America/New_York")


# =================================================================================================
# Registry
# =================================================================================================


def _latest_runs(conn: Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT DISTINCT ON (suite) suite, id::text, ruleset_version, total, passed, pass_rate, regressions,
               known_gap_failures, sensitivity, sensitivity_gated, gate_passed, created_at
        FROM eval_runs ORDER BY suite, created_at DESC
        """
    ).fetchall()
    return {r["suite"]: r for r in rows}


SUITE_FOR_AGENT = {"red-flag-rules": "red_flags", "intake-agent": "intent_routing"}


@router.get("/agents")
def agents(conn: DbConn, user: Admin) -> list[dict]:
    rows = ai_registry.load(conn)
    prompts = ai_registry.observe_prompts(conn, rows)
    activity = conn.execute(
        """
        SELECT e.agent, count(*) AS n, max(e.occurred_at) AS last_at
        FROM audit_events e LEFT JOIN users u ON u.id = e.actor_user_id LEFT JOIN patients p ON p.id = e.patient_id
        WHERE e.agent IS NOT NULL AND """ + ORG_SCOPE + " GROUP BY e.agent",
        {"org": user.organization_id},
    ).fetchall()
    versions = conn.execute(
        "SELECT agent_id, prompt_hash, prompt_ref, first_seen_at FROM ai_prompt_versions ORDER BY first_seen_at DESC"
    ).fetchall()
    runs = _latest_runs(conn)

    out = []
    for a in rows:
        mine = [r for r in activity if ai_registry.agent_for(r["agent"], [a])]
        prompt = prompts.get(a["id"])
        suite = SUITE_FOR_AGENT.get(a["id"])
        out.append({
            **a,
            "live_model": ai_registry.live_model(a["model"]),
            "prompt": prompt,
            "prompt_versions": [v for v in versions if v["agent_id"] == a["id"]][:10],
            "ruleset_version": ai_registry.ruleset_version() if a["id"] == "red-flag-rules" else None,
            "implementation_detected": prompt is not None or bool(mine),
            "events": sum(r["n"] for r in mine),
            "last_active_at": max((r["last_at"] for r in mine), default=None),
            "paths": sorted({ai_registry.path_of(r["agent"], [a]) or "default" for r in mine}),
            "evaluation": runs.get(suite) if suite else None,
            "evaluation_suite": suite,
        })
    return out


# =================================================================================================
# Activity log and traceability
# =================================================================================================


@router.get("/activity")
def activity(
    conn: DbConn,
    user: Admin,
    agent: str | None = Query(default=None, max_length=100),
    patient: str | None = Query(default=None, max_length=64),
    action: str | None = Query(default=None, max_length=100),
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """AI and rules-agent actions, newest first. `agent` is a registry id or a raw agent label."""
    where = ["e.agent IS NOT NULL", "e.agent <> ALL(%(not_ai)s)", ORG_SCOPE]
    params: dict[str, Any] = {"org": user.organization_id, "not_ai": list(NOT_AI), "limit": limit + 1}
    registry = ai_registry.load(conn)
    if agent:
        entry = next((a for a in registry if a["id"] == agent), None)
        prefixes = entry["audit_agents"] if entry else [agent]
        where.append("(e.agent = ANY(%(prefixes)s) OR split_part(e.agent, '/', 1) = ANY(%(prefixes)s)"
                     " OR e.agent LIKE ANY(%(likes)s))")
        params["prefixes"] = prefixes
        params["likes"] = [p.replace("%", "\\%").replace("_", "\\_") + "/%" for p in prefixes]
    if patient:
        where.append("e.patient_id::text = %(patient)s")
        params["patient"] = patient
    if action:
        where.append("e.action = %(action)s")
        params["action"] = action
    if before_id:
        where.append("e.id < %(before_id)s")
        params["before_id"] = before_id
    rows = conn.execute(
        f"""
        SELECT e.id, e.occurred_at, e.agent, e.model, e.action, e.entity_type, e.entity_id::text AS entity_id,
               e.patient_id::text AS patient_id, p.name AS patient_name, u.display_name AS actor_name,
               coalesce(e.actor_role, u.role) AS actor_role, e.detail
        FROM audit_events e LEFT JOIN users u ON u.id = e.actor_user_id LEFT JOIN patients p ON p.id = e.patient_id
        WHERE {" AND ".join(where)}
        ORDER BY e.id DESC LIMIT %(limit)s
        """,
        params,
    ).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    items = []
    for r in rows:
        entry = ai_registry.agent_for(r["agent"], registry)
        items.append({**r, "agent_id": entry["id"] if entry else None, "agent_name": entry["name"] if entry else None,
                      "path": ai_registry.path_of(r["agent"], registry)})
    return {"items": items, "next_before_id": rows[-1]["id"] if more and rows else None}


def _review_for(conn: Connection, event: dict[str, Any]) -> list[dict[str, Any]]:
    """Human review decisions connected to the event's entity, from the review queue and result explanations."""
    entity_id = event["entity_id"]
    if not entity_id:
        return []
    reviews: list[dict[str, Any]] = []
    for r in conn.execute(
        """
        SELECT r.id::text, r.kind, r.title, r.status, r.resolution, r.resolved_at, r.created_at,
               u.display_name AS reviewer
        FROM review_items r LEFT JOIN users u ON u.id = r.resolved_by
        WHERE r.ref_id = %(id)s::uuid OR r.id = %(id)s::uuid
        """,
        {"id": entity_id},
    ).fetchall():
        reviews.append({"source": "review_queue", **r})
    for x in conn.execute(
        """
        SELECT x.id::text, x.status, x.produced_by, x.reviewed_at, u.display_name AS reviewer,
               (x.final_text IS NOT NULL AND x.final_text <> x.draft_text) AS edited
        FROM result_explanations x LEFT JOIN users u ON u.id = x.reviewed_by
        WHERE x.id = %(id)s::uuid OR x.report_id = %(id)s::uuid
        """,
        {"id": entity_id},
    ).fetchall():
        reviews.append({"source": "result_explanation", **x})
    # Review decisions recorded in the audit trail against the same entity.
    for a in conn.execute(
        """
        SELECT e.id, e.action, e.occurred_at, u.display_name AS reviewer, e.detail
        FROM audit_events e LEFT JOIN users u ON u.id = e.actor_user_id
        WHERE e.entity_id = %s::uuid AND e.action LIKE 'review\\_%%' AND e.id <> %s
        ORDER BY e.id
        """,
        (entity_id, event["id"]),
    ).fetchall():
        reviews.append({"source": "audit", **a})
    return reviews


def _patient_saw(conn: Connection, event: dict[str, Any]) -> dict[str, Any] | None:
    """What the patient was shown as a result of this event, when the platform recorded it."""
    etype, eid = event["entity_type"], event["entity_id"]
    if not eid:
        return None
    if etype == "conversation":
        m = conn.execute(
            """
            SELECT content, payload->>'kind' AS kind, created_at FROM messages
            WHERE conversation_id = %s AND role = 'assistant' AND created_at >= %s
            ORDER BY seq LIMIT 1
            """,
            (eid, event["occurred_at"]),
        ).fetchone()
        if m:
            return {"text": m["content"], "kind": m["kind"], "at": m["created_at"], "source": "conversation message"}
    if etype == "intake":
        i = conn.execute("SELECT patient_summary, created_at FROM intakes WHERE id = %s", (eid,)).fetchone()
        if i:
            return {"text": i["patient_summary"], "kind": "intake summary", "at": i["created_at"], "source": "intake"}
    if etype in ("result_explanation", "diagnostic_report"):
        x = conn.execute(
            """
            SELECT status, final_text, reviewed_at FROM result_explanations WHERE id = %(id)s::uuid OR report_id = %(id)s::uuid
            """,
            {"id": eid},
        ).fetchone()
        if x:
            if x["status"] == "approved":
                return {"text": x["final_text"], "kind": "approved explanation", "at": x["reviewed_at"],
                        "source": "result explanation"}
            return {"text": None, "kind": f"nothing yet: explanation is {x['status'].replace('_', ' ')}",
                    "at": None, "source": "result explanation"}
    return None


@router.get("/activity/{event_id}/trace")
def trace(event_id: int, conn: DbConn, user: Admin) -> dict:
    """Answers the traceability questions of docs/04 for one AI event, as far as the record allows."""
    event = conn.execute(
        f"""
        SELECT e.id, e.occurred_at, e.agent, e.model, e.action, e.entity_type, e.entity_id::text AS entity_id,
               e.patient_id::text AS patient_id, p.name AS patient_name, u.display_name AS actor_name,
               coalesce(e.actor_role, u.role) AS actor_role, e.detail
        FROM audit_events e LEFT JOIN users u ON u.id = e.actor_user_id LEFT JOIN patients p ON p.id = e.patient_id
        WHERE e.id = %(id)s AND e.agent IS NOT NULL AND {ORG_SCOPE}
        """,
        {"id": event_id, "org": user.organization_id},
    ).fetchone()
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "AI event not found")

    registry = ai_registry.load(conn)
    entry = ai_registry.agent_for(event["agent"], registry)
    path = ai_registry.path_of(event["agent"], registry)
    detail = event["detail"] or {}
    deterministic = event["model"] is None and (
        path == "rules" or bool(entry and entry["model"] == ai_registry.DETERMINISTIC)
    )

    if detail.get("prompt_version"):
        prompt = {"hash": detail["prompt_version"], "basis": "recorded on the event"}
    elif deterministic:
        prompt = {"hash": None, "basis": "no prompt: deterministic rules"
                  + (f" (ruleset {detail['ruleset']})" if detail.get("ruleset") else "")}
    elif entry:
        at = ai_registry.prompt_version_at(conn, entry["id"], event["occurred_at"])
        prompt = ({"hash": at["prompt_hash"], "ref": at["prompt_ref"], "first_seen_at": at["first_seen_at"],
                   "basis": "inferred: the fingerprint the registry had observed when the event happened"}
                  if at else {"hash": None, "basis": "not recorded, and no fingerprint had been observed yet"})
    else:
        prompt = {"hash": None, "basis": "not recorded"}

    reviews = _review_for(conn, event)
    saw = _patient_saw(conn, event)
    sources = detail.get("sources") or detail.get("citations")

    audit.record(conn, action="ai_trace_viewed", entity_type="audit_event", actor=user,
                 patient_id=event["patient_id"], detail={"event_id": event_id})

    answers = [
        {"question": "Which agent produced it?",
         "answer": f"{entry['name']} ({event['agent']})" if entry else event["agent"],
         "recorded": True},
        {"question": "Which model and prompt version?",
         "answer": (event["model"] or ("none: deterministic rules" if deterministic else "not recorded"))
                   + (f"; prompt {prompt['hash'][:12]}" if prompt.get("hash") else "")
                   + f" ({prompt['basis']})",
         "recorded": bool(event["model"]) or deterministic},
        {"question": "What context did it see?",
         "answer": ("Patient record of " + (event["patient_name"] or "an unknown patient") if event["patient_id"] else "No patient context")
                   + f"; {event['entity_type']}" + (f" {event['entity_id']}" if event["entity_id"] else "")
                   + ". Full inputs are not stored on the audit event.",
         "recorded": event["patient_id"] is not None},
        {"question": "What sources did it cite?",
         "answer": ", ".join(map(str, sources)) if sources else "None recorded (this agent does not cite sources)",
         "recorded": bool(sources)},
        {"question": "Which human reviewed it, when, and what changed?",
         "answer": "; ".join(_describe_review(r) for r in reviews) if reviews else "No human review is linked to this event",
         "recorded": bool(reviews)},
        {"question": "What did the patient see, and when?",
         "answer": (f"{saw['kind']}" + (f" at {saw['at'].isoformat()}" if saw and saw.get("at") else "")) if saw else "Not recorded for this kind of event",
         "recorded": saw is not None},
    ]
    return {
        "event": event,
        "agent": entry,
        "path": path,
        "prompt": prompt,
        "reviews": reviews,
        "patient_saw": saw,
        "answers": answers,
    }


def _describe_review(r: dict[str, Any]) -> str:
    who = r.get("reviewer") or "unassigned"
    if r["source"] == "review_queue":
        state = r["resolution"] or r["status"]
        return f"Review queue ({r['kind']}): {state} by {who}" + (f" on {r['resolved_at']:%d %b %Y %H:%M}" if r.get("resolved_at") else "")
    if r["source"] == "result_explanation":
        edited = ", edited before release" if r.get("edited") else ""
        return f"Result explanation {r['status'].replace('_', ' ')} by {who}{edited}" + (f" on {r['reviewed_at']:%d %b %Y %H:%M}" if r.get("reviewed_at") else "")
    return f"{r['action'].replace('_', ' ')} by {who} on {r['occurred_at']:%d %b %Y %H:%M}"


# =================================================================================================
# Evaluations
# =================================================================================================

Suite = Literal["red_flags", "intent_routing"]


@router.get("/evals/cases")
def eval_cases(conn: DbConn, user: Admin, suite: Suite = "red_flags") -> list[dict]:
    return evals.load_cases(conn, suite)


class RunIn(BaseModel):
    suite: Suite


@router.post("/evals/run", status_code=status.HTTP_201_CREATED)
def run_eval(body: RunIn, conn: DbConn, user: Admin) -> dict:
    result = evals.run(conn, body.suite, user.id)
    audit.record(conn, action="evaluation_run", entity_type="eval_run", entity_id=result["id"], actor=user,
                 detail={"suite": body.suite, "ruleset": result["ruleset_version"], "passed": result["passed"],
                         "total": result["total"], "regressions": result["regressions"]})
    return result


@router.get("/evals/runs")
def eval_runs(conn: DbConn, user: Admin, suite: Suite | None = None, limit: int = Query(default=20, ge=1, le=100)) -> list[dict]:
    return conn.execute(
        """
        SELECT r.id::text, r.suite, r.ruleset_version, r.total, r.passed, r.pass_rate, r.regressions,
               r.known_gap_failures, r.sensitivity, r.sensitivity_gated, r.gate_passed, r.failures, r.created_at,
               u.display_name AS run_by
        FROM eval_runs r LEFT JOIN users u ON u.id = r.run_by
        WHERE %(suite)s::text IS NULL OR r.suite = %(suite)s
        ORDER BY r.created_at DESC LIMIT %(limit)s
        """,
        {"suite": suite, "limit": limit},
    ).fetchall()


# =================================================================================================
# Monitoring
# =================================================================================================

TRIAGE_PATHS = ("claude", "claude+fallback", "rules")


@router.get("/monitoring")
def monitoring(conn: DbConn, user: Admin, days: int = Query(default=30, ge=1, le=365)) -> dict:
    tz = _clinic_tz()
    params = {"org": user.organization_id, "days": days, "tz": tz}
    daily = conn.execute(
        f"""
        WITH span AS (
            SELECT generate_series((now() AT TIME ZONE %(tz)s)::date - (%(days)s - 1), (now() AT TIME ZONE %(tz)s)::date,
                                   interval '1 day')::date AS day
        ),
        ev AS (
            SELECT (e.occurred_at AT TIME ZONE %(tz)s)::date AS day, e.action, e.agent
            FROM audit_events e LEFT JOIN users u ON u.id = e.actor_user_id LEFT JOIN patients p ON p.id = e.patient_id
            WHERE e.occurred_at >= (((now() AT TIME ZONE %(tz)s)::date - (%(days)s - 1))::timestamp AT TIME ZONE %(tz)s)
              AND {ORG_SCOPE}
        )
        SELECT s.day,
               count(ev.*) FILTER (WHERE ev.action = 'triage' AND ev.agent = 'intake-agent/claude') AS claude,
               count(ev.*) FILTER (WHERE ev.action = 'triage' AND ev.agent = 'intake-agent/claude+fallback') AS claude_fallback,
               count(ev.*) FILTER (WHERE ev.action = 'triage' AND ev.agent = 'intake-agent/rules') AS rules,
               count(ev.*) FILTER (WHERE ev.action = 'red_flag_escalation') AS escalations,
               count(ev.*) FILTER (WHERE ev.action = 'safety_check_requested') AS safety_checks,
               count(ev.*) FILTER (WHERE ev.action ILIKE '%%refus%%') AS refusals
        FROM span s LEFT JOIN ev ON ev.day = s.day
        GROUP BY s.day ORDER BY s.day
        """,
        params,
    ).fetchall()

    totals = {k: sum(d[k] for d in daily) for k in ("claude", "claude_fallback", "rules", "escalations", "safety_checks", "refusals")}
    triaged = totals["claude"] + totals["claude_fallback"] + totals["rules"]

    esc_by = conn.execute(
        f"""
        SELECT coalesce(e.agent, 'unknown') AS source, count(*) AS n
        FROM audit_events e LEFT JOIN users u ON u.id = e.actor_user_id LEFT JOIN patients p ON p.id = e.patient_id
        WHERE e.action = 'red_flag_escalation' AND e.occurred_at >= now() - make_interval(days => %(days)s)
          AND {ORG_SCOPE}
        GROUP BY 1 ORDER BY 2 DESC
        """,
        params,
    ).fetchall()

    review = conn.execute(
        """
        SELECT count(*) FILTER (WHERE x.status IN ('approved', 'rejected')) AS reviewed,
               count(*) FILTER (WHERE x.status = 'rejected') AS rejected,
               count(*) FILTER (WHERE x.status = 'approved' AND x.final_text IS DISTINCT FROM x.draft_text) AS edited,
               count(*) FILTER (WHERE x.status = 'pending_review') AS pending
        FROM result_explanations x JOIN diagnostic_reports r ON r.id = x.report_id JOIN patients p ON p.id = r.patient_id
        WHERE p.organization_id = %(org)s
          AND (x.status = 'pending_review' OR x.reviewed_at >= now() - make_interval(days => %(days)s))
        """,
        params,
    ).fetchone()

    return {
        "days": days,
        "timezone": tz,
        "daily": daily,
        "totals": {
            **totals,
            "triaged": triaged,
            "rules_share": round(totals["rules"] / triaged, 4) if triaged else None,
            "fallback_share": round(totals["claude_fallback"] / triaged, 4) if triaged else None,
            "escalation_rate": round(totals["escalations"] / (triaged + totals["escalations"]), 4)
            if (triaged + totals["escalations"]) else None,
        },
        "escalations_by_source": esc_by,
        "review": {
            **review,
            "rejection_rate": round(review["rejected"] / review["reviewed"], 4) if review["reviewed"] else None,
        },
        "guardrails": {
            "safety_checks_requested": totals["safety_checks"],
            "note": "Guardrail triggers are the structured safety checks the red-flag engine asked for. "
                    "Prompt-injection and PHI-leakage guardrails do not record events yet.",
        },
        "refusals": {
            "count": totals["refusals"],
            "recorded": totals["refusals"] > 0,
            "note": "Model refusals fall back to the rules path inside the orchestrator and are not written to the "
                    "audit trail yet, so a refusal shows up only as a 'rules' triage.",
        },
    }


# =================================================================================================
# Clinical review matrix
# =================================================================================================


@router.get("/review-matrix")
def review_matrix(conn: DbConn, user: Admin) -> list[dict]:
    return conn.execute(
        "SELECT id::text, position, output_type, review_level, default_policy, rationale FROM review_policies ORDER BY position"
    ).fetchall()
