"""Referral Manager: closed-loop referrals, modeled on FHIR ServiceRequest.

Lifecycle: draft -> sent -> accepted -> scheduled -> completed, plus declined, expired and cancelled.

Some changes happen on read, with no background worker (`refresh`):
- a sent or accepted referral past `expires_on` becomes expired;
- an accepted referral becomes scheduled once the patient books an appointment in that specialty;
- a scheduled referral becomes completed when that visit is completed, or goes back to accepted if the
  appointment is cancelled.
Every change writes a history row (who and when; NULL actor for automatic changes) and an audit event.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from psycopg import Connection
from pydantic import BaseModel, Field

from bioverse import audit
from bioverse.auth import Clinician, CurrentUser, User, Workforce, assert_patient_access
from bioverse.db import DbConn
from bioverse.routers.visits import clinic_today

router = APIRouter(prefix="/api/referrals", tags=["referrals"])

Conn = DbConn

LEAK_DAYS = 5             # accepted but not booked after this many days: the referral is "leaking"
EXPIRING_DAYS = 7         # flag referrals that expire within this many days
DEFAULT_VALID_DAYS = {"routine": 90, "urgent": 30}

OPEN = ("sent", "accepted")
TERMINAL = ("completed", "declined", "expired", "cancelled")

# Transitions a person can make. Automatic ones (expired, booking detected) happen in `refresh`.
TRANSITIONS: dict[str, set[str]] = {
    "draft": {"sent", "cancelled"},
    "sent": {"accepted", "declined", "cancelled"},
    "accepted": {"scheduled", "declined", "cancelled"},
    "scheduled": {"completed", "cancelled"},
    "completed": set(),
    "declined": set(),
    "expired": set(),
    "cancelled": set(),
}
REQUESTER_ONLY = {"sent", "cancelled"}

STATUS_LABEL = {
    "draft": "Draft", "sent": "Sent", "accepted": "Accepted", "scheduled": "Scheduled",
    "completed": "Completed", "declined": "Declined", "expired": "Expired", "cancelled": "Cancelled",
}


def _valid_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        UUID(value)
        return True
    except ValueError:
        return False


def _history(conn: Connection, sr_id: str, patient_id: str, from_status: str | None, to_status: str,
             actor: User | None, note: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO service_request_history (service_request_id, patient_id, from_status, to_status, actor_user_id, note)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (sr_id, patient_id, from_status, to_status, actor.id if actor else None, note),
    )
    audit.record(conn, action=f"referral_{to_status}", entity_type="service_request", entity_id=sr_id, actor=actor,
                 agent=None if actor else "referral-manager/rules", patient_id=patient_id,
                 detail={"from": from_status, "note": note})


# --- Automatic changes on read ---------------------------------------------------------------------


def refresh(conn: Connection, *, patient_id: str | None = None, organization_id: str | None = None,
            referral_id: str | None = None) -> None:
    """Apply expiry and booking detection to the referrals in scope. Idempotent; cheap when nothing changed."""
    scope = """
        (%(p)s::uuid IS NULL OR sr.patient_id = %(p)s::uuid)
        AND (%(o)s::uuid IS NULL OR sr.organization_id = %(o)s::uuid)
        AND (%(r)s::uuid IS NULL OR sr.id = %(r)s::uuid)
    """
    params = {"p": patient_id, "o": organization_id, "r": referral_id, "today": clinic_today(conn)}

    # 1. Expiry: sent or accepted referrals past their date.
    for r in conn.execute(
        f"""
        WITH due AS (
            SELECT sr.id, sr.status FROM service_requests sr
            WHERE sr.status IN ('sent', 'accepted') AND sr.expires_on < %(today)s AND {scope}
            FOR UPDATE
        )
        UPDATE service_requests s SET status = 'expired', status_note = 'Expired before it was booked', updated_at = now()
        FROM due WHERE s.id = due.id
        RETURNING s.id::text, s.patient_id::text, due.status AS from_status
        """,
        params,
    ).fetchall():
        _history(conn, r["id"], r["patient_id"], r["from_status"], "expired", None, "Passed its expiry date")

    # 2. Booking detected: an appointment in the referred specialty, booked after the referral was accepted.
    for r in conn.execute(
        f"""
        SELECT sr.id::text, sr.patient_id::text, appt.id::text AS appointment_id, appt.starts_at
        FROM service_requests sr
        JOIN LATERAL (
            SELECT a.id, s.starts_at FROM appointments a
            JOIN practitioners pr ON pr.id = a.practitioner_id
            JOIN slots s ON s.id = a.slot_id
            WHERE a.patient_id = sr.patient_id AND a.status IN ('booked', 'fulfilled')
              AND lower(pr.specialty) = lower(sr.specialty)
              AND a.created_at >= sr.accepted_at
              AND NOT EXISTS (SELECT 1 FROM service_requests o WHERE o.appointment_id = a.id AND o.id <> sr.id)
            ORDER BY s.starts_at LIMIT 1
        ) appt ON true
        WHERE sr.status = 'accepted' AND {scope}
        FOR UPDATE OF sr
        """,
        params,
    ).fetchall():
        conn.execute(
            """
            UPDATE service_requests SET status = 'scheduled', appointment_id = %s, scheduled_at = now(),
                   status_note = NULL, updated_at = now()
            WHERE id = %s
            """,
            (r["appointment_id"], r["id"]),
        )
        _history(conn, r["id"], r["patient_id"], "accepted", "scheduled", None,
                 f"Appointment booked for {r['starts_at']:%Y-%m-%d %H:%M} UTC")

    # 3. Scheduled referrals follow their appointment: completed when the visit is, back to accepted if cancelled.
    for r in conn.execute(
        f"""
        SELECT sr.id::text, sr.patient_id::text, a.status AS appointment_status
        FROM service_requests sr JOIN appointments a ON a.id = sr.appointment_id
        WHERE sr.status = 'scheduled' AND a.status IN ('fulfilled', 'cancelled') AND {scope}
        FOR UPDATE OF sr
        """,
        params,
    ).fetchall():
        if r["appointment_status"] == "fulfilled":
            conn.execute(
                "UPDATE service_requests SET status = 'completed', completed_at = now(), updated_at = now() WHERE id = %s",
                (r["id"],),
            )
            _history(conn, r["id"], r["patient_id"], "scheduled", "completed", None, "Visit completed")
        else:
            conn.execute(
                """
                UPDATE service_requests SET status = 'accepted', appointment_id = NULL, scheduled_at = NULL,
                       accepted_at = now(), status_note = 'The appointment was cancelled. It needs a new booking.',
                       updated_at = now()
                WHERE id = %s
                """,
                (r["id"],),
            )
            _history(conn, r["id"], r["patient_id"], "scheduled", "accepted", None, "Appointment cancelled")


# --- Views -----------------------------------------------------------------------------------------

_SELECT = """
    SELECT sr.id::text, sr.patient_id::text, p.name AS patient_name, sr.specialty, sr.reason, sr.priority,
           sr.required_documents, sr.provided_documents, sr.status, sr.status_note, sr.expires_on,
           sr.created_at, sr.sent_at, sr.accepted_at, sr.scheduled_at, sr.completed_at, sr.updated_at,
           sr.requester_id::text, rq.name AS requester_name,
           sr.target_practitioner_id::text AS target_id, tg.name AS target_name, tg.location_name AS target_location,
           sr.appointment_id::text, s.starts_at AS appointment_starts_at, apr.name AS appointment_practitioner,
           apr.location_name AS appointment_location
    FROM service_requests sr
    JOIN patients p ON p.id = sr.patient_id
    JOIN practitioners rq ON rq.id = sr.requester_id
    LEFT JOIN practitioners tg ON tg.id = sr.target_practitioner_id
    LEFT JOIN appointments a ON a.id = sr.appointment_id
    LEFT JOIN slots s ON s.id = a.slot_id
    LEFT JOIN practitioners apr ON apr.id = a.practitioner_id
"""


def _flags(r: dict, now: datetime, today: date) -> list[dict]:
    flags = []
    missing = [d for d in r["required_documents"] if d not in r["provided_documents"]]
    if missing and r["status"] in ("draft", "sent", "accepted"):
        flags.append({"code": "missing_documents", "label": f"Missing {len(missing)} document{'s' if len(missing) != 1 else ''}"})
    days_left = (r["expires_on"] - today).days
    if r["status"] in OPEN and 0 <= days_left <= EXPIRING_DAYS:
        flags.append({"code": "expiring", "label": "Expires today" if days_left == 0 else
                      f"Expires in {days_left} day{'s' if days_left != 1 else ''}"})
    if r["status"] == "expired":
        flags.append({"code": "expired", "label": "Expired"})
    if r["status"] == "accepted" and r["accepted_at"] and now - r["accepted_at"] >= timedelta(days=LEAK_DAYS):
        flags.append({"code": "leaking", "label": f"Not booked {(now - r['accepted_at']).days} days after acceptance"})
    return flags


def _plain(r: dict) -> dict:
    """Plain-language status and next step for the patient."""
    who = r["target_name"] or r["specialty"]
    book = {"kind": "book", "label": "Book an appointment", "to": f"/care/find?specialty={quote(r['specialty'])}"}
    st = r["status"]
    if st == "sent":
        return {"headline": f"Sent to {who}. Waiting for them to accept it.",
                "next_step": "Nothing to do yet. You can book as soon as they accept.", "action": None}
    if st == "accepted":
        headline = (f"Your appointment with {who} was cancelled. You can book a new time." if r["status_note"]
                    else f"Accepted by {who}. You can book now.")
        return {"headline": headline,
                "next_step": f"Book your appointment before {r['expires_on']:%d %B %Y}, when this referral expires.",
                "action": book}
    if st == "scheduled":
        return {"headline": "Your appointment is booked.",
                "next_step": "See how to get ready for your visit.",
                "action": {"kind": "visits", "label": "Get ready for my visit", "to": "/visits"}}
    if st == "completed":
        return {"headline": "Done. You've had this appointment.",
                "next_step": f"{r['requester_name']} will get the results.", "action": None}
    if st == "declined":
        return {"headline": f"{who} couldn't accept this referral.",
                "next_step": f"{r['requester_name']}'s team will talk with you about other options.", "action": None}
    if st == "expired":
        return {"headline": f"This referral expired on {r['expires_on']:%d %B %Y}.",
                "next_step": "If you still need this appointment, ask your care team for a new referral.", "action": None}
    if st == "cancelled":
        return {"headline": "Your care team cancelled this referral.",
                "next_step": "Nothing to do. Ask your care team if you have questions.", "action": None}
    return {"headline": "Being prepared by your care team.", "next_step": "", "action": None}


def _view(r: dict, now: datetime, today: date, for_patient: bool) -> dict:
    out = {
        "id": r["id"],
        "patient": {"id": r["patient_id"], "name": r["patient_name"]},
        "requester": {"id": r["requester_id"], "name": r["requester_name"]},
        "specialty": r["specialty"],
        "target": {"id": r["target_id"], "name": r["target_name"], "location": r["target_location"]} if r["target_id"] else None,
        "reason": r["reason"],
        "priority": r["priority"],
        "status": r["status"],
        "status_label": STATUS_LABEL[r["status"]],
        "status_note": r["status_note"],
        "required_documents": r["required_documents"],
        "provided_documents": r["provided_documents"],
        "missing_documents": [d for d in r["required_documents"] if d not in r["provided_documents"]],
        "expires_on": r["expires_on"],
        "days_to_expiry": (r["expires_on"] - today).days,
        "created_at": r["created_at"],
        "sent_at": r["sent_at"],
        "accepted_at": r["accepted_at"],
        "scheduled_at": r["scheduled_at"],
        "completed_at": r["completed_at"],
        "age_days": (now - (r["sent_at"] or r["created_at"])).days,
        "appointment": {
            "id": r["appointment_id"], "starts_at": r["appointment_starts_at"],
            "practitioner_name": r["appointment_practitioner"], "location": r["appointment_location"],
        } if r["appointment_id"] else None,
    }
    if for_patient:
        out["plain"] = _plain(r)
    else:
        out["flags"] = _flags(r, now, today)
        out["actions"] = sorted(TRANSITIONS[r["status"]])
    return out


def _now(conn: Connection) -> datetime:
    return conn.execute("SELECT now() AS t").fetchone()["t"]


def _load(conn: Connection, referral_id: str, lock: bool = False) -> dict:
    row = None
    if _valid_uuid(referral_id):
        row = conn.execute(
            _SELECT + " WHERE sr.id = %s" + (" FOR UPDATE OF sr" if lock else ""), (referral_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Referral not found")
    return row


def _history_rows(conn: Connection, referral_id: str) -> list[dict]:
    return conn.execute(
        """
        SELECT h.from_status, h.to_status, h.note, h.occurred_at,
               coalesce(u.display_name, 'Bioverse (automatic)') AS actor, u.role AS actor_role
        FROM service_request_history h LEFT JOIN users u ON u.id = h.actor_user_id
        WHERE h.service_request_id = %s ORDER BY h.occurred_at, h.id
        """,
        (referral_id,),
    ).fetchall()


def _access(conn: Connection, user: User, r: dict) -> None:
    if user.role == "patient" and (r["patient_id"] != user.patient_id or r["status"] == "draft"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Referral not found")
    assert_patient_access(conn, user, r["patient_id"])


# --- Endpoints -------------------------------------------------------------------------------------


@router.get("")
def list_referrals(
    conn: Conn,
    user: CurrentUser,
    view: Literal["sent", "incoming", "patient"] = "sent",
    patient_id: str | None = None,
) -> list[dict]:
    """Patients: their own referrals. Workforce: referrals I sent, incoming to the organization, or one patient's."""
    now, today = _now(conn), clinic_today(conn)
    if user.role == "patient":
        refresh(conn, patient_id=user.patient_id)
        rows = conn.execute(
            _SELECT + " WHERE sr.patient_id = %s AND sr.status <> 'draft' ORDER BY sr.created_at DESC",
            (user.patient_id,),
        ).fetchall()
        return [_view(r, now, today, for_patient=True) for r in rows]

    if user.role not in ("clinician", "staff", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Staff access required")
    if view == "patient":
        if not _valid_uuid(patient_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "patient_id is required")
        assert_patient_access(conn, user, patient_id)  # type: ignore[arg-type]
        refresh(conn, patient_id=patient_id)
        rows = conn.execute(_SELECT + " WHERE sr.patient_id = %s ORDER BY sr.created_at DESC", (patient_id,)).fetchall()
    elif view == "incoming":
        refresh(conn, organization_id=user.organization_id)
        rows = conn.execute(
            _SELECT + """
            WHERE sr.organization_id = %s AND sr.status IN ('sent', 'accepted', 'scheduled')
            ORDER BY (sr.priority = 'urgent') DESC, sr.sent_at
            """,
            (user.organization_id,),
        ).fetchall()
    else:
        if not user.practitioner_id:
            return []
        refresh(conn, organization_id=user.organization_id)
        rows = conn.execute(
            _SELECT + " WHERE sr.requester_id = %s ORDER BY sr.created_at DESC", (user.practitioner_id,)
        ).fetchall()
    return [_view(r, now, today, for_patient=False) for r in rows]


@router.get("/directory")
def directory(conn: Conn, user: Workforce) -> dict:
    """Practitioners and services in the organization a referral can go to."""
    rows = conn.execute(
        """
        SELECT id::text, name, specialty, location_name FROM practitioners
        WHERE organization_id = %s ORDER BY specialty, name
        """,
        (user.organization_id,),
    ).fetchall()
    return {"specialties": sorted({r["specialty"] for r in rows}), "practitioners": rows}


@router.get("/{referral_id}")
def get_referral(referral_id: str, conn: Conn, user: CurrentUser) -> dict:
    r = _load(conn, referral_id)
    _access(conn, user, r)
    refresh(conn, referral_id=referral_id)
    r = _load(conn, referral_id)
    out = _view(r, _now(conn), clinic_today(conn), for_patient=user.role == "patient")
    out["history"] = _history_rows(conn, referral_id)
    return out


class ReferralIn(BaseModel):
    patient_id: str
    specialty: str | None = Field(default=None, max_length=80)
    target_practitioner_id: str | None = None
    reason: str = Field(min_length=3, max_length=2000)
    priority: Literal["routine", "urgent"] = "routine"
    required_documents: list[str] = Field(default_factory=list, max_length=12)
    provided_documents: list[str] = Field(default_factory=list, max_length=12)
    expires_on: date | None = None
    send: bool = False


def _clean_docs(docs: list[str]) -> list[str]:
    out: list[str] = []
    for d in docs:
        d = d.strip()[:120]
        if d and d not in out:
            out.append(d)
    return out


@router.post("", status_code=status.HTTP_201_CREATED)
def create(body: ReferralIn, conn: Conn, user: Clinician) -> dict:
    if not _valid_uuid(body.patient_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    assert_patient_access(conn, user, body.patient_id)

    specialty = (body.specialty or "").strip()
    target_id = body.target_practitioner_id or None
    if target_id:
        target = None
        if _valid_uuid(target_id):
            target = conn.execute(
                "SELECT id::text, specialty FROM practitioners WHERE id = %s AND organization_id = %s",
                (target_id, user.organization_id),
            ).fetchone()
        if target is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That practitioner is not in your organization's directory")
        if specialty and specialty.lower() != target["specialty"].lower():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The practitioner does not match the chosen specialty")
        specialty = target["specialty"]
    if not specialty:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose a specialty")
    known = conn.execute(
        "SELECT 1 FROM practitioners WHERE organization_id = %s AND lower(specialty) = lower(%s) LIMIT 1",
        (user.organization_id, specialty),
    ).fetchone()
    if known is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No one in your organization offers that specialty")

    today = clinic_today(conn)
    expires_on = body.expires_on or today + timedelta(days=DEFAULT_VALID_DAYS[body.priority])
    if expires_on < today:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The expiry date is in the past")
    required = _clean_docs(body.required_documents)
    provided = [d for d in _clean_docs(body.provided_documents) if d in required]

    row = conn.execute(
        """
        INSERT INTO service_requests (organization_id, patient_id, requester_id, specialty, target_practitioner_id,
                                      reason, priority, required_documents, provided_documents, expires_on)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text
        """,
        (user.organization_id, body.patient_id, user.practitioner_id, specialty, target_id,
         body.reason.strip(), body.priority, required, provided, expires_on),
    ).fetchone()
    _history(conn, row["id"], body.patient_id, None, "draft", user)
    if body.send:
        _transition(conn, user, _load(conn, row["id"], lock=True), "sent", None)
    return get_referral(row["id"], conn, user)


def _transition(conn: Connection, user: User, r: dict, new: str, note: str | None) -> None:
    current = r["status"]
    if new not in TRANSITIONS[current]:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "invalid_transition",
             "message": f"A {STATUS_LABEL[current].lower()} referral can't be marked {STATUS_LABEL[new].lower()}."},
        )
    if new in REQUESTER_ONLY and user.practitioner_id != r["requester_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the referring clinician can do that")
    if new == "declined" and not (note and note.strip()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give a reason for declining")

    stamp = {"sent": "sent_at", "accepted": "accepted_at", "scheduled": "scheduled_at", "completed": "completed_at"}.get(new)
    conn.execute(
        f"""
        UPDATE service_requests SET status = %s, status_note = %s, updated_at = now()
            {f', {stamp} = now()' if stamp else ''}
        WHERE id = %s
        """,
        (new, (note or "").strip() or None, r["id"]),
    )
    _history(conn, r["id"], r["patient_id"], current, new, user, (note or "").strip() or None)

    if new == "sent" and r["target_id"]:
        # Notify the receiving side through their review queue.
        conn.execute(
            """
            INSERT INTO review_items (kind, patient_id, practitioner_id, ref_id, title, body, priority, link)
            VALUES ('referral', %s, %s, %s, %s, %s, %s, '/clinician/referrals')
            """,
            (r["patient_id"], r["target_id"], r["id"], f"Referral · {r['specialty']} from {r['requester_name']}",
             r["reason"], r["priority"]),
        )
    if new in ("accepted", "declined", "cancelled"):
        conn.execute(
            """
            UPDATE review_items SET status = 'resolved', resolution = %s, resolved_by = %s, resolved_at = now()
            WHERE kind = 'referral' AND ref_id = %s AND status = 'open' AND practitioner_id IS DISTINCT FROM %s
            """,
            (f"{new} by {user.display_name}", user.id, r["id"], r["requester_id"]),
        )
    if new == "declined":
        conn.execute(
            """
            INSERT INTO review_items (kind, patient_id, practitioner_id, ref_id, title, body, priority, link)
            VALUES ('referral', %s, %s, %s, %s, %s, 'routine', '/clinician/referrals')
            """,
            (r["patient_id"], r["requester_id"], r["id"], f"Referral declined · {r['specialty']}",
             f"Declined by {user.display_name}: {note.strip()}"),  # type: ignore[union-attr]
        )


class StatusIn(BaseModel):
    status: Literal["sent", "accepted", "declined", "scheduled", "completed", "cancelled"]
    note: str | None = Field(default=None, max_length=1000)


@router.post("/{referral_id}/status")
def change_status(referral_id: str, body: StatusIn, conn: Conn, user: Workforce) -> dict:
    """Advance a referral. Accept, decline, scheduled and completed can be done by anyone in the organization;
    send and cancel only by the referring clinician. Who did it is recorded."""
    r = _load(conn, referral_id, lock=True)
    _access(conn, user, r)
    refresh(conn, referral_id=referral_id)  # an expired referral can't be accepted
    r = _load(conn, referral_id, lock=True)
    _transition(conn, user, r, body.status, body.note)
    return get_referral(referral_id, conn, user)


class DocumentsIn(BaseModel):
    provided: list[str] = Field(max_length=12)


@router.put("/{referral_id}/documents")
def set_documents(referral_id: str, body: DocumentsIn, conn: Conn, user: Workforce) -> dict:
    r = _load(conn, referral_id, lock=True)
    _access(conn, user, r)
    if r["status"] in TERMINAL:
        raise HTTPException(status.HTTP_409_CONFLICT, "This referral is closed")
    provided = _clean_docs(body.provided)
    unknown = [d for d in provided if d not in r["required_documents"]]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Not a required document: {unknown[0]}")
    conn.execute("UPDATE service_requests SET provided_documents = %s, updated_at = now() WHERE id = %s", (provided, r["id"]))
    audit.record(conn, action="referral_documents_updated", entity_type="service_request", entity_id=r["id"], actor=user,
                 patient_id=r["patient_id"], detail={"provided": provided})
    return get_referral(referral_id, conn, user)
