"""Scheduled jobs: reminders, alerts, digests and anything else that runs without a request.

A module adds a job by creating `bioverse/jobs/<name>.py`:

    from bioverse.jobs import job

    @job("medication_reminders", every_minutes=15, description="Create today's medication reminders")
    def run(conn, now):
        ...
        return {"created": 3}          # shown in the admin job history

`python -m bioverse.jobs` runs every job that is due, once, and exits. In the cloud, Cloud Scheduler
executes it as a Cloud Run job every five minutes; locally, run it by hand or from the admin screen.
Each job runs in its own transaction and every run is recorded in `job_runs`. Jobs must be idempotent
(use notification dedupe keys), because a run can repeat after a failure.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from psycopg import Connection
from psycopg.types.json import Jsonb

log = logging.getLogger("bioverse.jobs")


@dataclass(frozen=True)
class Job:
    name: str
    every_minutes: int
    description: str
    fn: Callable[[Connection, datetime], dict[str, Any] | None]


REGISTRY: dict[str, Job] = {}


def job(name: str, *, every_minutes: int, description: str):
    def wrap(fn):
        REGISTRY[name] = Job(name, every_minutes, description, fn)
        return fn
    return wrap


_loaded = False


def load_all() -> dict[str, Job]:
    global _loaded
    if not _loaded:
        for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
            if not info.name.startswith("_"):
                importlib.import_module(f"{__name__}.{info.name}")
        _loaded = True
    return REGISTRY


def last_runs(conn: Connection) -> dict[str, dict]:
    rows = conn.execute(
        """
        SELECT DISTINCT ON (name) name, id, started_at, finished_at, status, detail
        FROM job_runs ORDER BY name, started_at DESC
        """
    ).fetchall()
    return {r["name"]: r for r in rows}


def is_due(j: Job, last: dict | None, now: datetime) -> bool:
    if last is None:
        return True
    if last["status"] == "running" and (now - last["started_at"]).total_seconds() < 15 * 60:
        return False            # still running elsewhere; a run stuck for 15 minutes is retried
    return (now - last["started_at"]).total_seconds() >= j.every_minutes * 60 - 30


def run_job(conn: Connection, name: str, now: datetime | None = None) -> dict:
    """Run one job now, in its own transaction, and record the run."""
    j = load_all()[name]
    now = now or datetime.now(timezone.utc)
    run_id = conn.execute(
        "INSERT INTO job_runs (name, started_at) VALUES (%s, %s) RETURNING id", (name, now)
    ).fetchone()["id"]
    conn.commit()
    try:
        with conn.transaction():
            detail = j.fn(conn, now) or {}
        status = "succeeded"
    except Exception as exc:  # noqa: BLE001 - a failing job must not stop the others
        log.error("job %s failed: %s", name, traceback.format_exc())
        detail, status = {"error": type(exc).__name__, "message": str(exc)[:300]}, "failed"
    conn.execute(
        "UPDATE job_runs SET finished_at = clock_timestamp(), status = %s, detail = %s WHERE id = %s",
        (status, Jsonb(detail), run_id),
    )
    conn.commit()
    return {"name": name, "status": status, "detail": detail}


def run_due(conn: Connection, now: datetime | None = None, *, force: bool = False) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    jobs = load_all()
    last = last_runs(conn)
    return [run_job(conn, name, now) for name, j in sorted(jobs.items())
            if force or is_due(j, last.get(name), now)]
