"""Research & Clinical Trials: study browsing, consent-first matching, interest pipeline.

Anyone signed in can browse studies. Matching needs the patient's `research_matching` consent,
for the patient and for clinicians alike. Eligibility comes from bioverse/trials.py (rules only).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from psycopg import Connection
from pydantic import BaseModel, Field

from bioverse import audit, consent, trials
from bioverse.auth import Clinician, CurrentUser, Patient, User
from bioverse.db import DbConn
from bioverse.services.timeline import age as age_from

router = APIRouter(prefix="/api/research", tags=["research"])

SCOPE = "research_matching"
CONSENT_VERSION = "research-matching-v1"

# Who may move an interest record, and where to.
COORDINATOR_TRANSITIONS = {
    "interested": {"contacted", "not_eligible"},
    "contacted": {"screening", "not_eligible"},
    "screening": {"enrolled", "not_eligible"},
}
ACTIVE = ("interested", "contacted", "screening", "enrolled")


def _consent_state(conn: Connection, patient_id: str) -> dict[str, Any]:
    row = consent.get(conn, patient_id, SCOPE)
    return {
        "granted": consent.is_granted(conn, patient_id, SCOPE),
        "status": row["status"] if row else "not_decided",
        "updated_at": row["updated_at"] if row else None,
    }


def _interests(conn: Connection, patient_id: str) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT r.id::text, r.study_id::text, s.short_title, s.title, r.status, r.contact_permitted,
               r.history, r.created_at, r.updated_at
        FROM research_subjects r JOIN research_studies s ON s.id = r.study_id
        WHERE r.patient_id = %s
        ORDER BY r.updated_at DESC
        """,
        (patient_id,),
    ).fetchall()


def _history_entry(new_status: str, user: User, note: str | None = None) -> str:
    return json.dumps([{"status": new_status, "at": datetime.now(timezone.utc).isoformat(),
                        "by_role": user.role, "note": note}])


def _valid_id(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _load_study(conn: Connection, study_id: str) -> dict[str, Any]:
    study = trials.get_study(conn, study_id) if _valid_id(study_id) else None
    if study is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Study not found")
    return study


# --- Browsing (anyone signed in) -----------------------------------------------------------------


@router.get("/studies")
def studies(conn: DbConn, user: CurrentUser) -> list[dict]:
    return [trials.public_study(s) for s in trials.list_studies(conn)]


@router.get("/studies/{study_id}")
def study_detail(study_id: str, conn: DbConn, user: CurrentUser) -> dict:
    study = _load_study(conn, study_id)
    out: dict[str, Any] = {"study": trials.public_study(study), "match": None, "interest": None, "consent": None}
    if user.role == "patient" and user.patient_id:
        state = _consent_state(conn, user.patient_id)
        out["consent"] = state
        if state["granted"] and study["status"] == "recruiting":
            out["match"] = trials.evaluate(study, trials.load_record(conn, user.patient_id))
        out["interest"] = conn.execute(
            """
            SELECT id::text, status, contact_permitted, history, updated_at FROM research_subjects
            WHERE study_id = %s AND patient_id = %s
            """,
            (study_id, user.patient_id),
        ).fetchone()
    return out


@router.get("/studies/{study_id}/explanation")
def study_explanation(study_id: str, conn: DbConn, user: CurrentUser) -> dict:
    """A plainer-language version of the study summary. Uses no patient data."""
    study = _load_study(conn, study_id)
    allow_ai = consent.ai_allowed(conn, user.patient_id) if user.role == "patient" and user.patient_id else True
    result = trials.explain_study(study, allow_ai=allow_ai)
    if result["model"]:
        audit.record(conn, action="study_explained", entity_type="research_study", entity_id=study_id, actor=user,
                     agent=result["produced_by"], model=result["model"])
    return result


# --- Patient ---------------------------------------------------------------------------------


@router.get("/me")
def my_research(conn: DbConn, user: Patient) -> dict:
    state = _consent_state(conn, user.patient_id)
    matches = trials.matches_for(conn, user.patient_id) if state["granted"] else None
    if matches is not None:
        audit.record(conn, action="research_matches_viewed", entity_type="patient", entity_id=user.patient_id,
                     actor=user, agent="research-agent/rules", patient_id=user.patient_id,
                     detail={"matches": len(matches)})
    return {"consent": state, "matches": matches, "interests": _interests(conn, user.patient_id)}


class ConsentIn(BaseModel):
    granted: bool


@router.put("/consent")
def set_consent(body: ConsentIn, conn: DbConn, user: Patient) -> dict:
    pid = user.patient_id
    if body.granted:
        consent.set_status(conn, patient_id=pid, scope=SCOPE, status="granted", actor=user,
                           detail={"source": "research hub", "version": CONSENT_VERSION})
    else:
        consent.set_status(conn, patient_id=pid, scope=SCOPE, status="revoked", actor=user,
                           detail={"source": "research hub", "version": CONSENT_VERSION})
        paused = conn.execute(
            """
            UPDATE research_subjects
            SET contact_permitted = false, updated_at = now(), history = history || %s::jsonb
            WHERE patient_id = %s AND contact_permitted
            RETURNING id::text
            """,
            (_history_entry("contact_paused", user, "Research consent turned off"), pid),
        ).fetchall()
        for r in paused:
            audit.record(conn, action="research_contact_paused", entity_type="research_subject", entity_id=r["id"],
                         actor=user, patient_id=pid)
    return _consent_state(conn, pid)


@router.post("/studies/{study_id}/interest", status_code=201)
def express_interest(study_id: str, conn: DbConn, user: Patient) -> dict:
    pid = user.patient_id
    study = _load_study(conn, study_id)
    if not consent.is_granted(conn, pid, SCOPE):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Turn on research matching first, so the study team is allowed to contact you.")
    if study["status"] != "recruiting":
        raise HTTPException(status.HTTP_409_CONFLICT, "This study is not recruiting.")
    existing = conn.execute(
        "SELECT id::text, status, contact_permitted FROM research_subjects WHERE study_id = %s AND patient_id = %s FOR UPDATE",
        (study_id, pid),
    ).fetchone()
    if existing and existing["status"] in ("enrolled", "not_eligible"):
        raise HTTPException(status.HTTP_409_CONFLICT, "The study team has already made a decision about this study.")
    if existing and existing["status"] != "withdrawn" and existing["contact_permitted"]:
        return {"id": existing["id"], "status": existing["status"], "contact_permitted": True}

    if existing:
        new_status = "interested" if existing["status"] == "withdrawn" else existing["status"]
        row = conn.execute(
            """
            UPDATE research_subjects SET status = %s, contact_permitted = true, updated_at = now(),
                   history = history || %s::jsonb
            WHERE id = %s RETURNING id::text, status, contact_permitted
            """,
            (new_status, _history_entry(new_status, user, "Patient asked to be contacted"), existing["id"]),
        ).fetchone()
    else:
        row = conn.execute(
            """
            INSERT INTO research_subjects (study_id, patient_id, status, history)
            VALUES (%s, %s, 'interested', %s) RETURNING id::text, status, contact_permitted
            """,
            (study_id, pid, _history_entry("interested", user)),
        ).fetchone()
    audit.record(conn, action="research_interest", entity_type="research_subject", entity_id=row["id"], actor=user,
                 patient_id=pid, detail={"study_id": study_id})
    return row


@router.post("/interests/{interest_id}/withdraw")
def withdraw(interest_id: str, conn: DbConn, user: Patient) -> dict:
    row = _subject(conn, interest_id)
    if row is None or row["patient_id"] != user.patient_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if row["status"] == "withdrawn":
        raise HTTPException(status.HTTP_409_CONFLICT, "Already withdrawn")
    out = conn.execute(
        """
        UPDATE research_subjects SET status = 'withdrawn', contact_permitted = false, updated_at = now(),
               history = history || %s::jsonb
        WHERE id = %s RETURNING id::text, status, contact_permitted
        """,
        (_history_entry("withdrawn", user), interest_id),
    ).fetchone()
    audit.record(conn, action="research_withdrawn", entity_type="research_subject", entity_id=interest_id,
                 actor=user, patient_id=user.patient_id, detail={"from": row["status"]})
    return out


def _subject(conn: Connection, interest_id: str) -> dict | None:
    if not _valid_id(interest_id):
        return None
    return conn.execute(
        """
        SELECT r.id::text, r.status, r.contact_permitted, r.patient_id::text, r.study_id::text,
               p.organization_id::text
        FROM research_subjects r JOIN patients p ON p.id = r.patient_id
        WHERE r.id = %s FOR UPDATE OF r
        """,
        (interest_id,),
    ).fetchone()


# --- Coordinator / clinician -------------------------------------------------------------------


@router.get("/coordinator")
def coordinator(conn: DbConn, user: Clinician) -> dict:
    """Consented patients in the clinician's organization, their matches and interest pipeline.

    Patients without research consent never appear here, matched or not.
    """
    patients = conn.execute(
        """
        SELECT p.id::text, p.name, p.birth_date, c.updated_at AS consented_at
        FROM patients p
        JOIN consents c ON c.patient_id = p.id AND c.scope = %s AND c.grantee = '' AND c.status = 'granted'
                       AND (c.expires_at IS NULL OR c.expires_at > now())
        WHERE p.organization_id = %s
        ORDER BY p.name
        """,
        (SCOPE, user.organization_id),
    ).fetchall()
    out = []
    for p in patients:
        matches = trials.matches_for(conn, p["id"])
        out.append({
            "patient": {"id": p["id"], "name": p["name"], "age": age_from(p["birth_date"])},
            "consented_at": p["consented_at"],
            "matches": [{"study_id": m["study"]["id"], "short_title": m["study"]["short_title"],
                         "title": m["study"]["title"], "status": m["status"], "status_label": m["status_label"],
                         "criteria": m["criteria"]} for m in matches],
            "interests": _interests(conn, p["id"]),
        })
        audit.record(conn, action="research_pipeline_viewed", entity_type="patient", entity_id=p["id"], actor=user,
                     agent="research-agent/rules", patient_id=p["id"], detail={"matches": len(matches)})
    return {"patients": out, "transitions": {k: sorted(v) for k, v in COORDINATOR_TRANSITIONS.items()}}


class StatusIn(BaseModel):
    status: Literal["contacted", "screening", "enrolled", "not_eligible"]
    note: str | None = Field(default=None, max_length=500)


@router.post("/interests/{interest_id}/status")
def advance(interest_id: str, body: StatusIn, conn: DbConn, user: Clinician) -> dict:
    row = _subject(conn, interest_id)
    if row is None or row["organization_id"] != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not consent.is_granted(conn, row["patient_id"], SCOPE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not row["contact_permitted"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "The patient has paused contact for this study.")
    if body.status not in COORDINATOR_TRANSITIONS.get(row["status"], set()):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Can't move from {row['status']} to {body.status}.")
    note = body.note.strip() if body.note and body.note.strip() else None
    out = conn.execute(
        """
        UPDATE research_subjects SET status = %s, updated_at = now(), history = history || %s::jsonb
        WHERE id = %s RETURNING id::text, status, contact_permitted, history, updated_at
        """,
        (body.status, _history_entry(body.status, user, note), interest_id),
    ).fetchone()
    audit.record(conn, action="research_status_changed", entity_type="research_subject", entity_id=interest_id,
                 actor=user, patient_id=row["patient_id"],
                 detail={"from": row["status"], "to": body.status, "study_id": row["study_id"]})
    return out
