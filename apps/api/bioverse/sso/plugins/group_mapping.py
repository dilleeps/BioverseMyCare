"""Directory group -> Bioverse role ("sign-in rules", managed in routers/sign_in_rules.py).

A rule belongs to one organization and matches a claim of the verified ID token:
- `groups`: Entra group object ids (or names, for groups synced from on-premises), Okta group names
- `roles`: Entra app roles assigned to the person on the Bioverse app registration
- `hd`: the Google Workspace domain (Google sends no groups)
- `email_domain`: the domain of a provider-verified email (any provider)
Values compare case-insensitively. Rules are checked lowest `priority` first; the first match wins.

Two hooks, each off until an administrator turns it on for their organization:
- Just in time (provisioner): a verified sign-in with no Bioverse account gets one from the first matching
  rule of any organization with JIT on. Never a patient. Clinicians start unverified (no credential).
- Keep in sync (after_sign_in): administrators and staff get the role and team of their first matching
  admin/staff rule on every sign-in. Never demotes the organization's last administrator, never changes a
  clinician, patient or student, and leaves people who match no rule as they are.
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg import Connection

from bioverse import audit, people
from bioverse.sso import hooks

log = logging.getLogger(__name__)

RULE_ROLES = ("admin", "staff", "clinician", "student")
SYNC_ROLES = ("admin", "staff")
PSEUDO_CLAIMS = ("email_domain",)

RULE_COLUMNS = """r.id::text AS id, r.organization_id::text AS organization_id, r.provider, r.claim, r.match_value,
                  r.role, r.team, r.specialty, r.priority, r.label, r.created_at, r.updated_at"""


def settings(conn: Connection, org_id: str) -> dict:
    row = conn.execute(
        "SELECT jit_enabled, sync_on_sign_in FROM sign_in_rule_settings WHERE organization_id = %s", (org_id,),
    ).fetchone()
    return dict(row) if row else {"jit_enabled": False, "sync_on_sign_in": False}


def rules(conn: Connection, org_id: str) -> list[dict]:
    return conn.execute(
        f"SELECT {RULE_COLUMNS} FROM sign_in_rules r WHERE r.organization_id = %s ORDER BY r.priority, r.created_at",
        (org_id,),
    ).fetchall()


def claim_values(claims: dict[str, Any], claim: str, *, email: str | None = None,
                 email_verified: bool = False) -> list[str]:
    """A claim's values, lower-cased. Lists (groups, roles) give each item; a string gives itself."""
    if claim == "email_domain":
        return [email.rsplit("@", 1)[-1].lower()] if email and email_verified and "@" in email else []
    v = claims.get(claim)
    if v is None:
        return []
    items = v if isinstance(v, (list, tuple)) else [v]
    return [str(x).strip().lower() for x in items if x is not None and not isinstance(x, (dict, list))]


def rule_matches(rule: dict, provider_key: str | None, claims: dict, *, email: str | None,
                 email_verified: bool) -> bool:
    if rule["provider"] and provider_key and rule["provider"] != provider_key:
        return False
    return rule["match_value"].strip().lower() in claim_values(
        claims, rule["claim"], email=email, email_verified=email_verified)


def matching(rule_list: list[dict], provider_key: str | None, claims: dict, *, email: str | None,
             email_verified: bool) -> list[dict]:
    return [r for r in rule_list if rule_matches(r, provider_key, claims, email=email, email_verified=email_verified)]


def _display_name(name: str | None, email: str) -> str:
    name = (name or "").strip() or email.split("@")[0]
    return (name if len(name) >= 2 else email)[:120]


# --- Just-in-time accounts -------------------------------------------------------------------------------


@hooks.provisioner
def provision_from_group(conn: Connection, provider, ident, context: dict) -> tuple[str, str] | None:
    if (context or {}).get("invite") or not ident.email:
        return None                           # an invite is more specific: let its provisioner decide
    candidates = conn.execute(
        f"""
        SELECT {RULE_COLUMNS} FROM sign_in_rules r
        JOIN sign_in_rule_settings s ON s.organization_id = r.organization_id
        WHERE s.jit_enabled
        ORDER BY r.priority, r.created_at
        """,
    ).fetchall()
    found = matching(candidates, provider.key, ident.claims, email=ident.email, email_verified=ident.email_verified)
    if not found:
        return None
    rule = found[0]
    person = people.create_person(
        conn, organization_id=rule["organization_id"], display_name=_display_name(ident.name, ident.email),
        email=ident.email, role=rule["role"], team=rule["team"], specialty=rule["specialty"], source="sso_group",
    )
    audit.record(conn, action="access.user_create", entity_type="user", entity_id=person["id"], detail={
        "role": rule["role"], "team": person["team"], "source": "sso_group", "rule_id": rule["id"],
        "provider": provider.key})
    log.info("created %s account %s from sign-in rule %s", rule["role"], person["id"], rule["id"])
    return person["id"], "group_mapping"


# --- Keep role and team in sync --------------------------------------------------------------------------


def sync_change(conn: Connection, user: dict, rule: dict | None) -> dict | None:
    """What syncing `user` (role, team, organization_id, id) to `rule` would change, or None.
    `blocked` is set when the change must not happen (the organization's last administrator)."""
    if rule is None or user["role"] not in SYNC_ROLES or rule["role"] not in SYNC_ROLES:
        return None
    to_team = rule["team"] if rule["role"] == "staff" else None
    if rule["role"] == user["role"] and to_team == user["team"]:
        return None
    change = {"from_role": user["role"], "to_role": rule["role"], "from_team": user["team"], "to_team": to_team,
              "rule_id": rule["id"], "blocked": None}
    if user["role"] == "admin" and rule["role"] != "admin":
        others = conn.execute(
            "SELECT count(*) AS n FROM users WHERE organization_id = %s AND role = 'admin' AND NOT disabled "
            "AND id::text <> %s",
            (user["organization_id"], user["id"]),
        ).fetchone()["n"]
        if others == 0:
            change["blocked"] = "last_admin"
    return change


def sync_rule(rule_list: list[dict], provider_key: str | None, claims: dict, *, email: str | None,
              email_verified: bool) -> dict | None:
    for r in matching(rule_list, provider_key, claims, email=email, email_verified=email_verified):
        if r["role"] in SYNC_ROLES:
            return r
    return None


@hooks.after_sign_in
def sync_from_groups(conn: Connection, user_id: str, provider, ident, context: dict) -> None:
    try:
        with conn.transaction():              # a savepoint: a problem here never blocks the sign-in
            _sync(conn, user_id, provider, ident)
    except Exception:  # noqa: BLE001
        log.exception("group sync failed for user %s", user_id)


def _sync(conn: Connection, user_id: str, provider, ident) -> None:
    user = conn.execute(
        "SELECT id::text, role, team, organization_id::text AS organization_id FROM users WHERE id::text = %s",
        (user_id,),
    ).fetchone()
    if not user or user["role"] not in SYNC_ROLES or not user["organization_id"]:
        return
    if not settings(conn, user["organization_id"])["sync_on_sign_in"]:
        return
    rule = sync_rule(rules(conn, user["organization_id"]), provider.key, ident.claims, email=ident.email,
                     email_verified=ident.email_verified)
    change = sync_change(conn, user, rule)
    if change is None:
        return
    if change["blocked"]:
        log.warning("group sync: not demoting %s, the organization's last administrator", user_id)
    else:
        conn.execute("UPDATE users SET role = %s, team = %s WHERE id::text = %s",
                     (change["to_role"], change["to_team"], user_id))
        people.sync_pharmacy_staff(conn, user_id, user["organization_id"],
                                   change["to_team"] if change["to_role"] == "staff" else None)
    audit.record(conn, action="access.group_sync", entity_type="user", entity_id=user_id,
                 detail=change | {"provider": provider.key})


# --- Explain (the admin "test with sample claims" tool) --------------------------------------------------


def _email_from(claims: dict) -> str | None:
    for k in ("email", "preferred_username", "upn"):
        v = claims.get(k)
        if isinstance(v, str) and "@" in v:
            return v.strip().lower()
    return None


def explain(conn: Connection, org_id: str, provider_key: str | None, claims: dict) -> dict:
    """What a sign-in with these claims would do in this organization, and why."""
    email = _email_from(claims)
    # The sample isn't a verified token; treat its email as verified so email_domain rules can be tried.
    rule_list = rules(conn, org_id)
    cfg = settings(conn, org_id)
    found = matching(rule_list, provider_key, claims, email=email, email_verified=True)
    warnings = []
    names = claims.get("_claim_names")
    if (isinstance(names, dict) and "groups" in names) or claims.get("hasgroups"):
        warnings.append("Entra left the groups out because this person is in too many groups (over 200). "
                        "Filter the groups claim to groups assigned to the application, or use app roles.")
    for claim in sorted({r["claim"] for r in rule_list} - set(PSEUDO_CLAIMS)):
        if claim not in claims:
            warnings.append(f"The token has no '{claim}' claim, so rules on it can't match.")
    if not email:
        warnings.append("The token has no email (email, preferred_username or upn), so nobody can be matched.")

    user = conn.execute(
        "SELECT id::text, display_name, role, team, organization_id::text AS organization_id, disabled "
        "FROM users WHERE lower(email) = %s", (email,),
    ).fetchone() if email else None
    result: dict[str, Any] = {
        "email": email, "provider": provider_key, "settings": cfg,
        "matched_rules": [r["id"] for r in found],
        "rule": found[0] if found else None,
        "claims_seen": {c: claim_values(claims, c, email=email, email_verified=True)
                        for c in sorted({r["claim"] for r in rule_list} | {"groups", "roles", "hd"})},
        "warnings": warnings,
    }
    if user is None:
        if not found:
            result |= {"outcome": "not_registered",
                       "summary": "No rule matches and there is no account with this email: sign-in is refused."}
        elif not cfg["jit_enabled"]:
            result |= {"outcome": "not_registered",
                       "summary": "A rule matches, but creating accounts on first sign-in is off: sign-in is refused."}
        else:
            r = found[0]
            result |= {"outcome": "create", "role": r["role"], "team": r["team"] if r["role"] == "staff" else None,
                       "specialty": r["specialty"] if r["role"] == "clinician" else None,
                       "summary": f"A new {r['role']} account would be created on first sign-in."}
        return result

    result["user"] = {"id": user["id"], "display_name": user["display_name"], "role": user["role"],
                      "team": user["team"], "disabled": user["disabled"]}
    if user["disabled"]:
        return result | {"outcome": "disabled", "summary": "This account is turned off: sign-in is refused."}
    if user["organization_id"] not in (None, org_id):
        return result | {"outcome": "other_organization",
                         "summary": "This email belongs to another organization; its rules apply."}
    change = sync_change(conn, user, sync_rule(rule_list, provider_key, claims, email=email, email_verified=True))
    result["change"] = change
    if user["role"] not in SYNC_ROLES:
        summary = f"Signs in as the existing {user['role']}. Rules never change a {user['role']}'s role."
        return result | {"outcome": "sign_in", "summary": summary}
    if change is None:
        return result | {"outcome": "sign_in", "summary": "Signs in as the existing account; nothing to change."}
    if not cfg["sync_on_sign_in"]:
        return result | {"outcome": "sign_in",
                         "summary": "Signs in as the existing account. A rule would change their role or team, "
                                    "but keeping roles in sync is off."}
    if change["blocked"]:
        return result | {"outcome": "sign_in",
                         "summary": "Signs in, but stays an administrator: they are the organization's last one."}
    return result | {"outcome": "sync",
                     "summary": f"Signs in and becomes {change['to_role']}"
                                + (f" ({change['to_team']})" if change["to_team"] else "") + "."}
