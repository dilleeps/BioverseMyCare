"""Evidence Assistant for clinicians: cited answers, question history, and patient-relevant evidence.

Every answer is either statements that each carry a citation, or "No evidence found in the library."
See bioverse/agents/evidence.py.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from bioverse import audit
from bioverse.agents import evidence
from bioverse.auth import Clinician, assert_patient_access
from bioverse.db import DbConn

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    # Set only when the clinician ticks "use this patient's context". Only de-identified facts are used.
    patient_id: str | None = None

    @field_validator("question")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if len(v.strip()) < 3:
            raise ValueError("Ask a question of at least a few words")
        return v.strip()

    @field_validator("patient_id")
    @classmethod
    def valid_uuid(cls, v: str | None) -> str | None:
        if v:
            UUID(v)
        return v or None


def _public(answer: dict[str, Any]) -> dict[str, Any]:
    """Blocked uncited claims are kept for monitoring, never returned."""
    return {k: v for k, v in answer.items() if k != "removed"}


@router.post("/ask")
def ask(body: AskIn, conn: DbConn, user: Clinician) -> dict:
    if body.patient_id:
        assert_patient_access(conn, user, body.patient_id)
    try:
        answer = evidence.ask(conn, question=body.question, organization_id=user.organization_id,
                              patient_id=body.patient_id)
    except evidence.EmptyQuestion:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Your question was only patient identifiers. Ask it without names or record numbers.") from None
    public = _public(answer)
    row = conn.execute(
        """
        INSERT INTO evidence_queries (user_id, practitioner_id, patient_id, question, mode, model, answer,
                                      sources_count, removed_claims)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id::text, created_at
        """,
        (user.id, user.practitioner_id, body.patient_id, answer["question"], answer["mode"], answer["model"],
         Jsonb(public), len(answer["sources"]), Jsonb(answer["removed"])),
    ).fetchone()
    audit.record(
        conn,
        action="evidence_query",
        entity_type="evidence_query",
        entity_id=row["id"],
        actor=user,
        agent=answer["agent"],
        model=answer["model"],
        patient_id=body.patient_id,
        # Counts only: no question text and no patient details.
        detail={
            "mode": answer["mode"],
            "sources": len(answer["sources"]),
            "library_sources": sum(1 for s in answer["sources"] if s["origin"] == "library"),
            "web_sources": sum(1 for s in answer["sources"] if s["origin"] == "web"),
            "removed_uncited": answer["removed_count"],
            "no_evidence": answer["no_evidence"],
            "context_used": answer["context_used"],
            "redactions": answer["redactions"],
            "fallback_reason": answer["fallback_reason"],
        },
    )
    return {"id": row["id"], "created_at": row["created_at"], **public}


@router.get("/history")
def history(conn: DbConn, user: Clinician) -> list[dict]:
    return conn.execute(
        """
        SELECT id::text, question, mode, sources_count, (patient_id IS NOT NULL) AS context_used, created_at
        FROM evidence_queries WHERE user_id = %s
        ORDER BY created_at DESC LIMIT 25
        """,
        (user.id,),
    ).fetchall()


@router.get("/queries/{query_id}")
def get_query(query_id: str, conn: DbConn, user: Clinician) -> dict:
    try:
        UUID(query_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found") from None
    row = conn.execute(
        "SELECT id::text, answer, created_at FROM evidence_queries WHERE id = %s AND user_id = %s",
        (query_id, user.id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return {"id": row["id"], "created_at": row["created_at"], **row["answer"]}


@router.get("/patients/{patient_id}/suggestions")
def patient_suggestions(patient_id: str, conn: DbConn, user: Clinician) -> dict:
    """Two or three library items relevant to this patient's abnormal results and medicines. Rules only."""
    try:
        UUID(patient_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found") from None
    assert_patient_access(conn, user, patient_id)
    out = evidence.suggestions(conn, patient_id)
    audit.record(conn, action="evidence_suggestions_viewed", entity_type="patient", entity_id=patient_id,
                 actor=user, agent=evidence.AGENT_RULES, patient_id=patient_id,
                 detail={"items": len(out["items"])})
    return out
