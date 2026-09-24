"""Family and caregivers: proxy access, dependents, emergency contacts.

Access model (docs/04-safety-and-governance.md, "Consent"):

- A caregiver's access to a patient is a `caregiver_access` consent on that patient with
  grantee = the caregiver's user id and `detail.permissions` listing what they may see or do.
  `detail.proxy = true` makes them a full proxy: every permission, and they may manage the
  patient's other caregivers. Status, expiry and revocation all live on the consent, so
  `consent.is_granted` is the single gate. `related_persons` only records who they are.
- Only the patient, or an existing full proxy, grants and revokes. A proxy may create another
  full proxy only for a dependent under 18. Anyone may give up their own access.
- Every caregiver read and write checks the specific permission first, then audits with
  actor = the caregiver and patient_id = the dependent. Denied means 403.

Adolescent privacy. Rules for 13-17 year olds differ by jurisdiction; this is one simple, conservative
rule, isolated in `_adolescent_results_ok` so a deployment can replace it:
    For a dependent aged 13 to 17, `view_results` only takes effect when the dependent has ALSO
    granted it themselves (consent scope `caregiver_results_adolescent`, grantee = the caregiver).
    A parent-proxy granting `view_results` is not enough on its own.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from psycopg import Connection
from pydantic import BaseModel, Field

from bioverse import audit, consent
from bioverse.auth import CurrentUser, User
from bioverse.db import DbConn
from bioverse.services.timeline import age

router = APIRouter(prefix="/api/family", tags=["family"])

Conn = DbConn

SCOPE = "caregiver_access"
ADOLESCENT_SCOPE = "caregiver_results_adolescent"
Permission = Literal["view_appointments", "book_appointments", "view_care_plan", "view_results",
                     "view_medications", "message_care_team"]
PERMISSIONS: tuple[str, ...] = ("view_appointments", "book_appointments", "view_care_plan", "view_results",
                                "view_medications", "message_care_team")
PERMISSION_LABELS = {
    "view_appointments": "See appointments",
    "book_appointments": "Book appointments",
    "view_care_plan": "See the care plan",
    "view_results": "See results (clinician-reviewed only)",
    "view_medications": "See medicines",
    "message_care_team": "Message the care team",
}
Relationship = Literal["parent", "child", "spouse", "other"]
ADOLESCENT_AGES = range(13, 18)


# --- Access checks ------------------------------------------------------------------------------------


def _patient(conn: Connection, patient_id: str, user: User) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id::text, user_id::text, name, birth_date, pronouns, organization_id::text FROM patients WHERE id::text = %s",
        (patient_id,),
    ).fetchone()
    if row is None or row["organization_id"] != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    row["age"] = age(row["birth_date"])
    return row


def grant_of(conn: Connection, patient_id: str, caregiver_user_id: str) -> dict[str, Any] | None:
    """The caregiver's active grant, or None if absent, revoked, denied or expired."""
    if not consent.is_granted(conn, patient_id, SCOPE, caregiver_user_id):
        return None
    row = consent.get(conn, patient_id, SCOPE, caregiver_user_id)
    detail = row["detail"] or {}
    proxy = bool(detail.get("proxy"))
    perms = set(PERMISSIONS) if proxy else set(detail.get("permissions") or []) & set(PERMISSIONS)
    return {"permissions": perms, "proxy": proxy, "expires_at": row["expires_at"]}


def _adolescent_results_ok(conn: Connection, patient: dict[str, Any], caregiver_user_id: str) -> bool:
    if patient["age"] not in ADOLESCENT_AGES:
        return True
    return consent.is_granted(conn, patient["id"], ADOLESCENT_SCOPE, caregiver_user_id)


def effective_permissions(conn: Connection, patient: dict[str, Any], caregiver_user_id: str) -> set[str]:
    grant = grant_of(conn, patient["id"], caregiver_user_id)
    if grant is None:
        return set()
    perms = set(grant["permissions"])
    if "view_results" in perms and not _adolescent_results_ok(conn, patient, caregiver_user_id):
        perms.discard("view_results")
    return perms


def require_permission(conn: Connection, user: User, patient_id: str, permission: str) -> dict[str, Any]:
    patient = _patient(conn, patient_id, user)
    if patient["user_id"] == user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This is your own record. Open it from your own screens.")
    if permission not in effective_permissions(conn, patient, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have permission to do this for this person")
    return patient


def _manager_role(conn: Connection, user: User, patient: dict[str, Any]) -> str:
    """'self' when the user is the patient, 'proxy' when they hold full proxy. Otherwise 403."""
    if user.patient_id == patient["id"]:
        return "self"
    grant = grant_of(conn, patient["id"], user.id)
    if grant and grant["proxy"]:
        return "proxy"
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the patient or their full proxy can manage access")


def _audit_read(conn: Connection, user: User, patient_id: str, what: str) -> None:
    audit.record(conn, action=f"caregiver_viewed_{what}", entity_type="patient", entity_id=patient_id, actor=user,
                 patient_id=patient_id, detail={"via": SCOPE})


# --- Overview -----------------------------------------------------------------------------------------


def _caregivers_of(conn: Connection, patient: dict[str, Any]) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT c.grantee, c.status, c.detail, c.expires_at, c.updated_at, u.display_name, u.email,
               rp.relationship
        FROM consents c
        JOIN users u ON u.id::text = c.grantee
        LEFT JOIN related_persons rp ON rp.patient_id = c.patient_id AND rp.user_id::text = c.grantee
        WHERE c.patient_id = %s AND c.scope = %s
        ORDER BY c.status = 'granted' DESC, u.display_name
        """,
        (patient["id"], SCOPE),
    ).fetchall()
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        detail = r["detail"] or {}
        state = r["status"]
        if state == "granted" and r["expires_at"] is not None and r["expires_at"] <= now:
            state = "expired"
        proxy = bool(detail.get("proxy"))
        perms = list(PERMISSIONS) if proxy else [p for p in PERMISSIONS if p in (detail.get("permissions") or [])]
        out.append({
            "user_id": r["grantee"],
            "name": r["display_name"],
            "email": r["email"],
            "relationship": r["relationship"] or detail.get("relationship") or "other",
            "permissions": perms,
            "proxy": proxy,
            "status": "active" if state == "granted" else state,
            "expires_at": r["expires_at"],
            "updated_at": r["updated_at"],
            "results_need_own_consent": patient["age"] in ADOLESCENT_AGES and "view_results" in perms
                                         and not consent.is_granted(conn, patient["id"], ADOLESCENT_SCOPE, r["grantee"]),
        })
    return out


def _contacts(conn: Connection, patient_id: str) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id::text, name, relationship, phone, notes, created_at FROM emergency_contacts
        WHERE patient_id = %s ORDER BY created_at
        """,
        (patient_id,),
    ).fetchall()


@router.get("/me")
def overview(conn: Conn, user: CurrentUser) -> dict:
    """People I care for, who can see my care, and my emergency contacts."""
    rows = conn.execute(
        """
        SELECT p.id::text, p.user_id::text, p.name, p.birth_date, p.pronouns, p.organization_id::text,
               rp.relationship
        FROM consents c
        JOIN patients p ON p.id = c.patient_id
        LEFT JOIN related_persons rp ON rp.patient_id = c.patient_id AND rp.user_id::text = c.grantee
        WHERE c.scope = %s AND c.grantee = %s AND c.status = 'granted'
          AND (c.expires_at IS NULL OR c.expires_at > now()) AND p.organization_id = %s
        ORDER BY p.name
        """,
        (SCOPE, user.id, user.organization_id),
    ).fetchall()
    caring_for = []
    for p in rows:
        p["age"] = age(p["birth_date"])
        grant = grant_of(conn, p["id"], user.id)
        perms = effective_permissions(conn, p, user.id)
        caring_for.append({
            "patient_id": p["id"],
            "name": p["name"],
            "age": p["age"],
            "pronouns": p["pronouns"],
            "relationship": p["relationship"] or "other",
            "proxy": grant["proxy"] if grant else False,
            "permissions": [x for x in PERMISSIONS if x in perms],
            "expires_at": grant["expires_at"] if grant else None,
            "adolescent": p["age"] in ADOLESCENT_AGES,
        })

    mine = None
    if user.patient_id:
        me = _patient(conn, user.patient_id, user)
        mine = {
            "patient_id": me["id"],
            "adolescent": me["age"] in ADOLESCENT_AGES,
            "caregivers": _caregivers_of(conn, me),
            "emergency_contacts": _contacts(conn, me["id"]),
        }
    return {
        "permissions": [{"id": p, "label": PERMISSION_LABELS[p]} for p in PERMISSIONS],
        "relationships": ["parent", "child", "spouse", "other"],
        "caring_for": caring_for,
        "me": mine,
    }


# --- Granting and revoking ------------------------------------------------------------------------------


class GrantIn(BaseModel):
    user_id: str | None = None
    email: str | None = Field(default=None, max_length=200)
    relationship: Relationship
    permissions: list[Permission] = Field(default_factory=list)
    proxy: bool = False
    expires_at: datetime | None = None


def _grantee(conn: Connection, user: User, body: GrantIn) -> dict[str, Any]:
    if body.user_id:
        row = conn.execute("SELECT id::text, display_name, organization_id::text FROM users WHERE id::text = %s",
                           (body.user_id,)).fetchone()
    elif body.email:
        row = conn.execute("SELECT id::text, display_name, organization_id::text FROM users WHERE lower(email) = lower(%s)",
                           (body.email.strip(),)).fetchone()
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Say who should get access (user_id or email)")
    if row is None or row["organization_id"] != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Bioverse account with that email")
    return row


@router.get("/patients/{patient_id}/caregivers")
def list_caregivers(patient_id: str, conn: Conn, user: CurrentUser) -> dict:
    patient = _patient(conn, patient_id, user)
    _manager_role(conn, user, patient)
    return {"patient_id": patient_id, "name": patient["name"], "caregivers": _caregivers_of(conn, patient)}


@router.put("/patients/{patient_id}/caregivers")
def grant(patient_id: str, body: GrantIn, conn: Conn, user: CurrentUser) -> dict:
    """Grant or change a caregiver's access. Replaces their permissions and expiry."""
    patient = _patient(conn, patient_id, user)
    role = _manager_role(conn, user, patient)
    grantee = _grantee(conn, user, body)
    if grantee["id"] == patient["user_id"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A person can't be their own caregiver")
    if not body.proxy and not body.permissions:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose at least one permission, or revoke access")
    if body.expires_at is not None:
        expires = body.expires_at if body.expires_at.tzinfo else body.expires_at.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The end date must be in the future")
    else:
        expires = None

    existing = grant_of(conn, patient_id, grantee["id"])
    if role == "proxy":
        if grantee["id"] == user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "A proxy can't change their own access")
        creates_or_edits_proxy = body.proxy or (existing is not None and existing["proxy"])
        if creates_or_edits_proxy and patient["age"] >= 18:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the patient can give or change full proxy access")

    permissions = list(PERMISSIONS) if body.proxy else [p for p in PERMISSIONS if p in body.permissions]
    conn.execute(
        """
        INSERT INTO related_persons (patient_id, user_id, relationship, created_by) VALUES (%s, %s, %s, %s)
        ON CONFLICT (patient_id, user_id) DO UPDATE SET relationship = EXCLUDED.relationship, updated_at = now()
        """,
        (patient_id, grantee["id"], body.relationship, user.id),
    )
    consent.set_status(
        conn, patient_id=patient_id, scope=SCOPE, status="granted", actor=user, grantee=grantee["id"],
        detail={"permissions": permissions, "proxy": body.proxy, "relationship": body.relationship},
        expires_at=expires,
    )
    # An adolescent granting results themselves is their own consent for the results rule.
    if role == "self" and patient["age"] in ADOLESCENT_AGES:
        own = "granted" if "view_results" in permissions else "revoked"
        if own == "granted" or consent.get(conn, patient_id, ADOLESCENT_SCOPE, grantee["id"]) is not None:
            consent.set_status(conn, patient_id=patient_id, scope=ADOLESCENT_SCOPE, status=own, actor=user,
                               grantee=grantee["id"], expires_at=expires)
    audit.record(conn, action="caregiver_access_granted", entity_type="related_person", entity_id=None, actor=user,
                 patient_id=patient_id,
                 detail={"caregiver": grantee["id"], "permissions": permissions, "proxy": body.proxy,
                         "expires_at": expires, "granted_by": role})
    return {"patient_id": patient_id, "caregivers": _caregivers_of(conn, patient)}


@router.delete("/patients/{patient_id}/caregivers/{caregiver_user_id}")
def revoke(patient_id: str, caregiver_user_id: str, conn: Conn, user: CurrentUser) -> dict:
    patient = _patient(conn, patient_id, user)
    if caregiver_user_id == user.id:
        role = "caregiver"  # anyone may give up their own access
    else:
        role = _manager_role(conn, user, patient)
        existing = grant_of(conn, patient_id, caregiver_user_id)
        if role == "proxy" and existing and existing["proxy"] and patient["age"] >= 18:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the patient can remove a full proxy")
    row = consent.get(conn, patient_id, SCOPE, caregiver_user_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No access to revoke")
    consent.set_status(conn, patient_id=patient_id, scope=SCOPE, status="revoked", actor=user,
                       grantee=caregiver_user_id, detail=row["detail"])
    if consent.get(conn, patient_id, ADOLESCENT_SCOPE, caregiver_user_id) is not None:
        consent.set_status(conn, patient_id=patient_id, scope=ADOLESCENT_SCOPE, status="revoked", actor=user,
                           grantee=caregiver_user_id)
    audit.record(conn, action="caregiver_access_revoked", entity_type="related_person", entity_id=None, actor=user,
                 patient_id=patient_id, detail={"caregiver": caregiver_user_id, "revoked_by": role})
    return {"patient_id": patient_id, "revoked": caregiver_user_id}


class ResultsSharingIn(BaseModel):
    share: bool


@router.put("/patients/{patient_id}/results-sharing/{caregiver_user_id}")
def adolescent_results_sharing(patient_id: str, caregiver_user_id: str, body: ResultsSharingIn, conn: Conn,
                               user: CurrentUser) -> dict:
    """A 13-17 year old's own decision to let a caregiver see their results. Only they can make it."""
    patient = _patient(conn, patient_id, user)
    if user.patient_id != patient_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the patient can decide this")
    if patient["age"] not in ADOLESCENT_AGES:
        raise HTTPException(status.HTTP_409_CONFLICT, "This choice only applies to patients aged 13 to 17")
    grant_row = consent.get(conn, patient_id, SCOPE, caregiver_user_id)
    consent.set_status(conn, patient_id=patient_id, scope=ADOLESCENT_SCOPE,
                       status="granted" if body.share else "revoked", actor=user, grantee=caregiver_user_id,
                       expires_at=grant_row["expires_at"] if grant_row else None)
    return {"patient_id": patient_id, "caregivers": _caregivers_of(conn, patient)}


# --- The dependent view ---------------------------------------------------------------------------------


@router.get("/dependents/{patient_id}")
def dependent(patient_id: str, conn: Conn, user: CurrentUser) -> dict:
    patient = _patient(conn, patient_id, user)
    grant_row = grant_of(conn, patient_id, user.id)
    if grant_row is None or patient["user_id"] == user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have access to this person's care")
    perms = effective_permissions(conn, patient, user.id)
    _audit_read(conn, user, patient_id, "summary")
    rel = conn.execute("SELECT relationship FROM related_persons WHERE patient_id = %s AND user_id = %s",
                       (patient_id, user.id)).fetchone()
    return {
        "patient_id": patient_id,
        "name": patient["name"],
        "age": patient["age"],
        "pronouns": patient["pronouns"],
        "relationship": rel["relationship"] if rel else "other",
        "proxy": grant_row["proxy"],
        "expires_at": grant_row["expires_at"],
        "permissions": [p for p in PERMISSIONS if p in perms],
        "results_need_own_consent": patient["age"] in ADOLESCENT_AGES and "view_results" in grant_row["permissions"]
                                     and "view_results" not in perms,
        "permission_labels": PERMISSION_LABELS,
    }


def _appointments(conn: Connection, patient_id: str) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT a.id::text, a.status, a.reason, s.starts_at, s.mode, s.duration_min,
               pr.name AS practitioner_name, pr.specialty, pr.location_name
        FROM appointments a JOIN slots s ON s.id = a.slot_id JOIN practitioners pr ON pr.id = a.practitioner_id
        WHERE a.patient_id = %s AND a.status = 'booked' AND s.starts_at > now()
        ORDER BY s.starts_at
        """,
        (patient_id,),
    ).fetchall()


@router.get("/dependents/{patient_id}/appointments")
def dependent_appointments(patient_id: str, conn: Conn, user: CurrentUser) -> list[dict]:
    require_permission(conn, user, patient_id, "view_appointments")
    _audit_read(conn, user, patient_id, "appointments")
    return _appointments(conn, patient_id)


def _tasks(conn: Connection, patient_id: str) -> tuple[dict | None, list[dict]]:
    plan = conn.execute(
        """
        SELECT c.id::text, c.title, c.started_at, pr.name AS practitioner_name, pr.specialty
        FROM care_plans c JOIN practitioners pr ON pr.id = c.practitioner_id
        WHERE c.patient_id = %s AND c.status = 'active' ORDER BY c.started_at DESC LIMIT 1
        """,
        (patient_id,),
    ).fetchone()
    if plan is None:
        return None, []
    tasks = conn.execute(
        """
        SELECT id::text, position, kind, title, detail, specialty, due_on, status, completed_at
        FROM care_plan_tasks WHERE care_plan_id = %s ORDER BY position
        """,
        (plan["id"],),
    ).fetchall()
    today = date.today()
    for t in tasks:
        t["overdue"] = t["status"] == "todo" and t["due_on"] is not None and t["due_on"] < today
    return plan, tasks


@router.get("/dependents/{patient_id}/care-plan")
def dependent_care_plan(patient_id: str, conn: Conn, user: CurrentUser) -> dict | None:
    """The active care plan. Medicine tasks are left out unless the caregiver may also see medicines."""
    patient = require_permission(conn, user, patient_id, "view_care_plan")
    plan, tasks = _tasks(conn, patient_id)
    _audit_read(conn, user, patient_id, "care_plan")
    if plan is None:
        return None
    can_see_meds = "view_medications" in effective_permissions(conn, patient, user.id)
    visible = [t for t in tasks if can_see_meds or t["kind"] != "medication"]
    return {**plan, "tasks": visible, "hidden_medication_tasks": len(tasks) - len(visible),
            "done_count": sum(1 for t in visible if t["status"] == "done"), "total_count": len(visible)}


@router.get("/dependents/{patient_id}/medications")
def dependent_medications(patient_id: str, conn: Conn, user: CurrentUser) -> list[dict]:
    require_permission(conn, user, patient_id, "view_medications")
    _audit_read(conn, user, patient_id, "medications")
    return conn.execute(
        """
        SELECT t.id::text, t.title, t.detail, t.due_on, t.status, t.completed_at, c.title AS plan_title,
               pr.name AS prescriber
        FROM care_plan_tasks t JOIN care_plans c ON c.id = t.care_plan_id
        JOIN practitioners pr ON pr.id = c.practitioner_id
        WHERE c.patient_id = %s AND c.status = 'active' AND t.kind = 'medication'
        ORDER BY t.status = 'done', t.position
        """,
        (patient_id,),
    ).fetchall()


@router.get("/dependents/{patient_id}/results")
def dependent_results(patient_id: str, conn: Conn, user: CurrentUser) -> list[dict]:
    """Reports with values and explanation ONLY once a clinician approved the explanation. Anything not yet
    reviewed shows as awaiting review, with no values and no draft."""
    require_permission(conn, user, patient_id, "view_results")
    reports = conn.execute(
        """
        SELECT r.id::text, r.name, r.lab_name, r.collected_at, x.status AS explanation_status, x.final_text,
               x.questions, x.reviewed_at, u.display_name AS reviewed_by
        FROM diagnostic_reports r
        LEFT JOIN result_explanations x ON x.report_id = r.id
        LEFT JOIN users u ON u.id = x.reviewed_by
        WHERE r.patient_id = %s ORDER BY r.collected_at DESC
        """,
        (patient_id,),
    ).fetchall()
    out = []
    for r in reports:
        approved = r["explanation_status"] == "approved" and r["final_text"] is not None
        item = {"id": r["id"], "name": r["name"], "lab_name": r["lab_name"], "collected_at": r["collected_at"],
                "status": "reviewed" if approved else "awaiting_review"}
        if approved:
            item["explanation"] = r["final_text"]
            item["questions"] = r["questions"] or []
            item["reviewed_by"] = r["reviewed_by"]
            item["reviewed_at"] = r["reviewed_at"]
            item["observations"] = conn.execute(
                """
                SELECT display, value, unit, ref_low, ref_high, interpretation FROM observations
                WHERE report_id = %s ORDER BY (interpretation <> 'N') DESC, display
                """,
                (r["id"],),
            ).fetchall()
        out.append(item)
    _audit_read(conn, user, patient_id, "results")
    return out


@router.get("/dependents/{patient_id}/slots")
def dependent_slots(patient_id: str, conn: Conn, user: CurrentUser,
                    specialty: str = Query("Primary care", max_length=60), limit: int = Query(6, le=20)) -> list[dict]:
    require_permission(conn, user, patient_id, "book_appointments")
    return conn.execute(
        """
        SELECT s.id::text, s.starts_at, s.mode, pr.id::text AS practitioner_id, pr.name AS practitioner_name,
               pr.specialty, pr.location_name
        FROM slots s JOIN practitioners pr ON pr.id = s.practitioner_id
        WHERE pr.organization_id = %s AND lower(pr.specialty) = lower(%s) AND s.status = 'free' AND s.starts_at > now()
        ORDER BY s.starts_at LIMIT %s
        """,
        (user.organization_id, specialty, limit),
    ).fetchall()


class BookIn(BaseModel):
    slot_id: str
    reason: str | None = Field(default=None, max_length=300)


@router.post("/dependents/{patient_id}/appointments", status_code=status.HTTP_201_CREATED)
def book_for_dependent(patient_id: str, body: BookIn, conn: Conn, user: CurrentUser) -> dict:
    require_permission(conn, user, patient_id, "book_appointments")
    slot = conn.execute(
        """
        SELECT s.id::text, s.practitioner_id::text, s.status, s.starts_at > now() AS in_future
        FROM slots s JOIN practitioners pr ON pr.id = s.practitioner_id
        WHERE s.id::text = %s AND pr.organization_id = %s
        FOR UPDATE OF s
        """,
        (body.slot_id, user.organization_id),
    ).fetchone()
    if slot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Slot not found")
    if slot["status"] != "free" or not slot["in_future"]:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "slot_taken", "message": "That time was just taken. Please pick another."})
    conn.execute("UPDATE slots SET status = 'booked' WHERE id = %s", (slot["id"],))
    appt = conn.execute(
        """
        INSERT INTO appointments (patient_id, practitioner_id, slot_id, reason) VALUES (%s, %s, %s, %s)
        RETURNING id::text
        """,
        (patient_id, slot["practitioner_id"], slot["id"], body.reason),
    ).fetchone()
    audit.record(conn, action="appointment_booked", entity_type="appointment", entity_id=appt["id"], actor=user,
                 agent="caregiver", patient_id=patient_id,
                 detail={"slot_id": slot["id"], "on_behalf_of": patient_id, "via": SCOPE})
    return next(a for a in _appointments(conn, patient_id) if a["id"] == appt["id"])


# --- Emergency contacts ---------------------------------------------------------------------------------


def _contacts_access(conn: Connection, user: User, patient_id: str, write: bool) -> dict[str, Any]:
    patient = _patient(conn, patient_id, user)
    if user.patient_id == patient_id:
        return patient
    grant_row = grant_of(conn, patient_id, user.id)
    if grant_row and grant_row["proxy"]:
        return patient
    if not write and user.role in ("clinician", "staff", "admin"):
        return patient  # the care team can read contacts for patients in their organization
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the patient or their full proxy can manage emergency contacts")


@router.get("/patients/{patient_id}/emergency-contacts")
def list_contacts(patient_id: str, conn: Conn, user: CurrentUser) -> list[dict]:
    _contacts_access(conn, user, patient_id, write=False)
    if user.patient_id != patient_id:
        audit.record(conn, action="emergency_contacts_viewed", entity_type="patient", entity_id=patient_id,
                     actor=user, patient_id=patient_id)
    return _contacts(conn, patient_id)


class ContactIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    relationship: str = Field(min_length=2, max_length=60)
    phone: str = Field(min_length=5, max_length=40, pattern=r"^[0-9+()\-.\s]+$")
    notes: str | None = Field(default=None, max_length=300)


@router.post("/patients/{patient_id}/emergency-contacts", status_code=status.HTTP_201_CREATED)
def add_contact(patient_id: str, body: ContactIn, conn: Conn, user: CurrentUser) -> dict:
    _contacts_access(conn, user, patient_id, write=True)
    row = conn.execute(
        """
        INSERT INTO emergency_contacts (patient_id, name, relationship, phone, notes) VALUES (%s, %s, %s, %s, %s)
        RETURNING id::text, name, relationship, phone, notes, created_at
        """,
        (patient_id, body.name.strip(), body.relationship.strip(), body.phone.strip(), body.notes),
    ).fetchone()
    audit.record(conn, action="emergency_contact_added", entity_type="emergency_contact", entity_id=row["id"],
                 actor=user, patient_id=patient_id)
    return row


@router.delete("/patients/{patient_id}/emergency-contacts/{contact_id}")
def remove_contact(patient_id: str, contact_id: str, conn: Conn, user: CurrentUser) -> dict:
    _contacts_access(conn, user, patient_id, write=True)
    row = conn.execute("DELETE FROM emergency_contacts WHERE id::text = %s AND patient_id = %s RETURNING id::text",
                       (contact_id, patient_id)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    audit.record(conn, action="emergency_contact_removed", entity_type="emergency_contact", entity_id=contact_id,
                 actor=user, patient_id=patient_id)
    return {"removed": contact_id}
