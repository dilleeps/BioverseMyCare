"""Care pathways (templates) and clinician care-plan authoring.

Administrators define pathway templates: an ordered list of task templates, each due a number of days after
the plan starts. Clinicians start a care plan for a patient on their panel, from a template or blank, edit
its tasks while it is active, and complete it. The patient's existing care-plan page shows the result.

A clinician starting a plan is the clinician approval the review matrix asks for (docs/04). A patient has at
most one active plan per clinician.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, status
from psycopg import Connection
from pydantic import AfterValidator, BaseModel, Field, model_validator

from bioverse import audit
from bioverse.agents import hospital_agent as ha
from bioverse.auth import Admin, Clinician, User, Workforce, assert_patient_access
from bioverse.db import DbConn
from bioverse.routers.analytics import panel_patient_ids
from bioverse.routers.organization import _UUID

router = APIRouter(prefix="/api/pathways", tags=["pathways"])

TaskKind = Literal["lab", "medication", "appointment", "referral", "checkin", "lifestyle"]


def _clean(text: str) -> str:
    return " ".join(text.split())


def _opt_clean(text: str | None) -> str | None:
    if text is None:
        return None
    text = _clean(text)
    return text or None


Title = Annotated[str, Field(min_length=2, max_length=160), AfterValidator(_clean)]
Detail = Annotated[str | None, Field(max_length=400), AfterValidator(_opt_clean)]
Specialty = Annotated[str | None, Field(max_length=80), AfterValidator(_opt_clean)]


def _uuid_or_404(value: str, what: str = "Not found") -> str:
    if not _UUID.match(value or ""):
        raise HTTPException(status.HTTP_404_NOT_FOUND, what)
    return value


def _today() -> date:
    return ha.clock().today


# --- Pathway templates -------------------------------------------------------------------------------------


class ActionIn(BaseModel):
    kind: TaskKind
    title: Title
    detail: Detail = None
    specialty: Specialty = None
    due_offset_days: int = Field(ge=0, le=730)

    @model_validator(mode="after")
    def appointment_needs_specialty(self) -> "ActionIn":
        if self.kind in ("appointment", "referral") and not self.specialty:
            raise ValueError("Appointment and referral tasks need a specialty")
        return self


class PathwayIn(BaseModel):
    name: Title
    specialty: Annotated[str, Field(min_length=2, max_length=80), AfterValidator(_clean)]
    description: Detail = None
    active: bool = True
    actions: list[ActionIn] = Field(min_length=1, max_length=30)


def _pathways(conn: Connection, org_id: str, pathway_id: str | None = None, include_inactive: bool = True) -> list[dict]:
    rows = conn.execute(
        """
        SELECT d.id::text, d.name, d.specialty, d.description, d.active, d.updated_at,
               coalesce(json_agg(json_build_object(
                   'id', a.id::text, 'position', a.position, 'kind', a.kind, 'title', a.title, 'detail', a.detail,
                   'specialty', a.specialty, 'due_offset_days', a.due_offset_days) ORDER BY a.position)
                 FILTER (WHERE a.id IS NOT NULL), '[]') AS actions,
               (SELECT count(*) FROM care_plans c WHERE c.plan_definition_id = d.id) AS plans_started
        FROM plan_definitions d LEFT JOIN plan_definition_actions a ON a.plan_definition_id = d.id
        WHERE d.organization_id = %(org)s AND (%(id)s::uuid IS NULL OR d.id = %(id)s::uuid)
          AND (%(all)s OR d.active)
        GROUP BY d.id ORDER BY d.active DESC, d.specialty, d.name
        """,
        {"org": org_id, "id": pathway_id, "all": include_inactive},
    ).fetchall()
    return rows


@router.get("/templates")
def list_pathways(conn: DbConn, user: Workforce) -> list[dict]:
    """Admins see every template; clinicians see the active ones they can start a plan from."""
    return _pathways(conn, user.organization_id, include_inactive=user.role == "admin")


@router.get("/templates/{pathway_id}")
def get_pathway(pathway_id: str, conn: DbConn, user: Workforce) -> dict:
    _uuid_or_404(pathway_id)
    rows = _pathways(conn, user.organization_id, pathway_id, include_inactive=user.role == "admin")
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pathway not found")
    return rows[0]


def _write_actions(conn: Connection, pathway_id: str, actions: list[ActionIn]) -> None:
    conn.execute("DELETE FROM plan_definition_actions WHERE plan_definition_id = %s", (pathway_id,))
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO plan_definition_actions (plan_definition_id, position, kind, title, detail, specialty, due_offset_days)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [(pathway_id, i, a.kind, a.title, a.detail, a.specialty, a.due_offset_days) for i, a in enumerate(actions, 1)],
        )


def _save_pathway(conn: Connection, user: User, body: PathwayIn, pathway_id: str | None) -> dict:
    try:
        with conn.transaction():
            if pathway_id is None:
                row = conn.execute(
                    """
                    INSERT INTO plan_definitions (organization_id, name, specialty, description, active)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id::text
                    """,
                    (user.organization_id, body.name, body.specialty, body.description, body.active),
                ).fetchone()
                pathway_id_out = row["id"]
            else:
                row = conn.execute(
                    """
                    UPDATE plan_definitions SET name = %s, specialty = %s, description = %s, active = %s, updated_at = now()
                    WHERE id = %s AND organization_id = %s RETURNING id::text
                    """,
                    (body.name, body.specialty, body.description, body.active, pathway_id, user.organization_id),
                ).fetchone()
                if row is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "Pathway not found")
                pathway_id_out = pathway_id
            _write_actions(conn, pathway_id_out, body.actions)
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505":
            raise HTTPException(status.HTTP_409_CONFLICT, "A pathway with that name already exists") from None
        raise
    audit.record(conn, action="pathway_created" if pathway_id is None else "pathway_updated",
                 entity_type="plan_definition", entity_id=pathway_id_out, actor=user,
                 detail={"name": body.name, "tasks": len(body.actions), "active": body.active})
    return _pathways(conn, user.organization_id, pathway_id_out)[0]


@router.post("/templates", status_code=status.HTTP_201_CREATED)
def create_pathway(body: PathwayIn, conn: DbConn, user: Admin) -> dict:
    return _save_pathway(conn, user, body, None)


@router.put("/templates/{pathway_id}")
def update_pathway(pathway_id: str, body: PathwayIn, conn: DbConn, user: Admin) -> dict:
    _uuid_or_404(pathway_id, "Pathway not found")
    return _save_pathway(conn, user, body, pathway_id)


# --- Clinician care-plan authoring -----------------------------------------------------------------------------


class TaskIn(BaseModel):
    id: str | None = None
    kind: TaskKind
    title: Title
    detail: Detail = None
    specialty: Specialty = None
    due_on: date | None = None

    @model_validator(mode="after")
    def sensible(self) -> "TaskIn":
        if self.kind in ("appointment", "referral") and not self.specialty:
            raise ValueError("Appointment and referral tasks need a specialty")
        if self.due_on is not None:
            today = _today()
            if not (today - timedelta(days=365) <= self.due_on <= today + timedelta(days=730)):
                raise ValueError("Due dates must be within a year before and two years after today")
        return self


class PlanCreateIn(BaseModel):
    patient_id: str
    pathway_id: str | None = None
    title: Annotated[str | None, Field(max_length=160), AfterValidator(_opt_clean)] = None
    tasks: list[TaskIn] | None = Field(default=None, max_length=40)


class PlanUpdateIn(BaseModel):
    title: Title
    tasks: list[TaskIn] = Field(min_length=1, max_length=40)


def _plan(conn: Connection, plan_id: str, user: User) -> dict:
    _uuid_or_404(plan_id, "Care plan not found")
    plan = conn.execute(
        """
        SELECT c.id::text, c.title, c.status, c.started_at, c.completed_at, c.patient_id::text,
               p.name AS patient_name, c.plan_definition_id::text AS pathway_id, d.name AS pathway_name
        FROM care_plans c JOIN patients p ON p.id = c.patient_id
        LEFT JOIN plan_definitions d ON d.id = c.plan_definition_id
        WHERE c.id = %s AND c.practitioner_id = %s
        """,
        (plan_id, user.practitioner_id),
    ).fetchone()
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Care plan not found")
    assert_patient_access(conn, user, plan["patient_id"])
    plan["tasks"] = conn.execute(
        """
        SELECT id::text, position, kind, title, detail, specialty, due_on, status, completed_at
        FROM care_plan_tasks WHERE care_plan_id = %s ORDER BY position
        """,
        (plan_id,),
    ).fetchall()
    today = _today()
    for t in plan["tasks"]:
        t["overdue"] = t["status"] == "todo" and t["due_on"] is not None and t["due_on"] < today
    plan["done_count"] = sum(1 for t in plan["tasks"] if t["status"] == "done")
    return plan


@router.get("/patients")
def my_patients(conn: DbConn, user: Clinician) -> list[dict]:
    """Patients on the clinician's panel, with any active plan they already have with this clinician."""
    ids = panel_patient_ids(conn, user.practitioner_id, user.organization_id)
    return conn.execute(
        """
        SELECT p.id::text, p.name,
               (SELECT c.id::text FROM care_plans c WHERE c.patient_id = p.id AND c.practitioner_id = %(pr)s
                  AND c.status = 'active' ORDER BY c.started_at DESC LIMIT 1) AS active_plan_id,
               (SELECT c.title FROM care_plans c WHERE c.patient_id = p.id AND c.practitioner_id = %(pr)s
                  AND c.status = 'active' ORDER BY c.started_at DESC LIMIT 1) AS active_plan_title
        FROM patients p WHERE p.id = ANY(%(ids)s::uuid[]) ORDER BY p.name
        """,
        {"pr": user.practitioner_id, "ids": ids},
    ).fetchall()


@router.get("/care-plans")
def my_plans(conn: DbConn, user: Clinician) -> list[dict]:
    return conn.execute(
        """
        SELECT c.id::text, c.title, c.status, c.started_at, c.completed_at, p.id::text AS patient_id,
               p.name AS patient_name, d.name AS pathway_name,
               (SELECT count(*) FROM care_plan_tasks t WHERE t.care_plan_id = c.id) AS total_count,
               (SELECT count(*) FROM care_plan_tasks t WHERE t.care_plan_id = c.id AND t.status = 'done') AS done_count,
               (SELECT count(*) FROM care_plan_tasks t WHERE t.care_plan_id = c.id AND t.status = 'todo'
                  AND t.due_on < %(today)s) AS overdue_count
        FROM care_plans c JOIN patients p ON p.id = c.patient_id
        LEFT JOIN plan_definitions d ON d.id = c.plan_definition_id
        WHERE c.practitioner_id = %(pr)s AND p.organization_id = %(org)s
          AND (c.status = 'active' OR c.completed_at >= now() - interval '90 days')
        ORDER BY (c.status = 'active') DESC, p.name
        """,
        {"pr": user.practitioner_id, "org": user.organization_id, "today": _today()},
    ).fetchall()


@router.get("/care-plans/{plan_id}")
def get_plan(plan_id: str, conn: DbConn, user: Clinician) -> dict:
    return _plan(conn, plan_id, user)


def _insert_tasks(conn: Connection, plan_id: str, tasks: list[TaskIn]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO care_plan_tasks (care_plan_id, position, kind, title, detail, specialty, due_on)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [(plan_id, i, t.kind, t.title, t.detail, t.specialty, t.due_on) for i, t in enumerate(tasks, 1)],
        )


@router.post("/care-plans", status_code=status.HTTP_201_CREATED)
def start_plan(body: PlanCreateIn, conn: DbConn, user: Clinician) -> dict:
    _uuid_or_404(body.patient_id, "Patient not found")
    assert_patient_access(conn, user, body.patient_id)
    if body.patient_id not in panel_patient_ids(conn, user.practitioner_id, user.organization_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This patient is not on your panel")

    pathway = None
    if body.pathway_id:
        _uuid_or_404(body.pathway_id, "Pathway not found")
        rows = _pathways(conn, user.organization_id, body.pathway_id, include_inactive=False)
        if not rows:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Pathway not found")
        pathway = rows[0]

    tasks = body.tasks
    if tasks is None:
        if pathway is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A blank plan needs at least one task")
        today = _today()
        tasks = [TaskIn(kind=a["kind"], title=a["title"], detail=a["detail"], specialty=a["specialty"],
                        due_on=today + timedelta(days=a["due_offset_days"])) for a in pathway["actions"]]
    if not tasks:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A care plan needs at least one task")
    if any(t.id for t in tasks):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "New plans cannot reuse task ids")
    title = body.title or (pathway["name"] if pathway else None)
    if not title or len(title) < 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give the plan a title")

    # Serialize concurrent starts for the same patient and clinician, then enforce one active plan.
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"care_plan:{body.patient_id}:{user.practitioner_id}",))
    existing = conn.execute(
        "SELECT id::text FROM care_plans WHERE patient_id = %s AND practitioner_id = %s AND status = 'active'",
        (body.patient_id, user.practitioner_id),
    ).fetchone()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "code": "active_plan_exists", "plan_id": existing["id"],
            "message": "This patient already has an active care plan with you. Edit or complete it first."})

    plan = conn.execute(
        """
        INSERT INTO care_plans (patient_id, practitioner_id, title, plan_definition_id)
        VALUES (%s, %s, %s, %s) RETURNING id::text
        """,
        (body.patient_id, user.practitioner_id, title, pathway["id"] if pathway else None),
    ).fetchone()
    _insert_tasks(conn, plan["id"], tasks)
    audit.record(conn, action="care_plan_created", entity_type="care_plan", entity_id=plan["id"], actor=user,
                 patient_id=body.patient_id,
                 detail={"pathway_id": pathway["id"] if pathway else None, "tasks": len(tasks), "title": title})
    return _plan(conn, plan["id"], user)


@router.put("/care-plans/{plan_id}")
def update_plan(plan_id: str, body: PlanUpdateIn, conn: DbConn, user: Clinician) -> dict:
    """Replace the task list: add, remove, reorder, change due dates. Completed tasks stay as recorded."""
    current = _plan(conn, plan_id, user)
    if current["status"] != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only an active care plan can be edited")
    conn.execute("SELECT 1 FROM care_plans WHERE id = %s FOR UPDATE", (plan_id,))

    existing = {t["id"]: t for t in current["tasks"]}
    seen: set[str] = set()
    for t in body.tasks:
        if t.id is None:
            continue
        if t.id not in existing or t.id in seen:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A task in the list does not belong to this plan")
        seen.add(t.id)
        old = existing[t.id]
        if old["status"] == "done" and (t.kind, t.title, t.detail, t.specialty, t.due_on) != (
                old["kind"], old["title"], old["detail"], old["specialty"], old["due_on"]):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'{old['title']}' is done and can't be changed")
    removed = [tid for tid in existing if tid not in seen]
    done_removed = [existing[tid]["title"] for tid in removed if existing[tid]["status"] == "done"]
    if done_removed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'{done_removed[0]}' is done and can't be removed")

    changed = 0
    for position, t in enumerate(body.tasks, 1):
        if t.id is None:
            conn.execute(
                """
                INSERT INTO care_plan_tasks (care_plan_id, position, kind, title, detail, specialty, due_on)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (plan_id, position, t.kind, t.title, t.detail, t.specialty, t.due_on),
            )
        else:
            old = existing[t.id]
            if (t.kind, t.title, t.detail, t.specialty, t.due_on) != (
                    old["kind"], old["title"], old["detail"], old["specialty"], old["due_on"]):
                changed += 1
            conn.execute(
                """
                UPDATE care_plan_tasks SET position = %s, kind = %s, title = %s, detail = %s, specialty = %s, due_on = %s
                WHERE id = %s AND care_plan_id = %s
                """,
                (position, t.kind, t.title, t.detail, t.specialty, t.due_on, t.id, plan_id),
            )
    if removed:
        conn.execute("DELETE FROM care_plan_tasks WHERE care_plan_id = %s AND id = ANY(%s::uuid[])", (plan_id, removed))
    conn.execute("UPDATE care_plans SET title = %s WHERE id = %s", (body.title, plan_id))

    old_order = [t["id"] for t in current["tasks"] if t["id"] in seen]
    new_order = [t.id for t in body.tasks if t.id]
    audit.record(conn, action="care_plan_updated", entity_type="care_plan", entity_id=plan_id, actor=user,
                 patient_id=current["patient_id"],
                 detail={"added": sum(1 for t in body.tasks if t.id is None), "removed": len(removed),
                         "changed": changed, "reordered": old_order != new_order,
                         "title_changed": body.title != current["title"]})
    return _plan(conn, plan_id, user)


@router.post("/care-plans/{plan_id}/complete")
def complete_plan(plan_id: str, conn: DbConn, user: Clinician) -> dict:
    current = _plan(conn, plan_id, user)
    if current["status"] != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "This care plan is not active")
    conn.execute("UPDATE care_plans SET status = 'completed', completed_at = now() WHERE id = %s", (plan_id,))
    open_tasks = sum(1 for t in current["tasks"] if t["status"] == "todo")
    audit.record(conn, action="care_plan_completed", entity_type="care_plan", entity_id=plan_id, actor=user,
                 patient_id=current["patient_id"], detail={"open_tasks": open_tasks})
    return _plan(conn, plan_id, user)
