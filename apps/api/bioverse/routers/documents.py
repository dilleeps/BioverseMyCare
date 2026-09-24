"""Patient document upload (module 6): upload -> extract -> the patient checks and confirms -> clinician review.

Nothing reaches the record until the patient confirms the values (POST /api/documents/{id}/confirm with
`confirmed: true`). Confirmed values are saved as a patient-uploaded report (`source = 'patient_upload'`),
and the explanation waits in the responsible clinician's review queue before the patient sees it.

Uploads are sent as the raw request body (Content-Type = the file's type), so no multipart parser is needed
and the 10 MB limit is enforced while the body streams in.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from psycopg import Connection
from pydantic import BaseModel, Field, field_validator

from bioverse import audit, consent, terminology
from bioverse.agents import results_extraction as rx
from bioverse.auth import CurrentUser, Patient, User, assert_patient_access
from bioverse.db import DbConn
from bioverse.db.seeds.context import SeedContext

router = APIRouter(prefix="/api/documents", tags=["documents"])

MAX_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 100_000
ALLOWED_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp", "image/gif", "text/plain"}


# --- Validation ----------------------------------------------------------------------------------


def sniff(content: bytes) -> str | None:
    """The real type from the file's first bytes. A declared type that disagrees is refused."""
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return "text/plain" if "\x00" not in text else None


async def read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "That file is larger than 10 MB. Try a smaller file or paste the text instead.")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "That file is larger than 10 MB. Try a smaller file or paste the text instead.")
        chunks.append(chunk)
    return b"".join(chunks)


Body = Annotated[bytes, Depends(read_body)]


def _declared_type(request: Request) -> str:
    return (request.headers.get("content-type") or "").split(";")[0].strip().lower()


# --- Shared helpers ------------------------------------------------------------------------------


def _load(conn: Connection, user: User, document_id: str, *, lock: bool = False) -> dict[str, Any]:
    try:
        UUID(document_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found") from None
    row = conn.execute(
        f"""
        SELECT id::text, patient_id::text, uploaded_by::text, kind, filename, content_type, size_bytes, sha256,
               status, extraction, extracted_by, report_id::text, created_at, confirmed_at
        FROM document_references WHERE id = %s {'FOR UPDATE' if lock else ''}
        """,
        (document_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    assert_patient_access(conn, user, row["patient_id"])
    return row


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k != "content"}


def responsible_practitioner(conn: Connection, patient_id: str) -> str | None:
    """Who reviews a patient-supplied result: the care-plan clinician, else whoever last looked after them."""
    row = conn.execute(
        """
        SELECT practitioner_id::text AS id FROM (
            SELECT practitioner_id, 1 AS rank, started_at AS at FROM care_plans WHERE patient_id = %(p)s AND status = 'active'
            UNION ALL
            SELECT responsible_practitioner_id, 2, collected_at FROM diagnostic_reports
             WHERE patient_id = %(p)s AND responsible_practitioner_id IS NOT NULL
            UNION ALL
            SELECT practitioner_id, 3, occurred_at FROM encounters WHERE patient_id = %(p)s AND practitioner_id IS NOT NULL
            UNION ALL
            SELECT a.practitioner_id, 4, s.starts_at FROM appointments a JOIN slots s ON s.id = a.slot_id
             WHERE a.patient_id = %(p)s AND a.status <> 'cancelled'
        ) c ORDER BY rank, at DESC LIMIT 1
        """,
        {"p": patient_id},
    ).fetchone()
    return row["id"] if row else None


def _store(conn: Connection, user: User, patient_id: str, content: bytes, content_type: str,
           filename: str | None) -> dict[str, Any]:
    row = conn.execute(
        """
        INSERT INTO document_references (patient_id, uploaded_by, filename, content_type, size_bytes, sha256, content)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id::text
        """,
        (patient_id, user.id, filename, content_type, len(content), hashlib.sha256(content).hexdigest(), content),
    ).fetchone()
    doc_id = row["id"]
    audit.record(conn, action="document_uploaded", entity_type="document_reference", entity_id=doc_id, actor=user,
                 patient_id=patient_id, detail={"content_type": content_type, "size_bytes": len(content)})

    ai_ok = consent.ai_allowed(conn, patient_id)
    result = rx.extract(conn, content, content_type, ai_allowed=ai_ok)
    produced_by, model, notice = result.pop("produced_by"), result.pop("model"), result.pop("notice")
    result["notice"] = notice
    conn.execute(
        "UPDATE document_references SET status = 'extracted', extraction = %s, extracted_by = %s WHERE id = %s",
        (json.dumps(result), produced_by, doc_id),
    )
    audit.record(conn, action="document_extracted", entity_type="document_reference", entity_id=doc_id, actor=user,
                 agent=produced_by, model=model, patient_id=patient_id,
                 detail={"results": len(result["results"]), "ai_consent": ai_ok,
                         "dropped_unsupported": result["dropped_unsupported"]})
    return _public(_load(conn, user, doc_id))


def _resolve_patient(user: User, patient_id: str | None) -> str:
    if patient_id and patient_id != user.patient_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only upload to your own record")
    return user.patient_id


# --- Endpoints -----------------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
def upload(request: Request, content: Body, conn: DbConn, user: Patient,
           filename: Annotated[str | None, Query(max_length=200)] = None,
           patient_id: str | None = None) -> dict:
    """Upload a lab report as the raw request body: a PDF, a PNG/JPEG/WebP/GIF image, or plain text, up to 10 MB."""
    pid = _resolve_patient(user, patient_id)
    declared = _declared_type(request)
    if declared not in ALLOWED_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            "Upload a PDF, a photo (PNG, JPEG, WebP or GIF), or a text file.")
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is empty.")
    actual = sniff(content)
    if actual != declared:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            "That file's contents don't match its type. Upload a PDF, a photo, or a text file.")
    name = (filename or "").strip().replace("/", "_").replace("\\", "_") or None
    return _store(conn, user, pid, content, declared, name)


class PastedText(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    patient_id: str | None = None


@router.post("/text", status_code=status.HTTP_201_CREATED)
def upload_text(body: PastedText, conn: DbConn, user: Patient) -> dict:
    """Paste the text of a lab report instead of uploading a file."""
    pid = _resolve_patient(user, body.patient_id)
    if not body.text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Paste the text of your report first.")
    return _store(conn, user, pid, body.text.encode("utf-8"), "text/plain", None)


@router.get("")
def list_documents(conn: DbConn, user: CurrentUser, patient_id: str | None = None) -> list[dict]:
    pid = patient_id or user.patient_id
    if not pid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "patient_id is required")
    assert_patient_access(conn, user, pid)
    rows = conn.execute(
        """
        SELECT d.id::text, d.filename, d.content_type, d.size_bytes, d.status, d.extracted_by, d.created_at,
               d.confirmed_at, d.report_id::text, r.name AS report_name, r.lab_name, r.collected_at,
               x.status AS explanation_status, pr.name AS reviewer,
               jsonb_array_length(coalesce(d.extraction -> 'results', '[]'::jsonb)) AS extracted_count
        FROM document_references d
        LEFT JOIN diagnostic_reports r ON r.id = d.report_id
        LEFT JOIN result_explanations x ON x.report_id = d.report_id
        LEFT JOIN practitioners pr ON pr.id = r.responsible_practitioner_id
        WHERE d.patient_id = %s AND d.status <> 'discarded'
        ORDER BY d.created_at DESC
        """,
        (pid,),
    ).fetchall()
    audit.record(conn, action="documents_listed", entity_type="document_reference", actor=user, patient_id=pid)
    return rows


@router.get("/{document_id}")
def get_document(document_id: str, conn: DbConn, user: CurrentUser) -> dict:
    row = _load(conn, user, document_id)
    audit.record(conn, action="document_viewed", entity_type="document_reference", entity_id=document_id, actor=user,
                 patient_id=row["patient_id"])
    return _public(row)


@router.get("/{document_id}/content")
def document_content(document_id: str, conn: DbConn, user: CurrentUser) -> Response:
    row = _load(conn, user, document_id)
    data = conn.execute("SELECT content FROM document_references WHERE id = %s", (document_id,)).fetchone()["content"]
    audit.record(conn, action="document_downloaded", entity_type="document_reference", entity_id=document_id,
                 actor=user, patient_id=row["patient_id"])
    ext = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
           "image/gif": "gif", "text/plain": "txt"}[row["content_type"]]
    return Response(
        content=bytes(data),
        media_type=row["content_type"],
        headers={
            "Content-Disposition": f'attachment; filename="lab-report-{document_id[:8]}.{ext}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


class ConfirmedResult(BaseModel):
    test_name: str = Field(min_length=1, max_length=120)
    value: float
    unit: str = Field(default="", max_length=40)
    ref_low: float | None = None
    ref_high: float | None = None
    loinc_code: str | None = Field(default=None, max_length=20)

    @field_validator("test_name", "unit")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()


class Confirmation(BaseModel):
    # The patient ticks "I've checked these values against my report". Without it nothing is saved.
    confirmed: Literal[True]
    report_name: str = Field(min_length=1, max_length=120)
    lab_name: str = Field(min_length=1, max_length=120)
    collected_on: date
    results: list[ConfirmedResult] = Field(min_length=1, max_length=100)


def _clinic_tz() -> ZoneInfo:
    return SeedContext().tz


@router.post("/{document_id}/confirm")
def confirm(document_id: str, body: Confirmation, conn: DbConn, user: Patient) -> dict:
    doc = _load(conn, user, document_id, lock=True)
    if doc["status"] == "confirmed":
        raise HTTPException(status.HTTP_409_CONFLICT, "These results are already saved")
    if doc["status"] != "extracted":
        raise HTTPException(status.HTTP_409_CONFLICT, "This document can no longer be saved")
    if body.collected_on > date.today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The collection date can't be in the future")
    for r in body.results:
        if r.ref_low is not None and r.ref_high is not None and r.ref_low > r.ref_high:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{r.test_name}: the range's low end is above its high end")
    patient_id = doc["patient_id"]
    practitioner_id = responsible_practitioner(conn, patient_id)
    if practitioner_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "There's no clinician on your care team to review this yet. Book a visit first, then add your results.")

    collected_at = datetime.combine(body.collected_on, time(12, 0), tzinfo=_clinic_tz())
    report_name = body.report_name.strip()
    if "patient-reported" not in report_name.lower():
        report_name = f"{report_name} (patient-reported)"
    report_id = conn.execute(
        """
        INSERT INTO diagnostic_reports (patient_id, name, lab_name, collected_at, responsible_practitioner_id, source)
        VALUES (%s, %s, %s, %s, %s, 'patient_upload') RETURNING id::text
        """,
        (patient_id, report_name[:160], body.lab_name.strip(), collected_at, practitioner_id),
    ).fetchone()["id"]

    saved = []
    for r in body.results:
        code, display = None, r.test_name
        if r.loinc_code and terminology.LOINC_CODE.match(r.loinc_code):
            known = terminology.lookup(conn, terminology.LOINC, r.loinc_code)
            if known:
                code = r.loinc_code
        if code is None:
            mapped = terminology.map_lab_name(conn, r.test_name)
            code = mapped["code"] if mapped else terminology.local_code(r.test_name)
        interp = rx.interpretation(r.value, r.ref_low, r.ref_high, None)
        conn.execute(
            """
            INSERT INTO observations (patient_id, report_id, loinc_code, display, value, unit, ref_low, ref_high,
                                      interpretation, effective_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (patient_id, report_id, code, display, r.value, r.unit, r.ref_low, r.ref_high, interp, collected_at),
        )
        saved.append({"display": display, "value": r.value, "unit": r.unit, "ref_low": r.ref_low,
                      "ref_high": r.ref_high, "interpretation": interp})

    draft, questions = rx.draft_explanation(saved, report_name=body.report_name.strip(), source="patient_upload")
    expl_id = conn.execute(
        """
        INSERT INTO result_explanations (report_id, draft_text, questions, status, produced_by)
        VALUES (%s, %s, %s, 'pending_review', 'results-agent/rules') RETURNING id::text
        """,
        (report_id, draft, json.dumps(questions)),
    ).fetchone()["id"]
    abnormal = sum(1 for s in saved if s["interpretation"] != "N")
    item_id = conn.execute(
        """
        INSERT INTO review_items (kind, patient_id, practitioner_id, ref_id, title, body, priority, link)
        VALUES ('result_explanation', %s, %s, %s, %s, %s, 'routine', %s) RETURNING id::text
        """,
        (
            patient_id, practitioner_id, expl_id,
            f"Patient-uploaded result · {body.report_name.strip()}"
            + (f" · {abnormal} outside range" if abnormal else ""),
            "Values the patient typed or confirmed from another lab's report "
            f"({body.lab_name.strip()}, collected {body.collected_on:%d %b %Y}). Check them against the uploaded "
            "document before approving. Draft explanation, not yet visible to the patient: " + draft,
            f"/results/{report_id}",
        ),
    ).fetchone()["id"]
    conn.execute(
        "UPDATE document_references SET status = 'confirmed', report_id = %s, confirmed_at = now() WHERE id = %s",
        (report_id, document_id),
    )
    audit.record(conn, action="document_confirmed", entity_type="document_reference", entity_id=document_id,
                 actor=user, patient_id=patient_id, detail={"report_id": report_id, "results": len(saved)})
    audit.record(conn, action="result_explanation_drafted", entity_type="result_explanation", entity_id=expl_id,
                 actor=user, agent="results-agent/rules", patient_id=patient_id,
                 detail={"report_id": report_id, "review_item_id": item_id, "source": "patient_upload"})
    return {"document_id": document_id, "report_id": report_id, "review_item_id": item_id,
            "status": "awaiting_review", "results": len(saved)}


@router.post("/{document_id}/discard")
def discard(document_id: str, conn: DbConn, user: Patient) -> dict:
    doc = _load(conn, user, document_id, lock=True)
    if doc["status"] == "confirmed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Saved results can't be discarded here. Ask your care team.")
    conn.execute("UPDATE document_references SET status = 'discarded' WHERE id = %s", (document_id,))
    audit.record(conn, action="document_discarded", entity_type="document_reference", entity_id=document_id,
                 actor=user, patient_id=doc["patient_id"])
    return {"id": document_id, "status": "discarded"}
