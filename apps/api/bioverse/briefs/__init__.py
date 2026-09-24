"""Pre-visit brief contributors.

A module adds lines to the clinician's pre-visit brief by dropping a file here that defines:

    def bullets(conn, patient_id: str, practitioner_id: str) -> list[dict]:
        # each: {"text": str, "source": {"type": str, "id": str}, "flag": str | None}

`flag`, when set, is added to the brief's attention flags. Keep lines factual and sourced.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

log = logging.getLogger(__name__)


def collect(conn, patient_id: str, practitioner_id: str) -> list[dict]:
    out: list[dict] = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        module = importlib.import_module(f"{__name__}.{info.name}")
        if hasattr(module, "bullets"):
            out.extend(module.bullets(conn, patient_id, practitioner_id))
    return out
