"""The front door: one conversation, run by the orchestrator."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection
from pydantic import BaseModel, Field, model_validator

from bioverse import audit
from bioverse.agents import orchestrator
from bioverse.auth import CurrentUser
from bioverse.db import DbConn

router = APIRouter(prefix="/api/conversations", tags=["front door"])

Conn = DbConn


class TurnIn(BaseModel):
    text: str | None = Field(default=None, max_length=4000)
    safety_answer: list[str] | None = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def exactly_one(self) -> "TurnIn":
        has_text = bool(self.text and self.text.strip())
        if has_text == (self.safety_answer is not None):
            raise ValueError("Send either text or safety_answer")
        return self


def _load(conn: Connection, user, conversation_id: str) -> dict:
    row = conn.execute(
        "SELECT id::text, patient_id::text, status, state, created_at FROM conversations WHERE id = %s",
        (conversation_id,),
    ).fetchone()
    if row is None or user.role != "patient" or row["patient_id"] != user.patient_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return row


def _messages(conn: Connection, conversation_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id::text, role, content, payload, created_at
        FROM messages WHERE conversation_id = %s ORDER BY seq
        """,
        (conversation_id,),
    ).fetchall()
    return [orchestrator.to_json(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def start(conn: Conn, user: CurrentUser) -> dict:
    if user.role != "patient":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only patients start front-door conversations")
    row = conn.execute(
        "INSERT INTO conversations (patient_id) VALUES (%s) RETURNING id::text, status",
        (user.patient_id,),
    ).fetchone()
    audit.record(conn, action="conversation_started", entity_type="conversation", entity_id=row["id"], actor=user,
                 patient_id=user.patient_id)
    return {"id": row["id"], "status": row["status"], "messages": []}


@router.get("/{conversation_id}")
def get(conversation_id: str, conn: Conn, user: CurrentUser) -> dict:
    convo = _load(conn, user, conversation_id)
    return {"id": convo["id"], "status": convo["status"], "messages": _messages(conn, conversation_id)}


@router.post("/{conversation_id}/messages")
def send(conversation_id: str, body: TurnIn, conn: Conn, user: CurrentUser) -> dict:
    # Lock the conversation row so two concurrent turns cannot interleave.
    conn.execute("SELECT 1 FROM conversations WHERE id = %s FOR UPDATE", (conversation_id,))
    convo = _load(conn, user, conversation_id)
    orchestrator.handle_turn(
        conn,
        user,
        convo,
        text=body.text.strip() if body.text else None,
        safety_answer=body.safety_answer,
    )
    refreshed = _load(conn, user, conversation_id)
    return {"id": refreshed["id"], "status": refreshed["status"], "messages": _messages(conn, conversation_id)}
