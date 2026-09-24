"""Doctor Agent runtime: escalation rules, approved content, pre-visit interview, follow-up check-ins."""

import json

import psycopg
from bioverse.db.seed import DR_OKAFOR, P_HADDAD, U_FRONTDESK, U_HADDAD
from bioverse.db.seeds.ids import _id
from tests.conftest import DB, MAYA, OKAFOR, P_MAYA, PARK, as_user

HADDAD = as_user(U_HADDAD)
FRONTDESK = as_user(U_FRONTDESK)
AGENT_LABEL = "Dr. Okafor's assistant (automated)"
T_MAYA_FOLLOWUP = _id(3110)


def sql(query, *params):
    with psycopg.connect(DB) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else None


def set_rule(rule_id, **changes):
    rules = sql("SELECT escalation_rules FROM doctor_agent_configs WHERE practitioner_id = %s", DR_OKAFOR)[0][0]
    for r in rules:
        if r["id"] == rule_id:
            r.update(changes)
    sql("UPDATE doctor_agent_configs SET escalation_rules = %s WHERE practitioner_id = %s", json.dumps(rules), DR_OKAFOR)


def set_approval(req_id, required):
    reqs = sql("SELECT approval_requirements FROM doctor_agent_configs WHERE practitioner_id = %s", DR_OKAFOR)[0][0]
    for r in reqs:
        if r["id"] == req_id:
            r["required"] = required
    sql("UPDATE doctor_agent_configs SET approval_requirements = %s WHERE practitioner_id = %s", json.dumps(reqs), DR_OKAFOR)


def new_thread(client, text, headers=MAYA):
    r = client.post("/api/messages/threads", headers=headers, json={"body": text})
    assert r.status_code == 201, r.text
    return r.json()


def say(client, thread_id, text, headers=MAYA):
    r = client.post(f"/api/messages/threads/{thread_id}/messages", headers=headers, json={"body": text})
    assert r.status_code == 200, r.text
    return r.json()


def items_for(client, thread_id):
    """Open review items that point at this thread."""
    queue = client.get("/api/clinician/review-queue", headers=OKAFOR).json()
    return [i for i in queue if i["link"] == f"/clinician/inbox?thread={thread_id}"]


# ---------------------------------------------------------------------------------------------
# Side effects: approved content only
# ---------------------------------------------------------------------------------------------


def test_side_effect_answered_only_from_approved_content(client):
    thread = new_thread(client, "I've had some muscle aches since starting the new tablet")
    last = thread["messages"][-1]
    assert last["author_label"] == AGENT_LABEL
    assert last["automated"] is True
    assert last["payload"]["kind"] == "education"
    assert last["payload"]["title"] == "Statins and muscle aches"

    library = {c["id"]: c["body"] for c in client.get("/api/doctor-agent/content", headers=OKAFOR).json()}
    for cid in last["payload"]["content_ids"]:
        assert library[cid] in last["body"], "the agent quotes approved content verbatim"
    assert items_for(client, thread["id"]) == [], "no escalation when approved content answered it"


def test_side_effect_without_matching_content_escalates(client):
    set_rule("side_effect", route_to="clinician")
    thread = new_thread(client, "I've had a rash since starting the new tablet")
    last = thread["messages"][-1]
    assert last["payload"]["kind"] == "handoff"
    assert last["payload"]["to"] == "clinician"
    assert "education" not in [m["payload"]["kind"] for m in thread["messages"] if m["payload"]]
    assert [i["kind"] for i in items_for(client, thread["id"])] == ["agent_escalation"]


def test_side_effect_unresolved_goes_to_staff_by_default(client):
    # Dr. Okafor's seeded rule: answer from approved content, else staff.
    thread = new_thread(client, "I've had a rash since starting the new tablet")
    assert thread["messages"][-1]["payload"]["to"] == "nurse_triage"
    staff_inbox = {t["id"] for t in client.get("/api/messages/threads", headers=FRONTDESK).json()}
    assert thread["id"] in staff_inbox


def test_content_needing_approval_is_held_for_the_clinician(client):
    set_approval("routine_education", True)
    thread = new_thread(client, "I've had some muscle aches since starting the new tablet")
    kinds = [m["payload"]["kind"] for m in thread["messages"] if m["payload"]]
    assert "education" not in kinds
    assert thread["messages"][-1]["payload"]["to"] == "clinician_approval"
    assert [i["kind"] for i in items_for(client, thread["id"])] == ["doctor_agent_approval"]

    clinician = client.get(f"/api/messages/threads/{thread['id']}", headers=OKAFOR).json()
    (draft,) = clinician["drafts"]
    assert draft["source"] == "agent_pending_approval"
    assert "Statins and muscle aches" not in str(client.get(f"/api/messages/threads/{thread['id']}", headers=MAYA).json())
    assert draft["body"] not in str(client.get(f"/api/messages/threads/{thread['id']}", headers=MAYA).json())


def test_follow_up_after_education_escalates_as_unresolved(client):
    set_rule("side_effect", route_to="clinician")
    thread = new_thread(client, "I've had some muscle aches since starting the new tablet")
    thread = say(client, thread["id"], "The aches are still there and my legs feel weak")
    assert thread["messages"][-1]["payload"]["kind"] == "handoff"
    assert [i["kind"] for i in items_for(client, thread["id"])] == ["agent_escalation"]


# ---------------------------------------------------------------------------------------------
# New symptoms, logistics, out of scope
# ---------------------------------------------------------------------------------------------


def test_new_symptom_gathers_two_answers_then_escalates(client):
    thread = new_thread(client, "I've had a cough for a few days")
    assert thread["messages"][-1]["payload"] == {"kind": "clarifying_question", "n": 1}
    thread = say(client, thread["id"], "Since Monday, about the same")
    assert thread["messages"][-1]["payload"] == {"kind": "clarifying_question", "n": 2}
    thread = say(client, thread["id"], "Maybe a 3, worse at night")
    assert thread["messages"][-1]["payload"]["kind"] == "handoff"

    (item,) = items_for(client, thread["id"])
    assert item["kind"] == "agent_escalation"
    assert item["priority"] == "urgent", "Dr. Okafor routes new symptoms to herself, same day"
    assert "Since Monday" in item["body"] and "worse at night" in item["body"]
    questions = [m for m in thread["messages"] if (m["payload"] or {}).get("kind") == "clarifying_question"]
    assert len(questions) == 2


def test_escalate_immediately_rule(client):
    set_rule("new_symptom", action="escalate_immediately", route_to="nurse_triage")
    thread = new_thread(client, "I've had a cough for a few days")
    assert [m["author_kind"] for m in thread["messages"]] == ["patient", "agent"]
    assert thread["messages"][-1]["payload"]["to"] == "nurse_triage"


def test_red_flag_during_gathering_stops_routine_flow(client):
    thread = new_thread(client, "I've had a cough for a few days")
    thread = say(client, thread["id"], "Now I'm coughing up blood")
    assert thread["messages"][-1]["payload"]["kind"] == "emergency"
    assert [i["kind"] for i in items_for(client, thread["id"])] == ["red_flag"]
    state = sql("SELECT agent_state FROM communication_threads WHERE id = %s", thread["id"])[0][0]
    assert "gathering" not in state, "routine gathering does not resume after an emergency"
    thread = say(client, thread["id"], "It's calmer now")
    assert (thread["messages"][-1]["payload"] or {}).get("kind") != "clarifying_question"


def test_logistics_routes_to_front_desk(client):
    thread = new_thread(client, "Can I reschedule my appointment to next week?")
    assert thread["messages"][-1]["payload"] == {"kind": "handoff", "to": "front_desk"}
    staff = client.get("/api/messages/threads", headers=FRONTDESK).json()
    mine = next(t for t in staff if t["id"] == thread["id"])
    assert mine["assigned_to"] == "front_desk"
    assert mine["category"] == "logistics"
    assert client.post(f"/api/messages/threads/{thread['id']}/messages", headers=FRONTDESK,
                       json={"body": "Hi Maya, which day suits you?"}).status_code == 200
    assert items_for(client, thread["id"]) == []


def test_out_of_scope_question_escalates_to_clinician(client):
    thread = new_thread(client, "Should I take my atorvastatin in the morning or evening?")
    assert thread["messages"][-1]["payload"]["to"] == "clinician"
    assert [i["kind"] for i in items_for(client, thread["id"])] == ["agent_escalation"]


def test_inactive_agent_sends_nothing_automated(client):
    sql("UPDATE doctor_agent_configs SET active = false WHERE practitioner_id = %s", DR_OKAFOR)
    thread = new_thread(client, "Can I reschedule my appointment to next week?")
    assert [m["author_kind"] for m in thread["messages"]] == ["patient"]
    staff = {t["id"] for t in client.get("/api/messages/threads", headers=FRONTDESK).json()}
    assert thread["id"] in staff, "logistics still reaches the front desk without the agent"


# ---------------------------------------------------------------------------------------------
# Pre-visit interview
# ---------------------------------------------------------------------------------------------


def book_maya_with_okafor(client):
    slot = sql(
        "SELECT id::text FROM slots WHERE practitioner_id = %s AND status = 'free' AND starts_at > now() ORDER BY starts_at LIMIT 1",
        DR_OKAFOR,
    )[0][0]
    r = client.post("/api/appointments", headers=MAYA, json={"slot_id": slot})
    assert r.status_code == 201
    return r.json()["id"]


def test_previsit_answers_feed_the_brief(client):
    appt = book_maya_with_okafor(client)
    listed = client.get("/api/doctor-agent/previsit", headers=MAYA).json()
    assert [(p["appointment_id"], p["status"], p["questions"]) for p in listed] == [(appt, "not_started", 3)]

    started = client.post(f"/api/doctor-agent/previsit/{appt}/start", headers=MAYA)
    assert started.status_code == 201
    tid = started.json()["thread_id"]
    again = client.post(f"/api/doctor-agent/previsit/{appt}/start", headers=MAYA).json()
    assert again["thread_id"] == tid, "starting twice returns the same interview"

    thread = client.get(f"/api/messages/threads/{tid}", headers=MAYA).json()
    asked = [m for m in thread["messages"] if (m["payload"] or {}).get("kind") == "previsit_question"]
    assert len(asked) == 1 and asked[0]["author_label"] == AGENT_LABEL

    say(client, tid, "No chest pain, but my ankles have been swollen this week")
    say(client, tid, "Atorvastatin every evening, no missed doses")
    thread = say(client, tid, "Around 132 over 84")
    assert thread["messages"][-1]["payload"]["kind"] == "previsit_complete"
    assert "highlighted" in thread["messages"][-1]["body"]

    answers = client.get(f"/api/doctor-agent/previsit/{appt}/answers", headers=OKAFOR).json()["answers"]
    assert [a["question_id"] for a in answers] == ["q1", "q2", "q3"]
    assert [a["mentions_symptoms"] for a in answers] == [True, False, False]

    brief = client.get(f"/api/clinician/patients/{P_MAYA}/brief", headers=OKAFOR).json()
    lines = [b for b in brief["bullets"] if b["text"].startswith("Pre-visit answers")]
    assert len(lines) == 3
    assert "ankles have been swollen" in lines[0]["text"]
    assert lines[0]["source"]["type"] == "questionnaire_response"
    assert "Patient reported new symptoms" in brief["attention_flags"]

    # Answers are data, not requests: no triage escalation came out of the interview.
    assert items_for(client, tid) == []


def test_previsit_without_symptoms_raises_no_flag(client):
    appt = book_maya_with_okafor(client)
    tid = client.post(f"/api/doctor-agent/previsit/{appt}/start", headers=MAYA).json()["thread_id"]
    for text in ("No, none of those", "Atorvastatin, no missed doses", "I don't have any readings"):
        say(client, tid, text)
    brief = client.get(f"/api/clinician/patients/{P_MAYA}/brief", headers=OKAFOR).json()
    assert "Patient reported new symptoms" not in brief["attention_flags"]


def test_seeded_previsit_appears_in_rana_brief(client):
    brief = client.get(f"/api/clinician/patients/{P_HADDAD}/brief", headers=OKAFOR).json()
    assert any(b["text"].startswith("Pre-visit answers") and "dizzy" in b["text"] for b in brief["bullets"])
    assert "Patient reported new symptoms" in brief["attention_flags"]


def test_previsit_access(client):
    appt = book_maya_with_okafor(client)
    assert client.post(f"/api/doctor-agent/previsit/{appt}/start", headers=PARK).status_code == 404
    assert client.get(f"/api/doctor-agent/previsit/{appt}/answers", headers=HADDAD).status_code == 404
    assert client.post(f"/api/doctor-agent/previsit/{appt}/start", headers=FRONTDESK).status_code == 403
    assert client.post("/api/doctor-agent/previsit/not-a-uuid/start", headers=MAYA).status_code == 404
    sql("UPDATE doctor_agent_configs SET active = false WHERE practitioner_id = %s", DR_OKAFOR)
    assert client.post(f"/api/doctor-agent/previsit/{appt}/start", headers=MAYA).status_code == 409


def test_red_flag_stops_previsit_interview(client):
    appt = book_maya_with_okafor(client)
    tid = client.post(f"/api/doctor-agent/previsit/{appt}/start", headers=MAYA).json()["thread_id"]
    thread = say(client, tid, "Crushing chest pain right now and I'm sweating")
    assert thread["messages"][-1]["payload"]["kind"] == "emergency"
    thread = say(client, tid, "ok")
    assert (thread["messages"][-1]["payload"] or {}).get("kind") != "previsit_question"


# ---------------------------------------------------------------------------------------------
# Follow-up protocol
# ---------------------------------------------------------------------------------------------


def checkins(client, headers=MAYA):
    thread = client.get(f"/api/messages/threads/{T_MAYA_FOLLOWUP}", headers=headers).json()
    return [m for m in thread["messages"] if (m["payload"] or {}).get("kind") == "checkin"]


def test_day7_checkin_is_materialized_once(client):
    assert [c["payload"]["day"] for c in checkins(client)] == [1], "nothing sent before messaging is opened"

    for _ in range(2):
        client.get("/api/messages/threads", headers=MAYA)
    client.get("/api/messages/threads", headers=OKAFOR)
    assert client.post("/api/doctor-agent/followups/materialize", headers=MAYA).json() == {"sent": 0}

    sent = checkins(client)
    assert [c["payload"]["day"] for c in sent] == [1, 7]
    day7 = sent[-1]
    assert day7["author_label"] == AGENT_LABEL
    assert "muscle pain or fatigue" in day7["body"]
    steps = {r["step_day"]: r["status"] for r in client.get("/api/doctor-agent/followups", headers=MAYA).json()}
    assert steps == {1: "sent", 7: "sent", 30: "scheduled"}
    assert sql("SELECT count(*) FROM audit_events WHERE action = 'message_agent' AND agent = 'doctor-agent/rules' "
               "AND detail->>'kind' = 'checkin'") == [(1,)]


def test_clinician_inbox_also_materializes(client):
    client.get("/api/messages/threads", headers=OKAFOR)
    assert [c["payload"]["day"] for c in checkins(client, OKAFOR)] == [1, 7]


def test_checkin_reply_runs_through_the_agent(client):
    client.get("/api/messages/threads", headers=MAYA)
    thread = say(client, T_MAYA_FOLLOWUP, "A bit of muscle aching in my legs")
    assert thread["messages"][-1]["payload"]["kind"] == "education"


def test_new_plan_schedules_protocol_from_start(client):
    # A second medication task gets its own schedule; nothing is due yet on day 0.
    plan = sql("SELECT id::text FROM care_plans WHERE patient_id = %s", P_MAYA)[0][0]
    sql("""INSERT INTO care_plan_tasks (care_plan_id, position, kind, title, due_on)
           VALUES (%s, 9, 'medication', 'Start ezetimibe 10 mg', current_date)""", plan)
    sql("UPDATE care_plans SET started_at = now() WHERE id = %s", plan)
    client.get("/api/messages/threads", headers=MAYA)
    rows = sql("SELECT step_day, r.status FROM communication_requests r JOIN care_plan_tasks t ON t.id = r.task_id "
               "WHERE t.title = 'Start ezetimibe 10 mg' ORDER BY step_day")
    assert rows == [(1, "scheduled"), (7, "scheduled"), (30, "scheduled")]
    client.get("/api/messages/threads", headers=MAYA)
    assert sql("SELECT count(*) FROM communication_requests") == [(6,)]
