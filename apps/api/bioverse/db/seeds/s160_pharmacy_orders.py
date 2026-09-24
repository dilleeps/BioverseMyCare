"""Online pharmacy ordering demo data. Idempotent: fixed IDs 14000-14999, ON CONFLICT DO NOTHING.

Everything here is fictional: brand names are invented (the generic ingredients are real), the pharmacist, the
addresses and the courier are made up, and payments are demo cards.

- A demo pharmacist, Lena Marsh, PharmD (staff), with the verification and fulfilment workspace.
- An OTC catalog of about 45 products.
- Maya: one order delivered last week, one out for delivery today.
- Rana: a decongestant order flagged for pharmacist review (she takes amlodipine for blood pressure).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from psycopg.rows import dict_row

from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import ORG, P_HADDAD, P_MAYA, U_HADDAD, U_MAYA, _id
from bioverse.db.seeds.s050_billing_pharmacy import PH_NORTHSIDE
from bioverse.notify import notify

U_PHARMACIST = _id(14001)
ADDR_MAYA_HOME, ADDR_MAYA_WORK, ADDR_HADDAD_HOME = _id(14011), _id(14012), _id(14013)
ORDER_MAYA_DELIVERED, ORDER_MAYA_TRANSIT, ORDER_HADDAD_REVIEW = _id(14201), _id(14202), _id(14203)

W_ACET = ["Contains acetaminophen. Don't take with any other product that contains acetaminophen.",
          "Liver warning: more than 4,000 mg in 24 hours, or 3 or more alcoholic drinks a day, can cause severe liver damage."]
W_NSAID = ["Stomach bleeding warning: higher risk if you are over 60, take a blood thinner or steroid, or have had stomach ulcers.",
           "Heart attack and stroke warning: risk is higher at higher doses or with longer use.",
           "Ask a pharmacist first if you have high blood pressure, heart or kidney disease, or take a diuretic."]
W_DROWSY = ["May cause marked drowsiness. Don't drive or use machinery.", "Avoid alcohol and other sedating medicines."]
W_DECON = ["Ask a pharmacist first if you have high blood pressure, heart disease, thyroid disease or diabetes.",
           "Don't use if you take an MAO inhibitor or have taken one in the last 2 weeks."]


def _p(n, sku, name, generic, category, form, pack, price, ingredients, classes=(), allergens=(), *,
       pharmacist_only=False, min_age=None, max_qty=5, schedule=None, cold=False, warnings=()):
    return {
        "id": _id(14100 + n), "sku": sku, "name": name, "generic_name": generic, "category": category, "form": form,
        "pack_size": pack, "price_cents": price,
        "ingredients": [{"code": c, "name": nm, "strength": s} for c, nm, s in ingredients],
        "drug_classes": list(classes), "allergens": list(allergens), "pharmacist_only": pharmacist_only,
        "min_age": min_age, "max_qty_per_order": max_qty, "controlled_schedule": schedule,
        "requires_refrigeration": cold, "warnings": list(warnings),
    }


A = ("acetaminophen", "Acetaminophen")
PRODUCTS = [
    # Pain relief
    _p(1, "PAIN-001", "Calmira Acetaminophen 500 mg", "Acetaminophen", "pain_relief", "Tablets", "100 tablets", 899,
       [(*A, "500 mg")], ["analgesic"], min_age=12, max_qty=2, warnings=W_ACET),
    _p(2, "PAIN-002", "Ibrella Ibuprofen 200 mg", "Ibuprofen", "pain_relief", "Tablets", "50 tablets", 699,
       [("ibuprofen", "Ibuprofen", "200 mg")], ["nsaid"], min_age=12, max_qty=3, warnings=W_NSAID),
    _p(3, "PAIN-003", "Navora Naproxen Sodium 220 mg", "Naproxen sodium", "pain_relief", "Caplets", "24 caplets", 849,
       [("naproxen", "Naproxen", "220 mg")], ["nsaid"], min_age=12, max_qty=3, warnings=W_NSAID),
    _p(4, "PAIN-004", "Cardiva Low-Dose Aspirin 81 mg", "Aspirin", "pain_relief", "Enteric-coated tablets",
       "120 tablets", 599, [("aspirin", "Aspirin", "81 mg")], ["nsaid", "antiplatelet"], min_age=18, max_qty=2,
       warnings=["Take daily aspirin for your heart only if your doctor has told you to.",
                 "Not for children or teenagers: risk of Reye's syndrome.", *W_NSAID[:1]]),
    _p(5, "PAIN-005", "Thermacool Menthol Pain Patch", "Menthol 5%", "pain_relief", "Patches", "5 patches", 799,
       [("menthol", "Menthol", "5%")], min_age=12, warnings=["For external use only. Don't use on broken skin or with a heating pad."]),
    _p(6, "PAIN-006", "Arnessa Diclofenac 1% Gel", "Diclofenac sodium topical gel", "pain_relief", "Gel", "100 g tube",
       1299, [("diclofenac_topical", "Diclofenac (topical)", "1%")], ["topical_nsaid"], min_age=18,
       warnings=["For arthritis pain in the hands, knees and feet. Don't use on broken skin.",
                 "Ask a pharmacist first if you take a blood thinner or have kidney disease."]),
    # Allergy
    _p(10, "ALG-001", "Clarivo Loratadine 10 mg", "Loratadine", "allergy", "Tablets", "30 tablets", 1199,
       [("loratadine", "Loratadine", "10 mg")], ["antihistamine"], min_age=6, max_qty=3,
       warnings=["Don't take more than one tablet in 24 hours."]),
    _p(11, "ALG-002", "Zyrelle Cetirizine 10 mg", "Cetirizine", "allergy", "Tablets", "30 tablets", 1299,
       [("cetirizine", "Cetirizine", "10 mg")], ["antihistamine"], min_age=6, max_qty=3,
       warnings=["May cause drowsiness in some people. Use care driving."]),
    _p(12, "ALG-003", "Fexana Fexofenadine 180 mg", "Fexofenadine", "allergy", "Tablets", "30 tablets", 1499,
       [("fexofenadine", "Fexofenadine", "180 mg")], ["antihistamine"], min_age=12, max_qty=3,
       warnings=["Don't take with fruit juice. Take with water."]),
    _p(13, "ALG-004", "Drowsa Diphenhydramine 25 mg", "Diphenhydramine", "allergy", "Tablets", "24 tablets", 549,
       [("diphenhydramine", "Diphenhydramine", "25 mg")], ["antihistamine", "sedating_antihistamine"], min_age=12,
       max_qty=2, warnings=W_DROWSY),
    _p(14, "ALG-005", "Nasaclear Fluticasone Nasal Spray", "Fluticasone propionate 50 mcg", "allergy", "Nasal spray",
       "120 sprays", 1699, [("fluticasone", "Fluticasone", "50 mcg per spray")], ["nasal_corticosteroid"], min_age=4,
       max_qty=2, warnings=["Stop and ask a doctor if you have nosebleeds or changes in vision."]),
    _p(15, "ALG-006", "Brightview Allergy Eye Drops", "Ketotifen 0.035%", "allergy", "Eye drops", "5 mL", 1099,
       [("ketotifen", "Ketotifen", "0.035%")], ["ophthalmic_antihistamine"], min_age=3,
       warnings=["Remove contact lenses before use."]),
    _p(16, "ALG-007", "Clarivo-D 12 Hour", "Loratadine and pseudoephedrine", "allergy", "Extended-release tablets",
       "10 tablets", 1399, [("loratadine", "Loratadine", "5 mg"), ("pseudoephedrine", "Pseudoephedrine", "120 mg")],
       ["antihistamine", "decongestant"], pharmacist_only=True, min_age=18, max_qty=1,
       warnings=["Kept behind the pharmacy counter: a pharmacist checks it and photo ID is needed at handover.",
                 *W_DECON]),
    # Cold and flu
    _p(20, "CLD-001", "Sinuvex Pseudoephedrine 30 mg", "Pseudoephedrine", "cold_flu", "Tablets", "24 tablets", 899,
       [("pseudoephedrine", "Pseudoephedrine", "30 mg")], ["decongestant"], pharmacist_only=True, min_age=18,
       max_qty=1, warnings=["Kept behind the pharmacy counter. Purchase limits apply by law.", *W_DECON]),
    _p(21, "CLD-002", "Sinuvex PE", "Phenylephrine", "cold_flu", "Tablets", "18 tablets", 749,
       [("phenylephrine", "Phenylephrine", "10 mg")], ["decongestant"], min_age=12, max_qty=2, warnings=W_DECON),
    _p(22, "CLD-003", "Coughaway DM", "Dextromethorphan", "cold_flu", "Syrup", "120 mL", 899,
       [("dextromethorphan", "Dextromethorphan", "15 mg per 5 mL")], ["cough_suppressant"], min_age=12, max_qty=2,
       warnings=["Don't use if you take an MAO inhibitor. Ask a pharmacist if you take an antidepressant."]),
    _p(23, "CLD-004", "Tussinol Chest Congestion", "Guaifenesin", "cold_flu", "Tablets", "20 tablets", 799,
       [("guaifenesin", "Guaifenesin", "400 mg")], ["expectorant"], min_age=12,
       warnings=["Drink plenty of water. Ask a doctor if a cough lasts more than 7 days."]),
    _p(24, "CLD-005", "Daytrex Cold and Flu Day", "Acetaminophen, dextromethorphan and phenylephrine", "cold_flu",
       "Caplets", "24 caplets", 1099,
       [(*A, "325 mg"), ("dextromethorphan", "Dextromethorphan", "10 mg"), ("phenylephrine", "Phenylephrine", "5 mg")],
       ["analgesic", "cough_suppressant", "decongestant"], min_age=12, max_qty=2, warnings=[*W_ACET, *W_DECON[:1]]),
    _p(25, "CLD-006", "Nightrex Cold and Flu Night", "Acetaminophen, diphenhydramine and phenylephrine", "cold_flu",
       "Caplets", "24 caplets", 1099,
       [(*A, "325 mg"), ("diphenhydramine", "Diphenhydramine", "12.5 mg"), ("phenylephrine", "Phenylephrine", "5 mg")],
       ["analgesic", "antihistamine", "sedating_antihistamine", "decongestant"], min_age=12, max_qty=2,
       warnings=[*W_ACET, *W_DROWSY]),
    _p(26, "CLD-007", "Codelin Cough Syrup", "Codeine and guaifenesin", "cold_flu", "Syrup", "120 mL", 1299,
       [("codeine", "Codeine", "10 mg per 5 mL"), ("guaifenesin", "Guaifenesin", "100 mg per 5 mL")],
       ["opioid", "cough_suppressant"], pharmacist_only=True, min_age=18, max_qty=1, schedule="V",
       warnings=["Controlled medicine (schedule V): pickup only at the pharmacy counter, with photo ID.",
                 "Can cause drowsiness and slowed breathing. Don't take with alcohol or sleep medicines."]),
    _p(27, "CLD-008", "Throatease Lozenges", "Benzocaine", "cold_flu", "Lozenges", "18 lozenges", 599,
       [("benzocaine", "Benzocaine", "15 mg")], ["local_anesthetic"], min_age=6,
       warnings=["See a doctor if a sore throat is severe or lasts more than 2 days, or comes with a high fever."]),
    _p(28, "CLD-009", "Salinette Saline Nasal Spray", "Sodium chloride 0.65%", "cold_flu", "Nasal spray", "45 mL",
       499, [("sodium_chloride", "Sodium chloride", "0.65%")]),
    # Digestive
    _p(30, "DIG-001", "Calmtum Antacid Chews", "Calcium carbonate", "digestive", "Chewable tablets", "96 tablets", 699,
       [("calcium_carbonate", "Calcium carbonate", "750 mg")], ["antacid", "calcium"], min_age=12,
       warnings=["Take other medicines at least 2 hours apart from antacids."]),
    _p(31, "DIG-002", "Famora Famotidine 20 mg", "Famotidine", "digestive", "Tablets", "25 tablets", 1099,
       [("famotidine", "Famotidine", "20 mg")], ["h2_blocker"], min_age=12, max_qty=3,
       warnings=["See a doctor if you have trouble swallowing or heartburn for more than 3 months."]),
    _p(32, "DIG-003", "Omevia Omeprazole 20 mg", "Omeprazole", "digestive", "Delayed-release tablets",
       "14 tablets", 1399, [("omeprazole", "Omeprazole", "20 mg")], ["ppi"], min_age=18, max_qty=3,
       warnings=["A 14-day course. Don't use more than 3 courses a year without a doctor."]),
    _p(33, "DIG-004", "Lopera Loperamide 2 mg", "Loperamide", "digestive", "Caplets", "12 caplets", 699,
       [("loperamide", "Loperamide", "2 mg")], ["antidiarrheal"], min_age=12, max_qty=2,
       warnings=["Don't take more than directed: high doses can cause serious heart problems.",
                 "Don't use if you have bloody or black stools or a fever."]),
    _p(34, "DIG-005", "Regulis PEG 3350 Laxative", "Polyethylene glycol 3350", "digestive", "Powder",
       "17 doses", 1399, [("peg3350", "Polyethylene glycol 3350", "17 g per dose")], ["laxative"], min_age=17,
       warnings=["Don't use for more than 7 days without a doctor."]),
    _p(35, "DIG-006", "Florabiotic Daily Probiotic", "Lactobacillus and Bifidobacterium", "digestive",
       "Capsules (refrigerated)", "30 capsules", 2499,
       [("probiotic", "Lactobacillus and Bifidobacterium blend", "10 billion CFU")], allergens=["milk"], cold=True,
       warnings=["Keep refrigerated.", "Contains milk."]),
    _p(36, "DIG-007", "Oralyte Electrolyte Powder", "Oral rehydration salts", "digestive", "Powder sachets",
       "6 sachets", 699, [("oral_rehydration_salts", "Oral rehydration salts", "1 sachet in 250 mL")]),
    # First aid
    _p(40, "AID-001", "Patchwell Fabric Bandages", "Adhesive bandages", "first_aid", "Assorted sizes", "40 bandages",
       499, [], allergens=["latex"], warnings=["Contains natural rubber latex, which may cause allergic reactions."]),
    _p(41, "AID-002", "Patchwell Latex-Free Bandages", "Adhesive bandages", "first_aid", "Assorted sizes",
       "40 bandages", 549, []),
    _p(42, "AID-003", "Cleanse Antiseptic Wipes", "Benzalkonium chloride", "first_aid", "Wipes", "40 wipes", 449,
       [("benzalkonium_chloride", "Benzalkonium chloride", "0.13%")], warnings=["For external use only."]),
    _p(43, "AID-004", "Healix Triple Antibiotic Ointment", "Bacitracin, neomycin and polymyxin B", "first_aid",
       "Ointment", "28 g tube", 799,
       [("bacitracin", "Bacitracin", "400 units"), ("neomycin", "Neomycin", "3.5 mg"),
        ("polymyxin_b", "Polymyxin B", "5,000 units")], ["topical_antibiotic"], allergens=["neomycin"], min_age=2,
       warnings=["For external use only. Don't use on deep wounds, animal bites or serious burns."]),
    _p(44, "AID-005", "Itchaway Hydrocortisone 1% Cream", "Hydrocortisone", "first_aid", "Cream", "28 g tube", 649,
       [("hydrocortisone_topical", "Hydrocortisone (topical)", "1%")], ["topical_corticosteroid"], min_age=2,
       warnings=["Don't use for more than 7 days without a doctor."]),
    _p(45, "AID-006", "Patchwell 120-Piece First Aid Kit", "First aid kit", "first_aid", "Kit", "1 kit", 2499, [],
       allergens=["latex"], warnings=["Bandages contain natural rubber latex."]),
    # Vitamins
    _p(50, "VIT-001", "Sunvita Vitamin D3 1,000 IU", "Cholecalciferol", "vitamins", "Softgels", "120 softgels", 999,
       [("vitamin_d3", "Vitamin D3", "1,000 IU")], allergens=["gelatin"]),
    _p(51, "VIT-002", "Omegacore Fish Oil 1,000 mg", "Omega-3 fatty acids", "vitamins", "Softgels", "120 softgels",
       1499, [("fish_oil", "Fish oil", "1,000 mg")], allergens=["fish", "gelatin"],
       warnings=["Ask a pharmacist first if you take a blood thinner."]),
    _p(52, "VIT-003", "Dailyvita Adult Multivitamin", "Multivitamin and minerals", "vitamins", "Tablets",
       "100 tablets", 1199, [("multivitamin", "Multivitamin and minerals", "1 tablet")]),
    _p(53, "VIT-004", "Ferrosa Iron 65 mg", "Ferrous sulfate 325 mg", "vitamins", "Tablets", "100 tablets", 799,
       [("ferrous_sulfate", "Ferrous sulfate", "325 mg (65 mg iron)")], ["iron"], min_age=12, max_qty=2,
       warnings=["Accidental overdose of iron is a leading cause of fatal poisoning in children under 6. "
                 "Keep out of reach of children."]),
    _p(54, "VIT-005", "Calcivita Calcium 600 mg + D3", "Calcium carbonate and vitamin D3", "vitamins", "Tablets",
       "60 tablets", 999, [("calcium_carbonate", "Calcium carbonate", "600 mg"), ("vitamin_d3", "Vitamin D3", "400 IU")],
       ["calcium"], warnings=["Take levothyroxine and some antibiotics at a different time of day."]),
    # Sleep
    _p(60, "SLP-001", "Restora Melatonin 3 mg", "Melatonin", "sleep", "Tablets", "60 tablets", 899,
       [("melatonin", "Melatonin", "3 mg")], min_age=12, warnings=["May cause drowsiness. Don't drive after taking."]),
    _p(61, "SLP-002", "Drowsa Sleep 25 mg", "Doxylamine succinate", "sleep", "Tablets", "32 tablets", 799,
       [("doxylamine", "Doxylamine", "25 mg")], ["antihistamine", "sedating_antihistamine"], min_age=12, max_qty=2,
       warnings=W_DROWSY),
    _p(62, "SLP-003", "Nightwell PM", "Acetaminophen and diphenhydramine", "sleep", "Caplets", "50 caplets", 1049,
       [(*A, "500 mg"), ("diphenhydramine", "Diphenhydramine", "25 mg")],
       ["analgesic", "antihistamine", "sedating_antihistamine"], min_age=12, max_qty=2, warnings=[*W_ACET, *W_DROWSY]),
    # Devices
    _p(70, "DEV-001", "Pulsecheck Upper-Arm Blood Pressure Monitor", "Automatic blood pressure monitor", "devices",
       "Device with cuff (22 to 42 cm)", "1 monitor", 4999, [], max_qty=2,
       warnings=["Sit quietly for 5 minutes before measuring. Bring it to your next visit to check it against the clinic's."]),
    _p(71, "DEV-002", "Tempra Digital Thermometer", "Digital thermometer", "devices", "Oral or underarm",
       "1 thermometer", 1299, [], max_qty=3),
    _p(72, "DEV-003", "Oxilite Fingertip Pulse Oximeter", "Pulse oximeter", "devices", "Fingertip device",
       "1 device", 2999, [], max_qty=2,
       warnings=["Readings can be less accurate on darker skin, cold hands or with nail polish. "
                 "Don't rely on it alone if you feel unwell."]),
    _p(73, "DEV-004", "Pillwise Weekly Pill Organizer", "Pill organizer", "devices", "7-day, AM and PM", "1 organizer",
       599, [], max_qty=3),
]

PRODUCT_BY_SKU = {p["sku"]: p for p in PRODUCTS}


def _address(label, recipient, line1, line2, city, state, zip_, phone, instructions=None):
    return {"label": label, "recipient_name": recipient, "line1": line1, "line2": line2, "city": city, "state": state,
            "postal_code": zip_, "phone": phone, "instructions": instructions}


MAYA_HOME = _address("Home", "Maya Thornton", "27 Larkspur Lane", "Apt 3", "Northside", "NY", "10990", "+15550100127",
                     "Buzz 3. Leave with the building concierge if I'm out.")
MAYA_WORK = _address("Work", "Maya Thornton", "400 Demo Plaza", "Floor 6, reception", "Northside", "NY", "10991", None)
HADDAD_HOME = _address("Home", "Rana Haddad", "9 Orchard Row", None, "Northside", "NY", "10992", "+15550100199")


def run(conn, ctx: SeedContext) -> None:
    cur = conn.cursor()
    at, days = ctx.at, ctx.days
    now = datetime.now(ctx.tz).replace(second=0, microsecond=0)

    # --- Pharmacist ---------------------------------------------------------------------------------------------
    cur.execute(
        """
        INSERT INTO users (id, role, display_name, email, organization_id, demo_label, demo_order)
        VALUES (%s, 'staff', 'Lena Marsh, PharmD', 'l.marsh@northside.example', %s, 'Pharmacist', 41)
        ON CONFLICT DO NOTHING
        """,
        (U_PHARMACIST, ORG),
    )
    cur.execute(
        """
        INSERT INTO pharmacy_staff (user_id, organization_id, role, license_number, pharmacy_id)
        VALUES (%s, %s, 'pharmacist', 'DEMO-RPH-0418', %s) ON CONFLICT DO NOTHING
        """,
        (U_PHARMACIST, ORG, PH_NORTHSIDE),
    )

    # --- Catalog ------------------------------------------------------------------------------------------------
    cur.executemany(
        """
        INSERT INTO otc_products (id, sku, name, generic_name, category, form, pack_size, price_cents, ingredients,
                                  drug_classes, allergens, pharmacist_only, min_age, max_qty_per_order,
                                  controlled_schedule, requires_refrigeration, warnings)
        VALUES (%(id)s, %(sku)s, %(name)s, %(generic_name)s, %(category)s, %(form)s, %(pack_size)s, %(price_cents)s,
                %(ingredients)s, %(drug_classes)s, %(allergens)s, %(pharmacist_only)s, %(min_age)s,
                %(max_qty_per_order)s, %(controlled_schedule)s, %(requires_refrigeration)s, %(warnings)s)
        ON CONFLICT DO NOTHING
        """,
        [{**p, "ingredients": json.dumps(p["ingredients"])} for p in PRODUCTS],
    )

    # --- Addresses ----------------------------------------------------------------------------------------------
    for aid, pid, a, default in ((ADDR_MAYA_HOME, P_MAYA, MAYA_HOME, True), (ADDR_MAYA_WORK, P_MAYA, MAYA_WORK, False),
                                 (ADDR_HADDAD_HOME, P_HADDAD, HADDAD_HOME, True)):
        cur.execute(
            """
            INSERT INTO pharmacy_delivery_addresses (id, patient_id, label, recipient_name, line1, line2, city, state,
                                                     postal_code, phone, instructions, is_default, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
            """,
            (aid, pid, a["label"], a["recipient_name"], a["line1"], a["line2"], a["city"], a["state"],
             a["postal_code"], a["phone"], a["instructions"], default, at(days(-30), 12)),
        )

    if cur.execute("SELECT 1 FROM pharmacy_orders WHERE id = %s", (ORDER_MAYA_DELIVERED,)).fetchone():
        return  # orders below were seeded before; don't rewrite their history

    from bioverse.routers.pharmacy_orders import order_checks  # after tables exist; avoids an import cycle at load

    # --- Orders -------------------------------------------------------------------------------------------------
    def order(oid, number, pid, status, fulfillment, address_id, address, window, items, placed, events, *,
              review=False, reasons=(), courier=None, eta=None, proof=None, completed=None, payment_status,
              counseling=None, reviewed=None):
        slot = int(oid[-3:]) - 201  # 0, 1, 2: item, event and payment IDs are allotted per order
        subtotal = sum(PRODUCT_BY_SKU[sku]["price_cents"] * q for sku, q in items)
        fee = 0 if subtotal >= 3500 or fulfillment == "pickup" else 499
        cur.execute(
            """
            INSERT INTO pharmacy_orders (id, number, patient_id, organization_id, status, fulfillment, pharmacy_id,
                                         address_id, address, window_code, window_label, window_start, window_end,
                                         cold_chain, requires_review, review_reasons, subtotal_cents,
                                         delivery_fee_cents, total_cents, counseling_note, courier_name, eta,
                                         delivery_proof, completed_at, reviewed_by, reviewed_at, placed_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, false, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (oid, number, pid, ORG, status, fulfillment, PH_NORTHSIDE, address_id, json.dumps(address), *window,
             review, json.dumps(list(reasons)), subtotal, fee, subtotal + fee, counseling, courier, eta,
             json.dumps(proof) if proof else None, completed, U_PHARMACIST if reviewed else None, reviewed,
             placed, events[-1][1]),
        )
        for i, (sku, q) in enumerate(items):
            p = PRODUCT_BY_SKU[sku]
            cur.execute(
                """
                INSERT INTO pharmacy_order_items (id, order_id, kind, product_id, name, detail, quantity,
                                                  unit_price_cents, line_total_cents, requires_refrigeration)
                VALUES (%s, %s, 'otc', %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (_id(14250 + slot * 10 + i), oid, p["id"], p["name"], f"{p['generic_name']} · {p['pack_size']}", q, p["price_cents"],
                 p["price_cents"] * q, p["requires_refrigeration"]),
            )
        for i, (to, when, actor, note) in enumerate(events):
            frm = events[i - 1][0] if i else None
            cur.execute(
                """
                INSERT INTO pharmacy_order_events (id, order_id, patient_id, from_status, to_status, actor_user_id,
                                                   actor_role, agent, note, at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (_id(14300 + slot * 10 + i), oid, pid, frm, to, actor,
                 "staff" if actor == U_PHARMACIST else "patient" if actor else "system",
                 None if actor else "pharmacy-order-checks", note, when),
            )
        cur.execute(
            """
            INSERT INTO pharmacy_order_payments (id, order_id, patient_id, amount_cents, card_brand, card_last4,
                                                 status, receipt_number, created_at)
            VALUES (%s, %s, %s, %s, 'Visa', '4242', %s, %s, %s) ON CONFLICT DO NOTHING
            """,
            (_id(14400 + slot), oid, pid, subtotal + fee, payment_status,
             f"PO-{number[3:]}", placed),
        )
        # The router's helpers expect dict rows (the API pool's row factory); the seed connection has tuples.
        previous = conn.row_factory
        conn.row_factory = dict_row
        try:
            snapshot = _snapshot(order_checks(conn, oid, pid, fulfillment))
        finally:
            conn.row_factory = previous
        cur.execute("UPDATE pharmacy_orders SET checks = %s WHERE id = %s", (json.dumps(snapshot), oid))

    # Maya, last week: vitamins, allergy tablets and bandages, left at the door.
    d0 = days(-6)
    w = (at(d0, 17), at(d0, 20))
    order(ORDER_MAYA_DELIVERED, "BO-100001", P_MAYA, "delivered", "delivery", ADDR_MAYA_HOME, MAYA_HOME,
          ("today_evening", "Same day, 5 to 8 pm", *w),
          [("VIT-001", 1), ("ALG-001", 1), ("AID-002", 1)], at(d0, 10, 12),
          [("placed", at(d0, 10, 12), U_MAYA, None),
           ("approved", at(d0, 10, 12), None, "No flags: approved automatically"),
           ("packed", at(d0, 14, 30), U_PHARMACIST, None),
           ("out_for_delivery", at(d0, 16, 5), U_PHARMACIST, "Courier: Northside Demo Courier (Jordan)"),
           ("delivered", at(d0, 18, 22), U_PHARMACIST, None)],
          courier="Northside Demo Courier (Jordan)", eta=at(d0, 18, 30),
          proof={"type": "left_at_door", "at": at(d0, 18, 22).isoformat()}, completed=at(d0, 18, 22),
          payment_status="captured")

    # Maya, today: a home blood pressure monitor (her BP check is overdue) and a thermometer, on the way now.
    placed = now - timedelta(hours=3)
    eta = now + timedelta(minutes=95)
    eta = eta.replace(minute=(eta.minute // 5) * 5)
    order(ORDER_MAYA_TRANSIT, "BO-100002", P_MAYA, "out_for_delivery", "delivery", ADDR_MAYA_HOME, MAYA_HOME,
          ("today_evening", "Today, by early evening", now - timedelta(minutes=30), now + timedelta(hours=3)),
          [("DEV-001", 1), ("DEV-002", 1)], placed,
          [("placed", placed, U_MAYA, None),
           ("approved", placed, None, "No flags: approved automatically"),
           ("packed", placed + timedelta(minutes=80), U_PHARMACIST, None),
           ("out_for_delivery", now - timedelta(minutes=35), U_PHARMACIST, "Courier: Northside Demo Courier (Priya)")],
          courier="Northside Demo Courier (Priya)", eta=eta, payment_status="authorized")

    # Rana, this morning: a pseudoephedrine decongestant while on amlodipine for blood pressure. Flagged.
    placed = now - timedelta(minutes=50)
    tomorrow = days(1)
    order(ORDER_HADDAD_REVIEW, "BO-100003", P_HADDAD, "pharmacist_review", "delivery", ADDR_HADDAD_HOME, HADDAD_HOME,
          ("tomorrow_morning", "Tomorrow, 9 am to 12 pm", at(tomorrow, 9), at(tomorrow, 12)),
          [("CLD-001", 1), ("CLD-008", 1)], placed,
          [("placed", placed, U_HADDAD, None),
           ("pharmacist_review", placed, None, "interaction, pharmacist_only")],
          review=True, reasons=("interaction", "pharmacist_only"), payment_status="authorized")

    # Notifications the patients would have received.
    for uid, pid, oid, to, title, body, due in [
        (U_MAYA, P_MAYA, ORDER_MAYA_DELIVERED, "delivered", "Order BO-100001 was delivered",
         "Open the order for the delivery details.", at(d0, 18, 22)),
        (U_MAYA, P_MAYA, ORDER_MAYA_TRANSIT, "out_for_delivery", "Order BO-100002 is out for delivery",
         f"Northside Demo Courier (Priya) is on the way. Estimated arrival {eta.strftime('%I:%M %p').lstrip('0')}.",
         now - timedelta(minutes=35)),
        (U_HADDAD, P_HADDAD, ORDER_HADDAD_REVIEW, "pharmacist_review", "A pharmacist is checking order BO-100003",
         "A pharmacist checks some orders before they're packed. We'll let you know when it's done.", placed),
    ]:
        notify(conn, user_id=uid, kind="order_update", title=title, body=body, link=f"/shop/orders/{oid}",
               patient_id=pid, channels=["in_app", "push"], due_at=due, dedupe_key=f"pharmacy_order:{oid}:{to}",
               created_by="seed")


def _snapshot(checks: dict) -> dict:
    return {k: checks[k] for k in ("findings", "requires_review", "review_reasons", "cold_chain", "deliverable", "notice")}
