"""Mental wellbeing: PHQ-9 and GAD-7, a mood journal, retest reminders, and the crisis path.

Safety order, for every submission:
1. Crisis support is decided first and always returned: PHQ-9 item 9 above 0, or crisis language in any
   free text (bioverse.safety.red_flags). Raising the care-team alert runs in a savepoint afterwards, so a
   failure there can never block the support message.
2. Crisis and emergencies raise an URGENT review item and notify the clinician.
3. Moderate or worse scores raise a routine review item for the clinician.

Scores are shared with the clinician (Mood & anxiety panel). Journal notes stay private unless the patient
shares an entry; mood ratings and tags are visible to the care team. Every care-team read is audited.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from psycopg import Connection
from pydantic import BaseModel, Field

from bioverse import audit
from bioverse.auth import Clinician, CurrentUser
from bioverse.db import DbConn
from bioverse.mind_escalation import own_open_item, raise_review, resolve_item
from bioverse.mind_instruments import (INSTRUMENTS, MOOD_TAGS, RESOURCES, SCREENING_NOTE, crisis_support, score)
from bioverse.routers.nutrition import own_record, read_access
from bioverse.safety import red_flags

router = APIRouter(prefix="/api/mind", tags=["mind"])

Conn = DbConn
AGENT = "mind/rules"


def _link(patient_id: str) -> str:
    return f"/clinician/mind/{patient_id}"


@router.get("/instruments")
def instruments(user: CurrentUser) -> dict:
    return {"instruments": list(INSTRUMENTS.values()), "note": SCREENING_NOTE}


@router.get("/support")
def support() -> dict:
    """Crisis support and resources. Open to anyone, needs no database, so it can never be blocked."""
    return {"crisis": crisis_support(), "resources": RESOURCES}


# --- Questionnaires ---------------------------------------------------------------------------------------------


class ResponseIn(BaseModel):
    instrument: Literal["phq9", "gad7"]
    items: list[int]
    difficulty: str | None = Field(default=None, max_length=40)


def _crisis_block(notified: bool, flags: list[str] | None = None) -> dict[str, Any]:
    return {**crisis_support(), "care_team_notified": notified, "flags": flags or []}


@router.post("/patients/{patient_id}/responses", status_code=status.HTTP_201_CREATED)
def submit_response(patient_id: str, body: ResponseIn, conn: Conn, user: CurrentUser) -> dict:
    own_record(user, patient_id)
    spec = INSTRUMENTS[body.instrument]
    try:
        result = score(body.instrument, body.items)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    if body.difficulty is not None and body.difficulty not in spec["difficulty_options"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown answer for the last question")

    rid = str(uuid.uuid4())
    obs = conn.execute(
        """
        INSERT INTO observations (patient_id, loinc_code, display, value, unit, interpretation, effective_at,
                                  category, source, note)
        VALUES (%s, %s, %s, %s, '{score}', %s, now(), 'survey', 'manual', %s) RETURNING id::text
        """,
        (patient_id, spec["loinc"], spec["display"], result["total"], "A" if result["needs_review"] else "N",
         f"{spec['title']} · {result['severity_label']}"),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO mind_questionnaire_responses (id, patient_id, instrument, items, difficulty, total, severity,
                                                  item9, crisis, observation_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (rid, patient_id, body.instrument, body.items, body.difficulty, result["total"], result["severity"],
         result["item9"], result["crisis"], obs["id"]),
    )
    audit.record(conn, action="mind_questionnaire_completed", entity_type="questionnaire_response", entity_id=rid,
                 actor=user, agent=AGENT, patient_id=patient_id,
                 detail={"instrument": body.instrument, "total": result["total"], "severity": result["severity"],
                         "crisis": result["crisis"]})

    crisis = None
    review_id = None
    if result["crisis"]:
        # Decided before anything else can fail; the alert is best-effort on top of it.
        review_id = raise_review(
            conn, patient_id=patient_id, kind="mind_crisis", priority="urgent", actor=user, agent=AGENT, ref_id=rid,
            link=_link(patient_id),
            title=f"Urgent · PHQ-9 item 9 answered “{spec['options'][result['item9']]['label']}”",
            body=(f"The patient answered PHQ-9 item 9 (thoughts of being better off dead or of self-harm) with "
                  f"“{spec['options'][result['item9']]['label']}”. PHQ-9 total {result['total']} "
                  f"({result['severity_label'].lower()}). They were shown the 988 Suicide & Crisis Lifeline and "
                  f"{red_flags.EMERGENCY_NUMBER}. Please contact them today."),
            notify_title="Urgent: a patient needs follow-up today",
            detail={"instrument": "phq9", "item9": result["item9"]},
        )
        crisis = _crisis_block(review_id is not None)
    elif result["needs_review"]:
        review_id = raise_review(
            conn, patient_id=patient_id, kind="mind_score", priority="routine", actor=user, agent=AGENT, ref_id=rid,
            link=_link(patient_id),
            title=f"{spec['title']} {result['total']} · {result['severity_label'].lower()}",
            body=(f"{spec['title']} total {result['total']} of {spec['max']} ({result['severity_label'].lower()}), "
                  f"completed by the patient in Bioverse. Difficulty: {body.difficulty or 'not answered'}."),
            notify_title="A patient's wellbeing check needs your review",
        )
    if review_id:
        conn.execute("UPDATE mind_questionnaire_responses SET review_item_id = %s WHERE id = %s", (review_id, rid))

    return {"id": rid, **result, "title": spec["title"], "note": SCREENING_NOTE, "crisis": crisis,
            "shared_with_care_team": True, "review_requested": review_id is not None and not result["crisis"]}


def _responses(conn: Connection, patient_id: str) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id::text, instrument, items, difficulty, total, severity, item9, crisis, created_at
        FROM mind_questionnaire_responses WHERE patient_id = %s ORDER BY created_at
        """,
        (patient_id,),
    ).fetchall()


def _prefs(conn: Connection, patient_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT retest_reminders, retest_weeks FROM mind_preferences WHERE patient_id = %s",
                       (patient_id,)).fetchone()
    return row or {"retest_reminders": False, "retest_weeks": 4}


@router.get("/patients/{patient_id}/results")
def results(patient_id: str, conn: Conn, user: CurrentUser) -> dict:
    read_access(conn, user, patient_id, "mind_results")
    rows = _responses(conn, patient_id)
    prefs = _prefs(conn, patient_id)
    out: dict[str, Any] = {"note": SCREENING_NOTE, "preferences": prefs, "instruments": {}}
    for key, spec in INSTRUMENTS.items():
        mine = [r for r in rows if r["instrument"] == key]
        latest = mine[-1] if mine else None
        next_due = latest["created_at"] + timedelta(weeks=prefs["retest_weeks"]) if latest else None
        entry: dict[str, Any] = {
            "title": spec["title"], "name": spec["name"], "max": spec["max"],
            "history": [{"id": r["id"], "at": r["created_at"], "total": r["total"], "severity": r["severity"],
                         "severity_label": score(key, r["items"])["severity_label"]} for r in mine],
            "latest": {**score(key, latest["items"]), "id": latest["id"], "at": latest["created_at"]} if latest else None,
            "next_due": next_due,
        }
        if user.role != "patient":
            entry["responses"] = [{"id": r["id"], "at": r["created_at"], "items": r["items"],
                                   "difficulty": r["difficulty"], "total": r["total"], "item9": r["item9"],
                                   "crisis": r["crisis"]} for r in reversed(mine)]
        out["instruments"][key] = entry
    if user.role != "patient":
        out["open_items"] = conn.execute(
            """
            SELECT id::text, kind, title, body, priority, created_at FROM review_items
            WHERE patient_id = %s AND kind IN ('mind_crisis', 'mind_score', 'mind_journal') AND status = 'open'
            ORDER BY priority = 'urgent' DESC, created_at
            """,
            (patient_id,),
        ).fetchall()
        out["item_texts"] = {k: v["items"] for k, v in INSTRUMENTS.items()}
    return out


class PrefsIn(BaseModel):
    retest_reminders: bool
    retest_weeks: int = Field(default=4, ge=2, le=4)


@router.put("/patients/{patient_id}/preferences")
def set_prefs(patient_id: str, body: PrefsIn, conn: Conn, user: CurrentUser) -> dict:
    own_record(user, patient_id)
    conn.execute(
        """
        INSERT INTO mind_preferences (patient_id, retest_reminders, retest_weeks) VALUES (%s, %s, %s)
        ON CONFLICT (patient_id) DO UPDATE SET retest_reminders = EXCLUDED.retest_reminders,
            retest_weeks = EXCLUDED.retest_weeks, updated_at = now()
        """,
        (patient_id, body.retest_reminders, body.retest_weeks),
    )
    audit.record(conn, action="mind_preferences_updated", entity_type="patient", entity_id=patient_id, actor=user,
                 patient_id=patient_id, detail=body.model_dump())
    return _prefs(conn, patient_id)


# --- Mood journal ---------------------------------------------------------------------------------------------------


class JournalIn(BaseModel):
    mood: int = Field(ge=1, le=5)
    tags: list[str] = Field(default_factory=list, max_length=10)
    note: str | None = Field(default=None, max_length=2000)
    shared: bool = False


@router.post("/patients/{patient_id}/journal", status_code=status.HTTP_201_CREATED)
def add_journal(patient_id: str, body: JournalIn, conn: Conn, user: CurrentUser) -> dict:
    own_record(user, patient_id)
    tags = sorted({t for t in body.tags if t in MOOD_TAGS})
    note = (body.note or "").strip() or None
    screen = red_flags.screen(note) if note else red_flags.ScreenResult(level="none")
    eid = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO mind_journal_entries (id, patient_id, mood, tags, note, shared, red_flag_level)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (eid, patient_id, body.mood, tags, note, body.shared, screen.level),
    )
    audit.record(conn, action="mood_logged", entity_type="mood_entry", entity_id=eid, actor=user, patient_id=patient_id,
                 detail={"mood": body.mood, "shared": body.shared, "screen": screen.level})
    crisis = emergency = None
    if screen.level == "crisis":
        rid = raise_review(
            conn, patient_id=patient_id, kind="mind_journal", priority="urgent", actor=user, agent="safety/red-flags",
            ref_id=eid, link=_link(patient_id), title="Urgent · crisis language in mood journal",
            body=(f"Red-flag screen found {', '.join(screen.flags)} in a mood journal entry (mood {body.mood}/5). "
                  f"They wrote: “{note[:500]}”. They were shown the 988 Suicide & Crisis Lifeline."),
            notify_title="Urgent: a patient needs follow-up today",
            detail={"flags": screen.flags, "ruleset": screen.ruleset},
        )
        crisis = _crisis_block(rid is not None, screen.flags)
    elif screen.level == "emergency":
        rid = raise_review(
            conn, patient_id=patient_id, kind="mind_journal", priority="urgent", actor=user, agent="safety/red-flags",
            ref_id=eid, link=_link(patient_id), title=f"Red flag · {', '.join(screen.flags)}",
            body=f"Found in a mood journal entry. Patient was advised to seek emergency care. They wrote: “{note[:500]}”",
            notify_title="Urgent: a patient needs follow-up today",
            detail={"flags": screen.flags, "ruleset": screen.ruleset},
        )
        emergency = {"message": red_flags.emergency_message(screen), "emergency_number": red_flags.EMERGENCY_NUMBER,
                     "flags": screen.flags, "care_team_notified": rid is not None}
    notice = None
    if screen.level == "screen":
        notice = {"topic": screen.topic, "to": "/app", "initial": note,
                  "message": "You mentioned something that can sometimes need urgent care. Please tell Bioverse "
                             "about it so it can check a few things with you."}
    return {"id": eid, "crisis": crisis, "emergency": emergency, "symptom_notice": notice,
            "entries": _journal(conn, patient_id, patient_view=True)}


def _journal(conn: Connection, patient_id: str, patient_view: bool, days: int = 60) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id::text, mood, tags, note, shared, created_at FROM mind_journal_entries
        WHERE patient_id = %s AND created_at > now() - make_interval(days => %s) ORDER BY created_at DESC
        """,
        (patient_id, days),
    ).fetchall()
    if not patient_view:
        for r in rows:
            if not r["shared"]:
                r["note"] = None
    return rows


@router.get("/patients/{patient_id}/journal")
def get_journal(patient_id: str, conn: Conn, user: CurrentUser) -> dict:
    read_access(conn, user, patient_id, "mood_journal")
    return {"tags": MOOD_TAGS, "entries": _journal(conn, patient_id, patient_view=user.role == "patient")}


@router.delete("/patients/{patient_id}/journal/{entry_id}")
def delete_journal(patient_id: str, entry_id: str, conn: Conn, user: CurrentUser) -> dict:
    own_record(user, patient_id)
    gone = conn.execute("DELETE FROM mind_journal_entries WHERE id::text = %s AND patient_id = %s RETURNING id::text",
                        (entry_id, patient_id)).fetchone()
    if gone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    audit.record(conn, action="mood_deleted", entity_type="mood_entry", entity_id=entry_id, actor=user,
                 patient_id=patient_id)
    return {"tags": MOOD_TAGS, "entries": _journal(conn, patient_id, patient_view=True)}


# --- Clinician follow-up -----------------------------------------------------------------------------------------------


class FollowUpIn(BaseModel):
    note: str = Field(min_length=2, max_length=2000)


@router.post("/review-items/{item_id}/resolve")
def resolve(item_id: str, body: FollowUpIn, conn: Conn, user: Clinician) -> dict:
    item = own_open_item(conn, item_id, user, ("mind_crisis", "mind_score", "mind_journal"))
    resolve_item(conn, item, user, f"Followed up: {body.note.strip()}")
    return {"id": item_id, "status": "resolved"}


def retest_due(conn: Connection, now: datetime) -> list[dict[str, Any]]:
    """Opted-in patients whose latest PHQ-9 or GAD-7 is older than their chosen interval."""
    rows = conn.execute(
        """
        SELECT DISTINCT ON (r.patient_id, r.instrument) r.patient_id::text, r.instrument, r.id::text AS response_id,
               r.created_at, p.retest_weeks
        FROM mind_questionnaire_responses r JOIN mind_preferences p ON p.patient_id = r.patient_id
        WHERE p.retest_reminders
        ORDER BY r.patient_id, r.instrument, r.created_at DESC
        """
    ).fetchall()
    return [r for r in rows if r["created_at"] + timedelta(weeks=r["retest_weeks"]) <= now]
