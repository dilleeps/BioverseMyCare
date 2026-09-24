"""Run due jobs once and exit.

    python -m bioverse.jobs                 # every job that is due
    python -m bioverse.jobs --all           # every job, due or not
    python -m bioverse.jobs dispatch_notifications medication_reminders
"""

from __future__ import annotations

import json
import sys

import psycopg
from psycopg.rows import dict_row

from bioverse.config import get_settings
from bioverse.jobs import load_all, run_due, run_job


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    jobs = load_all()
    unknown = [a for a in args if a not in jobs]
    if unknown:
        print("Unknown job(s):", ", ".join(unknown), "| known:", ", ".join(sorted(jobs)), file=sys.stderr)
        return 2
    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as conn:
        if args:
            results = [run_job(conn, a) for a in args]
        else:
            results = run_due(conn, force="--all" in sys.argv)
    for r in results:
        print(json.dumps(r, default=str))
    if not results:
        print("No jobs due.")
    return 1 if any(r["status"] == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
