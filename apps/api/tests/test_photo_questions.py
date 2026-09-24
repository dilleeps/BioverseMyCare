"""Photo questions: image validation, medicine matching (vision and typed name), the skin safety checklist,
consented storage with a review item, the report hand-off, front-door intents, access control and audit."""

import base64
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse import consent
from bioverse.agents import llm
from bioverse.photo_medicines import drug_code_for, norm_strength
from bioverse.routers.photo_questions import MedicineLabel, ReportText
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, PARK

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def ask(client, headers=MAYA, **body):
    body.setdefault("image", b64(JPEG))
    body.setdefault("media_type", "image/jpeg")
    return client.post("/api/photo-questions", headers=headers, json=body)


@pytest.fixture
def fake_claude(monkeypatch):
    """A fake client returning whatever `state["output"]` holds; records every call."""
    state = {"output": None, "calls": []}

    def parse(**kwargs):
        state["calls"].append(kwargs)
        out = state["output"]
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(stop_reason="end_turn", stop_details=None, model="test-model",
                               usage=SimpleNamespace(iterations=None), parsed_output=out)

    monkeypatch.setattr(llm, "ai_enabled", lambda: True)
    llm.set_client(SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse))))
    yield state
    llm.set_client(None)


def audit_actions(action: str) -> list[dict]:
    with db() as conn:
        return conn.execute(
            "SELECT action, agent, patient_id::text, detail FROM audit_events WHERE action = %s ORDER BY id", (action,)
        ).fetchall()


# --- Image validation ---------------------------------------------------------------------------


def test_heic_is_refused_with_a_clear_message(client):
    r = ask(client, kind="medicine", image=b64(HEIC), media_type="image/heic")
    assert r.status_code == 415
    assert "HEIC" in r.json()["detail"] and "JPEG" in r.json()["detail"]
    # Declared as JPEG but actually HEIC: still refused as HEIC.
    r = ask(client, kind="medicine", image=b64(HEIC), media_type="image/jpeg")
    assert r.status_code == 415 and "HEIC" in r.json()["detail"]


def test_type_checks(client):
    assert ask(client, kind="medicine", media_type="application/pdf").status_code == 415
    assert ask(client, kind="medicine", media_type="image/gif").status_code == 415
    # Contents that don't match the declared type.
    assert ask(client, kind="medicine", image=b64(PNG), media_type="image/jpeg").status_code == 415
    assert ask(client, kind="medicine", image=b64(b"just some text"), media_type="image/png").status_code == 415
    assert ask(client, kind="medicine", image="not base64 !!", media_type="image/jpeg").status_code == 422
    assert ask(client, kind="medicine", image="", media_type="image/jpeg").status_code == 422
    assert ask(client, kind="xray").status_code == 422
    # A data URL prefix is accepted.
    r = ask(client, kind="report", image="data:image/png;base64," + b64(PNG), media_type="image/png")
    assert r.status_code == 200, r.text


def test_size_limit_is_5_mb_decoded(client):
    at_limit = JPEG + b"\x00" * (5 * 1024 * 1024 - len(JPEG))
    assert ask(client, kind="report", image=b64(at_limit)).status_code == 200
    over = at_limit + b"\x00"
    r = ask(client, kind="report", image=b64(over))
    assert r.status_code == 413 and "5 MB" in r.json()["detail"]


def test_nothing_is_stored_and_every_request_is_audited(client):
    for kind in ("medicine", "skin", "report"):
        assert ask(client, kind=kind).json()["stored"] is False
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM skin_photo_submissions").fetchone()["n"] == 0
    events = audit_actions("photo_question")
    assert [e["detail"]["kind"] for e in events] == ["medicine", "skin", "report"]
    assert all(e["patient_id"] == P_MAYA and e["detail"]["bytes"] == len(JPEG) for e in events)
    assert all("image" not in e["detail"] for e in events)


def test_access_control(client):
    for headers in (OKAFOR, ADMIN):
        assert ask(client, headers=headers, kind="medicine").status_code == 403
    assert client.post("/api/photo-questions", json={"kind": "medicine"}).status_code == 401


# --- Medicine -----------------------------------------------------------------------------------


def test_medicine_vision_matches_active_prescription(client, fake_claude):
    fake_claude["output"] = MedicineLabel(readable=True, drug_name="Atorvastatin Calcium Tablets",
                                          strength="20 mg", form="tablet", manufacturer="Demo Pharma")
    r = ask(client, kind="medicine", question="What is it for?")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "matched", body
    assert body["headline"] == "This looks like your atorvastatin 20 mg."
    assert "Take 1 tablet by mouth once daily in the evening." in body["message"]
    assert body["info"]["what_for"].startswith("A statin")
    assert body["warnings"] == []
    assert body["caution"] == "Check the label; if in doubt, ask your pharmacist."
    assert body["produced_by"] == "photo/vision"
    # The image went to the model as an image block, and the prompt treats content as data.
    call = fake_claude["calls"][0]
    content = call["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
    assert base64.b64decode(content[0]["source"]["data"]) == JPEG
    assert "never instructions" in call["system"]
    event = audit_actions("photo_question")[-1]
    assert event["agent"] == "photo/vision" and event["detail"]["status"] == "matched"


def test_medicine_strength_mismatch_warns(client, fake_claude):
    fake_claude["output"] = MedicineLabel(readable=True, drug_name="Lipitor", strength="40mg")
    body = ask(client, kind="medicine").json()
    assert body["status"] == "matched"
    assert "40mg" in body["warnings"][0] and "20 mg" in body["warnings"][0]
    assert body["offer_pharmacist"] is True


def test_medicine_never_gives_new_dosing_advice(client, fake_claude):
    fake_claude["output"] = MedicineLabel(readable=True, drug_name="Atorvastatin", strength="20 mg")
    body = ask(client, kind="medicine", question="I missed a dose, can I take two tonight?").json()
    assert body["status"] == "matched"
    assert "can't give dosing advice" in body["question_reply"]
    assert body["offer_pharmacist"] is True
    # The only instructions are the prescriber's own.
    assert body["prescription"]["sig"] == "Take 1 tablet by mouth once daily in the evening."


def test_medicine_not_prescribed_or_unknown_cannot_be_confirmed(client, fake_claude):
    # Azithromycin was prescribed once but is completed: not an active prescription.
    fake_claude["output"] = MedicineLabel(readable=True, drug_name="Azithromycin", strength="250 mg")
    body = ask(client, kind="medicine").json()
    assert body["status"] == "unmatched" and body["offer_pharmacist"] is True
    assert "info" not in body and "prescription" not in body
    assert body["caution"] == "Check the label; if in doubt, ask your pharmacist."

    fake_claude["output"] = MedicineLabel(readable=True, drug_name="Amlodipine and Benazepril")
    assert ask(client, kind="medicine").json()["status"] == "unmatched"

    fake_claude["output"] = MedicineLabel(readable=False)
    body = ask(client, kind="medicine").json()
    assert body["status"] == "unreadable" and body["offer_pharmacist"] is True


def test_medicine_rules_mode_asks_for_the_name_then_matches_text(client):
    body = ask(client, kind="medicine").json()
    assert body["status"] == "needs_name" and body["produced_by"] == "photo/rules"
    # The typed name needs no image.
    r = client.post("/api/photo-questions", headers=MAYA, json={"kind": "medicine", "typed_name": "atorvastatin 20mg"})
    body = r.json()
    assert r.status_code == 200 and body["status"] == "matched", body
    assert body["produced_by"] == "photo/typed-name"
    r = client.post("/api/photo-questions", headers=MAYA, json={"kind": "medicine", "typed_name": "atorvastatine"})
    assert r.json()["status"] == "unmatched"   # near misses are never matched


def test_medicine_ai_consent_denied_uses_rules(client, fake_claude):
    fake_claude["output"] = MedicineLabel(readable=True, drug_name="Atorvastatin")
    with db() as conn:
        consent.set_status(conn, patient_id=P_MAYA, scope="ai_processing", status="denied", actor=None)
    body = ask(client, kind="medicine").json()
    assert body["status"] == "needs_name"
    assert fake_claude["calls"] == []
    assert audit_actions("photo_question")[-1]["detail"]["ai_consent"] is False


def test_medicine_llm_failure_falls_back(client, fake_claude):
    fake_claude["output"] = llm.LLMUnavailable("refusal")
    body = ask(client, kind="medicine").json()
    assert body["status"] == "needs_name"
    assert audit_actions("ai_fallback")[-1]["detail"]["reason"] == "refusal"


def test_name_matching_rules():
    assert drug_code_for("ATORVASTATIN CALCIUM 20 MG") == "atorvastatin"
    assert drug_code_for("Norvasc") == "amlodipine"
    assert drug_code_for("my lipitor pills") == "atorvastatin"
    assert drug_code_for("atorvastatin and ezetimibe") is None
    assert drug_code_for("hydroxyzine") is None
    assert norm_strength("20 MG") == norm_strength("20mg") == "20mg"
    assert norm_strength("2.50 mg") == "2.5mg"


# --- Skin ---------------------------------------------------------------------------------------


def test_skin_asks_the_checklist_first(client):
    body = ask(client, kind="skin", question="An itchy patch on my arm").json()
    assert body["status"] == "checklist"
    ids = [o["id"] for o in body["checklist"]["options"]]
    assert {"face_swelling_breathing", "spreading_redness", "fever", "severe_pain", "bleeding", "mole_change"} == set(ids)


def test_skin_emergency_checklist_follows_red_flag_guidance(client):
    body = ask(client, kind="skin", checklist=["face_swelling_breathing"]).json()
    assert body["status"] == "emergency"
    assert "Please call 911 now" in body["message"] and body["emergency_number"] == "911"
    assert "send_to_care_team" not in body and "book_dermatology" not in body
    # Spreading redness with fever is also an emergency; either alone is urgent.
    assert ask(client, kind="skin", checklist=["spreading_redness", "fever"]).json()["status"] == "emergency"
    assert ask(client, kind="skin", checklist=["spreading_redness"]).json()["status"] == "urgent"
    # An unknown answer counts as positive.
    assert ask(client, kind="skin", checklist=["something_else"]).json()["status"] == "emergency"
    with db() as conn:
        items = conn.execute(
            "SELECT kind, priority FROM review_items WHERE patient_id = %s AND kind = 'red_flag' AND title LIKE 'Red flag · Swelling%%'",
            (P_MAYA,),
        ).fetchall()
    assert items and items[0]["priority"] == "urgent"
    assert audit_actions("red_flag_escalation")[0]["agent"] == "photo/skin-checklist"


def test_free_text_red_flags_come_first_for_every_kind(client, fake_claude):
    fake_claude["output"] = MedicineLabel(readable=True, drug_name="Atorvastatin")
    body = ask(client, kind="medicine", question="I think I took too many pills").json()
    assert body["status"] == "emergency" and fake_claude["calls"] == []
    body = ask(client, kind="skin", question="rash and my throat is swelling", checklist=["none"]).json()
    assert body["status"] == "emergency"


def test_skin_routine_offers_send_or_book_and_stores_nothing(client):
    body = ask(client, kind="skin", checklist=["none"]).json()
    assert body["status"] == "routine"
    assert body["send_to_care_team"] is True
    assert body["book_dermatology"] == "/care/find?specialty=Dermatology"
    assert body["care_team_phone"] == "(555) 010-2400"
    assert "diagnos" not in body["message"].lower() or "won't" in body["message"]
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM skin_photo_submissions").fetchone()["n"] == 0


def submit(client, headers=MAYA, **body):
    body.setdefault("image", b64(JPEG))
    body.setdefault("media_type", "image/jpeg")
    body.setdefault("checklist", ["none"])
    body.setdefault("consent", True)
    return client.post("/api/photo-questions/skin/submissions", headers=headers, json=body)


def test_skin_submission_needs_explicit_consent(client):
    assert submit(client, consent=False).status_code == 422
    r = client.post("/api/photo-questions/skin/submissions", headers=MAYA,
                    json={"image": b64(JPEG), "media_type": "image/jpeg", "checklist": ["none"]})
    assert r.status_code == 422
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM skin_photo_submissions").fetchone()["n"] == 0


def test_skin_submission_is_stored_with_review_item_and_clinician_view(client):
    r = submit(client, note="Dry patch on my elbow for two weeks", checklist=["mole_change"])
    assert r.status_code == 201, r.text
    sent = r.json()
    assert sent["stored"] is True and sent["status"] == "sent"
    sub_id = sent["submission_id"]

    with db() as conn:
        row = conn.execute("SELECT * FROM skin_photo_submissions WHERE id = %s", (sub_id,)).fetchone()
        item = conn.execute("SELECT * FROM review_items WHERE id = %s", (row["review_item_id"],)).fetchone()
    assert bytes(row["image"]) == JPEG and row["level"] == "urgent" and row["checklist"] == ["mole_change"]
    assert item["kind"] == "skin_photo" and item["link"] == f"/clinician/skin-photos/{sub_id}"
    assert item["priority"] == "urgent" and item["ref_id"] is not None

    queue = client.get("/api/clinician/review-queue", headers=OKAFOR).json()
    assert any(q["kind"] == "skin_photo" and q["link"] == f"/clinician/skin-photos/{sub_id}" for q in queue)

    detail = client.get(f"/api/photo-questions/skin/{sub_id}", headers=OKAFOR).json()
    assert detail["note"] == "Dry patch on my elbow for two weeks"
    assert detail["checklist_labels"] == ["A mole that is changing size, shape or color"]
    img = client.get(f"/api/photo-questions/skin/{sub_id}/image", headers=OKAFOR)
    assert img.status_code == 200 and img.content == JPEG and img.headers["content-type"] == "image/jpeg"
    assert img.headers["cache-control"] == "no-store"

    # Reply and resolve.
    r = client.post(f"/api/photo-questions/skin/{sub_id}/reply", headers=OKAFOR,
                    json={"text": "Thanks for sending this. Please book a dermatology visit this week."})
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    with db() as conn:
        item = conn.execute("SELECT status, resolution FROM review_items WHERE id = %s", (item["id"],)).fetchone()
        note = conn.execute(
            "SELECT n.link FROM notifications n JOIN patients p ON p.user_id = n.user_id "
            "WHERE p.id = %s AND n.kind = 'skin_photo_reply'", (P_MAYA,)
        ).fetchone()
    assert item["status"] == "resolved" and item["resolution"].startswith("reply: Thanks")
    assert note["link"] == "/ask/photo?view=sent"
    assert client.post(f"/api/photo-questions/skin/{sub_id}/resolve", headers=OKAFOR, json={}).status_code == 409

    # The patient sees the reply on their own list.
    mine = client.get("/api/photo-questions/skin", headers=MAYA).json()
    assert mine[0]["reply"].startswith("Thanks for sending") and mine[0]["replied_by_name"] == "Dr. Adaeze Okafor"

    actions = [a for a in ("skin_photo_submitted", "skin_photo_viewed", "skin_photo_image_viewed", "skin_photo_replied")]
    for action in actions:
        assert audit_actions(action), action


def test_skin_submission_refused_past_an_emergency(client):
    body = submit(client, checklist=["face_swelling_breathing"]).json()
    assert body["status"] == "emergency" and body["stored"] is False
    body = submit(client, note="my lips are blue").json()
    assert body["status"] == "emergency" and body["stored"] is False
    with db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM skin_photo_submissions").fetchone()["n"] == 0


def test_skin_photo_access_control(client):
    sub_id = submit(client).json()["submission_id"]
    assert client.get(f"/api/photo-questions/skin/{sub_id}", headers=PARK).status_code == 403
    assert client.get(f"/api/photo-questions/skin/{sub_id}/image", headers=PARK).status_code == 403
    assert client.get(f"/api/photo-questions/skin/{sub_id}", headers=ADMIN).status_code == 403
    assert client.get("/api/photo-questions/skin", headers=ADMIN).status_code == 403
    assert client.get(f"/api/photo-questions/skin/{sub_id}", headers=MAYA).status_code == 200
    assert client.get("/api/photo-questions/skin/not-a-uuid", headers=MAYA).status_code == 404
    # Only clinicians reply or resolve.
    assert client.post(f"/api/photo-questions/skin/{sub_id}/reply", headers=MAYA, json={"text": "hi"}).status_code == 403
    assert client.post(f"/api/photo-questions/skin/{sub_id}/resolve", headers=MAYA, json={}).status_code == 403
    assert client.get("/api/photo-questions/skin", headers=PARK).json() == []
    assert len(client.get("/api/photo-questions/skin", headers=OKAFOR).json()) == 1
    # Acknowledging from the core queue is refused: it is decided in its own screen.
    with db() as conn:
        item_id = conn.execute("SELECT review_item_id::text AS id FROM skin_photo_submissions").fetchone()["id"]
    r = client.post(f"/api/clinician/review-items/{item_id}/resolve", headers=OKAFOR, json={"action": "acknowledge"})
    assert r.status_code == 409


# --- Report -------------------------------------------------------------------------------------


def test_report_rules_mode_links_to_records(client):
    body = ask(client, kind="report").json()
    assert body["status"] == "report_link" and body["to"] == "/records"


def test_report_vision_transcribes_for_the_records_upload(client, fake_claude, monkeypatch):
    fake_claude["output"] = ReportText(is_lab_report=True, text="Riverside Diagnostics\nLDL Cholesterol 148 mg/dL (0-99) H")
    body = ask(client, kind="report").json()
    assert body["status"] == "report_text" and "LDL Cholesterol 148" in body["text"]
    assert body["to"] == "/records"
    # The hand-off: the web client sends the text to the documents module, where the patient confirms it.
    monkeypatch.setattr(llm, "ai_enabled", lambda: False)
    r = client.post("/api/documents/text", headers=MAYA, json={"text": body["text"]})
    assert r.status_code == 201 and r.json()["extraction"]["results"]
    monkeypatch.setattr(llm, "ai_enabled", lambda: True)
    fake_claude["output"] = ReportText(is_lab_report=False, text="")
    assert ask(client, kind="report").json()["status"] == "not_a_report"


# --- Front-door intents -------------------------------------------------------------------------


def converse(client, text):
    cid = client.post("/api/conversations", headers=MAYA).json()["id"]
    r = client.post(f"/api/conversations/{cid}/messages", headers=MAYA, json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()["messages"][-1]["payload"]


@pytest.mark.parametrize("text,to", [
    ("What is this pill?", "/ask/photo?kind=medicine"),
    ("what are these tablets I found in my bag", "/ask/photo?kind=medicine"),
    ("Can I send a photo of my rash?", "/ask/photo?kind=skin"),
    ("I'd like to send a picture of a mole", "/ask/photo?kind=skin"),
])
def test_photo_intents_route_to_the_photo_screen(client, text, to):
    payload = converse(client, text)
    assert payload["kind"] == "link" and payload["to"] == to


@pytest.mark.parametrize("text", [
    "photo of a rash, my throat is swelling",
    "rash with difficulty breathing",
    "I took too many pills, what is this pill",
])
def test_red_flag_screen_runs_before_photo_intents(client, text):
    assert converse(client, text)["kind"] == "emergency"


@pytest.mark.parametrize("text", [
    "I have an itchy rash",
    "photo of my rash, it's spreading and I have a fever",
    "what is this pill, I have chest pain",
])
def test_symptom_messages_are_not_stolen(client, text):
    assert converse(client, text)["kind"] in ("care_options", "safety_check", "question")


@pytest.mark.parametrize("text", ["rash with trouble breathing", "photo of my rash and my lips are swelling"])
def test_warning_sign_words_never_route_to_a_camera(client, text):
    payload = converse(client, text)
    assert not (payload.get("to") or "").startswith("/ask/photo")
