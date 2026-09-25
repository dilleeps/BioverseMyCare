"""Sign-in rules: map directory groups (Entra, Okta) or a Google Workspace domain to Bioverse roles.

How rules are applied lives in bioverse/sso/plugins/group_mapping.py. Admins only.
"""

from __future__ import annotations

import json
from typing import Any, Literal

import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError, model_validator

from bioverse import audit
from bioverse.auth import Admin
from bioverse.db import DbConn
from bioverse.sso import providers
from bioverse.sso.plugins import group_mapping

router = APIRouter(prefix="/api/admin/sign-in-rules", tags=["access"])

CLAIM_PATTERN = r"^[A-Za-z0-9_:./\-]{1,100}$"
CLAIM_HINTS = [
    {"claim": "groups", "label": "Groups", "help": "Entra: group object ids. Okta: group names (needs a groups claim)."},
    {"claim": "roles", "label": "App roles (Entra)", "help": "App roles assigned on the Bioverse app registration."},
    {"claim": "hd", "label": "Google Workspace domain", "help": "Google sends no groups; match the hosted domain."},
    {"claim": "email_domain", "label": "Email domain", "help": "The domain of an email the provider verified."},
]


class RuleIn(BaseModel):
    provider: Literal["entra", "okta", "google"] | None = None
    claim: str = Field(default="groups", pattern=CLAIM_PATTERN)
    match_value: str = Field(min_length=1, max_length=300)
    role: Literal["admin", "staff", "clinician", "student"]
    team: Literal["front_desk", "pharmacy"] | None = None
    specialty: str | None = Field(default=None, max_length=80)
    priority: int = Field(default=100, ge=0, le=10000)
    label: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def check(self) -> "RuleIn":
        self.match_value = self.match_value.strip()
        self.label = (self.label or "").strip() or None
        if not self.match_value:
            raise ValueError("Enter the value to match")
        if self.role != "staff":
            self.team = None
        if self.role != "clinician":
            self.specialty = None
        elif not (self.specialty or "").strip():
            raise ValueError("A clinician rule needs a specialty")
        return self


class RulePatch(BaseModel):
    provider: Literal["entra", "okta", "google", "any"] | None = None
    claim: str | None = Field(default=None, pattern=CLAIM_PATTERN)
    match_value: str | None = Field(default=None, min_length=1, max_length=300)
    role: Literal["admin", "staff", "clinician", "student"] | None = None
    team: Literal["front_desk", "pharmacy", "none"] | None = None
    specialty: str | None = Field(default=None, max_length=80)
    priority: int | None = Field(default=None, ge=0, le=10000)
    label: str | None = Field(default=None, max_length=120)


class SettingsIn(BaseModel):
    jit_enabled: bool | None = None
    sync_on_sign_in: bool | None = None


def _rule(conn, admin, rule_id: str) -> dict:
    row = conn.execute(
        f"SELECT {group_mapping.RULE_COLUMNS} FROM sign_in_rules r WHERE r.id::text = %s AND r.organization_id = %s",
        (rule_id, admin.organization_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Rule not found")
    return row


def _audit_detail(rule: dict) -> dict:
    # Group ids and names describe the directory, not a person; keep them for the trail.
    return {k: rule.get(k) for k in ("provider", "claim", "match_value", "role", "team", "priority")}


@router.get("")
def list_rules(conn: DbConn, admin: Admin) -> dict:
    return {
        "rules": group_mapping.rules(conn, admin.organization_id),
        "settings": group_mapping.settings(conn, admin.organization_id),
        "providers": [{"key": p.key, "label": p.label} for p in providers.configured().values()],
        "claims": CLAIM_HINTS,
    }


@router.post("", status_code=201)
def create_rule(body: RuleIn, conn: DbConn, admin: Admin) -> dict:
    rule_id = conn.execute(
        """
        INSERT INTO sign_in_rules (organization_id, provider, claim, match_value, role, team, specialty, priority, label)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text
        """,
        (admin.organization_id, body.provider, body.claim, body.match_value, body.role, body.team,
         body.specialty.strip() if body.specialty else None, body.priority, body.label),
    ).fetchone()["id"]
    audit.record(conn, action="access.sign_in_rule_create", entity_type="sign_in_rule", entity_id=rule_id,
                 actor=admin, detail=_audit_detail(body.model_dump()))
    return _rule(conn, admin, rule_id)


@router.put("/settings")
def update_settings(body: SettingsIn, conn: DbConn, admin: Admin) -> dict:
    current = group_mapping.settings(conn, admin.organization_id)
    new = current | body.model_dump(exclude_none=True)
    conn.execute(
        """
        INSERT INTO sign_in_rule_settings (organization_id, jit_enabled, sync_on_sign_in) VALUES (%s, %s, %s)
        ON CONFLICT (organization_id) DO UPDATE
        SET jit_enabled = EXCLUDED.jit_enabled, sync_on_sign_in = EXCLUDED.sync_on_sign_in, updated_at = now()
        """,
        (admin.organization_id, new["jit_enabled"], new["sync_on_sign_in"]),
    )
    audit.record(conn, action="access.sign_in_settings", entity_type="organization", entity_id=admin.organization_id,
                 actor=admin, detail=new)
    return new


class TryIn(BaseModel):
    provider: Literal["entra", "okta", "google"] | None = None
    claims: dict[str, Any] | None = None
    # Or paste an ID token (e.g. from jwt.ms): only its payload is read, the signature is not checked.
    token: str | None = Field(default=None, max_length=20000)


def _provider_from(claims: dict) -> str | None:
    iss = str(claims.get("iss", ""))
    for p in providers.configured().values():
        if p.issuer and iss.rstrip("/") == p.issuer.rstrip("/"):
            return p.key
    if "login.microsoftonline.com" in iss or "sts.windows.net" in iss:
        return "entra"
    if "accounts.google.com" in iss:
        return "google"
    if "okta" in iss:
        return "okta"
    return None


@router.post("/test")
def try_rules(body: TryIn, conn: DbConn, admin: Admin) -> dict:
    claims = body.claims
    if body.token:
        try:
            claims = jwt.decode(body.token.strip(), options={"verify_signature": False})
        except jwt.PyJWTError:
            raise HTTPException(422, "That isn't a readable ID token") from None
    if not isinstance(claims, dict):
        raise HTTPException(422, "Paste the token's claims as a JSON object, or the ID token itself")
    if len(json.dumps(claims, default=str)) > 100_000:
        raise HTTPException(413, "Those claims are too large")
    provider = body.provider or _provider_from(claims)
    return group_mapping.explain(conn, admin.organization_id, provider, claims)


@router.patch("/{rule_id}")
def update_rule(rule_id: str, body: RulePatch, conn: DbConn, admin: Admin) -> dict:
    current = _rule(conn, admin, rule_id)
    changes = body.model_dump(exclude_none=True)
    merged = {k: current[k] for k in ("provider", "claim", "match_value", "role", "team", "specialty",
                                       "priority", "label")}
    merged |= changes
    if merged["provider"] == "any":
        merged["provider"] = None
    if merged["team"] == "none":
        merged["team"] = None
    try:
        rule = RuleIn(**merged)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()[0]["msg"].removeprefix("Value error, ")) from None
    conn.execute(
        """
        UPDATE sign_in_rules SET provider = %s, claim = %s, match_value = %s, role = %s, team = %s, specialty = %s,
               priority = %s, label = %s, updated_at = now()
        WHERE id::text = %s
        """,
        (rule.provider, rule.claim, rule.match_value, rule.role, rule.team,
         rule.specialty.strip() if rule.specialty else None, rule.priority, rule.label, rule_id),
    )
    audit.record(conn, action="access.sign_in_rule_update", entity_type="sign_in_rule", entity_id=rule_id,
                 actor=admin, detail=_audit_detail(rule.model_dump()))
    return _rule(conn, admin, rule_id)


@router.delete("/{rule_id}")
def delete_rule(rule_id: str, conn: DbConn, admin: Admin) -> dict:
    rule = _rule(conn, admin, rule_id)
    conn.execute("DELETE FROM sign_in_rules WHERE id::text = %s", (rule_id,))
    audit.record(conn, action="access.sign_in_rule_delete", entity_type="sign_in_rule", entity_id=rule_id,
                 actor=admin, detail=_audit_detail(rule))
    return {"ok": True}
