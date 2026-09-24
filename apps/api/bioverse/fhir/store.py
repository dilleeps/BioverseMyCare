"""Read a patient's record as FHIR resources. Callers enforce access before calling in."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from psycopg import Connection

from bioverse import terminology
from bioverse.fhir import resources as R


def context(conn: Connection, base_url: str) -> R.Ctx:
    ucum: dict[str, str] = {}
    for row in conn.execute(
        "SELECT code, synonyms FROM code_system_concepts WHERE system = %s", (terminology.UCUM,)
    ).fetchall():
        ucum[row["code"]] = row["code"]
        ucum[row["code"].lower()] = row["code"]
        for s in row["synonyms"]:
            ucum[s] = row["code"]
    return R.Ctx(base_url=base_url, ucum=ucum)


# --- Single resources -----------------------------------------------------------------------


def patient_row(conn: Connection, patient_id: str) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT id::text, organization_id::text, name, birth_date, preferred_language, allergies, created_at
        FROM patients WHERE id = %s
        """,
        (patient_id,),
    ).fetchone()


def patient(conn: Connection, patient_id: str) -> dict[str, Any] | None:
    row = patient_row(conn, patient_id)
    if row is None:
        return None
    ids = conn.execute(
        "SELECT system, value, type_code FROM patient_identifiers WHERE patient_id = %s ORDER BY system, value",
        (patient_id,),
    ).fetchall()
    return R.patient(row, ids)


def practitioner(conn: Connection, practitioner_id: str, organization_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id::text, name, specialty, languages, created_at FROM practitioners
        WHERE id = %s AND organization_id = %s
        """,
        (practitioner_id, organization_id),
    ).fetchone()
    if row is None:
        return None
    ids = conn.execute(
        "SELECT system, value FROM practitioner_identifiers WHERE practitioner_id = %s ORDER BY system", (practitioner_id,)
    ).fetchall()
    return R.practitioner(row, ids)


def organization(conn: Connection, organization_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id::text, name, created_at FROM organizations WHERE id = %s", (organization_id,)
    ).fetchone()
    return R.organization(row) if row else None


# --- Searches by patient ---------------------------------------------------------------------


def observations(conn: Connection, ctx: R.Ctx, patient_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT o.id::text, o.patient_id::text, o.report_id::text, o.loinc_code, o.display, o.value, o.unit,
               o.ref_low, o.ref_high, o.interpretation, o.effective_at, o.category,
               coalesce(r.source, o.source) AS source
        FROM observations o LEFT JOIN diagnostic_reports r ON r.id = o.report_id
        WHERE o.patient_id = %s ORDER BY o.effective_at DESC, o.display
        """,
        (patient_id,),
    ).fetchall()
    return [R.observation(ctx, r) for r in rows]


def _panel_codes(conn: Connection) -> dict[str, dict[str, Any]]:
    """Report names that map to a LOINC panel ('Lipid panel' -> 24331-1)."""
    out = {}
    for row in conn.execute(
        "SELECT code, display, synonyms FROM code_system_concepts WHERE system = %s", (terminology.LOINC,)
    ).fetchall():
        for s in [row["display"], *row["synonyms"]]:
            out.setdefault(terminology.normalize_name(s), {"code": row["code"], "display": row["display"]})
    return out


def diagnostic_reports(conn: Connection, patient_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT r.id::text, r.patient_id::text, r.name, r.lab_name, r.collected_at, r.source,
               r.responsible_practitioner_id::text,
               CASE WHEN x.status = 'approved' THEN x.final_text END AS approved_text,
               coalesce((SELECT array_agg(o.id::text ORDER BY o.display) FROM observations o WHERE o.report_id = r.id),
                        '{}') AS observation_ids
        FROM diagnostic_reports r LEFT JOIN result_explanations x ON x.report_id = r.id
        WHERE r.patient_id = %s ORDER BY r.collected_at DESC
        """,
        (patient_id,),
    ).fetchall()
    panels = _panel_codes(conn)
    out = []
    for r in rows:
        name = terminology.normalize_name(r["name"].replace("(patient-reported)", ""))
        out.append(R.diagnostic_report(r, r["observation_ids"], panels.get(name)))
    return out


def encounters(conn: Connection, patient_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id::text, patient_id::text, practitioner_id::text, occurred_at, kind, summary
        FROM encounters WHERE patient_id = %s ORDER BY occurred_at DESC
        """,
        (patient_id,),
    ).fetchall()
    now = datetime.now(timezone.utc)
    return [R.encounter(r, now) for r in rows]


def immunizations(conn: Connection, patient_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id::text, patient_id::text, vaccine, location, occurred_at FROM immunizations WHERE patient_id = %s ORDER BY occurred_at DESC",
        (patient_id,),
    ).fetchall()
    return [R.immunization(r) for r in rows]


def care_plans(conn: Connection, patient_id: str) -> list[dict[str, Any]]:
    plans = conn.execute(
        """
        SELECT id::text, patient_id::text, practitioner_id::text, title, started_at, status
        FROM care_plans WHERE patient_id = %s ORDER BY started_at DESC
        """,
        (patient_id,),
    ).fetchall()
    out = []
    for p in plans:
        tasks = conn.execute(
            "SELECT kind, title, detail, due_on, status FROM care_plan_tasks WHERE care_plan_id = %s ORDER BY position",
            (p["id"],),
        ).fetchall()
        out.append(R.care_plan(p, tasks))
    return out


def appointments(conn: Connection, patient_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT a.id::text, a.patient_id::text, a.practitioner_id::text, a.reason, a.status, a.created_at,
               s.starts_at, s.duration_min, s.mode
        FROM appointments a JOIN slots s ON s.id = a.slot_id
        WHERE a.patient_id = %s ORDER BY s.starts_at DESC
        """,
        (patient_id,),
    ).fetchall()
    return [R.appointment(r) for r in rows]


def allergies(conn: Connection, patient_id: str) -> list[dict[str, Any]]:
    row = patient_row(conn, patient_id)
    if row is None:
        return []
    out = []
    for substance in row["allergies"] or []:
        coding = None
        match = conn.execute(
            "SELECT code, display FROM code_system_concepts WHERE system = %s AND %s = ANY(synonyms) LIMIT 1",
            (terminology.SNOMED, substance.strip().lower()),
        ).fetchone()
        if match:
            coding = {"system": terminology.SNOMED, "code": match["code"], "display": match["display"]}
        out.append(R.allergy_intolerance(patient_id, substance, coding))
    return out


def consents(conn: Connection, patient_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id::text, patient_id::text, scope, grantee, status, expires_at, updated_at
        FROM consents WHERE patient_id = %s ORDER BY scope, grantee
        """,
        (patient_id,),
    ).fetchall()
    return [R.consent(r) for r in rows]


def documents(conn: Connection, ctx: R.Ctx, patient_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id::text, patient_id::text, filename, content_type, size_bytes, status, report_id::text,
               created_at, confirmed_at
        FROM document_references WHERE patient_id = %s AND status <> 'discarded' ORDER BY created_at DESC
        """,
        (patient_id,),
    ).fetchall()
    return [R.document_reference(ctx, r) for r in rows]


SEARCHES = {
    "Observation": lambda conn, ctx, pid: observations(conn, ctx, pid),
    "DiagnosticReport": lambda conn, ctx, pid: diagnostic_reports(conn, pid),
    "Encounter": lambda conn, ctx, pid: encounters(conn, pid),
    "Immunization": lambda conn, ctx, pid: immunizations(conn, pid),
    "CarePlan": lambda conn, ctx, pid: care_plans(conn, pid),
    "Appointment": lambda conn, ctx, pid: appointments(conn, pid),
    "AllergyIntolerance": lambda conn, ctx, pid: allergies(conn, pid),
    "Consent": lambda conn, ctx, pid: consents(conn, pid),
    "DocumentReference": lambda conn, ctx, pid: documents(conn, ctx, pid),
}


def everything(conn: Connection, ctx: R.Ctx, patient_id: str) -> list[dict[str, Any]]:
    """Patient $everything: the patient, every resource about them, and the practitioners and
    organization those resources reference, so every reference inside the bundle resolves."""
    pat = patient(conn, patient_id)
    if pat is None:
        return []
    clinical: list[dict[str, Any]] = []
    for search in SEARCHES.values():
        clinical.extend(search(conn, ctx, patient_id))

    org_id = patient_row(conn, patient_id)["organization_id"]
    practitioner_ids: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            r = node.get("reference")
            if isinstance(r, str) and r.startswith("Practitioner/"):
                practitioner_ids.add(r.split("/", 1)[1])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(clinical)
    extras = [organization(conn, org_id)]
    extras += [p for p in (practitioner(conn, pid, org_id) for pid in sorted(practitioner_ids)) if p]
    return [pat, *clinical, *[e for e in extras if e]]
