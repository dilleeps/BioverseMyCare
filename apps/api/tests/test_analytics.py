"""Analytics: organization trends and leakage for admins; a clinician's own panel for clinicians."""

import uuid
from datetime import timedelta

import psycopg

from bioverse.agents import hospital_agent as ha
from bioverse.db.seed import DR_RAMAN, ORG, P_MAYA, PLAN
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_PARK


def org_analytics(client):
    r = client.get("/api/analytics/organization", headers=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()


def panel(client):
    r = client.get("/api/analytics/clinician", headers=OKAFOR)
    assert r.status_code == 200, r.text
    return r.json()


def test_access_by_role(client):
    assert client.get("/api/analytics/organization").status_code == 401
    assert client.get("/api/analytics/organization", headers=OKAFOR).status_code == 403
    assert client.get("/api/analytics/organization", headers=MAYA).status_code == 403
    assert client.get("/api/analytics/clinician", headers=ADMIN).status_code == 403
    assert client.get("/api/analytics/clinician", headers=MAYA).status_code == 403


# --- Organization ----------------------------------------------------------------------------------------


def test_weekly_trends_add_up_to_the_intake_table(client):
    trends = org_analytics(client)["trends"]
    weeks = trends["weeks"]
    assert len(weeks) == 13
    clk = ha.clock()
    start, end = clk.tomorrow_start - timedelta(days=91), clk.tomorrow_start
    with psycopg.connect(DB) as conn:
        n, emergencies = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE urgency = 'emergency') FROM intakes WHERE created_at >= %s AND created_at < %s",
            (start, end),
        ).fetchone()
        bookings = conn.execute(
            "SELECT count(*) FROM appointments WHERE status <> 'cancelled' AND created_at >= %s AND created_at < %s",
            (start, end),
        ).fetchone()[0]
        median = conn.execute(
            """
            SELECT round((percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch from resolved_at - created_at) / 3600))::numeric, 1)
            FROM review_items WHERE status = 'resolved' AND resolved_at >= %s AND resolved_at < %s
            """,
            (start, end),
        ).fetchone()[0]
    totals = trends["totals"]
    assert totals["intakes"] == n == sum(w["intakes"] for w in weeks)
    assert sum(sum(w["by_specialty"].values()) for w in weeks) == n
    assert sum(totals["urgency_mix"].values()) == n
    assert totals["escalations"] == emergencies
    assert totals["escalation_rate_pct"] == round(100 * emergencies / n, 1)
    assert totals["bookings"] == bookings
    assert totals["review_turnaround_median_hours"] == float(median)
    assert trends["specialties"][0] == "Dermatology", "most intakes over the period"
    assert weeks[-1]["end"] == clk.today.isoformat()
    # The seeded story: Dermatology demand climbs in the latest week.
    assert weeks[-1]["by_specialty"]["Dermatology"] > weeks[0]["by_specialty"]["Dermatology"]


def test_new_intake_lands_in_the_current_week(client):
    before = org_analytics(client)["trends"]["weeks"][-1]
    cid = client.post("/api/conversations", headers=MAYA).json()["id"]
    client.post(f"/api/conversations/{cid}/messages", headers=MAYA, json={"text": "I have an itchy rash on my arm"})
    after = org_analytics(client)["trends"]["weeks"][-1]
    assert after["intakes"] == before["intakes"] + 1
    assert after["by_specialty"]["Dermatology"] == before["by_specialty"]["Dermatology"] + 1


def test_referral_leakage_counts_routed_intakes_without_a_booking(client):
    before = org_analytics(client)["leakage"]
    assert before["eligible"] > 0
    assert before["rate_pct"] == round(100 * before["leaked"] / before["eligible"], 1)

    intake_id = str(uuid.uuid4())
    with psycopg.connect(DB) as conn:
        conn.execute(
            """
            INSERT INTO intakes (id, patient_id, chief_complaint, urgency, specialty, patient_summary, clinician_summary,
                                 status, produced_by, created_at)
            VALUES (%s, %s, 'Numb fingers', 'routine', 'Neurology', 's', 's', 'routed', 'test', now() - interval '20 days')
            """,
            (intake_id, P_PARK),
        )
    mid = org_analytics(client)["leakage"]
    assert (mid["eligible"], mid["leaked"]) == (before["eligible"] + 1, before["leaked"] + 1)

    # Booked 3 days after the intake: no longer leaked.
    with psycopg.connect(DB) as conn:
        slot = conn.execute(
            """
            INSERT INTO slots (practitioner_id, starts_at, status)
            SELECT id, now() - interval '10 days' + interval '7 minutes', 'booked' FROM practitioners WHERE specialty = 'Neurology' LIMIT 1
            RETURNING id, practitioner_id
            """
        ).fetchone()
        conn.execute(
            """
            INSERT INTO appointments (patient_id, practitioner_id, slot_id, intake_id, status, created_at)
            VALUES (%s, %s, %s, %s, 'fulfilled', now() - interval '17 days')
            """,
            (P_PARK, slot[1], slot[0], intake_id),
        )
    after = org_analytics(client)["leakage"]
    assert (after["eligible"], after["leaked"]) == (before["eligible"] + 1, before["leaked"])
    neuro = next(r for r in after["by_specialty"] if r["specialty"] == "Neurology")
    assert neuro["rate_pct"] == round(100 * neuro["leaked"] / neuro["eligible"], 1)


# --- Clinician panel ----------------------------------------------------------------------------------------


def test_clinician_panel_known_values(client):
    data = panel(client)
    s = data["summary"]
    by_name = {p["name"]: p for p in data["patients"]}
    # Maya: blood test done (due 2 days ago), statin due today not done.
    assert (by_name["Maya Thornton"]["tasks_due"], by_name["Maya Thornton"]["tasks_done"]) == (2, 1)
    # Seeded panel plans: Sofia 2 of 3 due tasks done, Tomas 2 of 3.
    assert (by_name["Sofia Delgado"]["tasks_due"], by_name["Sofia Delgado"]["tasks_done"]) == (3, 2)
    assert (by_name["Tomas Varga"]["tasks_due"], by_name["Tomas Varga"]["tasks_done"]) == (3, 2)
    assert s["tasks_due"] == sum(p["tasks_due"] for p in data["patients"])
    assert s["adherence_pct"] == round(100 * s["tasks_done"] / s["tasks_due"], 1)
    assert {t["title"] for t in data["overdue_tasks"]} >= {"Check in about side effects", "Kidney function blood test"}
    assert s["overdue_tasks"] == len(data["overdue_tasks"])
    # Park's HbA1c awaits review; Tomas's potassium has no explanation at all.
    unexplained = {(r["patient_name"], r["explanation_status"]) for r in data["unexplained_results"]}
    assert unexplained >= {("Jun Park", "pending_review"), ("Tomas Varga", "none")}
    assert "Maya Thornton" not in {r["patient_name"] for r in data["unexplained_results"]}
    gaps = {(g["patient_name"], g["title"]) for g in data["care_gaps"]}
    assert ("Maya Thornton", "Blood pressure check overdue") in gaps


def test_panel_moves_when_the_record_changes(client):
    before = panel(client)["summary"]
    plan = client.get(f"/api/patients/{P_MAYA}/care-plan", headers=MAYA).json()
    med = next(t for t in plan["tasks"] if t["kind"] == "medication")
    client.patch(f"/api/care-plan-tasks/{med['id']}", headers=MAYA, json={"status": "done"})

    item = next(i for i in client.get("/api/clinician/review-queue", headers=OKAFOR).json() if i["kind"] == "result_explanation")
    client.post(f"/api/clinician/review-items/{item['id']}/resolve", headers=OKAFOR, json={"action": "approve"})

    after = panel(client)["summary"]
    assert after["tasks_done"] == before["tasks_done"] + 1
    assert after["tasks_due"] == before["tasks_due"]
    assert after["unexplained_abnormal_results"] == before["unexplained_abnormal_results"] - 1


def test_panel_only_includes_own_patients_and_is_audited(client):
    stranger = str(uuid.uuid4())
    with psycopg.connect(DB) as conn:
        conn.execute(
            "INSERT INTO patients (id, organization_id, name, birth_date, insurance_plan) VALUES (%s, %s, 'Quinn Arlo', '1980-01-01', %s)",
            (stranger, ORG, PLAN),
        )
        conn.execute("INSERT INTO care_plans (patient_id, practitioner_id, title) VALUES (%s, %s, 'Other clinician')",
                     (stranger, DR_RAMAN))
    data = panel(client)
    assert stranger not in {p["id"] for p in data["patients"]}
    assert data["summary"]["patients"] == len(data["patients"])
    with psycopg.connect(DB) as conn:
        audited = {r[0] for r in conn.execute(
            "SELECT patient_id::text FROM audit_events WHERE action = 'panel_analytics_viewed'").fetchall()}
    assert audited == {p["id"] for p in data["patients"]}
