"""Duplicate patient records: the review queue, merge, and "find a patient record" for the front desk.

Admins and front-desk staff only. Merged (retired) records never appear here: every query filters
`merged_into IS NULL`. A merge cannot be undone from the app.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from bioverse import audit
from bioverse.auth import CurrentUser, User
from bioverse.db import DbConn
from bioverse.patient_match import search as match_search
from bioverse.patient_registry import MergeRefused, merge_patients, record_counts

router = APIRouter(prefix="/api/patient-matching", tags=["patient-matching"])


def require_registrar(user: CurrentUser) -> User:
    """Organization admins, and staff on the front desk team."""
    if user.role == "admin" or (user.role == "staff" and user.team == "front_desk"):
        return user
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin or front desk access required")


Registrar = Annotated[User, Depends(require_registrar)]

_PATIENT_SQL = """
    SELECT p.id::text, p.name, p.birth_date, p.sex_at_birth, p.created_at, p.merged_into::text,
           COALESCE(p.email, u.email) AS email, p.phone, (p.user_id IS NOT NULL) AS has_login,
           u.disabled AS login_disabled,
           COALESCE((SELECT json_agg(json_build_object('system', i.system, 'authority', i.hl7_authority,
                                                        'value', i.value, 'type', i.type_code) ORDER BY i.system)
                     FROM patient_identifiers i WHERE i.patient_id = p.id), '[]') AS identifiers
    FROM patients p LEFT JOIN users u ON u.id = p.user_id
"""


def _patient(conn, patient_id: str, with_counts: bool = False) -> dict | None:
    row = conn.execute(_PATIENT_SQL + " WHERE p.id = %s", (patient_id,)).fetchone()
    if row and with_counts:
        counts = record_counts(conn, patient_id)
        counts.pop("patient_identifiers", None)
        row["records"] = {"total": sum(counts.values()), "by_module": counts}
    return row


def _review(conn, row: dict, with_counts: bool = True) -> dict:
    return {
        "id": row["id"], "status": row["status"], "level": row["level"], "score": row["score"],
        "reasons": row["reasons"], "source": row["source"], "created_at": row["created_at"],
        "decided_at": row["decided_at"], "decided_by": row.get("decided_by_name"), "survivor": row["survivor"],
        "merge_report": row["merge_report"],
        "existing": _patient(conn, row["patient_a"], with_counts),
        "new": _patient(conn, row["patient_b"], with_counts),
    }


_REVIEW_SQL = """
    SELECT r.id::text, r.status, r.level, r.score, r.reasons, r.source, r.created_at, r.decided_at,
           r.survivor::text, r.merge_report, r.patient_a::text, r.patient_b::text, d.display_name AS decided_by_name
    FROM match_reviews r LEFT JOIN users d ON d.id = r.decided_by
"""


def _load_review(conn, user: User, review_id: str, lock: bool = False) -> dict:
    row = conn.execute(
        _REVIEW_SQL + " WHERE r.id::text = %s AND r.organization_id = %s" + (" FOR UPDATE OF r" if lock else ""),
        (review_id, user.organization_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Review not found")
    return row


@router.get("/reviews")
def list_reviews(conn: DbConn, user: Registrar,
                 status_: Annotated[Literal["open", "merged", "not_duplicate", "decided", "all"],
                                    Query(alias="status")] = "open") -> dict:
    where = {"open": "r.status = 'open'", "merged": "r.status = 'merged'", "not_duplicate": "r.status = 'not_duplicate'",
             "decided": "r.status <> 'open'", "all": "true"}[status_]
    rows = conn.execute(
        _REVIEW_SQL + f" WHERE r.organization_id = %s AND {where} "
        "ORDER BY (r.status = 'open') DESC, CASE r.level WHEN 'certain' THEN 0 WHEN 'probable' THEN 1 ELSE 2 END, "
        "COALESCE(r.decided_at, r.created_at) DESC LIMIT 100",
        (user.organization_id,),
    ).fetchall()
    open_count = conn.execute(
        "SELECT count(*) AS n FROM match_reviews WHERE organization_id = %s AND status = 'open'", (user.organization_id,)
    ).fetchone()["n"]
    reviews = [_review(conn, r, with_counts=r["status"] == "open") for r in rows]
    audit.record(conn, action="patient_match.reviews_viewed", entity_type="match_review", actor=user,
                 detail={"status": status_, "count": len(reviews)})
    return {"reviews": reviews, "open": open_count}


@router.get("/reviews/{review_id}")
def get_review(review_id: str, conn: DbConn, user: Registrar) -> dict:
    row = _load_review(conn, user, review_id)
    audit.record(conn, action="patient_match.review_viewed", entity_type="match_review", entity_id=review_id, actor=user)
    return _review(conn, row)


class MergeBody(BaseModel):
    survivor: str


@router.post("/reviews/{review_id}/merge")
def merge(review_id: str, body: MergeBody, conn: DbConn, user: Registrar) -> dict:
    row = _load_review(conn, user, review_id, lock=True)
    if row["status"] != "open":
        raise HTTPException(409, "This review has already been decided")
    pair = {row["patient_a"], row["patient_b"]}
    if body.survivor not in pair:
        raise HTTPException(422, "The record to keep must be one of the two in this review")
    retired = (pair - {body.survivor}).pop()
    try:
        report = merge_patients(conn, survivor_id=body.survivor, retired_id=retired,
                                organization_id=user.organization_id, actor=user, review_id=review_id)
    except MergeRefused as e:
        raise HTTPException(409, str(e)) from None
    except psycopg.Error:
        raise HTTPException(409, "These records could not be merged; nothing was changed.") from None
    conn.execute(
        """
        UPDATE match_reviews SET status = 'merged', survivor = %s, decided_by = %s, decided_at = now(), merge_report = %s
        WHERE id = %s
        """,
        (body.survivor, user.id, json.dumps(report, default=str), review_id),
    )
    return {"review": _review(conn, _load_review(conn, user, review_id), with_counts=False), "report": report}


@router.post("/reviews/{review_id}/not-duplicate")
def not_duplicate(review_id: str, conn: DbConn, user: Registrar) -> dict:
    row = _load_review(conn, user, review_id, lock=True)
    if row["status"] != "open":
        raise HTTPException(409, "This review has already been decided")
    conn.execute(
        "UPDATE match_reviews SET status = 'not_duplicate', decided_by = %s, decided_at = now() WHERE id = %s",
        (user.id, review_id),
    )
    audit.record(conn, action="patient_match.not_duplicate", entity_type="match_review", entity_id=review_id,
                 actor=user, detail={"level": row["level"], "score": row["score"]})
    return {"review": _review(conn, _load_review(conn, user, review_id), with_counts=False)}


@router.get("/search")
def search(conn: DbConn, user: Registrar, name: str | None = None, birth_date: date | None = None,
           identifier: str | None = None, email: str | None = None, phone: str | None = None) -> dict:
    """Find existing records before registering someone. At least a name (2+ letters), date of birth,
    identifier, email or phone."""
    name = (name or "").strip() or None
    if not any([name and len(name) >= 2, birth_date, (identifier or "").strip(), (email or "").strip(),
                (phone or "").strip()]):
        raise HTTPException(422, "Enter a name, date of birth, identifier, email or phone number")
    matches = match_search(conn, user.organization_id, name=name, birth_date=birth_date, identifier=identifier,
                           email=email, phone=phone)
    results = []
    for m in matches:
        p = _patient(conn, m.patient_id)
        results.append({**p, "level": m.level, "score": m.score, "reasons": m.reasons})
    audit.record(conn, action="patient_match.search", entity_type="patient", actor=user,
                 detail={"criteria": sorted(k for k, v in {"name": name, "birth_date": birth_date,
                                                           "identifier": identifier, "email": email,
                                                           "phone": phone}.items() if v),
                         "results": len(results)})
    return {"results": results}
