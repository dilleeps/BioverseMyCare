"""Hospital operations: today's and next week's capacity, demand, intakes, escalations and workload,
plus the Hospital Agent. Administrators only. Every number comes from bioverse.agents.hospital_agent."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from bioverse import audit
from bioverse.agents import hospital_agent as ha
from bioverse.auth import Admin
from bioverse.db import DbConn

router = APIRouter(prefix="/api/ops", tags=["operations"])


@router.get("/dashboard")
def dashboard(conn: DbConn, user: Admin) -> dict:
    """Aggregates only: no patient names or identifiers."""
    clk = ha.clock()
    org = user.organization_id
    return {
        "generated_at": clk.now,
        "today": clk.today,
        "timezone": str(clk.now.tzinfo),
        "capacity_today": ha.capacity(conn, org, "today", clk=clk),
        "capacity_next_7_days": ha.capacity(conn, org, "next_7_days", clk=clk),
        "intakes_today": ha.intakes_today(conn, org, clk=clk),
        "red_flags_today": ha.red_flag_escalations_today(conn, org, clk=clk),
        "demand_vs_capacity": ha.demand_vs_capacity(conn, org, clk=clk),
        "clinician_workload": ha.clinician_workload(conn, org, clk=clk),
    }


@router.get("/assistant/metrics")
def assistant_metrics(user: Admin) -> list[dict]:
    """The fixed, read-only metrics the Hospital Agent may use."""
    return [{"name": t.name, "label": t.label, "description": t.description} for t in ha.REGISTRY.values()]


class QuestionIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)

    @field_validator("question")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 3:
            raise ValueError("Ask a question of at least 3 characters")
        return v


@router.post("/assistant")
def ask(body: QuestionIn, conn: DbConn, user: Admin) -> dict:
    result = ha.answer(conn, user.organization_id, body.question)
    audit.record(
        conn,
        action="hospital_agent_question",
        entity_type="organization",
        entity_id=user.organization_id,
        actor=user,
        agent=result.produced_by,
        model=result.model,
        detail={"question": body.question, "metrics": [m.name for m in result.metrics]},
    )
    return {
        "question": body.question,
        "answer": result.answer,
        "metrics_used": [m.as_dict() for m in result.metrics],
        "produced_by": result.produced_by,
        "model": result.model,
    }
