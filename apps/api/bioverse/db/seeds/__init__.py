"""Demo data, one file per module.

Every file here that defines `run(conn, ctx)` is executed in filename order, inside one
transaction. `core.py` runs first and only once. Every other module MUST be idempotent:
use fixed IDs from `ids.py` and `INSERT ... ON CONFLICT DO NOTHING`, so re-running the seed
against a database that is already in use (for example the Cloud SQL demo) only adds what
is missing.
"""

from __future__ import annotations

import importlib
import pkgutil

import psycopg

from bioverse.db.seeds.context import SeedContext


def modules() -> list[str]:
    names = [m.name for m in pkgutil.iter_modules(__path__) if m.name not in ("context", "ids")]
    # core first, then the rest in filename order (numeric prefixes set the order).
    return ["core"] + sorted(n for n in names if n != "core")


def run_all(database_url: str) -> list[str]:
    ctx = SeedContext()
    ran = []
    with psycopg.connect(database_url) as conn:
        for name in modules():
            module = importlib.import_module(f"{__name__}.{name}")
            if hasattr(module, "run"):
                module.run(conn, ctx)
                ran.append(name)
        conn.commit()
    return ran
