"""Organization platform: profile and branding, locations, departments, services, provider directory, roles.

Administrators only, except the public branding read. Every change is audited with the fields it touched.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, status
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import AfterValidator, BaseModel, Field, field_validator, model_validator

from bioverse import audit
from bioverse.auth import Admin, User
from bioverse.db import DbConn

router = APIRouter(prefix="/api/org", tags=["organization"])

# Accent colours an organization may choose. Each keeps white text at WCAG AA (4.5:1) or better.
ACCENT_PALETTE = {
    "#0e6b60": "Teal",
    "#1f5a8a": "Harbour blue",
    "#5b4a8a": "Heather",
    "#2f6b3a": "Forest",
    "#7a3f5e": "Plum",
    "#3b4a5a": "Slate",
}
DEFAULT_ACCENT = "#0e6b60"
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
KINDS = ("in_person", "video", "either")

_PHONE = re.compile(r"^[0-9+()\-. ]{7,20}$")
_HHMM = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


def _clean(text: str) -> str:
    return " ".join(text.split())


Name = Annotated[str, Field(min_length=2, max_length=120), AfterValidator(_clean)]


def _phone(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    if not _PHONE.match(value) or sum(c.isdigit() for c in value) < 7:
        raise ValueError("Enter a phone number with at least 7 digits")
    return value


Phone = Annotated[str | None, AfterValidator(_phone)]


def _list(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        v = _clean(v)
        if not v or len(v) > 60:
            raise ValueError("Each entry needs 1 to 60 characters")
        if v.lower() not in {o.lower() for o in out}:
            out.append(v)
    return out


TextList = Annotated[list[str], Field(max_length=12), AfterValidator(_list)]


_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _org_row(conn: Connection, table: str, row_id: str, org_id: str) -> dict:
    if not _UUID.match(row_id or ""):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    row = conn.execute(f"SELECT * FROM {table} WHERE id = %s AND organization_id = %s", (row_id, org_id)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return row


def _changes(before: dict, after: dict[str, Any]) -> list[str]:
    return sorted(k for k, v in after.items() if before.get(k) != v)


def _unique_violation(message: str):
    return HTTPException(status.HTTP_409_CONFLICT, message)


# --- Profile and branding ------------------------------------------------------------------------


def _profile(conn: Connection, org_id: str) -> dict:
    row = conn.execute(
        """
        SELECT o.id::text AS organization_id, coalesce(p.display_name, o.name) AS display_name,
               coalesce(p.accent_color, %s) AS accent_color, p.support_phone, p.updated_at
        FROM organizations o LEFT JOIN organization_profiles p ON p.organization_id = o.id
        WHERE o.id = %s
        """,
        (DEFAULT_ACCENT, org_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    return row


@router.get("/branding")
def branding(conn: DbConn, organization_id: str | None = None) -> dict:
    """Public: what a sign-in page needs to theme itself. No authentication, no private fields."""
    if organization_id is None:
        first = conn.execute("SELECT id::text FROM organizations ORDER BY created_at, id LIMIT 1").fetchone()
        if first is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
        organization_id = first["id"]
    if not _UUID.match(organization_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    p = _profile(conn, organization_id)
    return {"organization_id": p["organization_id"], "display_name": p["display_name"],
            "accent_color": p["accent_color"], "support_phone": p["support_phone"]}


@router.get("/profile")
def get_profile(conn: DbConn, user: Admin) -> dict:
    return {**_profile(conn, user.organization_id),
            "palette": [{"value": k, "label": v} for k, v in ACCENT_PALETTE.items()]}


class ProfileIn(BaseModel):
    display_name: Name
    accent_color: str
    support_phone: Phone = None

    @field_validator("accent_color")
    @classmethod
    def approved(cls, v: str) -> str:
        v = v.lower()
        if v not in ACCENT_PALETTE:
            raise ValueError("Choose one of the approved accent colours")
        return v


@router.put("/profile")
def put_profile(body: ProfileIn, conn: DbConn, user: Admin) -> dict:
    before = _profile(conn, user.organization_id)
    conn.execute(
        """
        INSERT INTO organization_profiles (organization_id, display_name, accent_color, support_phone, updated_by)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (organization_id) DO UPDATE
          SET display_name = EXCLUDED.display_name, accent_color = EXCLUDED.accent_color,
              support_phone = EXCLUDED.support_phone, updated_by = EXCLUDED.updated_by, updated_at = now()
        """,
        (user.organization_id, body.display_name, body.accent_color, body.support_phone, user.id),
    )
    audit.record(conn, action="org_profile_updated", entity_type="organization", entity_id=user.organization_id,
                 actor=user, detail={"changed": _changes(before, body.model_dump())})
    return get_profile(conn, user)


# --- Locations -------------------------------------------------------------------------------------


class LocationIn(BaseModel):
    name: Name
    kind: Literal["physical", "virtual"] = "physical"
    address: Annotated[str | None, Field(max_length=200)] = None
    phone: Phone = None
    step_free: bool = False
    active: bool = True

    @model_validator(mode="after")
    def needs_address(self) -> "LocationIn":
        if self.kind == "physical" and not (self.address and self.address.strip()):
            raise ValueError("A physical location needs an address")
        if self.kind == "virtual":
            self.address = None
        return self


_LOCATION_COLS = "id::text, name, mode AS kind, address, phone, step_free, active"


@router.get("/locations")
def list_locations(conn: DbConn, user: Admin) -> list[dict]:
    return conn.execute(
        f"""
        SELECT {_LOCATION_COLS},
               (SELECT count(*) FROM practitioners p WHERE p.location_id = l.id) AS providers,
               (SELECT count(*) FROM departments d WHERE d.location_id = l.id) AS departments
        FROM locations l WHERE organization_id = %s ORDER BY active DESC, name
        """,
        (user.organization_id,),
    ).fetchall()


def _save_location(conn: Connection, user: User, body: LocationIn, location_id: str | None) -> dict:
    values = body.model_dump()
    try:
        with conn.transaction():
            if location_id is None:
                row = conn.execute(
                    f"""
                    INSERT INTO locations (organization_id, name, mode, address, phone, step_free, active)
                    VALUES (%(org)s, %(name)s, %(kind)s, %(address)s, %(phone)s, %(step_free)s, %(active)s)
                    RETURNING {_LOCATION_COLS}
                    """,
                    {**values, "org": user.organization_id},
                ).fetchone()
                changed = sorted(values)
            else:
                before = dict(_org_row(conn, "locations", location_id, user.organization_id))
                before["kind"] = before["mode"]  # the API's "kind" is stored in the shared `mode` column
                row = conn.execute(
                    f"""
                    UPDATE locations SET name = %(name)s, mode = %(kind)s, address = %(address)s, phone = %(phone)s,
                           step_free = %(step_free)s, active = %(active)s
                    WHERE id = %(id)s RETURNING {_LOCATION_COLS}
                    """,
                    {**values, "id": location_id},
                ).fetchone()
                changed = _changes(before, values)
                # Keep the provider directory's display name in step with a renamed location.
                if "name" in changed:
                    conn.execute("UPDATE practitioners SET location_name = %s WHERE location_id = %s",
                                 (row["name"], location_id))
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505":
            raise _unique_violation("A location with that name already exists") from None
        raise
    audit.record(conn, action="location_created" if location_id is None else "location_updated",
                 entity_type="location", entity_id=row["id"], actor=user, detail={"changed": changed})
    return row


@router.post("/locations", status_code=status.HTTP_201_CREATED)
def create_location(body: LocationIn, conn: DbConn, user: Admin) -> dict:
    return _save_location(conn, user, body, None)


@router.put("/locations/{location_id}")
def update_location(location_id: str, body: LocationIn, conn: DbConn, user: Admin) -> dict:
    return _save_location(conn, user, body, location_id)


# --- Departments -------------------------------------------------------------------------------------


class Hours(BaseModel):
    open: str
    close: str

    @model_validator(mode="after")
    def valid(self) -> "Hours":
        if not (_HHMM.match(self.open) and _HHMM.match(self.close)):
            raise ValueError("Use 24-hour HH:MM times")
        if self.open >= self.close:
            raise ValueError("Closing time must be after opening time")
        return self


class DepartmentIn(BaseModel):
    name: Name
    specialty: Name
    location_id: str | None = None
    hours: dict[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"], Hours | None] = Field(default_factory=dict)
    active: bool = True


def _hours_json(hours: dict[str, Hours | None]) -> dict[str, Any]:
    return {d: (hours[d].model_dump() if hours.get(d) else None) for d in WEEKDAYS}


_DEPT_SELECT = """
    SELECT d.id::text, d.name, d.specialty, d.location_id::text, l.name AS location_name, d.hours, d.active,
           (SELECT count(*) FROM healthcare_services s WHERE s.department_id = d.id AND s.active) AS services
    FROM departments d LEFT JOIN locations l ON l.id = d.location_id
"""


@router.get("/departments")
def list_departments(conn: DbConn, user: Admin) -> list[dict]:
    return conn.execute(_DEPT_SELECT + " WHERE d.organization_id = %s ORDER BY d.active DESC, d.name",
                        (user.organization_id,)).fetchall()


def _check_location(conn: Connection, location_id: str | None, org_id: str) -> None:
    if location_id is not None:
        try:
            _org_row(conn, "locations", location_id, org_id)
        except HTTPException:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown location") from None


def _valid_uuid(value: str | None, what: str) -> None:
    if value is not None and not _UUID.match(value):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown {what}")


def _save_department(conn: Connection, user: User, body: DepartmentIn, dept_id: str | None) -> dict:
    _valid_uuid(body.location_id, "location")
    _check_location(conn, body.location_id, user.organization_id)
    values = {"name": body.name, "specialty": body.specialty, "location_id": body.location_id,
              "hours": _hours_json(body.hours), "active": body.active}
    try:
        with conn.transaction():
            if dept_id is None:
                new = conn.execute(
                    """
                    INSERT INTO departments (organization_id, name, specialty, location_id, hours, active)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING id::text
                    """,
                    (user.organization_id, body.name, body.specialty, body.location_id, Jsonb(values["hours"]), body.active),
                ).fetchone()
                dept_id_out, changed = new["id"], sorted(values)
            else:
                _valid_uuid(dept_id, "department")
                before = _org_row(conn, "departments", dept_id, user.organization_id)
                before = {**before, "location_id": str(before["location_id"]) if before["location_id"] else None}
                conn.execute(
                    """
                    UPDATE departments SET name = %s, specialty = %s, location_id = %s, hours = %s, active = %s
                    WHERE id = %s
                    """,
                    (body.name, body.specialty, body.location_id, Jsonb(values["hours"]), body.active, dept_id),
                )
                dept_id_out, changed = dept_id, _changes(before, values)
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505":
            raise _unique_violation("A department with that name already exists") from None
        raise
    audit.record(conn, action="department_created" if dept_id is None else "department_updated",
                 entity_type="department", entity_id=dept_id_out, actor=user, detail={"changed": changed})
    return conn.execute(_DEPT_SELECT + " WHERE d.id = %s", (dept_id_out,)).fetchone()


@router.post("/departments", status_code=status.HTTP_201_CREATED)
def create_department(body: DepartmentIn, conn: DbConn, user: Admin) -> dict:
    return _save_department(conn, user, body, None)


@router.put("/departments/{dept_id}")
def update_department(dept_id: str, body: DepartmentIn, conn: DbConn, user: Admin) -> dict:
    return _save_department(conn, user, body, dept_id)


# --- Services and appointment types --------------------------------------------------------------------


class ServiceIn(BaseModel):
    name: Name
    department_id: str
    duration_min: int = Field(ge=5, le=240)
    mode: Literal["in_person", "video", "either"]
    active: bool = True

    @field_validator("duration_min")
    @classmethod
    def five_minute_steps(cls, v: int) -> int:
        if v % 5:
            raise ValueError("Duration must be in 5-minute steps")
        return v


_SERVICE_SELECT = """
    SELECT s.id::text, s.name, s.department_id::text, d.name AS department_name, d.specialty,
           s.duration_min, s.mode, s.active
    FROM healthcare_services s JOIN departments d ON d.id = s.department_id
"""


@router.get("/services")
def list_services(conn: DbConn, user: Admin) -> list[dict]:
    return conn.execute(_SERVICE_SELECT + " WHERE s.organization_id = %s ORDER BY s.active DESC, d.name, s.name",
                        (user.organization_id,)).fetchall()


def _save_service(conn: Connection, user: User, body: ServiceIn, service_id: str | None) -> dict:
    _valid_uuid(body.department_id, "department")
    try:
        _org_row(conn, "departments", body.department_id, user.organization_id)
    except HTTPException:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown department") from None
    values = body.model_dump()
    try:
        with conn.transaction():
            if service_id is None:
                row = conn.execute(
                    """
                    INSERT INTO healthcare_services (organization_id, department_id, name, duration_min, mode, active)
                    VALUES (%(org)s, %(department_id)s, %(name)s, %(duration_min)s, %(mode)s, %(active)s) RETURNING id::text
                    """,
                    {**values, "org": user.organization_id},
                ).fetchone()
                out_id, changed = row["id"], sorted(values)
            else:
                _valid_uuid(service_id, "service")
                before = _org_row(conn, "healthcare_services", service_id, user.organization_id)
                before = {**before, "department_id": str(before["department_id"])}
                conn.execute(
                    """
                    UPDATE healthcare_services SET department_id = %(department_id)s, name = %(name)s,
                           duration_min = %(duration_min)s, mode = %(mode)s, active = %(active)s
                    WHERE id = %(id)s
                    """,
                    {**values, "id": service_id},
                )
                out_id, changed = service_id, _changes(before, values)
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505":
            raise _unique_violation("That department already has a service with this name") from None
        raise
    audit.record(conn, action="service_created" if service_id is None else "service_updated",
                 entity_type="healthcare_service", entity_id=out_id, actor=user, detail={"changed": changed})
    return conn.execute(_SERVICE_SELECT + " WHERE s.id = %s", (out_id,)).fetchone()


@router.post("/services", status_code=status.HTTP_201_CREATED)
def create_service(body: ServiceIn, conn: DbConn, user: Admin) -> dict:
    return _save_service(conn, user, body, None)


@router.put("/services/{service_id}")
def update_service(service_id: str, body: ServiceIn, conn: DbConn, user: Admin) -> dict:
    return _save_service(conn, user, body, service_id)


# --- Provider directory ----------------------------------------------------------------------------------


class ProviderIn(BaseModel):
    name: Name
    specialty: Name
    location_id: str
    languages: TextList = Field(min_length=1)
    accessibility: TextList = Field(default_factory=list)
    accepted_plans: TextList = Field(default_factory=list)
    offers_telehealth: bool = False


_PROVIDER_SELECT = """
    SELECT p.id::text, p.name, p.specialty, p.location_id::text, p.location_name, p.languages, p.accessibility,
           p.accepted_plans, p.offers_telehealth, (p.user_id IS NOT NULL) AS has_account
    FROM practitioners p
"""


@router.get("/providers")
def list_providers(conn: DbConn, user: Admin) -> list[dict]:
    return conn.execute(_PROVIDER_SELECT + " WHERE p.organization_id = %s ORDER BY p.specialty, p.name",
                        (user.organization_id,)).fetchall()


def _save_provider(conn: Connection, user: User, body: ProviderIn, provider_id: str | None) -> dict:
    _valid_uuid(body.location_id, "location")
    try:
        location = _org_row(conn, "locations", body.location_id, user.organization_id)
    except HTTPException:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown location") from None
    if not location["active"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That location is inactive")
    if location["mode"] == "virtual" and not body.offers_telehealth:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Providers at a virtual location must offer telehealth")
    values = {**body.model_dump(), "location_name": location["name"]}
    if provider_id is None:
        row = conn.execute(
            """
            INSERT INTO practitioners (organization_id, name, specialty, location_id, location_name, languages,
                                       accessibility, accepted_plans, offers_telehealth)
            VALUES (%(org)s, %(name)s, %(specialty)s, %(location_id)s, %(location_name)s, %(languages)s,
                    %(accessibility)s, %(accepted_plans)s, %(offers_telehealth)s)
            RETURNING id::text
            """,
            {**values, "org": user.organization_id},
        ).fetchone()
        out_id, changed = row["id"], sorted(values)
    else:
        _valid_uuid(provider_id, "provider")
        before = _org_row(conn, "practitioners", provider_id, user.organization_id)
        before = {**before, "location_id": str(before["location_id"]) if before["location_id"] else None}
        conn.execute(
            """
            UPDATE practitioners SET name = %(name)s, specialty = %(specialty)s, location_id = %(location_id)s,
                   location_name = %(location_name)s, languages = %(languages)s, accessibility = %(accessibility)s,
                   accepted_plans = %(accepted_plans)s, offers_telehealth = %(offers_telehealth)s
            WHERE id = %(id)s
            """,
            {**values, "id": provider_id},
        )
        out_id, changed = provider_id, _changes(before, values)
    audit.record(conn, action="provider_created" if provider_id is None else "provider_updated",
                 entity_type="practitioner", entity_id=out_id, actor=user, detail={"changed": changed})
    return conn.execute(_PROVIDER_SELECT + " WHERE p.id = %s", (out_id,)).fetchone()


@router.post("/providers", status_code=status.HTTP_201_CREATED)
def create_provider(body: ProviderIn, conn: DbConn, user: Admin) -> dict:
    return _save_provider(conn, user, body, None)


@router.put("/providers/{provider_id}")
def update_provider(provider_id: str, body: ProviderIn, conn: DbConn, user: Admin) -> dict:
    return _save_provider(conn, user, body, provider_id)


# --- Roles (read-only) ------------------------------------------------------------------------------------


@router.get("/users")
def list_users(conn: DbConn, user: Admin) -> dict:
    """Workforce accounts and their roles. Patient accounts are counted, not listed."""
    staff = conn.execute(
        """
        SELECT u.id::text, u.display_name, u.email, u.role, pr.name AS practitioner_name, pr.specialty
        FROM users u LEFT JOIN practitioners pr ON pr.user_id = u.id
        WHERE u.organization_id = %s AND u.role <> 'patient'
        ORDER BY u.role, u.display_name
        """,
        (user.organization_id,),
    ).fetchall()
    counts = conn.execute(
        "SELECT role, count(*) AS n FROM users WHERE organization_id = %s GROUP BY role ORDER BY role",
        (user.organization_id,),
    ).fetchall()
    return {
        "users": staff,
        "role_counts": {r["role"]: r["n"] for r in counts},
        "roles_editable": False,
        "note": "Changing roles is not available here yet. Roles come from the identity provider once real sign-in is connected.",
    }
