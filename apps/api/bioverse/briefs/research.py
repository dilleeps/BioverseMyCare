"""Pre-visit brief lines for research: only for patients who opted in to research matching."""

from __future__ import annotations

from bioverse import consent, trials

LABELS = {"contacted": "contacted by the study team", "screening": "in screening"}


def bullets(conn, patient_id: str, practitioner_id: str) -> list[dict]:
    if not consent.is_granted(conn, patient_id, "research_matching"):
        return []
    out: list[dict] = []
    matches = trials.matches_for(conn, patient_id)
    n = len(matches)
    if n:
        names = ", ".join(m["study"]["short_title"] for m in matches)
        text = f"Consented to research; matches {n} {'study' if n == 1 else 'studies'} ({names})."
    else:
        text = "Consented to research; no current study matches."
    out.append({"text": text, "source": {"type": "research_consent", "id": patient_id}})
    for r in conn.execute(
        """
        SELECT r.id::text, r.status, s.short_title FROM research_subjects r
        JOIN research_studies s ON s.id = r.study_id
        WHERE r.patient_id = %s AND r.contact_permitted
          AND r.status IN ('interested', 'contacted', 'screening', 'enrolled')
        ORDER BY r.updated_at DESC
        """,
        (patient_id,),
    ).fetchall():
        verb = "Enrolled in" if r["status"] == "enrolled" else "Interested in"
        suffix = f" ({LABELS[r['status']]})" if r["status"] in LABELS else ""
        out.append({"text": f"{verb} study {r['short_title']}{suffix}.",
                    "source": {"type": "research_subject", "id": r["id"]}})
    return out
