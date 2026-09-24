"""Trust and Safety governance: compliance audit search, tamper evidence, break-glass access,
retention policies (dry run only) and safety / privacy incidents.

Access: the audit trail, retention and incident triage are for organization admins. Clinicians use
break-glass and report incidents. Every write is audited, with the patient's id when one is involved.

Break-glass grants are recorded and time-limited here, but other modules' access checks do not consult
them yet (`has_active_grant` is the hook they would call). Retention never deletes anything in this
version: the dry run only counts.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Iterable, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from bioverse import audit
from bioverse.auth import Admin, Clinician, CurrentUser, User, assert_patient_access
from bioverse.db import DbConn

router = APIRouter(prefix="/api/governance", tags=["governance"])


def require_clinician_or_admin(user: CurrentUser) -> User:
    if user.role == "admin" or (user.role == "clinician" and user.practitioner_id):
        return user
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Clinician or administrator access required")


ClinicianOrAdmin = Annotated[User, Depends(require_clinician_or_admin)]


# =================================================================================================
# Compliance audit search
# =================================================================================================

MAX_PAGE = 200
MAX_EXPORT = 50_000


class AuditFilters(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    actor: str | None = None          # user id
    patient: str | None = None        # patient id
    action: str | None = None
    entity_type: str | None = None
    agent_only: bool = False
    break_glass_only: bool = False
    q: str | None = None


def _filters(
    date_from: date | None = None,
    date_to: date | None = None,
    actor: str | None = Query(default=None, max_length=64),
    patient: str | None = Query(default=None, max_length=64),
    action: str | None = Query(default=None, max_length=100),
    entity_type: str | None = Query(default=None, max_length=100),
    agent_only: bool = False,
    break_glass_only: bool = False,
    q: str | None = Query(default=None, max_length=200),
) -> AuditFilters:
    return AuditFilters(date_from=date_from, date_to=date_to, actor=actor or None, patient=patient or None,
                        action=action or None, entity_type=entity_type or None, agent_only=agent_only,
                        break_glass_only=break_glass_only, q=(q or "").strip() or None)


Filters = Annotated[AuditFilters, Depends(_filters)]


def _uuid_or_422(value: str, field: str) -> str:
    from uuid import UUID

    try:
        return str(UUID(value))
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{field} must be an id") from None


def _search_sql(f: AuditFilters, org: str, before_id: int | None, limit: int) -> tuple[str, dict[str, Any]]:
    where = [
        # Events belong to this organization through their actor or their patient; system events with
        # neither are platform-wide and visible to every organization admin.
        "(u.organization_id = %(org)s OR p.organization_id = %(org)s"
        " OR (e.actor_user_id IS NULL AND e.patient_id IS NULL))"
    ]
    params: dict[str, Any] = {"org": org, "limit": limit}
    if f.date_from:
        where.append("e.occurred_at >= %(date_from)s::date")
        params["date_from"] = f.date_from
    if f.date_to:
        where.append("e.occurred_at < %(date_to)s::date + 1")
        params["date_to"] = f.date_to
    if f.actor:
        where.append("e.actor_user_id = %(actor)s::uuid")
        params["actor"] = _uuid_or_422(f.actor, "actor")
    if f.patient:
        where.append("e.patient_id = %(patient)s::uuid")
        params["patient"] = _uuid_or_422(f.patient, "patient")
    if f.action:
        where.append("e.action = %(action)s")
        params["action"] = f.action
    if f.entity_type:
        where.append("e.entity_type = %(entity_type)s")
        params["entity_type"] = f.entity_type
    if f.agent_only:
        where.append("e.agent IS NOT NULL")
    if f.break_glass_only:
        where.append("e.action LIKE 'break_glass%%'")
    if f.q:
        where.append(
            "(e.action ILIKE %(q)s OR e.entity_type ILIKE %(q)s OR e.agent ILIKE %(q)s OR e.model ILIKE %(q)s"
            " OR u.display_name ILIKE %(q)s OR p.name ILIKE %(q)s OR e.entity_id::text ILIKE %(q)s"
            " OR e.detail::text ILIKE %(q)s)"
        )
        params["q"] = "%" + f.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    if before_id is not None:
        where.append("e.id < %(before_id)s")
        params["before_id"] = before_id
    sql = f"""
        SELECT e.id, e.occurred_at, e.actor_user_id::text AS actor_id, u.display_name AS actor_name,
               coalesce(e.actor_role, u.role) AS actor_role, e.agent, e.model, e.action, e.entity_type,
               e.entity_id::text AS entity_id, e.patient_id::text AS patient_id, p.name AS patient_name, e.detail
        FROM audit_events e
        LEFT JOIN users u ON u.id = e.actor_user_id
        LEFT JOIN patients p ON p.id = e.patient_id
        WHERE {" AND ".join(where)}
        ORDER BY e.id DESC
        LIMIT %(limit)s
    """
    return sql, params


def _item(r: dict[str, Any]) -> dict[str, Any]:
    return {**r, "break_glass": r["action"].startswith("break_glass"), "ai": r["agent"] is not None}


@router.get("/audit")
def search_audit(
    f: Filters,
    conn: DbConn,
    user: Admin,
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE),
) -> dict:
    """Keyset-paginated audit search, newest first. Pass `next_before_id` back as `before_id`."""
    sql, params = _search_sql(f, user.organization_id, before_id, limit + 1)
    rows = conn.execute(sql, params).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [_item(r) for r in rows], "next_before_id": rows[-1]["id"] if more and rows else None}


@router.get("/audit/facets")
def audit_facets(conn: DbConn, user: Admin) -> dict:
    """Values for the audit filters."""
    org = user.organization_id
    actions = [r["action"] for r in conn.execute(
        "SELECT DISTINCT action FROM audit_events ORDER BY action LIMIT 500").fetchall()]
    entity_types = [r["entity_type"] for r in conn.execute(
        "SELECT DISTINCT entity_type FROM audit_events ORDER BY entity_type LIMIT 500").fetchall()]
    actors = conn.execute(
        "SELECT id::text, display_name, role FROM users WHERE organization_id = %s ORDER BY role, display_name",
        (org,),
    ).fetchall()
    patients = conn.execute(
        "SELECT id::text, name FROM patients WHERE organization_id = %s ORDER BY name", (org,)
    ).fetchall()
    return {"actions": actions, "entity_types": entity_types, "actors": actors, "patients": patients}


def _csv_cell(value: Any) -> str:
    """Spreadsheet-safe: a cell that starts with a formula character is prefixed with a quote."""
    if value is None:
        return ""
    text = json.dumps(value, default=str, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
    if isinstance(value, datetime):
        text = value.astimezone(timezone.utc).isoformat()
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


CSV_COLUMNS = ["id", "occurred_at", "actor_name", "actor_role", "actor_id", "agent", "model", "action",
               "entity_type", "entity_id", "patient_name", "patient_id", "break_glass", "detail"]


@router.get("/audit/export.csv")
def export_audit(f: Filters, conn: DbConn, user: Admin) -> Response:
    """The same search as a CSV file (newest first, up to 50,000 rows). The export itself is audited."""
    sql, params = _search_sql(f, user.organization_id, None, MAX_EXPORT)
    rows = conn.execute(sql, params).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for r in rows:
        item = _item(r)
        writer.writerow([_csv_cell(item[c]) for c in CSV_COLUMNS])
    audit.record(conn, action="audit_exported", entity_type="audit_events", actor=user,
                 patient_id=params.get("patient"),
                 detail={"rows": len(rows), "filters": f.model_dump(mode="json", exclude_defaults=True)})
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="bioverse-audit-{stamp}.csv"'},
    )


# =================================================================================================
# Tamper evidence: a hash chain beside the append-only audit trail
# =================================================================================================

GENESIS = "0" * 64
CHAIN_LOCK = 80_080  # advisory lock id: one chain builder at a time

EVENT_COLUMNS = """e.id, e.occurred_at, e.actor_user_id::text AS actor_user_id, e.actor_role, e.agent, e.model,
                   e.action, e.entity_type, e.entity_id::text AS entity_id, e.patient_id::text AS patient_id,
                   e.detail"""


def canonical(row: dict[str, Any]) -> str:
    """The exact bytes that are hashed for one audit event. Stable across reads and time zones."""
    occurred = row["occurred_at"]
    if isinstance(occurred, datetime):
        occurred = occurred.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return json.dumps(
        {
            "id": row["id"],
            "occurred_at": occurred,
            "actor_user_id": row["actor_user_id"],
            "actor_role": row["actor_role"],
            "agent": row["agent"],
            "model": row["model"],
            "action": row["action"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "patient_id": row["patient_id"],
            "detail": row["detail"],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def link_hash(prev_hash: str, row: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical(row)).encode("utf-8")).hexdigest()


def verify_rows(events: Iterable[dict[str, Any]], chain: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Pure check of a chain (in seq order) against a set of event rows.

    Reports the first link whose event is missing, whose prev_hash does not follow on from the link
    before it, or whose stored hash no longer matches the event's contents.
    """
    by_id = {e["id"]: e for e in events}
    prev = GENESIS
    checked = 0
    for link in chain:
        event = by_id.get(link["event_id"])
        problem = None
        if event is None:
            problem = "event missing from the audit trail"
        elif link["prev_hash"] != prev:
            problem = "chain link broken (previous hash does not match)"
        elif link_hash(prev, event) != link["hash"]:
            problem = "event contents differ from when they were chained"
        if problem:
            return {"ok": False, "checked": checked, "head_hash": prev,
                    "first_mismatch": {"seq": link["seq"], "event_id": link["event_id"], "reason": problem}}
        prev = link["hash"]
        checked += 1
    return {"ok": True, "checked": checked, "head_hash": prev, "first_mismatch": None}


def load_chain(conn: Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chain = conn.execute("SELECT seq, event_id, prev_hash, hash FROM audit_chain ORDER BY seq").fetchall()
    events = conn.execute(
        f"SELECT {EVENT_COLUMNS} FROM audit_events e JOIN audit_chain c ON c.event_id = e.id"
    ).fetchall()
    return events, chain


@router.post("/audit/verify")
def verify_audit_chain(conn: DbConn, user: Admin) -> dict:
    """Check every chained event, then extend the chain with events not yet chained.

    Does not extend a broken chain: a mismatch is reported and nothing is appended.
    """
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (CHAIN_LOCK,))
    events, chain = load_chain(conn)
    result = verify_rows(events, chain)
    appended = 0
    if result["ok"]:
        prev = result["head_hash"]
        new_events = conn.execute(
            f"""
            SELECT {EVENT_COLUMNS} FROM audit_events e
            WHERE NOT EXISTS (SELECT 1 FROM audit_chain c WHERE c.event_id = e.id)
            ORDER BY e.id
            """
        ).fetchall()
        links = []
        for event in new_events:
            h = link_hash(prev, event)
            links.append((event["id"], prev, h))
            prev = h
        if links:
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO audit_chain (event_id, prev_hash, hash) VALUES (%s, %s, %s)", links)
        appended = len(links)
        result["head_hash"] = prev
    total = conn.execute("SELECT count(*) AS n FROM audit_chain").fetchone()["n"]
    audit.record(conn, action="audit_chain_verified", entity_type="audit_chain", actor=user,
                 detail={"ok": result["ok"], "checked": result["checked"], "appended": appended,
                         "first_mismatch": result["first_mismatch"]})
    return {**result, "appended": appended, "chain_length": total,
            "verified_at": datetime.now(timezone.utc).isoformat()}


@router.get("/audit/chain")
def chain_status(conn: DbConn, user: Admin) -> dict:
    row = conn.execute(
        """
        SELECT (SELECT count(*) FROM audit_chain) AS chained,
               (SELECT count(*) FROM audit_events e WHERE NOT EXISTS
                    (SELECT 1 FROM audit_chain c WHERE c.event_id = e.id)) AS unchained,
               (SELECT hash FROM audit_chain ORDER BY seq DESC LIMIT 1) AS head_hash,
               (SELECT max(chained_at) FROM audit_chain) AS last_chained_at
        """
    ).fetchone()
    last = conn.execute(
        """
        SELECT occurred_at, detail FROM audit_events WHERE action = 'audit_chain_verified'
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    return {**row, "last_verification": last}


# =================================================================================================
# Break-glass access
# =================================================================================================


def has_active_grant(conn: Connection, user_id: str, patient_id: str) -> bool:
    """Hook for other modules' access checks (not wired into them in this version)."""
    return conn.execute(
        """
        SELECT 1 FROM break_glass_grants
        WHERE user_id = %s AND patient_id = %s AND revoked_at IS NULL AND expires_at > now() LIMIT 1
        """,
        (user_id, patient_id),
    ).fetchone() is not None


class BreakGlassIn(BaseModel):
    patient_id: str
    reason: str = Field(min_length=15, max_length=1000)
    minutes: int = Field(default=60, ge=5, le=240)


GRANT_COLUMNS = """g.id::text, g.patient_id::text, p.name AS patient_name, g.user_id::text, u.display_name AS user_name,
                   g.reason, g.created_at, g.expires_at, g.revoked_at,
                   (g.revoked_at IS NULL AND g.expires_at > now()) AS active"""


@router.get("/break-glass/patients")
def break_glass_patient_search(conn: DbConn, user: Clinician, q: str = Query(min_length=2, max_length=100)) -> list[dict]:
    """Find a patient in the organization by name, to request emergency access."""
    like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    return conn.execute(
        """
        SELECT id::text, name, extract(year FROM birth_date)::int AS birth_year
        FROM patients WHERE organization_id = %s AND name ILIKE %s ORDER BY name LIMIT 10
        """,
        (user.organization_id, like),
    ).fetchall()


@router.post("/break-glass", status_code=status.HTTP_201_CREATED)
def break_glass(body: BreakGlassIn, conn: DbConn, user: Clinician) -> dict:
    patient_id = _uuid_or_422(body.patient_id, "patient_id")
    assert_patient_access(conn, user, patient_id)
    reason = " ".join(body.reason.split())
    if len(reason) < 15:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give a reason of at least 15 characters")
    row = conn.execute(
        """
        INSERT INTO break_glass_grants (patient_id, user_id, reason, expires_at)
        VALUES (%s, %s, %s, now() + make_interval(mins => %s))
        RETURNING id::text
        """,
        (patient_id, user.id, reason, body.minutes),
    ).fetchone()
    grant = conn.execute(
        f"""SELECT {GRANT_COLUMNS} FROM break_glass_grants g JOIN patients p ON p.id = g.patient_id
            JOIN users u ON u.id = g.user_id WHERE g.id = %s""",
        (row["id"],),
    ).fetchone()
    audit.record(conn, action="break_glass", entity_type="break_glass_grant", entity_id=row["id"], actor=user,
                 patient_id=patient_id,
                 detail={"reason": reason, "minutes": body.minutes, "expires_at": grant["expires_at"]})
    return grant


@router.get("/break-glass/mine")
def my_break_glass(conn: DbConn, user: Clinician) -> list[dict]:
    return conn.execute(
        f"""SELECT {GRANT_COLUMNS} FROM break_glass_grants g JOIN patients p ON p.id = g.patient_id
            JOIN users u ON u.id = g.user_id WHERE g.user_id = %s ORDER BY g.created_at DESC LIMIT 50""",
        (user.id,),
    ).fetchall()


@router.post("/break-glass/{grant_id}/end")
def end_break_glass(grant_id: str, conn: DbConn, user: Clinician) -> dict:
    grant_id = _uuid_or_422(grant_id, "grant")
    row = conn.execute(
        """
        UPDATE break_glass_grants SET revoked_at = now()
        WHERE id = %s AND user_id = %s AND revoked_at IS NULL AND expires_at > now()
        RETURNING id::text, patient_id::text
        """,
        (grant_id, user.id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active grant")
    audit.record(conn, action="break_glass_ended", entity_type="break_glass_grant", entity_id=grant_id,
                 actor=user, patient_id=row["patient_id"])
    return {"id": grant_id, "active": False}


@router.get("/break-glass")
def all_break_glass(conn: DbConn, user: Admin, active_only: bool = False) -> list[dict]:
    return conn.execute(
        f"""SELECT {GRANT_COLUMNS} FROM break_glass_grants g JOIN patients p ON p.id = g.patient_id
            JOIN users u ON u.id = g.user_id
            WHERE p.organization_id = %s AND (NOT %s OR (g.revoked_at IS NULL AND g.expires_at > now()))
            ORDER BY g.created_at DESC LIMIT 200""",
        (user.organization_id, active_only),
    ).fetchall()


# =================================================================================================
# Retention policies: configuration and a dry run. Nothing is deleted in this version.
# =================================================================================================

RETENTION_CATEGORIES = {
    "conversations": {"label": "Front-door conversations", "table": "conversations", "min_days": 30},
    "messages": {"label": "Conversation messages", "table": "messages", "min_days": 30},
    "audit_events": {"label": "Audit events", "table": "audit_events", "min_days": 2190},
    "documents": {"label": "Lab reports and documents", "table": "diagnostic_reports", "min_days": 365},
}

# Per category: rows in this organization, and the timestamp that ages them.
_RETENTION_COUNTS = {
    "conversations": """
        SELECT count(*) FILTER (WHERE c.created_at < %(cutoff)s) AS would_purge, count(*) AS total,
               min(c.created_at) AS oldest
        FROM conversations c JOIN patients p ON p.id = c.patient_id WHERE p.organization_id = %(org)s""",
    "messages": """
        SELECT count(*) FILTER (WHERE m.created_at < %(cutoff)s) AS would_purge, count(*) AS total,
               min(m.created_at) AS oldest
        FROM messages m JOIN conversations c ON c.id = m.conversation_id JOIN patients p ON p.id = c.patient_id
        WHERE p.organization_id = %(org)s""",
    "audit_events": """
        SELECT count(*) FILTER (WHERE e.occurred_at < %(cutoff)s) AS would_purge, count(*) AS total,
               min(e.occurred_at) AS oldest
        FROM audit_events e LEFT JOIN users u ON u.id = e.actor_user_id LEFT JOIN patients p ON p.id = e.patient_id
        WHERE u.organization_id = %(org)s OR p.organization_id = %(org)s""",
    "documents": """
        SELECT count(*) FILTER (WHERE r.collected_at < %(cutoff)s) AS would_purge, count(*) AS total,
               min(r.collected_at) AS oldest
        FROM diagnostic_reports r JOIN patients p ON p.id = r.patient_id WHERE p.organization_id = %(org)s""",
}


def _policies(conn: Connection, org: str) -> list[dict[str, Any]]:
    rows = {
        r["category"]: r
        for r in conn.execute(
            """
            SELECT r.category, r.retention_days, r.notes, r.updated_at, u.display_name AS updated_by
            FROM retention_policies r LEFT JOIN users u ON u.id = r.updated_by
            WHERE r.organization_id = %s
            """,
            (org,),
        ).fetchall()
    }
    out = []
    for cat, info in RETENTION_CATEGORIES.items():
        r = rows.get(cat)
        out.append({
            "category": cat, "label": info["label"], "min_days": info["min_days"],
            "retention_days": r["retention_days"] if r else None, "notes": r["notes"] if r else "",
            "updated_at": r["updated_at"] if r else None, "updated_by": r["updated_by"] if r else None,
        })
    return out


@router.get("/retention")
def get_retention(conn: DbConn, user: Admin) -> dict:
    return {"policies": _policies(conn, user.organization_id), "deletion_enabled": False}


class RetentionIn(BaseModel):
    retention_days: int = Field(ge=30, le=36500)
    notes: str = Field(default="", max_length=500)


@router.put("/retention/{category}")
def put_retention(category: str, body: RetentionIn, conn: DbConn, user: Admin) -> dict:
    info = RETENTION_CATEGORIES.get(category)
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown data category")
    if body.retention_days < info["min_days"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"{info['label']} must be kept at least {info['min_days']} days")
    before = conn.execute(
        "SELECT retention_days FROM retention_policies WHERE organization_id = %s AND category = %s",
        (user.organization_id, category),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO retention_policies (organization_id, category, retention_days, notes, updated_by)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (organization_id, category) DO UPDATE
          SET retention_days = EXCLUDED.retention_days, notes = EXCLUDED.notes,
              updated_by = EXCLUDED.updated_by, updated_at = now()
        """,
        (user.organization_id, category, body.retention_days, body.notes.strip(), user.id),
    )
    audit.record(conn, action="retention_policy_updated", entity_type="retention_policy", actor=user,
                 detail={"category": category, "from_days": before["retention_days"] if before else None,
                         "to_days": body.retention_days})
    return {"policies": _policies(conn, user.organization_id), "deletion_enabled": False}


@router.post("/retention/dry-run")
def retention_dry_run(conn: DbConn, user: Admin) -> dict:
    """Count what each policy would purge today. Deletes nothing."""
    now = conn.execute("SELECT now() AS now").fetchone()["now"]
    out = []
    for p in _policies(conn, user.organization_id):
        if p["retention_days"] is None:
            out.append({**p, "cutoff": None, "would_purge": 0, "total": None, "oldest": None})
            continue
        cutoff = now - timedelta(days=p["retention_days"])
        counts = conn.execute(_RETENTION_COUNTS[p["category"]], {"cutoff": cutoff, "org": user.organization_id}).fetchone()
        out.append({**p, "cutoff": cutoff, **counts})
    audit.record(conn, action="retention_dry_run", entity_type="retention_policy", actor=user,
                 detail={c["category"]: c["would_purge"] for c in out})
    return {"as_of": now, "dry_run": True, "deleted": 0, "categories": out,
            "note": "Dry run only. This version of Bioverse never deletes data under a retention policy."}


# =================================================================================================
# Safety and privacy incidents
# =================================================================================================

IncidentCategory = Literal["ai_safety", "privacy", "security", "clinical_safety"]
Severity = Literal["low", "moderate", "high", "critical"]
IncidentStatus = Literal["open", "investigating", "resolved"]

TRANSITIONS = {"open": {"investigating", "resolved"}, "investigating": {"resolved", "open"}, "resolved": {"investigating"}}


class IncidentIn(BaseModel):
    category: IncidentCategory
    severity: Severity
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=5000)
    patient_id: str | None = None
    linked_entity_type: str | None = Field(default=None, max_length=60)
    linked_entity_id: str | None = Field(default=None, max_length=100)


class TransitionIn(BaseModel):
    status: IncidentStatus
    note: str = Field(default="", max_length=2000)


INCIDENT_COLUMNS = """i.id::text, i.category, i.severity, i.title, i.description, i.patient_id::text,
                      p.name AS patient_name, i.linked_entity_type, i.linked_entity_id, i.status, i.resolution,
                      i.history, i.created_at, i.updated_at, i.resolved_at, i.reported_by::text,
                      u.display_name AS reported_by_name, u.role AS reported_by_role"""
INCIDENT_FROM = """FROM safety_incidents i JOIN users u ON u.id = i.reported_by
                   LEFT JOIN patients p ON p.id = i.patient_id"""


def _incident(conn: Connection, incident_id: str, user: User) -> dict[str, Any]:
    incident_id = _uuid_or_422(incident_id, "incident")
    row = conn.execute(
        f"SELECT {INCIDENT_COLUMNS} {INCIDENT_FROM} WHERE i.id = %s AND i.organization_id = %s",
        (incident_id, user.organization_id),
    ).fetchone()
    if row is None or (user.role != "admin" and row["reported_by"] != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incident not found")
    return row


@router.post("/incidents", status_code=status.HTTP_201_CREATED)
def report_incident(body: IncidentIn, conn: DbConn, user: ClinicianOrAdmin) -> dict:
    patient_id = None
    if body.patient_id:
        patient_id = _uuid_or_422(body.patient_id, "patient_id")
        assert_patient_access(conn, user, patient_id)
    history = [{"status": "open", "at": datetime.now(timezone.utc).isoformat(), "by": user.display_name,
                "note": "Reported"}]
    row = conn.execute(
        """
        INSERT INTO safety_incidents (organization_id, reported_by, category, severity, title, description,
                                      patient_id, linked_entity_type, linked_entity_id, history)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text
        """,
        (user.organization_id, user.id, body.category, body.severity, body.title.strip(), body.description.strip(),
         patient_id, (body.linked_entity_type or "").strip() or None, (body.linked_entity_id or "").strip() or None,
         Jsonb(history)),
    ).fetchone()
    audit.record(conn, action="incident_reported", entity_type="safety_incident", entity_id=row["id"], actor=user,
                 patient_id=patient_id, detail={"category": body.category, "severity": body.severity})
    return _incident(conn, row["id"], user)


@router.get("/incidents")
def list_incidents(conn: DbConn, user: ClinicianOrAdmin, status_filter: IncidentStatus | None = Query(default=None, alias="status")) -> list[dict]:
    """Admins see every incident in the organization; clinicians see the ones they reported."""
    return conn.execute(
        f"""
        SELECT {INCIDENT_COLUMNS} {INCIDENT_FROM}
        WHERE i.organization_id = %(org)s
          AND (%(admin)s OR i.reported_by = %(me)s)
          AND (%(status)s::text IS NULL OR i.status = %(status)s)
        ORDER BY (i.status = 'resolved'), array_position(ARRAY['critical','high','moderate','low'], i.severity),
                 i.created_at DESC
        LIMIT 200
        """,
        {"org": user.organization_id, "admin": user.role == "admin", "me": user.id, "status": status_filter},
    ).fetchall()


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, conn: DbConn, user: ClinicianOrAdmin) -> dict:
    return _incident(conn, incident_id, user)


@router.post("/incidents/{incident_id}/transition")
def transition_incident(incident_id: str, body: TransitionIn, conn: DbConn, user: Admin) -> dict:
    current = _incident(conn, incident_id, user)
    if body.status not in TRANSITIONS[current["status"]]:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Can't move an incident from {current['status']} to {body.status}")
    note = body.note.strip()
    if body.status == "resolved" and not note:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Say how the incident was resolved")
    entry = {"status": body.status, "at": datetime.now(timezone.utc).isoformat(), "by": user.display_name,
             "note": note or None}
    conn.execute(
        """
        UPDATE safety_incidents
        SET status = %s, history = history || %s::jsonb, updated_at = now(),
            resolution = CASE WHEN %s = 'resolved' THEN %s ELSE resolution END,
            resolved_at = CASE WHEN %s = 'resolved' THEN now() ELSE NULL END
        WHERE id = %s
        """,
        (body.status, Jsonb([entry]), body.status, note, body.status, current["id"]),
    )
    audit.record(conn, action="incident_updated", entity_type="safety_incident", entity_id=current["id"], actor=user,
                 patient_id=current["patient_id"],
                 detail={"from": current["status"], "to": body.status})
    return _incident(conn, current["id"], user)
