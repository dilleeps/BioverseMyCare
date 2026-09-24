"""Timeline contributors for My Health Story and the clinician timeline.

A module adds dated events by dropping a file here that defines:

    def events(conn, patient_id: str, since) -> list[dict]:
        # each: {"at": datetime, "type": str, "title": str, "detail": str, "tone": "neutral"|"alert"|"plan"|"visit",
        #        "ref_id": str}
        # `since` is a datetime or None; return only events at or after it.
"""

from __future__ import annotations

import importlib
import pkgutil


def collect(conn, patient_id: str, since) -> list[dict]:
    out: list[dict] = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        module = importlib.import_module(f"{__name__}.{info.name}")
        if hasattr(module, "events"):
            out.extend(module.events(conn, patient_id, since))
    return out
