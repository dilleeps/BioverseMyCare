"""Online pharmacy ordering: safety checks, checkout, demo payment, status machine, pharmacist workspace, courier job,
access control and audit."""

from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.rows import dict_row

from bioverse.agents.triage import rules_triage
from bioverse.db.seed import P_HADDAD, U_FRONTDESK, U_HADDAD
from bioverse.db.seeds.s050_billing_pharmacy import DISP_ATORVA_1, RX_MAYA_ATORVA
from bioverse.db.seeds.s160_pharmacy_orders import (
    ADDR_HADDAD_HOME, ADDR_MAYA_HOME, ORDER_HADDAD_REVIEW, ORDER_MAYA_DELIVERED, ORDER_MAYA_TRANSIT, PRODUCT_BY_SKU,
    U_PHARMACIST,
)
from bioverse.jobs import run_job
from bioverse.services.pharmacy_orders_checks import (
    Line, Med, PatientProfile, PaymentTokenError, parse_demo_token, run_checks,
)
from tests.conftest import ADMIN, DB, MAYA, OKAFOR, P_MAYA, P_PARK, PARK, as_user

PHARM = as_user(U_PHARMACIST)
HADDAD = as_user(U_HADDAD)
FRONTDESK = as_user(U_FRONTDESK)
API = "/api/pharmacy-orders"


def db():
    return psycopg.connect(DB, row_factory=dict_row)


def sku(code):
    return PRODUCT_BY_SKU[code]["id"]


def add(client, headers, code=None, qty=1, rx=None):
    body = {"medication_request_id": rx} if rx else {"product_id": sku(code), "quantity": qty}
    return client.post(f"{API}/cart/items", headers=headers, json=body)


def window(client, headers, fulfillment="delivery"):
    return client.get(f"{API}/checkout-options", headers=headers).json()["windows"][fulfillment][0]["code"]


def checkout(client, headers=MAYA, fulfillment="delivery", address=ADDR_MAYA_HOME, token="demo_tok_visa", ack=True,
             **extra):
    body = {"fulfillment": fulfillment, "window_code": window(client, headers, fulfillment),
            "payment": {"token": token}, "acknowledge_warnings": ack, **extra}
    if fulfillment == "delivery":
        body["address_id"] = address
    return client.post(f"{API}/checkout", headers=headers, json=body)


def place(client, codes, headers=MAYA, **kw):
    for c in codes:
        assert add(client, headers, c).status_code == 201
    r = checkout(client, headers, **kw)
    assert r.status_code == 201, r.text
    return r.json()


def act(client, order_id, action, body=None, headers=PHARM):
    return client.post(f"{API}/staff/orders/{order_id}/{action}", headers=headers, json=body or {})


def line(key, name, ingredients=(), classes=(), **kw):
    return Line(key=key, kind=kw.pop("kind", "otc"), name=name,
                ingredients=[{"code": i, "name": i.title()} for i in ingredients], classes=list(classes), **kw)


ADULT = PatientProfile(age=40)


def codes(result):
    return [f["code"] for f in result["findings"]]


# --- Safety checks (pure) ---------------------------------------------------------------------------------------


def test_duplicate_ingredient_across_cart_and_current_meds():
    a = line("a", "Calmira", ["acetaminophen"])
    b = line("b", "Nightwell PM", ["acetaminophen", "diphenhydramine"], ["sedating_antihistamine"])
    r = run_checks([a, b], ADULT)
    dup = [f for f in r["findings"] if f["code"] == "duplicate_ingredient"]
    assert len(dup) == 1 and dup[0]["lines"] == ["a", "b"] and dup[0]["severity"] == "high" and r["requires_review"]

    on_combo = PatientProfile(age=40, meds=[Med("m1", "hydrocodone", "Hydrocodone 5/325",
                                                classes=["opioid"], ingredients=[{"code": "acetaminophen", "name": "Acetaminophen"}])])
    r = run_checks([a], on_combo)
    assert "duplicate_ingredient" in codes(r) and "current medicine" in r["findings"][0]["message"]
    assert run_checks([a], ADULT)["findings"] == []


def test_duplicate_class_and_interactions():
    ibu = line("i", "Ibrella", ["ibuprofen"], ["nsaid"])
    nap = line("n", "Navora", ["naproxen"], ["nsaid"])
    assert "duplicate_class" in codes(run_checks([ibu, nap], ADULT))

    warfarin = PatientProfile(age=70, meds=[Med("w", "warfarin", "Warfarin 5 mg", ["anticoagulant"], [{"code": "warfarin", "name": "Warfarin"}])])
    r = run_checks([ibu], warfarin)
    ix = next(f for f in r["findings"] if f["code"] == "interaction")
    assert ix["severity"] == "high" and "Bleeding" in ix["title"] and r["requires_review"]

    ace = PatientProfile(age=60, meds=[Med("l", "lisinopril", "Lisinopril 10 mg", ["ace_inhibitor", "antihypertensive"])])
    assert [f["severity"] for f in run_checks([ibu], ace)["findings"]] == ["moderate"]

    pse = line("p", "Sinuvex", ["pseudoephedrine"], ["decongestant"])
    hbp = PatientProfile(age=60, hypertension=True, hypertension_reason="you take Amlodipine 5 mg for blood pressure")
    r = run_checks([pse], hbp)
    assert codes(r) == ["interaction"] and "Amlodipine" in r["findings"][0]["message"]
    assert run_checks([pse], ADULT)["findings"] == []

    statin = line("s", "Atorvastatin 20 mg", ["atorvastatin"], ["statin"], kind="rx", medication_request_id="x")
    r = run_checks([statin], ADULT)
    grapefruit = next(f for f in r["findings"] if f["code"] == "advisory")
    assert grapefruit["severity"] == "info" and not grapefruit["review"]


def test_allergy_checks():
    ibu = line("i", "Ibrella", ["ibuprofen"], ["nsaid"])
    asp_allergy = PatientProfile(age=40, allergies=["Aspirin"])
    f = run_checks([ibu], asp_allergy)["findings"]
    assert f[0]["code"] == "allergy" and f[0]["title"] == "Possible allergy"  # NSAID cross-sensitivity
    direct = run_checks([ibu], PatientProfile(age=40, allergies=["Ibuprofen"]))["findings"]
    assert direct[0]["title"] == "Allergy on your record" and direct[0]["review"]
    bandage = line("b", "Patchwell Fabric Bandages", allergens=["latex"])
    assert codes(run_checks([bandage], PatientProfile(age=40, allergies=["Latex allergy"]))) == ["allergy"]
    amox = line("x", "Amoxicillin 500 mg", ["amoxicillin"], ["penicillin"], kind="rx", medication_request_id="r")
    assert "allergy" in codes(run_checks([amox], PatientProfile(age=40, allergies=["Penicillin"])))
    assert "allergy" not in codes(run_checks([ibu], PatientProfile(age=40, allergies=["Penicillin", "Sulfa drugs"])))


def test_age_quantity_controlled_and_review_flags():
    pse = line("p", "Sinuvex", ["pseudoephedrine"], ["decongestant"], min_age=18, max_qty=1, quantity=2,
               pharmacist_only=True)
    r = run_checks([pse], PatientProfile(age=16))
    assert {"age_restriction", "quantity_limit"} <= {b["code"] for b in r["blocks"]}

    cod = line("c", "Codelin", ["codeine"], ["opioid"], controlled_schedule="V")
    shop = run_checks([cod], ADULT)
    assert not shop["blocks"] and "controlled_substance" in codes(shop) and not shop["deliverable"]
    deliver = run_checks([cod], ADULT, "delivery")
    assert [b["code"] for b in deliver["blocks"]] == ["controlled_not_deliverable"]
    assert not run_checks([cod], ADULT, "pickup")["blocks"]

    rx = line("r", "Atorvastatin", ["atorvastatin"], kind="rx", medication_request_id="m")
    assert "rx_verification" in run_checks([rx], ADULT)["review_reasons"]
    assert run_checks([pse.__class__(key="p", kind="otc", name="x", pharmacist_only=True)], ADULT)["review_reasons"] == ["pharmacist_only"]
    cold = run_checks([line("f", "Florabiotic", refrigerated=True)], ADULT)
    assert cold["cold_chain"] and not cold["requires_review"]


def test_demo_token_parsing():
    assert parse_demo_token("demo_tok_visa") == ("Visa", "4242")
    for bad, code in [("4111 1111 1111 1111", "card_number_rejected"), ("4111-1111-1111-1111", "card_number_rejected"),
                      ("tok_4111111111111111", "card_number_rejected"), ("tok_live_abc", "invalid_token"),
                      ("", "invalid_token"), ("demo_tok_declined", "payment_declined")]:
        with pytest.raises(PaymentTokenError) as e:
            parse_demo_token(bad)
        assert e.value.code == code, bad


# --- Catalog, Rx items, cart ------------------------------------------------------------------------------------


def test_catalog_and_rx_items(client):
    cat = client.get(f"{API}/catalog", headers=MAYA).json()
    assert len(cat["products"]) >= 40 and "Demo catalog" in cat["notice"]
    assert {p["category"] for p in cat["products"]} >= {"pain_relief", "allergy", "cold_flu", "digestive", "first_aid",
                                                         "vitamins", "devices"}
    allergy = client.get(f"{API}/catalog?category=allergy", headers=MAYA).json()["products"]
    assert allergy and all(p["category"] == "allergy" for p in allergy)
    found = client.get(f"{API}/catalog?q=acetaminophen", headers=MAYA).json()["products"]
    assert {p["sku"] for p in found} >= {"PAIN-001", "SLP-003", "CLD-005"}
    assert client.get(f"{API}/catalog", headers=PHARM).status_code == 403

    rx = client.get(f"{API}/rx-items", headers=MAYA).json()["items"]
    atorva = next(i for i in rx if i["medication_request_id"] == RX_MAYA_ATORVA)
    assert atorva["orderable"] and atorva["mode"] == "ready_fill"
    assert atorva["estimate"]["patient_cents"] > 0 and "Northside Health Plus" in atorva["estimate"]["basis"]


def test_add_to_cart_warns_and_blocks(client):
    assert add(client, MAYA, "PAIN-001").json()["findings"] == []
    r = add(client, MAYA, "SLP-003")
    assert r.status_code == 201
    assert [f["code"] for f in r.json()["findings"]] == ["duplicate_ingredient"]
    cart = r.json()["cart"]
    assert cart["checks"]["requires_review"] and len(cart["items"]) == 2

    over = add(client, MAYA, "PAIN-001", qty=2)  # already 1; limit is 2 per order
    assert over.status_code == 422 and over.json()["detail"]["code"] == "quantity_limit"
    assert len(client.get(f"{API}/cart", headers=MAYA).json()["items"]) == 2, "a blocked add is not saved"
    item = client.get(f"{API}/cart", headers=MAYA).json()["items"][0]
    assert client.patch(f"{API}/cart/items/{item['id']}", headers=MAYA, json={"quantity": 2}).status_code == 200
    assert client.patch(f"{API}/cart/items/{item['id']}", headers=MAYA, json={"quantity": 3}).status_code == 422
    assert client.patch(f"{API}/cart/items/{item['id']}", headers=PARK, json={"quantity": 1}).status_code == 404
    assert client.delete(f"{API}/cart/items/{item['id']}", headers=PARK).status_code == 404
    assert len(client.delete(f"{API}/cart/items/{item['id']}", headers=MAYA).json()["items"]) == 1


def test_age_restriction_and_allergy_from_patient_record(client):
    with db() as conn:
        conn.execute("UPDATE patients SET birth_date = current_date - interval '15 years', allergies = '{Ibuprofen}' "
                     "WHERE id = %s", (P_PARK,))
    young = add(client, PARK, "CLD-001")
    assert young.status_code == 422 and young.json()["detail"]["code"] == "age_restriction"
    r = add(client, PARK, "PAIN-002")
    assert r.status_code == 201 and r.json()["findings"][0]["code"] == "allergy"


def test_rana_decongestant_is_flagged_for_her_blood_pressure(client):
    r = add(client, HADDAD, "CLD-002")  # phenylephrine, not pharmacist-only
    f = r.json()["findings"]
    assert [x["code"] for x in f] == ["interaction"] and "Amlodipine 5 mg" in f[0]["message"]


# --- Checkout and payment ---------------------------------------------------------------------------------------


def test_checkout_plain_otc_is_approved_automatically(client):
    order = place(client, ["VIT-003", "DEV-004"])
    assert order["status"] == "approved" and not order["requires_review"]
    assert [e["to_status"] for e in order["events"]] == ["placed", "approved"]
    assert order["payment"]["card_brand"] == "Visa" and order["payment"]["card_last4"] == "4242"
    assert order["payment"]["status"] == "authorized" and order["total_cents"] == 1199 + 599 + 499
    assert order["address"]["line1"] == "27 Larkspur Lane"
    assert client.get(f"{API}/cart", headers=MAYA).json()["items"] == []
    assert checkout(client).json()["detail"]["code"] == "empty_cart"
    with db() as conn:
        kinds = conn.execute(
            "SELECT title FROM notifications WHERE kind = 'order_update' AND dedupe_key LIKE %s ORDER BY created_at",
            (f"pharmacy_order:{order['id']}:%",),
        ).fetchall()
        audits = conn.execute("SELECT action FROM audit_events WHERE entity_id = %s AND patient_id = %s",
                              (order["id"], P_MAYA)).fetchall()
    assert [k["title"] for k in kinds] == [f"Order {order['number']} received", f"Order {order['number']} approved"]
    assert {"pharmacy_order_placed", "pharmacy_order_approved"} <= {a["action"] for a in audits}


def test_checkout_requires_acknowledging_warnings(client):
    add(client, MAYA, "PAIN-001")
    add(client, MAYA, "CLD-005")
    r = checkout(client, ack=False)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "acknowledge_warnings"
    order = checkout(client).json()
    assert order["status"] == "pharmacist_review" and "duplicate_ingredient" in order["review_reasons"]


def test_payment_token_handling(client):
    add(client, MAYA, "VIT-001")
    card = "4111 1111 1111 1111"
    r = checkout(client, token=card)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "card_number_rejected"
    assert card not in r.text
    r = client.post(f"{API}/checkout", headers=MAYA, json={
        "fulfillment": "delivery", "address_id": ADDR_MAYA_HOME, "window_code": window(client, MAYA),
        "payment": {"token": "demo_tok_visa", "card_number": "4242424242424242", "cvv": "123"}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "card_number_rejected"
    assert "4242424242424242" not in r.text
    assert checkout(client, token="tok_live_123").json()["detail"]["code"] == "invalid_token"
    declined = checkout(client, token="demo_tok_declined")
    assert declined.status_code == 402 and declined.json()["detail"]["code"] == "payment_declined"
    assert checkout(client, note="card 4111111111111111 thanks").json()["detail"]["code"] == "card_number_rejected"
    ok = checkout(client, token="demo_tok_mastercard")
    assert ok.status_code == 201 and ok.json()["payment"]["card_last4"] == "4444"
    with db() as conn:
        cols = {r["column_name"] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'pharmacy_order_payments'").fetchall()}
        leaked = conn.execute("SELECT count(*) AS n FROM audit_events WHERE detail::text LIKE '%%4111%%'").fetchone()["n"]
    assert not cols & {"card_number", "cvv", "token", "expiry"} and leaked == 0


def test_checkout_validation(client):
    add(client, MAYA, "VIT-001")
    assert checkout(client, address=None).json()["detail"]["code"] == "address_required"
    assert checkout(client, address=ADDR_HADDAD_HOME).status_code == 404, "another patient's address"
    bad_window = client.post(f"{API}/checkout", headers=MAYA, json={
        "fulfillment": "pickup", "window_code": "yesterday", "payment": {"token": "demo_tok_visa"}})
    assert bad_window.json()["detail"]["code"] == "invalid_window"
    pickup = checkout(client, fulfillment="pickup")
    assert pickup.status_code == 201 and pickup.json()["address"] is None and pickup.json()["delivery_fee_cents"] == 0
    assert pickup.json()["pharmacy"]["name"] == "Northside Community Pharmacy"


def test_addresses_are_validated_and_private(client):
    good = {"label": "Mum's", "recipient_name": "Maya Thornton", "line1": "5 Test Street", "city": "Northside",
            "state": "ny", "postal_code": "10990", "phone": "(555) 010-0127"}
    r = client.post(f"{API}/addresses", headers=MAYA, json=good)
    assert r.status_code == 201 and r.json()["state"] == "NY" and r.json()["phone"] == "5550100127"
    for field, value in [("postal_code", "1099"), ("state", "New York"), ("line1", "12"), ("phone", "123"),
                         ("city", "N0rth$ide"), ("recipient_name", " ")]:
        assert client.post(f"{API}/addresses", headers=MAYA, json={**good, field: value}).status_code == 422, field
    assert client.post(f"{API}/addresses", headers=MAYA, json={**good, "card": "x"}).status_code == 422
    assert client.delete(f"{API}/addresses/{ADDR_MAYA_HOME}", headers=PARK).status_code == 404
    mine = client.get(f"{API}/addresses", headers=MAYA).json()
    assert mine[0]["id"] == ADDR_MAYA_HOME and mine[0]["is_default"]
    rest = client.delete(f"{API}/addresses/{ADDR_MAYA_HOME}", headers=MAYA).json()
    assert ADDR_MAYA_HOME not in {a["id"] for a in rest} and sum(a["is_default"] for a in rest) == 1


# --- Controlled substances --------------------------------------------------------------------------------------


def test_controlled_otc_is_never_delivered(client):
    r = add(client, MAYA, "CLD-007")
    assert r.status_code == 201 and r.json()["findings"][0]["code"] == "controlled_substance"
    assert not r.json()["cart"]["deliverable"]
    blocked = checkout(client)
    assert blocked.status_code == 422 and blocked.json()["detail"]["code"] == "controlled_not_deliverable"
    order = checkout(client, fulfillment="pickup").json()
    assert order["status"] == "pharmacist_review" and "controlled_substance" in order["review_reasons"]
    oid = order["id"]
    assert act(client, oid, "approve").status_code == 200
    assert act(client, oid, "pack").status_code == 200
    assert act(client, oid, "dispatch", {"courier_name": "Courier", "eta": datetime.now(timezone.utc).isoformat()}).status_code == 409
    assert act(client, oid, "ready-for-pickup").json()["status"] == "ready_for_pickup"
    no_id = act(client, oid, "picked-up", {"recipient_name": "Maya Thornton"})
    assert no_id.status_code == 422 and no_id.json()["detail"]["code"] == "id_required"
    done = act(client, oid, "picked-up", {"recipient_name": "Maya Thornton", "id_checked": True}).json()
    assert done["status"] == "picked_up" and done["payment"]["status"] == "captured"


def test_controlled_prescription_is_never_delivered(client):
    with db() as conn:
        conn.execute("INSERT INTO drug_monographs (code, name, drug_class, uses, how_to_take) "
                     "VALUES ('tramadol', 'Tramadol', 'Opioid', 'Pain', 'As prescribed')")
        rx = conn.execute(
            """
            INSERT INTO medication_requests (patient_id, prescriber_id, drug_code, drug_name, strength, sig, quantity,
                                             refills_authorized, refills_remaining)
            SELECT %s, id, 'tramadol', 'Tramadol', '50 mg', 'One tablet every 6 hours as needed', 20, 1, 1
            FROM practitioners LIMIT 1 RETURNING id::text
            """,
            (P_PARK,),
        ).fetchone()["id"]
        conn.execute("INSERT INTO pharmacy_delivery_addresses (patient_id, label, recipient_name, line1, city, state, "
                     "postal_code, is_default) VALUES (%s, 'Home', 'Jun Park', '1 Demo Way', 'Northside', 'NY', '10990', true)",
                     (P_PARK,))
    item = next(i for i in client.get(f"{API}/rx-items", headers=PARK).json()["items"] if i["medication_request_id"] == rx)
    assert item["orderable"] and item["controlled_schedule"] == "IV"
    assert add(client, PARK, rx=rx).status_code == 201
    addr = client.get(f"{API}/addresses", headers=PARK).json()[0]["id"]
    r = checkout(client, PARK, address=addr)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "controlled_not_deliverable"
    assert checkout(client, PARK, fulfillment="pickup").json()["status"] == "pharmacist_review"


# --- Status machine ---------------------------------------------------------------------------------------------


def test_full_delivery_path_with_counseling_note_and_rx_fill(client):
    assert add(client, MAYA, rx=RX_MAYA_ATORVA).status_code == 201
    assert add(client, MAYA, rx=RX_MAYA_ATORVA).json()["detail"]["code"] == "already_in_cart"
    order = place(client, ["VIT-001"])
    oid = order["id"]
    assert order["status"] == "pharmacist_review" and "rx_verification" in order["review_reasons"]
    rx_item = next(i for i in client.get(f"{API}/rx-items", headers=MAYA).json()["items"]
                   if i["medication_request_id"] == RX_MAYA_ATORVA)
    assert not rx_item["orderable"] and order["number"] in rx_item["reason"]

    # Illegal moves before approval.
    assert act(client, oid, "pack").json()["detail"]["code"] == "illegal_transition"
    assert act(client, oid, "deliver", {"proof": "left_at_door"}).status_code == 409
    assert act(client, oid, "reject", {"reason": "  "}).status_code == 422

    note = "Take atorvastatin in the evening. Tell us about any muscle aches."
    approved = act(client, oid, "approve", {"counseling_note": note}).json()
    assert approved["status"] == "approved" and approved["counseling_note"] == note
    assert act(client, oid, "approve").status_code == 409
    assert act(client, oid, "reject", {"reason": "Too late"}).status_code == 409
    assert act(client, oid, "ready-for-pickup").status_code == 409  # not packed, and a delivery order
    assert act(client, oid, "pack").json()["status"] == "packed"
    assert act(client, oid, "ready-for-pickup").json()["detail"]["code"] == "illegal_transition"
    assert client.post(f"{API}/orders/{oid}/cancel", headers=MAYA, json={}).status_code == 409

    far = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    assert act(client, oid, "dispatch", {"courier_name": "Sam", "eta": far}).status_code == 422
    eta = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    out = act(client, oid, "dispatch", {"courier_name": "Northside Demo Courier (Sam)", "eta": eta}).json()
    assert out["status"] == "out_for_delivery" and out["courier_name"].endswith("(Sam)")
    assert act(client, oid, "deliver", {"proof": "recipient"}).status_code == 422
    done = act(client, oid, "deliver", {"proof": "recipient", "recipient_name": "Maya Thornton"}).json()
    assert done["status"] == "delivered" and done["delivery_proof"]["recipient_name"] == "Maya Thornton"
    assert done["payment"]["status"] == "captured"
    assert act(client, oid, "deliver", {"proof": "left_at_door"}).status_code == 409

    seen = client.get(f"{API}/orders/{oid}", headers=MAYA).json()
    assert seen["counseling_note"] == note and [p["state"] for p in seen["progress"]] == ["done"] * 6
    assert all("actor_name" not in e for e in seen["events"])
    fill = client.get(f"/api/pharmacy/prescriptions/{RX_MAYA_ATORVA}", headers=MAYA).json()["latest_fill"]
    assert fill["id"] == DISP_ATORVA_1 and fill["status"] == "picked_up", "delivery completes the waiting fill"
    with db() as conn:
        steps = [r["to_status"] for r in conn.execute(
            "SELECT to_status FROM pharmacy_order_events WHERE order_id = %s ORDER BY at", (oid,)).fetchall()]
        notes = conn.execute("SELECT count(*) AS n FROM notifications WHERE kind = 'order_update' AND dedupe_key LIKE %s",
                             (f"pharmacy_order:{oid}:%",)).fetchone()["n"]
        audited = {r["action"] for r in conn.execute(
            "SELECT action FROM audit_events WHERE entity_id = %s AND patient_id = %s", (oid, P_MAYA)).fetchall()}
    assert steps == ["placed", "pharmacist_review", "approved", "packed", "out_for_delivery", "delivered"]
    assert notes == 6
    assert {f"pharmacy_order_{s}" for s in steps} <= audited


def test_refill_order_creates_the_fill_when_packed(client):
    client.post(f"/api/pharmacy/fills/{DISP_ATORVA_1}/pickup", headers=MAYA)
    item = next(i for i in client.get(f"{API}/rx-items", headers=MAYA).json()["items"]
                if i["medication_request_id"] == RX_MAYA_ATORVA)
    assert item["mode"] == "refill"
    add(client, MAYA, rx=RX_MAYA_ATORVA)
    oid = checkout(client, fulfillment="pickup").json()["id"]
    act(client, oid, "approve")
    assert act(client, oid, "pack").status_code == 200
    rx = client.get(f"/api/pharmacy/prescriptions/{RX_MAYA_ATORVA}", headers=MAYA).json()
    assert rx["refills_remaining"] == 4 and rx["latest_fill"]["status"] == "ready"
    assert rx["latest_fill"]["pharmacy_name"] == "Northside Community Pharmacy"
    act(client, oid, "ready-for-pickup")
    act(client, oid, "picked-up", {"recipient_name": "Maya Thornton"})
    rx = client.get(f"/api/pharmacy/prescriptions/{RX_MAYA_ATORVA}", headers=MAYA).json()
    assert rx["latest_fill"]["status"] == "picked_up"


def test_reject_and_cancel_rules(client):
    rana = client.get(f"{API}/orders/{ORDER_HADDAD_REVIEW}", headers=HADDAD).json()
    assert rana["status"] == "pharmacist_review" and rana["can_cancel"]
    r = act(client, ORDER_HADDAD_REVIEW, "reject",
            {"reason": "Pseudoephedrine can raise your blood pressure. Try the saline spray, or talk to Dr. Okafor."}).json()
    assert r["status"] == "rejected" and r["payment"]["status"] == "voided"
    assert client.post(f"{API}/orders/{ORDER_HADDAD_REVIEW}/cancel", headers=HADDAD, json={}).status_code == 409
    seen = client.get(f"{API}/orders/{ORDER_HADDAD_REVIEW}", headers=HADDAD).json()
    assert "saline" in seen["rejection_reason"] and seen["progress"][-1]["status"] == "rejected"

    order = place(client, ["VIT-003"])
    assert client.post(f"{API}/orders/{order['id']}/cancel", headers=PARK, json={}).status_code == 404
    c = client.post(f"{API}/orders/{order['id']}/cancel", headers=MAYA, json={"reason": "Ordered by mistake"}).json()
    assert c["status"] == "cancelled" and c["cancel_reason"] == "Ordered by mistake" and c["payment"]["status"] == "voided"
    assert act(client, order["id"], "pack").status_code == 409, "cancelled is terminal"

    # Packed orders can't be cancelled by the patient.
    packed = place(client, ["VIT-003"])
    act(client, packed["id"], "pack")
    assert client.post(f"{API}/orders/{packed['id']}/cancel", headers=MAYA, json={}).json()["detail"]["code"] == "not_cancellable"
    assert client.post(f"{API}/orders/{ORDER_MAYA_TRANSIT}/cancel", headers=MAYA, json={}).status_code == 409


def test_cold_chain_orders_are_handed_over(client):
    order = place(client, ["DIG-006"])
    assert order["cold_chain"]
    act(client, order["id"], "pack")
    eta = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    act(client, order["id"], "dispatch", {"courier_name": "Courier", "eta": eta})
    r = act(client, order["id"], "deliver", {"proof": "left_at_door"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "cold_chain_handover"


# --- Pharmacist workspace and access ----------------------------------------------------------------------------


def test_pharmacist_only_endpoints(client):
    for who in (MAYA, OKAFOR, ADMIN, FRONTDESK):
        assert client.get(f"{API}/staff/queue", headers=who).status_code == 403
        assert client.get(f"{API}/staff/orders/{ORDER_HADDAD_REVIEW}", headers=who).status_code == 403
        assert act(client, ORDER_HADDAD_REVIEW, "approve", headers=who).status_code == 403
    q = client.get(f"{API}/staff/queue", headers=PHARM).json()
    assert [o["number"] for o in q["orders"]] == ["BO-100003"]
    assert q["orders"][0]["flags"][0]["code"] == "interaction" and q["counts"]["transit"] == 1
    detail = client.get(f"{API}/staff/orders/{ORDER_HADDAD_REVIEW}", headers=PHARM).json()
    assert detail["patient"]["allergies"] == ["Sulfa drugs"]
    assert [m["drug_name"] for m in detail["current_meds"]] == ["Amlodipine"]
    assert "interaction" in detail["live_checks"]["review_reasons"] and set(detail["next_actions"]) == {"approved", "rejected"}
    with db() as conn:
        viewed = conn.execute("SELECT actor_user_id::text FROM audit_events WHERE action = 'pharmacy_order_viewed' "
                              "AND patient_id = %s", (P_HADDAD,)).fetchone()
    assert viewed["actor_user_id"] == U_PHARMACIST
    assert any(u["subtitle"] == "Pharmacist" for u in client.get("/api/session/demo-users").json())


def test_patients_see_only_their_orders_and_other_orgs_are_hidden(client):
    mine = client.get(f"{API}/orders", headers=MAYA).json()
    assert {o["id"] for o in mine} == {ORDER_MAYA_DELIVERED, ORDER_MAYA_TRANSIT}
    assert client.get(f"{API}/orders", headers=PARK).json() == []
    assert client.get(f"{API}/orders/{ORDER_MAYA_TRANSIT}", headers=PARK).status_code == 404
    assert client.get(f"{API}/orders/{ORDER_MAYA_TRANSIT}", headers=OKAFOR).status_code == 403
    assert client.get(f"{API}/orders/not-a-uuid", headers=MAYA).status_code == 404
    with db() as conn:
        org = conn.execute("INSERT INTO organizations (name) VALUES ('Elsewhere Health') RETURNING id::text").fetchone()["id"]
        other = conn.execute("INSERT INTO users (role, display_name, email, organization_id) VALUES "
                             "('staff', 'Other Pharmacist', 'o@elsewhere.example', %s) RETURNING id::text", (org,)).fetchone()["id"]
        conn.execute("INSERT INTO pharmacy_staff (user_id, organization_id) VALUES (%s, %s)", (other, org))
    assert client.get(f"{API}/staff/queue", headers=as_user(other)).json()["orders"] == []
    assert client.get(f"{API}/staff/orders/{ORDER_HADDAD_REVIEW}", headers=as_user(other)).status_code == 404
    assert act(client, ORDER_HADDAD_REVIEW, "approve", headers=as_user(other)).status_code == 404


def test_seeded_orders_and_tracking(client):
    transit = client.get(f"{API}/orders/{ORDER_MAYA_TRANSIT}", headers=MAYA).json()
    assert transit["status"] == "out_for_delivery" and transit["courier_name"] and transit["eta"]
    assert [p["state"] for p in transit["progress"]][-2:] == ["current", "upcoming"]
    delivered = client.get(f"{API}/orders/{ORDER_MAYA_DELIVERED}", headers=MAYA).json()
    assert delivered["delivery_proof"]["type"] == "left_at_door" and delivered["payment"]["status"] == "captured"
    notes = client.get("/api/notifications", headers=MAYA).json()["items"]
    assert any(n["kind"] == "order_update" and "out for delivery" in n["title"] for n in notes)


# --- Courier job ------------------------------------------------------------------------------------------------


def test_demo_courier_job_is_idempotent(client, monkeypatch):
    with db() as conn:
        eta = conn.execute("SELECT eta FROM pharmacy_orders WHERE id = %s", (ORDER_MAYA_TRANSIT,)).fetchone()["eta"]
        early = run_job(conn, "pharmacy_demo_courier", eta - timedelta(minutes=1))
        assert early["status"] == "succeeded" and early["detail"]["delivered"] == 0
        monkeypatch.setenv("BIOVERSE_DEMO_COURIER", "off")
        off = run_job(conn, "pharmacy_demo_courier", eta + timedelta(minutes=1))
        assert off["detail"]["skipped"].startswith("disabled")
        monkeypatch.delenv("BIOVERSE_DEMO_COURIER")
        first = run_job(conn, "pharmacy_demo_courier", eta + timedelta(minutes=1))
        second = run_job(conn, "pharmacy_demo_courier", eta + timedelta(minutes=6))
        assert first["detail"] == {"delivered": 1, "simulation": True} and second["detail"]["delivered"] == 0
        events = conn.execute("SELECT to_status, agent FROM pharmacy_order_events WHERE order_id = %s AND to_status = 'delivered'",
                              (ORDER_MAYA_TRANSIT,)).fetchall()
        notes = conn.execute("SELECT count(*) AS n FROM notifications WHERE dedupe_key = %s",
                             (f"pharmacy_order:{ORDER_MAYA_TRANSIT}:delivered",)).fetchone()["n"]
        audit = conn.execute("SELECT agent FROM audit_events WHERE action = 'pharmacy_order_delivered' AND entity_id = %s",
                             (ORDER_MAYA_TRANSIT,)).fetchall()
    assert events == [{"to_status": "delivered", "agent": "demo-courier"}] and notes == 1
    assert [a["agent"] for a in audit] == ["demo-courier"]
    order = client.get(f"{API}/orders/{ORDER_MAYA_TRANSIT}", headers=MAYA).json()
    assert order["status"] == "delivered" and order["delivery_proof"]["simulated"] is True


# --- Integration --------------------------------------------------------------------------------------------------


def test_timeline_has_order_events(client):
    events = client.get(f"/api/patients/{P_MAYA}/story", headers=MAYA).json()["events"]
    titles = [e["title"] for e in events]
    assert "Medicines delivered · BO-100001" in titles and "Medicine order placed · BO-100002" in titles


@pytest.mark.parametrize("text,intent", [
    ("order my medicine", "pharmacy_orders"),
    ("Can you deliver my prescription?", "pharmacy_orders"),
    ("buy allergy medicine", "pharmacy_orders"),
    ("I want to buy a blood pressure monitor", "pharmacy_orders"),
    ("where is my medicine delivery", "pharmacy_orders"),
    ("I need a refill", "pharmacy"),
    ("where do I pick up my prescription", "pharmacy"),
    ("I need medicine delivered, my chest hurts", "symptom"),
    ("show my medication schedule", "care_plan"),
])
def test_order_intent_routing(text, intent):
    assert rules_triage([{"role": "user", "content": text}], {}).intent == intent, text
