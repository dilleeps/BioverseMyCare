"""HL7 v2 lab import (module 22): ORU^R01 -> DiagnosticReport + Observations -> clinician review.

Pipeline per message (docs/05-interoperability.md, "Data normalization pipeline"):
parse -> validate -> patient matching -> terminology mapping -> store -> draft explanation -> review item.

Patient matching is deliberately conservative. A wrong merge is a patient-safety event, so a message is
REJECTED (never guessed) when identifiers disagree with each other or with the demographics, when no
patient matches, or when name and date of birth match more than one patient. Every message, accepted or
rejected, is kept in the import log with its reason.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from psycopg import Connection
from pydantic import BaseModel, Field

from bioverse import audit, hl7v2, terminology
from bioverse.agents import results_extraction as rx
from bioverse.auth import Admin, User
from bioverse.db import DbConn
from bioverse.db.seeds.context import SeedContext

router = APIRouter(prefix="/api/lab-import", tags=["lab-import"])

BIOVERSE_AUTHORITY = "BIOVERSE"  # PID-3 with this assigning authority carries the Bioverse patient id


class Rejected(Exception):
    def __init__(self, reason: str, stage: str, **detail: Any):
        super().__init__(reason)
        self.reason = reason
        self.stage = stage
        self.detail = detail


def _norm(s: str) -> str:
    return " ".join(s.lower().replace(",", " ").split())


def _name_parts(full: str) -> tuple[str, str]:
    parts = _norm(full).split()
    return (parts[0], parts[-1]) if len(parts) >= 2 else (parts[0] if parts else "", "")


# --- Patient matching -----------------------------------------------------------------------------


def match_patient(conn: Connection, pid: hl7v2.Segment, organization_id: str) -> tuple[str, str]:
    """(patient_id, method). Raises Rejected when the match is missing or not certain."""
    family = pid.component(5, 1).strip()
    given = pid.component(5, 2).strip()
    dob = hl7v2.parse_date(pid.component(7, 1))

    candidates: dict[str, str] = {}
    for rep in range(len(pid.repetitions(3))):
        value = pid.component(3, 1, rep).strip()
        authority = pid.component(3, 4, rep).strip()
        if not value or not authority:
            continue
        if authority.upper() == BIOVERSE_AUTHORITY:
            try:
                UUID(value)
            except ValueError:
                raise Rejected(f"PID-3 '{value}' is not a valid Bioverse patient id. Nothing was imported.",
                               "patient_match") from None
            row = conn.execute(
                "SELECT id::text FROM patients WHERE id = %s AND organization_id = %s", (value, organization_id)
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT pi.patient_id::text AS id FROM patient_identifiers pi JOIN patients p ON p.id = pi.patient_id
                WHERE upper(pi.hl7_authority) = upper(%s) AND pi.value = %s AND p.organization_id = %s
                """,
                (authority, value, organization_id),
            ).fetchone()
        if row:
            candidates[f"{authority}:{value}"] = row["id"]

    if len(set(candidates.values())) > 1:
        raise Rejected("The identifiers in PID-3 belong to different patients. Nothing was imported.",
                       "patient_match", identifiers=sorted(candidates))

    if candidates:
        patient_id = next(iter(candidates.values()))
        # An identifier on a record that was merged away belongs to the surviving record now.
        patient_id = conn.execute("SELECT coalesce(merged_into, id)::text AS id FROM patients WHERE id = %s",
                                  (patient_id,)).fetchone()["id"]
        p = conn.execute("SELECT name, birth_date FROM patients WHERE id = %s", (patient_id,)).fetchone()
        p_given, p_family = _name_parts(p["name"])
        if dob and dob != p["birth_date"]:
            raise Rejected("The identifier matches a patient, but the date of birth in PID-7 does not. Nothing was imported.",
                           "patient_match")
        if family and _norm(family).split()[-1] != p_family:
            raise Rejected("The identifier matches a patient, but the family name in PID-5 does not. Nothing was imported.",
                           "patient_match")
        return patient_id, "identifier"

    if not (family and given and dob):
        raise Rejected("No known identifier, and the message lacks the full name and date of birth needed to match. "
                       "Nothing was imported.", "patient_match")
    rows = conn.execute(
        "SELECT id::text, name FROM patients WHERE birth_date = %s AND organization_id = %s AND merged_into IS NULL",
        (dob, organization_id)
    ).fetchall()
    matches = [r["id"] for r in rows if _name_parts(r["name"]) == (_norm(given).split()[0], _norm(family).split()[-1])]
    if not matches:
        raise Rejected("No patient matches this identifier, name and date of birth. Nothing was imported.", "patient_match")
    if len(matches) > 1:
        raise Rejected(f"{len(matches)} patients share this name and date of birth, so the match is ambiguous. "
                       "Nothing was imported; resolve it by adding the patient's MRN to the message.",
                       "patient_match", candidates=len(matches))
    return matches[0], "name_dob"


def ordering_practitioner(conn: Connection, obr: hl7v2.Segment, organization_id: str) -> str | None:
    """OBR-16 ordering provider -> practitioner, by identifier, else by an exact, unique name."""
    ident = obr.component(16, 1).strip()
    authority = obr.component(16, 9).strip()
    if ident and authority:
        row = conn.execute(
            """
            SELECT pi.practitioner_id::text AS id FROM practitioner_identifiers pi
            JOIN practitioners pr ON pr.id = pi.practitioner_id
            WHERE upper(pi.hl7_authority) = upper(%s) AND pi.value = %s AND pr.organization_id = %s
            """,
            (authority, ident, organization_id),
        ).fetchone()
        if row:
            return row["id"]
    family, given = obr.component(16, 2).strip(), obr.component(16, 3).strip()
    if family and given:
        rows = conn.execute(
            "SELECT id::text, name FROM practitioners WHERE organization_id = %s", (organization_id,)
        ).fetchall()
        hits = [r["id"] for r in rows if _name_parts(r["name"].replace("Dr. ", "")) == (_norm(given), _norm(family))]
        if len(hits) == 1:
            return hits[0]
    return None


def care_plan_clinician(conn: Connection, patient_id: str) -> str | None:
    row = conn.execute(
        """
        SELECT practitioner_id::text AS id FROM care_plans WHERE patient_id = %s AND status = 'active'
        ORDER BY started_at DESC LIMIT 1
        """,
        (patient_id,),
    ).fetchone()
    return row["id"] if row else None


# --- Import ---------------------------------------------------------------------------------------


def _interpretation(flags: list[str], value: float, low: float | None, high: float | None) -> tuple[str, bool]:
    """(H/L/N, critical). OBX-8 flags win when they give a direction; otherwise the range decides."""
    upper = [f.upper() for f in flags if f]
    critical = any(f in ("HH", "LL", "AA") for f in upper)
    if any(f in ("H", "HH", ">") for f in upper):
        return "H", critical
    if any(f in ("L", "LL", "<") for f in upper):
        return "L", critical
    by_range = rx.interpretation(value, low, high, None)
    if by_range == "N" and any(f in ("A", "AA") for f in upper):
        # Abnormal without a direction and nothing in the range to say which way: never show it as normal.
        return "H", critical
    return by_range, critical


def import_message(conn: Connection, user: User, msg: hl7v2.Message) -> dict[str, Any]:
    """Create the report, observations, pending explanation and review item. Raises Rejected."""
    tz = SeedContext().tz
    if msg.message_type != "ORU^R01":
        raise Rejected(f"Only ORU^R01 results are imported; this is {msg.message_type or 'an unknown type'}.", "validate")
    control_id = msg.control_id
    facility = msg.msh.component(4, 1) or msg.msh.component(3, 1)
    if not control_id:
        raise Rejected("MSH-10 (message control id) is missing.", "validate")
    if conn.execute(
        "SELECT 1 FROM hl7_inbound_messages WHERE outcome = 'accepted' AND control_id = %s AND sending_facility = %s",
        (control_id, facility),
    ).fetchone():
        raise Rejected(f"Message {control_id} from {facility} was already imported. Duplicates are ignored.", "validate")
    pid = msg.first("PID")
    if pid is None:
        raise Rejected("The message has no PID segment, so there is no patient to match.", "validate")
    groups = msg.observation_groups()
    if not groups:
        raise Rejected("The message has no OBR segment.", "validate")
    if not any(g.obx for g in groups):
        raise Rejected("The message has no OBX results.", "validate")

    patient_id, method = match_patient(conn, pid, user.organization_id)

    reports: list[dict[str, Any]] = []
    skipped: list[str] = []
    critical_any = False
    for group in groups:
        obr = group.obr
        collected = (hl7v2.parse_dtm(obr.component(7, 1), tz) or hl7v2.parse_dtm(obr.component(22, 1), tz)
                     or hl7v2.parse_dtm(msh_time(msg), tz))
        if collected is None:
            raise Rejected("OBR-7 (collection time) is missing or unreadable.", "validate")
        name = obr.component(4, 2) or obr.component(4, 1) or "Lab result"
        observations = []
        for obx in group.obx:
            label = obx.component(3, 2) or obx.component(3, 1) or "result"
            if obx.component(11, 1).upper() in ("X", "D", "W"):
                skipped.append(f"{label}: not reported (status {obx.component(11, 1)})")
                continue
            value = hl7v2.numeric_value(obx)
            if value is None:
                skipped.append(f"{label}: not a numeric value")
                continue
            code, system = obx.component(3, 1).strip(), terminology.resolve_system(obx.component(3, 3))
            display = obx.component(3, 2).strip() or code
            if system == terminology.LOINC and terminology.LOINC_CODE.match(code):
                loinc = code
            else:
                mapped = terminology.map_lab_name(conn, display)
                loinc = mapped["code"] if mapped else terminology.local_code(display)
            unit = obx.component(6, 1).strip()
            low, high = hl7v2.parse_range(obx.text(7))
            flags = [obx.component(8, 1, r) for r in range(len(obx.repetitions(8)))]
            interp, critical = _interpretation(flags, value, low, high)
            critical_any = critical_any or critical
            effective = hl7v2.parse_dtm(obx.component(14, 1), tz) or collected
            observations.append({"loinc": loinc, "display": display, "value": value, "unit": unit, "ref_low": low,
                                 "ref_high": high, "interpretation": interp, "effective_at": effective})
        if observations:
            reports.append({"obr": obr, "name": name, "collected": collected, "observations": observations,
                            "lab": (obx_performer(group) or facility or "External lab")})
    if not reports:
        raise Rejected("None of the OBX results are numeric values Bioverse can store.", "validate", skipped=skipped)

    created = []
    for rep in reports:
        practitioner_id = ordering_practitioner(conn, rep["obr"], user.organization_id) or care_plan_clinician(conn, patient_id)
        if practitioner_id is None:
            raise Rejected("No ordering provider or care-plan clinician to review these results. Nothing was imported.",
                           "routing")
        report_id = conn.execute(
            """
            INSERT INTO diagnostic_reports (patient_id, name, lab_name, collected_at, responsible_practitioner_id, source)
            VALUES (%s, %s, %s, %s, %s, 'hl7_import') RETURNING id::text
            """,
            (patient_id, rep["name"][:160], rep["lab"][:160], rep["collected"], practitioner_id),
        ).fetchone()["id"]
        for o in rep["observations"]:
            conn.execute(
                """
                INSERT INTO observations (patient_id, report_id, loinc_code, display, value, unit, ref_low, ref_high,
                                          interpretation, effective_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (patient_id, report_id, o["loinc"], o["display"][:160], o["value"], o["unit"], o["ref_low"],
                 o["ref_high"], o["interpretation"], o["effective_at"]),
            )
        draft, questions = rx.draft_explanation(rep["observations"], report_name=rep["name"], source="hl7_import")
        expl_id = conn.execute(
            """
            INSERT INTO result_explanations (report_id, draft_text, questions, status, produced_by)
            VALUES (%s, %s, %s, 'pending_review', 'results-agent/rules') RETURNING id::text
            """,
            (report_id, draft, json.dumps(questions)),
        ).fetchone()["id"]
        abnormal = sum(1 for o in rep["observations"] if o["interpretation"] != "N")
        item_id = conn.execute(
            """
            INSERT INTO review_items (kind, patient_id, practitioner_id, ref_id, title, body, priority, link)
            VALUES ('result_explanation', %s, %s, %s, %s, %s, %s, %s) RETURNING id::text
            """,
            (
                patient_id, practitioner_id, expl_id,
                f"Result explanation · {rep['name']} (lab feed)" + (f" · {abnormal} outside range" if abnormal else ""),
                f"Received from {rep['lab']} by HL7 v2 (message {control_id}). "
                "Draft explanation, not yet visible to the patient: " + draft,
                "urgent" if critical_any else "routine",
                f"/results/{report_id}",
            ),
        ).fetchone()["id"]
        audit.record(conn, action="result_explanation_drafted", entity_type="result_explanation", entity_id=expl_id,
                     actor=user, agent="results-agent/rules", patient_id=patient_id,
                     detail={"report_id": report_id, "review_item_id": item_id, "source": "hl7_import"})
        created.append({"report_id": report_id, "review_item_id": item_id, "practitioner_id": practitioner_id,
                        "name": rep["name"], "results": len(rep["observations"]), "abnormal": abnormal})
    return {"patient_id": patient_id, "match_method": method, "reports": created, "skipped": skipped,
            "control_id": control_id, "facility": facility, "critical": critical_any}


def msh_time(msg: hl7v2.Message) -> str:
    return msg.msh.component(7, 1)


def obx_performer(group: hl7v2.ObservationGroup) -> str | None:
    for obx in group.obx:
        name = obx.component(23, 1).strip()  # OBX-23 performing organization (v2.5+)
        if name:
            return name
    return None


def process(conn: Connection, user: User, raw: str) -> dict[str, Any]:
    """Import one message inside a savepoint and log the outcome either way."""
    info: dict[str, Any] = {"message_type": None, "control_id": None, "facility": None}
    try:
        msg = hl7v2.parse(raw)
        info = {"message_type": msg.message_type, "control_id": msg.control_id,
                "facility": msg.msh.component(4, 1) or msg.msh.component(3, 1)}
        with conn.transaction():
            result = import_message(conn, user, msg)
    except hl7v2.HL7ParseError as exc:
        return _log(conn, user, raw, info, outcome="rejected", reason=str(exc), detail={"stage": "parse"})
    except Rejected as exc:
        return _log(conn, user, raw, info, outcome="rejected", reason=exc.reason, detail={"stage": exc.stage, **exc.detail})
    first = result["reports"][0]
    return _log(conn, user, raw, info, outcome="accepted", reason=None, patient_id=result["patient_id"],
                report_id=first["report_id"], review_item_id=first["review_item_id"],
                match_method=result["match_method"],
                detail={"reports": result["reports"], "skipped": result["skipped"], "critical": result["critical"]})


def _log(conn: Connection, user: User, raw: str, info: dict[str, Any], *, outcome: str, reason: str | None,
         detail: dict[str, Any], patient_id: str | None = None, report_id: str | None = None,
         review_item_id: str | None = None, match_method: str | None = None) -> dict[str, Any]:
    row = conn.execute(
        """
        INSERT INTO hl7_inbound_messages (received_at, received_by, organization_id, message_type, control_id,
                                          sending_facility, raw, outcome, reason, match_method, patient_id, report_id,
                                          review_item_id, detail)
        VALUES (clock_timestamp(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id::text, received_at
        """,
        (user.id, user.organization_id, info["message_type"], info["control_id"], info["facility"], raw[:200_000],
         outcome, reason, match_method, patient_id, report_id, review_item_id, json.dumps(detail, default=str)),
    ).fetchone()
    audit.record(conn, action=f"hl7_import_{outcome}", entity_type="hl7_message", entity_id=row["id"], actor=user,
                 patient_id=patient_id, detail={"control_id": info["control_id"], "reason": reason})
    return _entry(conn, row["id"])


def _entry(conn: Connection, message_id: str) -> dict[str, Any]:
    return conn.execute(
        """
        SELECT m.id::text, m.received_at, m.message_type, m.control_id, m.sending_facility, m.outcome, m.reason,
               m.match_method, m.patient_id::text, p.name AS patient_name, m.report_id::text, m.review_item_id::text,
               pr.name AS reviewer, m.detail
        FROM hl7_inbound_messages m
        LEFT JOIN patients p ON p.id = m.patient_id
        LEFT JOIN review_items ri ON ri.id = m.review_item_id
        LEFT JOIN practitioners pr ON pr.id = ri.practitioner_id
        WHERE m.id = %s
        """,
        (message_id,),
    ).fetchone()


# --- Endpoints -------------------------------------------------------------------------------------


class ImportIn(BaseModel):
    text: str = Field(min_length=1, max_length=1_000_000)


@router.post("/messages")
def import_messages(body: ImportIn, conn: DbConn, user: Admin) -> dict:
    """Import one or more pasted ORU^R01 messages. Each is accepted or rejected on its own."""
    raws = hl7v2.split_messages(body.text)
    if not raws:
        raws = [body.text]
    results = [process(conn, user, raw) for raw in raws[:50]]
    return {
        "results": results,
        "accepted": sum(1 for r in results if r["outcome"] == "accepted"),
        "rejected": sum(1 for r in results if r["outcome"] == "rejected"),
    }


@router.get("/messages")
def import_log(conn: DbConn, user: Admin, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """
        SELECT m.id::text FROM hl7_inbound_messages m WHERE m.organization_id = %s
        ORDER BY m.received_at DESC LIMIT %s
        """,
        (user.organization_id, max(1, min(limit, 200))),
    ).fetchall()
    audit.record(conn, action="hl7_import_log_viewed", entity_type="hl7_message", actor=user)
    return [_entry(conn, r["id"]) for r in rows]


@router.get("/sample")
def sample(conn: DbConn, user: Admin) -> dict:
    """A fictional ORU^R01 for Maya Thornton, dated today, for the demo."""
    now = datetime.now(SeedContext().tz)
    stamp = now.strftime("%Y%m%d%H%M")
    collected = now.strftime("%Y%m%d") + "0715"
    text = "\r".join([
        f"MSH|^~\\&|NSH-LIS|Northside Lab|BIOVERSE|NSH|{stamp}||ORU^R01^ORU_R01|NSL-{now:%Y%m%d%H%M%S}|P|2.5.1",
        "PID|1||NSH-0201^^^NSH^MR||Thornton^Maya||19720309|F",
        f"OBR|1|ORD-{now:%m%d}|ACC-{now:%H%M%S}|24323-8^Metabolic panel \\T\\ HbA1c^LN|||{collected}|||||||||D301^Okafor^Adaeze^^^Dr.^^^NSH",
        "OBX|1|NM|2345-7^Glucose^LN||104|mg/dL^^UCUM|70-99|H|||F",
        "OBX|2|NM|4548-4^Hemoglobin A1c^LN||5.9|%^^UCUM|<5.7|H|||F",
        "OBX|3|NM|2160-0^Creatinine^LN||0.8|mg/dL^^UCUM|0.5-1.1|N|||F",
        "OBX|4|NM|2823-3^Potassium^LN||4.2|mmol/L^^UCUM|3.5-5.1|N|||F",
        "NTE|1||Fasting specimen\\.br\\Reviewed by lab: no interference detected",
    ])
    return {"message": text.replace("\r", "\n"), "note": "Fictional sample for the demo. Dated today; the control id is unique each time."}
