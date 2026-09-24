"""Personal Health AI: questions about my own record, and my year in review. See agents/health_ai.py."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from bioverse import audit, consent
from bioverse.agents import health_ai, llm
from bioverse.auth import CurrentUser, assert_patient_access
from bioverse.db import DbConn

router = APIRouter(prefix="/api/health-ai", tags=["health-ai"])

Conn = DbConn


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=500)


@router.post("/patients/{patient_id}/ask")
def ask(patient_id: str, body: AskIn, conn: Conn, user: CurrentUser) -> dict:
    assert_patient_access(conn, user, patient_id)
    allowed = consent.ai_allowed(conn, patient_id)
    result = health_ai.ask(conn, user, patient_id, body.question.strip(), ai_allowed=allowed)
    return {**result, "ai_consent": allowed}


@router.get("/patients/{patient_id}/year-in-review")
def year_in_review(patient_id: str, conn: Conn, user: CurrentUser,
                   year: int | None = Query(None, ge=1900, le=2100)) -> dict:
    assert_patient_access(conn, user, patient_id)
    allowed = consent.ai_allowed(conn, patient_id)
    result = health_ai.year_in_review(conn, user, patient_id, year or date.today().year, ai_allowed=allowed)
    return {**result, "ai_consent": allowed}


@router.get("/patients/{patient_id}/facts")
def facts(patient_id: str, conn: Conn, user: CurrentUser) -> dict:
    """Everything the Personal Health AI can see: the patient's own record, as numbered facts."""
    assert_patient_access(conn, user, patient_id)
    sheet = health_ai.fact_sheet(conn, patient_id)
    audit.record(conn, action="health_ai_facts_viewed", entity_type="patient", entity_id=patient_id, actor=user,
                 patient_id=patient_id)
    return {
        "facts": [health_ai.public_fact(f) for f in sheet],
        "ai_consent": consent.ai_allowed(conn, patient_id),
        "ai_available": llm.ai_enabled(),
    }
