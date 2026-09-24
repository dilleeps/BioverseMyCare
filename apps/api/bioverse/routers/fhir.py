"""FHIR R4 read API (module 22) and the terminology service's FHIR operations.

Same identity and access rules as the rest of the API: the caller names themselves in X-Bioverse-User,
patients reach only their own record, clinicians and staff only patients in their organization.
Errors come back as OperationOutcome. Every read is audited (action `fhir_read`) with the patient it
concerns.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute

from bioverse import audit, terminology
from bioverse.auth import CurrentUser, User, assert_patient_access
from bioverse.db import DbConn
from bioverse.fhir import FHIR_VERSION, store
from bioverse.fhir import resources as R

FHIR_JSON = "application/fhir+json"


class FhirResponse(JSONResponse):
    media_type = FHIR_JSON


def outcome(status_code: int, message: str) -> FhirResponse:
    return FhirResponse(R.operation_outcome(status_code, message), status_code=status_code)


class FhirRoute(APIRoute):
    """Turns every error on these routes (auth, access, validation) into an OperationOutcome."""

    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()

        async def fhir_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
                return outcome(exc.status_code, detail)
            except RequestValidationError as exc:
                msgs = "; ".join(f"{'.'.join(str(p) for p in e.get('loc', []))}: {e.get('msg')}" for e in exc.errors())
                return outcome(400, msgs or "Invalid request")

        return fhir_handler


router = APIRouter(prefix="/api/fhir/R4", tags=["fhir"], route_class=FhirRoute)

SEARCHABLE = list(store.SEARCHES)


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/api/fhir/R4"


def _uuid(value: str, what: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what}/{value} not found") from None


def _patient_param(patient: str | None) -> str:
    if not patient:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Search requires the 'patient' parameter (patient=<id> or patient=Patient/<id>)")
    return _uuid(patient.removeprefix("Patient/"), "Patient")


def _read_audit(conn, user: User, resource_type: str, *, entity_id: str | None, patient_id: str | None,
                interaction: str, count: int | None = None) -> None:
    detail: dict[str, Any] = {"interaction": interaction, "resource": resource_type}
    if count is not None:
        detail["count"] = count
    audit.record(conn, action="fhir_read", entity_type=resource_type, entity_id=entity_id, actor=user,
                 patient_id=patient_id, detail=detail)


# --- Capability statement ----------------------------------------------------------------------


@router.get("/metadata")
def metadata(request: Request) -> FhirResponse:
    """Public, as FHIR expects: it describes the server, not any patient."""
    search_param = [{"name": "patient", "type": "reference", "documentation": "Required. The patient the resources are about."}]
    resources: list[dict[str, Any]] = [
        {
            "type": "Patient",
            "interaction": [{"code": "read"}],
            "operation": [{"name": "everything", "definition": "http://hl7.org/fhir/OperationDefinition/Patient-everything"}],
        },
        {"type": "Practitioner", "interaction": [{"code": "read"}]},
        {"type": "Organization", "interaction": [{"code": "read"}]},
        *[{"type": t, "interaction": [{"code": "search-type"}], "searchParam": search_param} for t in SEARCHABLE],
        {
            "type": "CodeSystem",
            "interaction": [{"code": "search-type"}],
            "operation": [
                {"name": "lookup", "definition": "http://hl7.org/fhir/OperationDefinition/CodeSystem-lookup"},
                {"name": "validate-code", "definition": "http://hl7.org/fhir/OperationDefinition/CodeSystem-validate-code"},
            ],
        },
    ]
    return FhirResponse({
        "resourceType": "CapabilityStatement",
        "status": "active",
        "date": datetime.now(timezone.utc).date().isoformat(),
        "publisher": "Bioverse",
        "kind": "instance",
        "software": {"name": "Bioverse API", "version": request.app.version},
        "implementation": {"description": "Bioverse FHIR R4 read API", "url": _base(request)},
        "fhirVersion": FHIR_VERSION,
        "format": ["json"],
        "rest": [{
            "mode": "server",
            "documentation": "Read-only. JSON only. Searches must be scoped to one patient.",
            "security": {
                "description": "Demo identity: send the caller's Bioverse user id in the X-Bioverse-User header. "
                               "Patients read only their own record; clinicians and staff read patients in their organization.",
            },
            "resource": resources,
        }],
    })


# --- Reads ---------------------------------------------------------------------------------------


@router.get("/Patient/{patient_id}")
def read_patient(patient_id: str, conn: DbConn, user: CurrentUser) -> FhirResponse:
    pid = _uuid(patient_id, "Patient")
    assert_patient_access(conn, user, pid)
    resource = store.patient(conn, pid)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Patient/{patient_id} not found")
    _read_audit(conn, user, "Patient", entity_id=pid, patient_id=pid, interaction="read")
    return FhirResponse(resource)


@router.get("/Patient/{patient_id}/$everything")
def patient_everything(patient_id: str, request: Request, conn: DbConn, user: CurrentUser) -> FhirResponse:
    pid = _uuid(patient_id, "Patient")
    assert_patient_access(conn, user, pid)
    ctx = store.context(conn, _base(request))
    resources = store.everything(conn, ctx, pid)
    if not resources:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Patient/{patient_id} not found")
    included = {f"{r['resourceType']}/{r['id']}" for r in resources if r["resourceType"] in ("Practitioner", "Organization")}
    bundle = R.bundle(ctx, resources, bundle_type="searchset", self_link=f"{ctx.base_url}/Patient/{pid}/$everything",
                      include_ids=included)
    _read_audit(conn, user, "Patient", entity_id=pid, patient_id=pid, interaction="everything", count=len(resources))
    return FhirResponse(bundle)


@router.get("/Practitioner/{practitioner_id}")
def read_practitioner(practitioner_id: str, conn: DbConn, user: CurrentUser) -> FhirResponse:
    prid = _uuid(practitioner_id, "Practitioner")
    resource = store.practitioner(conn, prid, user.organization_id)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Practitioner/{practitioner_id} not found")
    _read_audit(conn, user, "Practitioner", entity_id=prid, patient_id=None, interaction="read")
    return FhirResponse(resource)


@router.get("/Organization/{organization_id}")
def read_organization(organization_id: str, conn: DbConn, user: CurrentUser) -> FhirResponse:
    oid = _uuid(organization_id, "Organization")
    if oid != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Organization/{organization_id} not found")
    resource = store.organization(conn, oid)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Organization/{organization_id} not found")
    _read_audit(conn, user, "Organization", entity_id=oid, patient_id=None, interaction="read")
    return FhirResponse(resource)


# --- Terminology ---------------------------------------------------------------------------------


def _parameters(params: list[dict[str, Any]]) -> dict[str, Any]:
    return {"resourceType": "Parameters", "parameter": params}


@router.get("/CodeSystem/$lookup")
def code_lookup(conn: DbConn, user: CurrentUser, system: str | None = None, code: str | None = None) -> FhirResponse:
    if not system or not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "$lookup requires 'system' and 'code'")
    concept = terminology.lookup(conn, system, code)
    if concept is None:
        canonical = terminology.resolve_system(system)
        if canonical is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown code system '{system}'")
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"Code '{code}' is not in the Bioverse subset of {terminology.SYSTEMS[canonical]['name']}")
    params: list[dict[str, Any]] = [
        {"name": "name", "valueString": concept["name"]},
        {"name": "system", "valueUri": concept["system"]},
        {"name": "code", "valueCode": concept["code"]},
        {"name": "display", "valueString": concept["display"]},
    ]
    params += [{"name": "designation", "part": [{"name": "value", "valueString": s}]} for s in concept["synonyms"]]
    params += [{"name": "property", "part": [{"name": "code", "valueCode": k}, {"name": "value", "valueString": str(v)}]}
               for k, v in (concept["properties"] or {}).items()]
    params.append({"name": "property", "part": [{"name": "code", "valueCode": "subset-notice"},
                                                {"name": "value", "valueString": terminology.SUBSET_NOTICE}]})
    return FhirResponse(_parameters(params))


@router.get("/CodeSystem/$validate-code")
def code_validate(conn: DbConn, user: CurrentUser, system: str | None = None, code: str | None = None,
                  display: str | None = None, url: str | None = None) -> FhirResponse:
    system = system or url
    if not system or not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "$validate-code requires 'url' (or 'system') and 'code'")
    result = terminology.validate(conn, system, code, display)
    params: list[dict[str, Any]] = [{"name": "result", "valueBoolean": result["result"]}]
    if result.get("message"):
        params.append({"name": "message", "valueString": result["message"]})
    if result.get("display"):
        params.append({"name": "display", "valueString": result["display"]})
    return FhirResponse(_parameters(params))


@router.get("/CodeSystem")
def code_systems(request: Request, conn: DbConn, user: CurrentUser) -> FhirResponse:
    """The code systems the terminology service holds, each marked content = 'fragment' (a subset)."""
    counts = {r["system"]: r["n"] for r in conn.execute(
        "SELECT system, count(*) AS n FROM code_system_concepts GROUP BY system").fetchall()}
    items = []
    for url, meta in terminology.SYSTEMS.items():
        items.append({
            "resourceType": "CodeSystem",
            "id": meta["name"].lower().replace("_", "-"),
            "url": url,
            "name": meta["name"],
            "title": meta["title"],
            "status": "active",
            "publisher": meta["publisher"],
            "description": terminology.SUBSET_NOTICE,
            "content": "fragment",
            "count": counts.get(url, 0),
        })
    ctx = store.context(conn, _base(request))
    return FhirResponse(R.bundle(ctx, items, bundle_type="searchset", self_link=f"{ctx.base_url}/CodeSystem"))


# --- Searches ------------------------------------------------------------------------------------


def _search(resource_type: str):
    def search(request: Request, conn: DbConn, user: CurrentUser, patient: str | None = None) -> FhirResponse:
        pid = _patient_param(patient)
        assert_patient_access(conn, user, pid)
        if store.patient_row(conn, pid) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Patient/{pid} not found")
        ctx = store.context(conn, _base(request))
        found = store.SEARCHES[resource_type](conn, ctx, pid)
        _read_audit(conn, user, resource_type, entity_id=None, patient_id=pid, interaction="search", count=len(found))
        return FhirResponse(R.bundle(ctx, found, self_link=f"{ctx.base_url}/{resource_type}?patient={pid}"))

    search.__name__ = f"search_{resource_type.lower()}"
    return search


for _type in SEARCHABLE:
    router.add_api_route(f"/{_type}", _search(_type), methods=["GET"], name=f"search_{_type}")


@router.api_route("/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def unsupported(rest: str, request: Request) -> FhirResponse:
    if request.method != "GET":
        return outcome(405, "This FHIR server is read-only")
    return outcome(404, f"'{rest}' is not supported. See {_base(request)}/metadata for what is.")
