"""Pre-visit brief lines from home vitals: BP average and share high, weight change, open alerts, plan adherence."""

from __future__ import annotations

from bioverse.routers.vitals_core import brief_bullets


def bullets(conn, patient_id: str, practitioner_id: str) -> list[dict]:
    return brief_bullets(conn, patient_id, practitioner_id)
