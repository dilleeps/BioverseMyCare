"""HL7 v2 parsing and the ORU^R01 lab import: matching refusals, review routing, and the core approval flow."""

from datetime import date
from zoneinfo import ZoneInfo

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse import hl7v2
from bioverse.db.seed import DR_LINDQVIST, DR_OKAFOR, ORG
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, P_PARK, PARK

TZ = ZoneInfo("America/New_York")


def oru(pid="PID|1||NSH-0201^^^NSH^MR||Thornton^Maya||19720309|F", control="CTL-1",
        obr="OBR|1|ORD1|ACC1|24331-1^Lipid panel^LN|||20260915071500|||||||||D301^Okafor^Adaeze^^^Dr.^^^NSH",
        obx=("OBX|1|NM|13457-7^LDL Cholesterol^LN||152|mg/dL^^UCUM|0-99|H|||F",
             "OBX|2|NM|2085-9^HDL Cholesterol^LN||60|mg/dL^^UCUM|>40|N|||F")):
    segs = [f"MSH|^~\\&|NSH-LIS|Northside Lab|BIOVERSE|NSH|20260915080000||ORU^R01^ORU_R01|{control}|P|2.5.1"]
    if pid:
        segs.append(pid)
    if obr:
        segs.append(obr)
    segs += list(obx)
    return "\r".join(segs)


def post(client, text, headers=ADMIN):
    return client.post("/api/lab-import/messages", headers=headers, json={"text": text})


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def report_count(patient_id=None):
    with db() as conn:
        if patient_id:
            return conn.execute("SELECT count(*) AS n FROM diagnostic_reports WHERE patient_id = %s", (patient_id,)).fetchone()["n"]
        return conn.execute("SELECT count(*) AS n FROM diagnostic_reports").fetchone()["n"]


# --- Parser ------------------------------------------------------------------------------------------


def test_parse_segments_fields_components_and_repeats():
    msg = hl7v2.parse(oru(pid="PID|1||12345^^^OTHER^MR~NSH-0201^^^NSH^MR||Thornton^Maya^J||19720309|F"))
    assert msg.message_type == "ORU^R01"
    assert msg.control_id == "CTL-1"
    assert msg.msh.field(1) == "|" and msg.msh.field(2) == "^~\\&"
    assert msg.msh.component(4, 1) == "Northside Lab"
    pid = msg.first("PID")
    assert len(pid.repetitions(3)) == 2
    assert pid.component(3, 1, rep=1) == "NSH-0201" and pid.component(3, 4, rep=1) == "NSH"
    assert pid.component(5, 1) == "Thornton" and pid.component(5, 3) == "J"
    groups = msg.observation_groups()
    assert len(groups) == 1 and len(groups[0].obx) == 2
    assert hl7v2.numeric_value(groups[0].obx[0]) == 152.0


def test_escape_sequences():
    d = hl7v2.Delimiters()
    assert hl7v2.unescape(r"Metabolic panel \T\ HbA1c", d) == "Metabolic panel & HbA1c"
    assert hl7v2.unescape(r"a\F\b\S\c\R\d\E\e", d) == "a|b^c~d\\e"
    assert hl7v2.unescape(r"line one\.br\line two", d) == "line one\nline two"
    assert hl7v2.unescape(r"\X41\\X42\C", d) == "ABC"
    assert hl7v2.unescape(r"\H\bold\N\ text", d) == "bold text"
    # Escaped delimiters survive splitting: the OBR-4 text keeps its '^' and '&'.
    msg = hl7v2.parse(oru(obr="OBR|1|||X1^Panel \\S\\ 2 \\T\\ more^L|||20260915"))
    assert msg.first("OBR").component(4, 2) == "Panel ^ 2 & more"


def test_custom_delimiters_and_line_endings():
    text = "MSH#*~!@#APP#Fac#R#F#20260915##ORU*R01#C9#P#2.5\nPID#1##NSH-0201***NSH*MR##Thornton*Maya##19720309\r\n" \
           "OBR#1###X*Glucose*LN###20260915\nOBX#1#NM#2345-7*Glucose*LN##99#mg/dL#70-99#N"
    msg = hl7v2.parse(text)
    assert msg.message_type == "ORU^R01"
    assert msg.first("PID").component(3, 4) == "NSH"
    assert msg.first("PID").component(5, 2) == "Maya"
    assert hl7v2.unescape("a!T!b", msg.delims) == "a@b"


@pytest.mark.parametrize(("text", "fragment"), [
    ("", "empty"),
    ("PID|1||x", "start with an MSH"),
    ("MSH|^~", "too short"),
    ("MSH|^~\\|X|Y", "MSH-2"),
    ("MSH|^~\\&|A|B\rpid|bad", "not a valid segment"),
])
def test_parse_errors(text, fragment):
    with pytest.raises(hl7v2.HL7ParseError) as exc:
        hl7v2.parse(text)
    assert fragment in str(exc.value)


def test_datatypes():
    assert hl7v2.parse_dtm("20260915071500", TZ).isoformat() == "2026-09-15T07:15:00-04:00"
    assert hl7v2.parse_dtm("202609150715-0000", TZ).utcoffset().total_seconds() == 0
    assert hl7v2.parse_dtm("20261", TZ) is None
    assert hl7v2.parse_date("19720309") == date(1972, 3, 9)
    assert hl7v2.parse_range("0-99") == (0, 99)
    assert hl7v2.parse_range("3.5 - 5.1") == (3.5, 5.1)
    assert hl7v2.parse_range("<5.7") == (None, 5.7)
    assert hl7v2.parse_range(">= 40") == (40, None)
    assert hl7v2.parse_range("negative") == (None, None)
    sn = hl7v2.parse("MSH|^~\\&|A|B|C|D|1||ORU^R01|1|P|2.5\rOBX|1|SN|x||^7.2|%\rOBX|2|SN|x||<^5|%").segments
    assert hl7v2.numeric_value(sn[1]) == 7.2
    assert hl7v2.numeric_value(sn[2]) is None, "a comparator value is not an exact number"


def test_split_multiple_messages():
    parts = hl7v2.split_messages(oru(control="A") + "\n\n" + oru(control="B"))
    assert [hl7v2.parse(p).control_id for p in parts] == ["A", "B"]


# --- Import --------------------------------------------------------------------------------------------


def test_import_creates_pending_explanation_that_core_review_approves(client):
    before = report_count(P_MAYA)
    r = post(client, oru())
    assert r.status_code == 200, r.text
    entry = r.json()["results"][0]
    assert entry["outcome"] == "accepted", entry
    assert entry["match_method"] == "identifier"
    assert entry["patient_id"] == P_MAYA and entry["reviewer"] == "Dr. Adaeze Okafor"
    assert report_count(P_MAYA) == before + 1

    report_id = entry["report_id"]
    with db() as conn:
        rep = conn.execute("SELECT source, lab_name, name, responsible_practitioner_id::text AS pr FROM diagnostic_reports WHERE id = %s",
                           (report_id,)).fetchone()
        obs = conn.execute("SELECT loinc_code, value, unit, ref_low, ref_high, interpretation FROM observations "
                           "WHERE report_id = %s ORDER BY loinc_code", (report_id,)).fetchall()
        expl = conn.execute("SELECT id::text, status, draft_text, final_text FROM result_explanations WHERE report_id = %s",
                            (report_id,)).fetchone()
        item = conn.execute("SELECT kind, ref_id::text, practitioner_id::text, link, status FROM review_items WHERE id = %s",
                            (entry["review_item_id"],)).fetchone()
    assert rep == {"source": "hl7_import", "lab_name": "Northside Lab", "name": "Lipid panel", "pr": DR_OKAFOR}
    assert [(o["loinc_code"], float(o["value"]), o["interpretation"]) for o in obs] == [
        ("13457-7", 152.0, "H"), ("2085-9", 60.0, "N")]
    assert float(obs[0]["ref_high"]) == 99 and float(obs[1]["ref_low"]) == 40
    assert expl["status"] == "pending_review" and expl["final_text"] is None
    assert "LDL Cholesterol is 152 mg/dL, above the reference range of 0 to 99" in expl["draft_text"]
    assert item == {"kind": "result_explanation", "ref_id": expl["id"], "practitioner_id": DR_OKAFOR,
                    "link": f"/results/{report_id}", "status": "open"}

    # The patient sees the values but not the draft.
    seen = client.get(f"/api/reports/{report_id}", headers=MAYA).json()
    assert seen["explanation"]["status"] == "pending_review" and seen["explanation"]["text"] is None

    # The core review flow approves it, then the patient sees the approved text.
    queue = client.get("/api/clinician/review-queue", headers=OKAFOR).json()
    assert any(i["id"] == entry["review_item_id"] for i in queue)
    ok = client.post(f"/api/clinician/review-items/{entry['review_item_id']}/resolve", headers=OKAFOR,
                     json={"action": "approve"})
    assert ok.status_code == 200
    after = client.get(f"/api/reports/{report_id}", headers=MAYA).json()["explanation"]
    assert after["status"] == "approved" and after["text"] == expl["draft_text"]

    # And FHIR carries the import provenance tag.
    dr = client.get(f"/api/fhir/R4/DiagnosticReport?patient={P_MAYA}", headers=MAYA).json()
    imported = next(e["resource"] for e in dr["entry"] if e["resource"]["id"] == report_id)
    assert imported["meta"]["tag"][0]["code"] == "hl7v2-import"


def test_only_admins_import(client):
    for who in (MAYA, OKAFOR):
        assert post(client, oru(), headers=who).status_code == 403
        assert client.get("/api/lab-import/messages", headers=who).status_code == 403


def rejected(client, text, fragment):
    before = report_count()
    entry = post(client, text).json()["results"][0]
    assert entry["outcome"] == "rejected", entry
    assert fragment in entry["reason"], entry["reason"]
    assert entry["patient_id"] is None and entry["report_id"] is None
    assert report_count() == before, "a rejected message must not create anything"
    return entry


def test_ambiguous_name_and_dob_is_refused(client):
    with db() as conn:
        conn.execute(
            "INSERT INTO patients (organization_id, name, birth_date) VALUES (%s, 'Maya Thornton', '1972-03-09')", (ORG,))
    rejected(client, oru(pid="PID|1||||Thornton^Maya||19720309|F"), "ambiguous")


def test_name_and_dob_match_when_unique(client):
    entry = post(client, oru(pid="PID|1||99-UNKNOWN^^^RSL^MR||THORNTON^MAYA||19720309|F")).json()["results"][0]
    assert entry["outcome"] == "accepted" and entry["match_method"] == "name_dob"


def test_matching_refusals(client):
    rejected(client, oru(pid="PID|1||NSH-0201^^^NSH^MR||Thornton^Maya||19720310|F"), "date of birth")
    rejected(client, oru(pid="PID|1||NSH-0201^^^NSH^MR||Park^Maya||19720309|F"), "family name")
    rejected(client, oru(pid="PID|1||NSH-0201^^^NSH^MR~NSH-0202^^^NSH^MR||Thornton^Maya||19720309|F"), "different patients")
    rejected(client, oru(pid="PID|1||||Example^Jordan||19800101|U"), "No patient matches")
    rejected(client, oru(pid="PID|1||||Thornton^Maya|||F"), "lacks the full name and date of birth")
    rejected(client, oru(pid="PID|1||not-a-uuid^^^BIOVERSE^PI||Thornton^Maya||19720309|F"), "not a valid Bioverse patient id")
    # The Bioverse id itself is an exact identifier.
    entry = post(client, oru(pid=f"PID|1||{P_MAYA}^^^BIOVERSE^PI||Thornton^Maya||19720309|F", control="X")).json()["results"][0]
    assert entry["outcome"] == "accepted" and entry["patient_id"] == P_MAYA


def test_structural_rejections(client):
    rejected(client, oru(pid=None), "no PID")
    rejected(client, oru(obr=None, obx=()), "no OBR")
    rejected(client, oru(obx=()), "no OBX")
    rejected(client, oru(obx=("OBX|1|ST|x^Comment^L||See note||||||F",)), "numeric")
    rejected(client, oru().replace("ORU^R01^ORU_R01", "ADT^A01"), "Only ORU^R01")
    rejected(client, "PID|1||x", "MSH")


def test_duplicates_are_rejected(client):
    assert post(client, oru(control="DUP-1")).json()["results"][0]["outcome"] == "accepted"
    rejected(client, oru(control="DUP-1"), "already imported")


def test_review_routing_falls_back_to_care_plan_clinician_and_flags_criticals(client):
    no_provider = oru(obr="OBR|1|||2345-7^Glucose^LN|||20260915",
                      obx=("OBX|1|NM|2345-7^Glucose^LN||420|mg/dL|70-99|HH|||F",
                           "OBX|2|NM|9999-9^Unlisted^LN||1|mg/dL||X|||X"))
    entry = post(client, no_provider).json()["results"][0]
    assert entry["outcome"] == "accepted" and entry["reviewer"] == "Dr. Adaeze Okafor"  # Maya's care plan
    assert entry["detail"]["skipped"] == ["Unlisted: not reported (status X)"]
    with db() as conn:
        item = conn.execute("SELECT priority FROM review_items WHERE id = %s", (entry["review_item_id"],)).fetchone()
    assert item["priority"] == "urgent"

    # Ordering provider by staff id wins over the care-plan clinician.
    lindqvist = oru(control="L1", obr="OBR|1|||2345-7^Glucose^LN|||20260915|||||||||D305^Lindqvist^Erik^^^^^^NSH")
    entry = post(client, lindqvist).json()["results"][0]
    with db() as conn:
        pr = conn.execute("SELECT practitioner_id::text AS p FROM review_items WHERE id = %s", (entry["review_item_id"],)).fetchone()
    assert pr["p"] == DR_LINDQVIST

    # Park has no care plan and the message names no provider: nobody to review it, so it is refused.
    park = oru(control="P1", pid="PID|1||NSH-0202^^^NSH^MR||Park^Jun||19851102|M",
               obr="OBR|1|||2345-7^Glucose^LN|||20260915")
    rejected(client, park, "No ordering provider")


def test_interpretation_from_range_when_flags_are_missing(client):
    msg = oru(obx=("OBX|1|NM|2345-7^Glucose^LN||60|mg/dL|70-99||||F",
                   "OBX|2|NM|LOCAL1^Mystery marker^L||3|U/L||A|||F",
                   "OBX|3|NM|X^HDL^L||55|mg/dL|>40||||F"))
    entry = post(client, msg).json()["results"][0]
    assert entry["outcome"] == "accepted"
    with db() as conn:
        obs = {o["display"]: o for o in conn.execute(
            "SELECT display, loinc_code, interpretation FROM observations WHERE report_id = %s", (entry["report_id"],)).fetchall()}
    assert obs["Glucose"]["interpretation"] == "L"
    assert obs["Mystery marker"]["interpretation"] == "H", "an abnormal flag is never stored as normal"
    assert obs["Mystery marker"]["loinc_code"] == "local:mystery-marker"
    assert obs["HDL"]["loinc_code"] == "2085-9", "local codes map to LOINC by name through the terminology service"


def test_multiple_messages_and_the_log(client):
    text = oru(control="M1") + "\n" + oru(control="M2", pid="PID|1||||Nobody^Here||19990101|U")
    body = post(client, text).json()
    assert (body["accepted"], body["rejected"]) == (1, 1)
    log = client.get("/api/lab-import/messages", headers=ADMIN).json()
    assert [e["control_id"] for e in log[:2]] == ["M2", "M1"]
    assert log[0]["outcome"] == "rejected" and log[1]["outcome"] == "accepted"
    assert any(e["control_id"] == "RSL-DEMO-0001" for e in log), "seeded demo rejection"
    with db() as conn:
        actions = [r["action"] for r in conn.execute(
            "SELECT action FROM audit_events WHERE action IN ('hl7_import_accepted', 'hl7_import_rejected') ORDER BY id").fetchall()]
    assert actions[-2:] == ["hl7_import_accepted", "hl7_import_rejected"]


def test_sample_message_imports_and_shows_on_the_timeline(client):
    sample = client.get("/api/lab-import/sample", headers=ADMIN).json()["message"]
    entry = post(client, sample).json()["results"][0]
    assert entry["outcome"] == "accepted", entry
    with db() as conn:
        name = conn.execute("SELECT name FROM diagnostic_reports WHERE id = %s", (entry["report_id"],)).fetchone()["name"]
    assert name == "Metabolic panel & HbA1c"
    story = client.get(f"/api/patients/{P_MAYA}/story", headers=MAYA).json()
    assert any(e["type"] == "lab_import" and e["ref_id"] == entry["report_id"] for e in story["events"])
    # Park can't see Maya's imported report.
    assert client.get(f"/api/reports/{entry['report_id']}", headers=PARK).status_code == 403
    assert P_PARK != entry["patient_id"]
