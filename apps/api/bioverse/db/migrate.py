"""Apply SQL migrations in order. `--reset` drops and recreates the public schema first.

Usage:
    python -m bioverse.db.migrate [--reset]
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg

from bioverse.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def migrate(database_url: str, reset: bool = False) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(database_url, autocommit=False) as conn:
        if reset:
            conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
            conn.execute("CREATE SCHEMA public")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            conn.execute(path.read_text())
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
            applied.append(path.name)
        conn.commit()
    return applied


def main() -> None:
    reset = "--reset" in sys.argv
    applied = migrate(get_settings().database_url, reset=reset)
    if applied:
        print("Applied:", ", ".join(applied))
    else:
        print("Database is up to date.")


if __name__ == "__main__":
    main()
