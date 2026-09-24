"""Trust and Safety + AI Platform demo data (ids 8000-8499).

- Agent registry rows and the first observed prompt fingerprints.
- Labelled evaluation cases (red-flag regression set, rules intent-routing set).
- The clinical review matrix from docs/04, as data.
- Default retention policies for Northside Health.
- Two fictional safety incidents.
- A small, clearly marked set of demo audit events (detail.seed = 's080') so the access log, AI activity
  log and monitoring have history on a fresh database. They are appended once, never edited.
"""

from __future__ import annotations

import json

from bioverse import ai_registry, evals
from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import ORG, P_MAYA, P_PARK, U_ADMIN, U_MAYA, U_OKAFOR, U_PARK, _id

REVIEW_MATRIX = [
    ("General health education", "none", "No review, from approved content only", "Low risk, content pre-approved"),
    ("Symptom follow-up questions during intake", "none", "No review", "Questions gather information, they do not advise"),
    ("Urgency classification and care-pathway recommendation", "tiered",
     "No review for routine and low urgency. Staff review for moderate. Immediate escalation for high.",
     "Speed matters for high urgency, so escalation replaces review"),
    ("Intake summary sent to clinician", "none", "No review", "Recipient is a clinician"),
    ("Explanation of normal results", "staff", "Clinician review, may be delegated to staff",
     "Low harm, but sets patient expectations"),
    ("Explanation of abnormal results", "clinician", "Clinician review required", "Interpretation is clinical judgment"),
    ("Medication instructions", "clinician", "Clinician review required", "Direct patient safety impact"),
    ("Draft clinical notes, referrals, discharge instructions", "clinician_edit", "Clinician review and edit required",
     "Legal clinical record"),
    ("Care plan tasks", "clinician",
     "Clinician approval on creation. Follow-up Agent may send reminders without further review.",
     "Plan is clinical, reminders are operational"),
    ("Doctor Agent post-visit answers", "configurable",
     "Per the clinician's configuration. Default: routine education unreviewed, anything else escalated.",
     "Clinician owns their agent's scope"),
    ("Evidence Assistant answers", "none", "No review, but never uncited",
     "Recipient is a clinician who exercises judgment"),
]

RETENTION_DEFAULTS = [
    ("conversations", 2555, "Seven years, aligned with the medical record."),
    ("messages", 2555, "Seven years, aligned with the medical record."),
    ("audit_events", 2190, "Six years minimum (HIPAA documentation retention). Cannot be set lower."),
    ("documents", 3650, "Ten years for lab reports and uploaded documents."),
]


def run(conn, ctx: SeedContext) -> None:
    cur = conn.cursor()

    # Agent registry -------------------------------------------------------------------------------
    for pos, a in enumerate(ai_registry.AGENTS):
        cur.execute(
            """
            INSERT INTO ai_agents (id, name, purpose, owner, model, status, permitted_tools, human_review,
                                   prompt_refs, audit_agents, position)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (a["id"], a["name"], a["purpose"], a["owner"], a["model"], a["status"], a["permitted_tools"],
             a["human_review"], a["prompt_refs"], a["audit_agents"], (pos + 1) * 10),
        )
    ai_registry.observe_prompts(conn, ai_registry.AGENTS)

    # Evaluation cases -----------------------------------------------------------------------------
    for suite in evals.SUITES:
        for c in evals.cases_for(suite):
            cur.execute(
                """
                INSERT INTO eval_cases (id, suite, text, category, expected_level, expected_topic, expected_intent,
                                        expected_specialty, known_gap, note)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET known_gap = EXCLUDED.known_gap, note = EXCLUDED.note
                """,
                (_id(c.n), suite, c.text, c.category, c.level, c.topic, c.intent, c.specialty, c.known_gap, c.note),
            )

    # Review matrix ----------------------------------------------------------------------------------
    for i, (output_type, level, policy, rationale) in enumerate(REVIEW_MATRIX):
        cur.execute(
            """
            INSERT INTO review_policies (id, position, output_type, review_level, default_policy, rationale)
            VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
            """,
            (_id(8200 + i), i + 1, output_type, level, policy, rationale),
        )

    # Retention ------------------------------------------------------------------------------------------
    for category, days, notes in RETENTION_DEFAULTS:
        cur.execute(
            """
            INSERT INTO retention_policies (organization_id, category, retention_days, notes)
            VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
            """,
            (ORG, category, days, notes),
        )

    # Incidents ------------------------------------------------------------------------------------------
    cur.execute(
        """
        INSERT INTO safety_incidents (id, organization_id, reported_by, category, severity, title, description,
                                      linked_entity_type, linked_entity_id, status, history, created_at, updated_at)
        VALUES (%s, %s, %s, 'ai_safety', 'high', %s, %s, 'eval_case', %s, 'investigating', %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (
            _id(8300), ORG, U_OKAFOR,
            "Red-flag screen missed 'pain in my chest ... into my jaw'",
            "Demo incident. In a test conversation the phrase 'the pain in my chest is going into my jaw and I feel "
            "faint' passed the red-flag screen as routine. The same wording is now a known-gap case in the red-flag "
            "evaluation set so every ruleset release is checked against it.",
            _id(8072),
            json.dumps([
                {"status": "open", "at": ctx.at(ctx.days(-3), 10, 5).isoformat(), "by": "Dr. Adaeze Okafor", "note": "Reported"},
                {"status": "investigating", "at": ctx.at(ctx.days(-2), 9, 0).isoformat(), "by": "Northside Operations",
                 "note": "Added to evaluation set; ruleset owner notified."},
            ]),
            ctx.at(ctx.days(-3), 10, 5), ctx.at(ctx.days(-2), 9, 0),
        ),
    )
    cur.execute(
        """
        INSERT INTO safety_incidents (id, organization_id, reported_by, category, severity, title, description,
                                      status, resolution, history, created_at, updated_at, resolved_at)
        VALUES (%s, %s, %s, 'privacy', 'low', %s, %s, 'resolved', %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (
            _id(8301), ORG, U_ADMIN,
            "Printed pre-visit brief left at a shared workstation",
            "Demo incident. A printed brief was found at a shared workstation at the end of a clinic session.",
            "Brief shredded. Reminder sent to clinic staff about the print policy.",
            json.dumps([
                {"status": "open", "at": ctx.at(ctx.days(-12), 17, 30).isoformat(), "by": "Northside Operations", "note": "Reported"},
                {"status": "resolved", "at": ctx.at(ctx.days(-11), 9, 15).isoformat(), "by": "Northside Operations",
                 "note": "Brief shredded. Reminder sent to clinic staff about the print policy."},
            ]),
            ctx.at(ctx.days(-12), 17, 30), ctx.at(ctx.days(-11), 9, 15), ctx.at(ctx.days(-11), 9, 15),
        ),
    )

    _demo_audit_events(conn, ctx)


def _demo_audit_events(conn, ctx: SeedContext) -> None:
    if conn.execute("SELECT 1 FROM audit_events WHERE detail->>'seed' = 's080' LIMIT 1").fetchone():
        return
    report = conn.execute(
        """
        SELECT r.id, x.id FROM diagnostic_reports r JOIN result_explanations x ON x.report_id = r.id
        WHERE r.patient_id = %s ORDER BY r.collected_at DESC LIMIT 1
        """,
        (P_MAYA,),
    ).fetchone()
    report_id, expl_id = (report[0], report[1]) if report else (None, None)
    model = "claude-opus-5"
    d = ctx.days
    # (when, actor, role, agent, model, action, entity_type, entity_id, patient, detail)
    events = [
        (ctx.at(d(-13), 9, 12), U_PARK, "patient", "intake-agent/claude", model, "triage", "conversation", None, P_PARK,
         {"intent": "symptom", "urgency": "routine", "specialty": "Primary care"}),
        (ctx.at(d(-11), 18, 40), U_MAYA, "patient", "intake-agent/claude", model, "triage", "conversation", None, P_MAYA,
         {"intent": "results", "urgency": "routine", "specialty": None}),
        (ctx.at(d(-9), 7, 55), U_PARK, "patient", "safety/red-flags", None, "safety_check_requested", "conversation",
         None, P_PARK, {"topic": "headache", "ruleset": "2026.09-demo"}),
        (ctx.at(d(-9), 7, 56), U_PARK, "patient", "intake-agent/claude+fallback", "claude-opus-4-8", "triage",
         "conversation", None, P_PARK, {"intent": "symptom", "urgency": "routine", "specialty": "Neurology"}),
        (ctx.at(d(-6), 21, 5), U_PARK, "patient", "intake-agent/rules", None, "triage", "conversation", None, P_PARK,
         {"intent": "symptom", "urgency": "routine", "specialty": "Dermatology"}),
        (ctx.at(d(-4), 8, 12), U_MAYA, "patient", "safety/red-flags", None, "safety_check_requested", "conversation",
         None, P_MAYA, {"topic": "chest", "ruleset": "2026.09-demo"}),
        (ctx.at(d(-4), 8, 13), U_MAYA, "patient", "safety/red-flags", None, "safety_check_answered", "conversation",
         None, P_MAYA, {"topic": "chest", "answer": ["none"], "level": "none"}),
        (ctx.at(d(-4), 8, 14), U_MAYA, "patient", "intake-agent/rules", None, "triage", "conversation", None, P_MAYA,
         {"intent": "symptom", "urgency": "routine", "specialty": "Cardiology"}),
        (ctx.at(d(-2), 8, 30), None, "system", "results-agent/rules", None, "explanation_drafted", "result_explanation",
         expl_id, P_MAYA, {"report_id": str(report_id) if report_id else None}),
        (ctx.at(d(-2), 9, 5), U_OKAFOR, "clinician", "doctor-agent/rules", None, "brief_viewed", "patient", P_MAYA,
         P_MAYA, {}),
        (ctx.at(d(-1), 12, 0), U_OKAFOR, "clinician", None, None, "review_approve", "result_explanation", expl_id,
         P_MAYA, {"kind": "result_explanation", "edited": False}),
        (ctx.at(d(-1), 12, 2), U_OKAFOR, "clinician", None, None, "report_viewed", "diagnostic_report", report_id,
         P_MAYA, {}),
        (ctx.at(d(-1), 16, 20), U_PARK, "patient", "intake-agent/claude", model, "triage", "conversation", None, P_PARK,
         {"intent": "find_care", "urgency": "routine", "specialty": "Dermatology"}),
    ]
    for when, actor, role, agent, mdl, action, etype, eid, patient, detail in events:
        conn.execute(
            """
            INSERT INTO audit_events (occurred_at, actor_user_id, actor_role, agent, model, action, entity_type,
                                      entity_id, patient_id, detail)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (when, actor, role, agent, mdl, action, etype, eid, patient,
             json.dumps({**detail, "seed": "s080", "demo": True})),
        )
