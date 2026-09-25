"""Extension points for sign-in, so features can plug in without editing the core flow.

- provisioner(fn): fn(conn, provider, identity, context) -> (user_id, how) | None. Called, in registration order,
  when a verified sign-in matches no linked identity and no existing user by email. The first non-None wins.
  Use it to create accounts for invited patients or for members of a mapped directory group.
- after_sign_in(fn): fn(conn, user_id, provider, identity, context) -> None. Called after every successful
  sign-in (linked, matched or provisioned), e.g. to re-apply group-to-role mapping.

`context` is what the sign-in was started with (e.g. {"invite": token}), carried through the OIDC round trip.
Plug-ins live in bioverse/sso/plugins/*.py and are imported on first use.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Callable

_provisioners: list[Callable] = []
_after_sign_in: list[Callable] = []
_loaded = False

# Query parameters /api/auth/login accepts and carries through to the callback as context.
CONTEXT_PARAMS = ("invite",)


def provisioner(fn: Callable) -> Callable:
    _provisioners.append(fn)
    return fn


def after_sign_in(fn: Callable) -> Callable:
    _after_sign_in.append(fn)
    return fn


def load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from bioverse.sso import plugins
    for mod in pkgutil.iter_modules(plugins.__path__):
        importlib.import_module(f"{plugins.__name__}.{mod.name}")


def provisioners() -> list[Callable]:
    load()
    return list(_provisioners)


def after_sign_in_hooks() -> list[Callable]:
    load()
    return list(_after_sign_in)
