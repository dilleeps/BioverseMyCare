"""Row -> FHIR R4 resource mappers. Pure functions over dict rows; no database access."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from html import escape
from typing import Any

from bioverse import terminology

BIOVERSE = "https://bioverse.example/fhir"
SID_PATIENT = f"{BIOVERSE}/sid/patient-id"
SID_PRACTITIONER = f"{BIOVERSE}/sid/practitioner-id"
SID_USER = f"{BIOVERSE}/sid/user-id"
CS_SOURCE = f"{BIOVERSE}/CodeSystem/data-source"
CS_LOCAL_LAB = f"{BIOVERSE}/CodeSystem/local-lab"
CS_CONSENT_SCOPE = f"{BIOVERSE}/CodeSystem/consent-scope"
CS_ENCOUNTER_KIND = f"{BIOVERSE}/CodeSystem/encounter-kind"

V3_INTERP = "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"
V3_ACT = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
V3_PARTICIPATION = "http://terminology.hl7.org/CodeSystem/v3-ParticipationType"
OBS_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
V2_0074 = "http://terminology.hl7.org/CodeSystem/v2-0074"
V2_0203 = "http://terminology.hl7.org/CodeSystem/v2-0203"
ALLERGY_CLINICAL = "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical"
CONSENT_SCOPE = "http://terminology.hl7.org/CodeSystem/consentscope"
CONSENT_POLICY = "http://terminology.hl7.org/CodeSystem/consentpolicycodes"
BCP47 = "urn:ietf:bcp:47"

PATIENT_REPORTED_TAG = {"system": CS_SOURCE, "code": "patient-reported", "display": "Patient-reported (uploaded by the patient)"}
HL7_IMPORT_TAG = {"system": CS_SOURCE, "code": "hl7v2-import", "display": "Imported from an HL7 v2 lab feed"}

_INTERP_DISPLAY = {"H": "High", "L": "Low", "N": "Normal"}
_LANG = {"english": "en", "spanish": "es", "igbo": "ig", "swedish": "sv", "hindi": "hi", "japanese": "ja",
         "german": "de", "french": "fr", "arabic": "ar", "korean": "ko", "portuguese": "pt", "chinese": "zh"}


@dataclass
class Ctx:
    """Per-request mapping context: base URL for absolute links and the UCUM lookup table."""

    base_url: str  # e.g. http://host/api/fhir/R4
    ucum: dict[str, str] = field(default_factory=dict)  # unit as written (lower-case) -> UCUM code

    def ucum_code(self, unit: str | None) -> str | None:
        if not unit:
            return None
        return self.ucum.get(unit) or self.ucum.get(unit.lower())


def instant(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def fhir_date(d: date | None) -> str | None:
    return d.isoformat() if d else None


def num(v: Any) -> int | float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def ref(resource_type: str, rid: Any, display: str | None = None) -> dict[str, str]:
    out = {"reference": f"{resource_type}/{rid}"}
    if display:
        out["display"] = display
    return out


def _meta(last_updated: datetime | None = None, tags: list[dict] | None = None) -> dict[str, Any] | None:
    meta: dict[str, Any] = {}
    if last_updated:
        meta["lastUpdated"] = instant(last_updated)
    if tags:
        meta["tag"] = tags
    return meta or None


def _clean(resource: dict[str, Any]) -> dict[str, Any]:
    """Drop empty values: FHIR forbids empty strings, arrays and objects."""
    out = {}
    for k, v in resource.items():
        if isinstance(v, dict):
            v = _clean(v)
        elif isinstance(v, list):
            v = [_clean(i) if isinstance(i, dict) else i for i in v if i not in (None, "", [], {})]
            v = [i for i in v if i not in ({}, [])]
        if v not in (None, "", [], {}):
            out[k] = v
    return out


def _narrative(text: str) -> dict[str, str]:
    return {"status": "generated", "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{escape(text)}</div>'}


def _split_name(name: str) -> dict[str, Any]:
    parts = name.replace("Dr. ", "").split()
    human: dict[str, Any] = {"use": "official", "text": name}
    if len(parts) >= 2:
        human["family"] = parts[-1]
        human["given"] = parts[:-1]
    if name.startswith("Dr. "):
        human["prefix"] = ["Dr."]
    return human


def _language(lang: str) -> dict[str, Any]:
    code = _LANG.get(lang.strip().lower())
    concept: dict[str, Any] = {"text": lang}
    if code:
        concept["coding"] = [{"system": BCP47, "code": code, "display": lang}]
    return concept


def _quantity(ctx: Ctx, value: Any, unit: str | None) -> dict[str, Any]:
    q: dict[str, Any] = {"value": num(value)}
    if unit:
        q["unit"] = unit
        code = ctx.ucum_code(unit)
        if code:
            q["system"] = terminology.UCUM
            q["code"] = code
    return q


# --- Administrative -------------------------------------------------------------------------


def organization(row: dict[str, Any]) -> dict[str, Any]:
    return _clean({
        "resourceType": "Organization",
        "id": row["id"],
        "meta": _meta(row.get("created_at")),
        "active": True,
        "name": row["name"],
    })


def practitioner(row: dict[str, Any], identifiers: list[dict[str, Any]] = ()) -> dict[str, Any]:
    ids = [{"system": SID_PRACTITIONER, "value": row["id"]}]
    ids += [{"system": i["system"], "value": i["value"]} for i in identifiers]
    return _clean({
        "resourceType": "Practitioner",
        "id": row["id"],
        "meta": _meta(row.get("created_at")),
        "identifier": ids,
        "active": True,
        "name": [_split_name(row["name"])],
        "communication": [_language(lang) for lang in row.get("languages") or []],
        # Specialty lives on PractitionerRole in FHIR; carried as text here so a reader still sees it.
        "qualification": [{"code": {"text": row["specialty"]}}] if row.get("specialty") else [],
    })


def patient(row: dict[str, Any], identifiers: list[dict[str, Any]] = ()) -> dict[str, Any]:
    ids = [{"use": "official", "system": SID_PATIENT, "value": row["id"]}]
    for i in identifiers:
        ids.append({
            "use": "usual",
            "type": {"coding": [{"system": V2_0203, "code": i["type_code"]}]},
            "system": i["system"],
            "value": i["value"],
        })
    return _clean({
        "resourceType": "Patient",
        "id": row["id"],
        "meta": _meta(row.get("created_at")),
        "identifier": ids,
        "active": True,
        "name": [_split_name(row["name"])],
        "birthDate": fhir_date(row["birth_date"]),
        "communication": [{"language": _language(row["preferred_language"]), "preferred": True}]
        if row.get("preferred_language") else [],
        "managingOrganization": ref("Organization", row["organization_id"]),
    })


# --- Results --------------------------------------------------------------------------------


def _source_tags(source: str | None) -> list[dict[str, str]]:
    if source == "patient_upload":
        return [PATIENT_REPORTED_TAG]
    if source == "hl7_import":
        return [HL7_IMPORT_TAG]
    return []


def lab_code(code: str, display: str) -> dict[str, Any]:
    if terminology.is_local(code):
        return {"coding": [{"system": CS_LOCAL_LAB, "code": code.removeprefix("local:"), "display": display}], "text": display}
    return {"coding": [{"system": terminology.LOINC, "code": code, "display": display}], "text": display}


def observation(ctx: Ctx, row: dict[str, Any]) -> dict[str, Any]:
    """row: observations.* plus report `source`."""
    patient_reported = row.get("source") == "patient_upload"
    rng: dict[str, Any] = {}
    if row["ref_low"] is not None:
        rng["low"] = _quantity(ctx, row["ref_low"], row["unit"])
    if row["ref_high"] is not None:
        rng["high"] = _quantity(ctx, row["ref_high"], row["unit"])
    interp = row["interpretation"]
    return _clean({
        "resourceType": "Observation",
        "id": row["id"],
        "meta": _meta(tags=_source_tags(row.get("source"))),
        # Values a patient typed in from another lab's report are not verified results.
        "status": "preliminary" if patient_reported else "final",
        "category": [{"coding": [{"system": OBS_CATEGORY, "code": "laboratory", "display": "Laboratory"}]}],
        "code": lab_code(row["loinc_code"], row["display"]),
        "subject": ref("Patient", row["patient_id"]),
        "effectiveDateTime": instant(row["effective_at"]),
        "performer": [ref("Patient", row["patient_id"])] if patient_reported else [],
        "valueQuantity": _quantity(ctx, row["value"], row["unit"]),
        "interpretation": [{"coding": [{"system": V3_INTERP, "code": interp, "display": _INTERP_DISPLAY[interp]}]}],
        "referenceRange": [rng] if rng else [],
    })


def diagnostic_report(row: dict[str, Any], observation_ids: list[str], panel: dict[str, Any] | None) -> dict[str, Any]:
    """row: diagnostic_reports.* plus `approved_text` (only when a clinician approved the explanation)."""
    patient_reported = row.get("source") == "patient_upload"
    code: dict[str, Any] = {"text": row["name"]}
    if panel:
        code["coding"] = [{"system": terminology.LOINC, "code": panel["code"], "display": panel["display"]}]
    return _clean({
        "resourceType": "DiagnosticReport",
        "id": row["id"],
        "meta": _meta(tags=_source_tags(row.get("source"))),
        "status": "preliminary" if patient_reported else "final",
        "category": [{"coding": [{"system": V2_0074, "code": "LAB", "display": "Laboratory"}]}],
        "code": code,
        "subject": ref("Patient", row["patient_id"]),
        "effectiveDateTime": instant(row["collected_at"]),
        "performer": [{"display": row["lab_name"]}],
        "resultsInterpreter": [ref("Practitioner", row["responsible_practitioner_id"])]
        if row.get("responsible_practitioner_id") else [],
        "result": [ref("Observation", oid) for oid in observation_ids],
        "conclusion": row.get("approved_text"),
    })


def document_reference(ctx: Ctx, row: dict[str, Any]) -> dict[str, Any]:
    return _clean({
        "resourceType": "DocumentReference",
        "id": row["id"],
        "meta": _meta(row.get("confirmed_at") or row["created_at"], [PATIENT_REPORTED_TAG]),
        "status": "current",
        "docStatus": "final" if row["status"] == "confirmed" else "preliminary",
        "type": {"coding": [{"system": terminology.LOINC, "code": "11502-2", "display": "Laboratory report"}],
                 "text": "Lab report"},
        "subject": ref("Patient", row["patient_id"]),
        "date": instant(row["created_at"]),
        "author": [ref("Patient", row["patient_id"])],
        "description": "Uploaded by the patient",
        "content": [{"attachment": {
            "contentType": row["content_type"],
            "size": row["size_bytes"],
            "title": row.get("filename") or "Pasted text",
            "creation": instant(row["created_at"]),
            "url": f"{ctx.base_url.rsplit('/fhir/R4', 1)[0]}/documents/{row['id']}/content",
        }}],
        "context": {"related": [ref("DiagnosticReport", row["report_id"])]} if row.get("report_id") else None,
    })


# --- Care -----------------------------------------------------------------------------------


def encounter(row: dict[str, Any], now: datetime) -> dict[str, Any]:
    finished = row["occurred_at"] <= now
    return _clean({
        "resourceType": "Encounter",
        "id": row["id"],
        "text": _narrative(row["summary"]),
        "status": "finished" if finished else "planned",
        "class": {"system": V3_ACT, "code": "AMB", "display": "ambulatory"},
        "type": [{"text": row["kind"]}],
        "subject": ref("Patient", row["patient_id"]),
        "participant": [{"individual": ref("Practitioner", row["practitioner_id"])}] if row.get("practitioner_id") else [],
        "period": {"start": instant(row["occurred_at"])},
    })


def immunization(row: dict[str, Any]) -> dict[str, Any]:
    return _clean({
        "resourceType": "Immunization",
        "id": row["id"],
        "status": "completed",
        "vaccineCode": {"text": row["vaccine"]},
        "patient": ref("Patient", row["patient_id"]),
        "occurrenceDateTime": instant(row["occurred_at"]),
        "primarySource": False,
        "location": {"display": row["location"]} if row.get("location") else None,
    })


_ACTIVITY_KIND = {
    "lab": "ServiceRequest",
    "medication": "MedicationRequest",
    "appointment": "Appointment",
    "referral": "ServiceRequest",
    "checkin": "CommunicationRequest",
    "lifestyle": "Task",
}


def care_plan(row: dict[str, Any], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    status = {"active": "active", "completed": "completed", "revoked": "revoked"}[row["status"]]
    activities = []
    for t in tasks:
        activities.append({"detail": {
            "kind": _ACTIVITY_KIND.get(t["kind"], "Task"),
            "code": {"text": t["title"]},
            "status": "completed" if t["status"] == "done" else "not-started",
            "doNotPerform": False,
            "scheduledPeriod": {"end": fhir_date(t["due_on"])} if t.get("due_on") else None,
            "description": t.get("detail"),
        }})
    return _clean({
        "resourceType": "CarePlan",
        "id": row["id"],
        "status": status,
        "intent": "plan",
        "title": row["title"],
        "subject": ref("Patient", row["patient_id"]),
        "period": {"start": instant(row["started_at"])},
        "author": ref("Practitioner", row["practitioner_id"]),
        "activity": activities,
    })


def appointment(row: dict[str, Any]) -> dict[str, Any]:
    start = row["starts_at"]
    end = start + timedelta(minutes=row["duration_min"])
    return _clean({
        "resourceType": "Appointment",
        "id": row["id"],
        "meta": _meta(row.get("created_at")),
        "status": row["status"],  # booked | cancelled | fulfilled map one-to-one
        "serviceType": [{"text": "Video visit" if row.get("mode") == "video" else "In-person visit"}],
        "description": row.get("reason"),
        "start": instant(start),
        "end": instant(end),
        "minutesDuration": row["duration_min"],
        "created": instant(row.get("created_at")),
        "participant": [
            {"actor": ref("Patient", row["patient_id"]), "status": "accepted"},
            {"actor": ref("Practitioner", row["practitioner_id"]), "status": "accepted"},
        ],
    })


def allergy_id(patient_id: str, substance: str) -> str:
    return str(uuid.uuid5(uuid.UUID(patient_id), "allergy:" + substance.strip().lower()))


def allergy_intolerance(patient_id: str, substance: str, coding: dict[str, Any] | None) -> dict[str, Any]:
    code: dict[str, Any] = {"text": substance}
    if coding:
        code["coding"] = [coding]
    return _clean({
        "resourceType": "AllergyIntolerance",
        "id": allergy_id(patient_id, substance),
        "clinicalStatus": {"coding": [{"system": ALLERGY_CLINICAL, "code": "active", "display": "Active"}]},
        "code": code,
        "patient": ref("Patient", patient_id),
    })


def consent(row: dict[str, Any]) -> dict[str, Any]:
    granted = row["status"] == "granted"
    research = row["scope"] == "research_matching"
    provision: dict[str, Any] = {
        "type": "permit" if granted else "deny",
        "code": [{"coding": [{"system": CS_CONSENT_SCOPE, "code": row["scope"]}], "text": row["scope"].replace("_", " ")}],
    }
    if row.get("expires_at"):
        provision["period"] = {"end": instant(row["expires_at"])}
    if row.get("grantee"):
        provision["actor"] = [{
            "role": {"coding": [{"system": V3_PARTICIPATION, "code": "IRCP", "display": "information recipient"}]},
            "reference": {"identifier": {"system": SID_USER, "value": row["grantee"]}},
        }]
    return _clean({
        "resourceType": "Consent",
        "id": row["id"],
        "meta": _meta(row.get("updated_at")),
        "status": "inactive" if row["status"] == "revoked" else "active",
        "scope": {"coding": [{"system": CONSENT_SCOPE, "code": "research" if research else "patient-privacy"}]},
        "category": [{"coding": [{"system": terminology.LOINC, "code": "59284-0", "display": "Patient Consent"}]}],
        "patient": ref("Patient", row["patient_id"]),
        "dateTime": instant(row.get("updated_at")),
        "policyRule": {"coding": [{"system": V3_ACT, "code": "OPTIN" if granted else "OPTOUT"}]},
        "provision": provision,
    })


# --- Envelopes ------------------------------------------------------------------------------


def bundle(ctx: Ctx, resources: list[dict[str, Any]], *, bundle_type: str = "searchset",
           self_link: str | None = None, include_ids: set[str] | None = None) -> dict[str, Any]:
    entries = []
    for r in resources:
        entry: dict[str, Any] = {"fullUrl": f"{ctx.base_url}/{r['resourceType']}/{r['id']}", "resource": r}
        if bundle_type == "searchset":
            key = f"{r['resourceType']}/{r['id']}"
            entry["search"] = {"mode": "include" if include_ids and key in include_ids else "match"}
        entries.append(entry)
    out: dict[str, Any] = {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "meta": {"lastUpdated": instant(datetime.now().astimezone())},
        "type": bundle_type,
    }
    if bundle_type == "searchset":
        out["total"] = sum(1 for e in entries if e["search"]["mode"] == "match")
    if self_link:
        out["link"] = [{"relation": "self", "url": self_link}]
    out["entry"] = entries
    return out


_ISSUE_CODE = {400: "invalid", 401: "login", 403: "forbidden", 404: "not-found", 405: "not-supported",
               409: "conflict", 422: "invalid"}


def operation_outcome(status: int, message: str) -> dict[str, Any]:
    return {
        "resourceType": "OperationOutcome",
        "issue": [{
            "severity": "error" if status < 500 else "fatal",
            "code": _ISSUE_CODE.get(status, "exception"),
            "diagnostics": message,
        }],
    }
