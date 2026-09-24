"""Seed the demo tenant. Safe to run repeatedly: see bioverse/db/seeds/__init__.py.

Usage:
    python -m bioverse.db.seed
"""

from __future__ import annotations

from bioverse.config import get_settings
from bioverse.db.seeds import run_all
from bioverse.db.seeds.ids import *  # noqa: F403  (re-exported for tests and scripts)


def seed(database_url: str) -> list[str]:
    return run_all(database_url)


def main() -> None:
    ran = seed(get_settings().database_url)
    print("Seeded demo tenant: Northside Health (" + ", ".join(ran) + ")")


if __name__ == "__main__":
    main()
