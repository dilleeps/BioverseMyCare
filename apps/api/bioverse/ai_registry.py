"""Agent registry (docs/03 "Agent governance", docs/04 "Model registry", "Prompt management").

The registry rows live in `ai_agents` (seeded from AGENTS below). Two things are computed live, never
trusted from the table:

- **Prompt version**: sha256 of the system prompt text the running code would send. Each agent names
  candidate `module:ATTRIBUTE` references; the first one that imports is fingerprinted. Agents whose
  module is not installed in this build report no prompt (they are "planned", or live elsewhere).
- **Live model**: the configured model when AI is on, or rules mode.

`ai_prompt_versions` records every fingerprint the first time it is observed, so the activity log can
say which prompt was live when an event happened, even though audit events do not record it themselves.
"""

from __future__ import annotations

import hashlib
import importlib
from datetime import datetime
from typing import Any

from psycopg import Connection

DETERMINISTIC = "none (deterministic rules)"
CONFIGURED = "MedGemma on Vertex AI, then Claude, rules fallback"
# Earlier text for the same setting, still stored in databases seeded before MedGemma was added.
LEGACY_CONFIGURED = {"Claude (BIOVERSE_MODEL), rules fallback"}

# Order is the display order. `audit_agents` are the audit_events.agent prefixes each one writes.
AGENTS: list[dict[str, Any]] = [
    {
        "id": "orchestrator", "name": "Front-door orchestrator",
        "purpose": "Owns the conversation: red-flag screen first, safety checks, triage, routing, confirmation.",
        "owner": "AI Platform", "model": DETERMINISTIC, "status": "active",
        "permitted_tools": ["red-flag screen", "intake agent", "intent registry", "conversation write", "review queue write"],
        "human_review": "Red flags escalate immediately to the care team; nothing routine continues past them.",
        "prompt_refs": [], "audit_agents": ["orchestrator"],
    },
    {
        "id": "red-flag-rules", "name": "Red-flag rules engine",
        "purpose": "Deterministic screen of every patient message for emergencies, crises and screen topics.",
        "owner": "Clinical governance", "model": DETERMINISTIC, "status": "active",
        "permitted_tools": ["ruleset (versioned)", "safety checks"],
        "human_review": "Immediate escalation replaces review for high urgency (docs/04 matrix).",
        "prompt_refs": [], "audit_agents": ["safety/red-flags"],
    },
    {
        "id": "patient-agent", "name": "Patient Agent",
        "purpose": "Understands what the patient needs: conversational front door, education, document understanding, summaries.",
        "owner": "Patient experience", "model": CONFIGURED, "status": "planned",
        "permitted_tools": ["intent classification", "patient record read", "document OCR", "knowledge retrieval", "conversation memory"],
        "human_review": "Education from approved content only; clinical content goes through clinician review.",
        "prompt_refs": ["bioverse.agents.patient:SYSTEM_PROMPT", "bioverse.agents.patient_agent:SYSTEM_PROMPT"],
        "audit_agents": ["patient-agent"],
    },
    {
        "id": "intake-agent", "name": "Intake Agent (triage)",
        "purpose": "Turns a conversation into a structured intake: questions, urgency, specialty, two summaries.",
        "owner": "Care journey", "model": CONFIGURED, "status": "active",
        "permitted_tools": ["questionnaire", "red-flag rules", "summary generation", "intent registry"],
        "human_review": "No review for routine urgency and clinician-facing summaries; moderate urgency gets staff review; high escalates.",
        "prompt_refs": ["bioverse.agents.triage:SYSTEM_PROMPT"], "audit_agents": ["intake-agent"],
    },
    {
        "id": "care-navigator-agent", "name": "Care Navigator Agent",
        "purpose": "Matches specialty, provider, location, coverage, language and accessibility.",
        "owner": "Care journey", "model": DETERMINISTIC, "status": "active",
        "permitted_tools": ["provider directory", "slot search", "coverage match", "distance"],
        "human_review": "None: operational matching, confirmed by the patient.",
        "prompt_refs": ["bioverse.agents.navigator:SYSTEM_PROMPT"], "audit_agents": ["care-navigator-agent"],
    },
    {
        "id": "scheduling-agent", "name": "Scheduling Agent",
        "purpose": "Books, reschedules and cancels; reminders and pre-visit checklists.",
        "owner": "Care journey", "model": DETERMINISTIC, "status": "active",
        "permitted_tools": ["slot search", "appointment write", "notifications"],
        "human_review": "None: the patient confirms every booking.",
        "prompt_refs": [], "audit_agents": ["scheduling-agent"],
    },
    {
        "id": "doctor-agent", "name": "Doctor Agent",
        "purpose": "Extends a specific clinician: pre-visit brief, questions, follow-up protocol, post-visit answers.",
        "owner": "Clinical workspace", "model": CONFIGURED, "status": "active",
        "permitted_tools": ["physician configuration", "patient record read", "encounter write", "approved education"],
        "human_review": "Per the clinician's configuration; locked organization requirements always apply.",
        "prompt_refs": ["bioverse.agents.doctor:SYSTEM_PROMPT", "bioverse.agents.doctor_agent:SYSTEM_PROMPT"],
        "audit_agents": ["doctor-agent"],
    },
    {
        "id": "evidence-agent", "name": "Evidence Agent",
        "purpose": "Guidelines, literature, drug and trial information with citations; 'no evidence found' otherwise.",
        "owner": "Clinical workspace", "model": CONFIGURED, "status": "planned",
        "permitted_tools": ["guideline index", "literature index", "drug labels", "trial registry", "citation formatter"],
        "human_review": "No review, but never uncited (recipient is a clinician).",
        "prompt_refs": ["bioverse.agents.evidence:SYSTEM_PROMPT", "bioverse.evidence:SYSTEM_PROMPT"],
        "audit_agents": ["evidence-agent"],
    },
    {
        "id": "results-agent", "name": "Results Agent",
        "purpose": "Structures reports, flags abnormals, drafts plain-language explanations for clinician review.",
        "owner": "Care journey", "model": DETERMINISTIC, "status": "active",
        "permitted_tools": ["structured extraction", "LOINC mapping", "reference ranges", "trend engine", "review queue write"],
        "human_review": "Clinician review before any explanation reaches the patient.",
        "prompt_refs": ["bioverse.agents.results:SYSTEM_PROMPT", "bioverse.agents.results_agent:SYSTEM_PROMPT"],
        "audit_agents": ["results-agent"],
    },
    {
        "id": "follow-up-agent", "name": "Follow-up Agent",
        "purpose": "Care-plan tasks, reminders, missed-task alerts, referral status, follow-up scheduling.",
        "owner": "Care journey", "model": CONFIGURED, "status": "planned",
        "permitted_tools": ["care plan read/write", "task write", "reminders", "referral tracker"],
        "human_review": "Clinician approves plan tasks on creation; reminders need no further review.",
        "prompt_refs": ["bioverse.agents.followup:SYSTEM_PROMPT", "bioverse.agents.follow_up:SYSTEM_PROMPT"],
        "audit_agents": ["follow-up-agent", "followup-agent"],
    },
    {
        "id": "hospital-agent", "name": "Hospital Agent",
        "purpose": "Patient flow, queue status, department utilization, staff assistance, capacity.",
        "owner": "Hospital operations", "model": CONFIGURED, "status": "planned",
        "permitted_tools": ["operational data", "queue system", "capacity model", "staff directory"],
        "human_review": "Operational outputs for staff; no patient-facing clinical content.",
        "prompt_refs": ["bioverse.agents.hospital:SYSTEM_PROMPT", "bioverse.agents.hospital_agent:SYSTEM_PROMPT"],
        "audit_agents": ["hospital-agent"],
    },
    {
        "id": "vitals-photo", "name": "Meter photo reader",
        "purpose": "Reads the display of a blood pressure cuff, glucometer, thermometer, scale or oximeter from a photo.",
        "owner": "Patient experience", "model": CONFIGURED, "status": "active",
        "permitted_tools": ["image read"],
        "human_review": "The patient confirms or edits every value before it is saved; alerts use fixed rules.",
        "prompt_refs": ["bioverse.routers.vitals_import:PHOTO_SYSTEM"], "audit_agents": ["vitals-photo"],
    },
    {
        "id": "photo-questions", "name": "Photo questions",
        "purpose": "Reads medicine packaging and paper reports from a photo; skin photos get a safety checklist only.",
        "owner": "Patient experience", "model": CONFIGURED, "status": "active",
        "permitted_tools": ["image read", "patient medication list"],
        "human_review": "Answers come only from the patient's own prescriptions; skin photos go to a clinician with consent.",
        "prompt_refs": ["bioverse.routers.photo_questions:MEDICINE_PROMPT"], "audit_agents": ["photo-questions", "photo/"],
    },
    {
        "id": "nutrition-scan", "name": "Food photo scan",
        "purpose": "Names foods and portions in a meal photo and matches them to the food list.",
        "owner": "Wellbeing", "model": CONFIGURED, "status": "active",
        "permitted_tools": ["image read", "food database"],
        "human_review": "The person confirms every item before it is logged.",
        "prompt_refs": ["bioverse.routers.nutrition:SCAN_SYSTEM"], "audit_agents": ["nutrition-scan"],
    },
    {
        "id": "card-scan", "name": "Insurance card reader",
        "purpose": "Reads payer, member and pharmacy fields from a photo of an insurance card.",
        "owner": "Revenue cycle", "model": CONFIGURED, "status": "active",
        "permitted_tools": ["image read"],
        "human_review": "The patient confirms the fields and the payer's eligibility response must come back active.",
        "prompt_refs": ["bioverse.routers.insurance:SCAN_SYSTEM"], "audit_agents": ["card-scan"],
    },
    {
        "id": "consult-intake", "name": "Consultation intake brief",
        "purpose": "Prepares a pre-consultation brief for the clinician from the request and the record.",
        "owner": "Care journey", "model": CONFIGURED, "status": "active",
        "permitted_tools": ["patient record read"],
        "human_review": "Clinician-facing only; the clinician runs the consultation.",
        "prompt_refs": ["bioverse.routers.consultations:INTAKE_SYSTEM"], "audit_agents": ["consult-intake"],
    },
    {
        "id": "companion", "name": "Health companion",
        "purpose": "Phrases proactive check-ins and reminders from structured facts.",
        "owner": "Patient experience", "model": CONFIGURED, "status": "active",
        "permitted_tools": ["notifications", "check-in write"],
        "human_review": "No clinical advice: wording that looks like advice falls back to templates. Replies are screened and escalated.",
        "prompt_refs": ["bioverse.companion:CHECKIN_SYSTEM"], "audit_agents": ["companion"],
    },
    {
        "id": "factcheck", "name": "Health fact check",
        "purpose": "Extracts health claims from pasted text and checks them against the evidence library.",
        "owner": "Clinical governance", "model": CONFIGURED, "status": "active",
        "permitted_tools": ["evidence library search"],
        "human_review": "Citations are library rows only; a verdict without a citation becomes 'not enough evidence'.",
        "prompt_refs": ["bioverse.routers.factcheck:JUDGE_SYSTEM"], "audit_agents": ["factcheck"],
    },
    {
        "id": "public-agent", "name": "Public specialist agents",
        "purpose": "General education in a clinician's scope, from their approved guidance and the evidence library.",
        "owner": "Clinical governance", "model": CONFIGURED, "status": "active",
        "permitted_tools": ["approved guidance notes", "evidence library search"],
        "human_review": "Clinician approves sample answers and an administrator approves listing; no personal advice.",
        "prompt_refs": ["bioverse.routers.specialists:SYSTEM_PROMPT"], "audit_agents": ["public-agent"],
    },
    {
        "id": "learning-tutor", "name": "Case tutor for students",
        "purpose": "Socratic feedback on de-identified teaching cases.",
        "owner": "Education", "model": CONFIGURED, "status": "active",
        "permitted_tools": ["de-identified case library"],
        "human_review": "Scoring is by fixed rules; the tutor only writes feedback. No identifiable data.",
        "prompt_refs": ["bioverse.routers.learning:TUTOR_SYSTEM"], "audit_agents": ["learning-tutor"],
    },
]


def prompt_text(ref: str) -> str | None:
    """Import `package.module:ATTRIBUTE` and return it when it is a string. Only bioverse modules."""
    module_name, _, attr = ref.partition(":")
    if not module_name.startswith("bioverse.") or not attr:
        return None
    try:
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
    except Exception:  # noqa: BLE001  (not installed in this build, or broken: report as absent)
        return None
    return value if isinstance(value, str) else None


def prompt_fingerprint(ref: str) -> str | None:
    text = prompt_text(ref)
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None


def live_prompt(prompt_refs: list[str]) -> dict[str, Any] | None:
    for ref in prompt_refs or []:
        text = prompt_text(ref)
        if text is not None:
            return {"ref": ref, "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(), "length": len(text)}
    return None


def ruleset_version() -> str:
    from bioverse.safety.red_flags import RULESET_VERSION

    return RULESET_VERSION


def live_model(registered: str) -> str:
    from bioverse.agents import llm, medgemma
    from bioverse.config import get_settings

    if registered != CONFIGURED and registered not in LEGACY_CONFIGURED:
        return registered
    provider = llm.active_provider()
    if provider == "medgemma":
        return f"{medgemma.model_label()} (MedGemma, Vertex AI)"
    if provider == "claude":
        return get_settings().ai_model
    return "rules mode (AI is off)"


def agent_for(agent_value: str | None, agents: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Map an audit_events.agent value (e.g. 'intake-agent/claude+fallback') to its registry row."""
    if not agent_value:
        return None
    for a in agents:
        for prefix in a["audit_agents"] or []:
            if agent_value == prefix or agent_value.startswith(prefix + "/"):
                return a
    return None


def path_of(agent_value: str | None, agents: list[dict[str, Any]] | None = None) -> str | None:
    """'intake-agent/claude+fallback' -> 'claude+fallback'; 'safety/red-flags' -> None (the prefix itself).

    With the registry, the path is whatever follows the agent's registered audit prefix.
    """
    if not agent_value:
        return None
    for a in agents or []:
        for prefix in a["audit_agents"] or []:
            if agent_value == prefix:
                return None
            if agent_value.startswith(prefix + "/"):
                return agent_value[len(prefix) + 1:]
    if "/" not in agent_value:
        return None
    return agent_value.split("/", 1)[1]


def load(conn: Connection) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, name, purpose, owner, model, status, permitted_tools, human_review, prompt_refs,
               audit_agents, position, updated_at
        FROM ai_agents ORDER BY position, name
        """
    ).fetchall()


def observe_prompts(conn: Connection, agents: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Fingerprint every agent's live prompt and remember fingerprints seen for the first time."""
    out: dict[str, dict[str, Any]] = {}
    for a in agents if agents is not None else load(conn):
        prompt = live_prompt(a["prompt_refs"])
        if prompt is None:
            continue
        out[a["id"]] = prompt
        conn.execute(
            """
            INSERT INTO ai_prompt_versions (agent_id, prompt_hash, prompt_ref) VALUES (%s, %s, %s)
            ON CONFLICT (agent_id, prompt_hash) DO NOTHING
            """,
            (a["id"], prompt["hash"], prompt["ref"]),
        )
    return out


def prompt_version_at(conn: Connection, agent_id: str, at: datetime) -> dict[str, Any] | None:
    """The most recent fingerprint first observed at or before `at`."""
    return conn.execute(
        """
        SELECT prompt_hash, prompt_ref, first_seen_at FROM ai_prompt_versions
        WHERE agent_id = %s AND first_seen_at <= %s ORDER BY first_seen_at DESC LIMIT 1
        """,
        (agent_id, at),
    ).fetchone()
