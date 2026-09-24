"""Online pharmacy ordering: OTC catalog, prescriptions ready to fill, safety checks, checkout, pharmacist
verification, fulfilment and delivery tracking.

Builds on Pharmacy (routers/pharmacy.py): prescriptions and fills are read from its tables. When an order with a
prescription is packed, the fill is created (or the fill already waiting is used), and delivery or pickup marks
that fill picked up, so dose tracking starts as it does for an in-store pickup.

Safety checks come ONLY from the static demo tables in services/pharmacy_orders_checks.py. Anything flagged, and
every prescription, waits for a pharmacist. Controlled substances are never delivered.

Payment is a DEMO: the patient picks a demo card, the API accepts only demo tokens, refuses anything that looks
like a card number, and keeps the demo card's brand and last four digits only. No money moves. The charge is kept
in this module's own table: billing's payments table records payments against insurance claim statements only.

Access: patients reach only their own cart, addresses and orders. The verification and fulfilment workspace is for
pharmacists (staff users listed in `pharmacy_staff`) and only for orders in their organization.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from bioverse import audit
from bioverse.auth import CurrentUser, Patient, User
from bioverse.db import DbConn
from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.s050_billing_pharmacy import PH_NORTHSIDE
from bioverse.notify import notify, patient_user
from bioverse.routers.billing import _active_coverage, calculate_estimate
from bioverse.services.pharmacy_orders_checks import (
    CARD_LIKE, DEMO_CARDS, Line, Med, PatientProfile, PaymentTokenError, parse_demo_token, run_checks, rx_profile,
)

router = APIRouter(prefix="/api/pharmacy-orders", tags=["pharmacy-orders"])

Conn = DbConn

CLINIC_PHARMACY_ID = PH_NORTHSIDE
DELIVERY_FEE_CENTS = 499
FREE_DELIVERY_OVER_CENTS = 3500
MAX_ADDRESSES = 5

CATALOG_NOTICE = (
    "Demo catalog: fictional brands with real generic ingredients. Product information is a short demo summary, "
    "not the full label. Read the label and ask a pharmacist if you're unsure."
)
PAYMENT_NOTICE = (
    "Demo payment: no money moves, and real card details are never accepted or stored."
)
COURIER_NOTICE = "Demo delivery: couriers and tracking are simulated."
RX_PRICE_NOTICE = (
    "Prescription prices are estimates from your demo coverage. The pharmacy confirms the final amount."
)

# Demo cash prices for prescriptions (per fill). Allowed amount is the demo payer's rate for the fill.
RX_CASH_PRICE_CENTS = {"atorvastatin": 1500, "simvastatin": 1400, "amlodipine": 1200, "azithromycin": 2200,
                       "clarithromycin": 3000}
RX_DEFAULT_CASH_CENTS = 2500
RX_ALLOWED_PCT = 60

STATUS_LABELS = {
    "placed": "Order placed",
    "pharmacist_review": "Pharmacist check",
    "approved": "Approved",
    "rejected": "Not approved",
    "packed": "Packed",
    "out_for_delivery": "Out for delivery",
    "delivered": "Delivered",
    "ready_for_pickup": "Ready for pickup",
    "picked_up": "Picked up",
    "cancelled": "Cancelled",
}
TRANSITIONS: dict[str, set[str]] = {
    "placed": {"pharmacist_review", "approved", "cancelled"},
    "pharmacist_review": {"approved", "rejected", "cancelled"},
    "approved": {"packed", "cancelled"},
    "packed": {"out_for_delivery", "ready_for_pickup"},
    "out_for_delivery": {"delivered"},
    "ready_for_pickup": {"picked_up"},
}
DELIVERY_ONLY = {"out_for_delivery", "delivered"}
PICKUP_ONLY = {"ready_for_pickup", "picked_up"}
CANCELLABLE = {"placed", "pharmacist_review", "approved"}
OPEN_STATUSES = ("placed", "pharmacist_review", "approved", "packed", "out_for_delivery", "ready_for_pickup")
TERMINAL = ("rejected", "delivered", "picked_up", "cancelled")

STAGES = {
    "review": ("placed", "pharmacist_review"),
    "fulfil": ("approved", "packed"),
    "transit": ("out_for_delivery", "ready_for_pickup"),
    "done": TERMINAL,
}


def clinic_tz():
    return SeedContext().tz


def clinic_today() -> date:
    return SeedContext().today


def _valid_id(value: str | None, what: str = "Record") -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found") from None


def _err(code: int, key: str, message: str, **extra) -> HTTPException:
    return HTTPException(code, {"code": key, "message": message, **extra})


def _local_time(dt: datetime) -> str:
    return dt.astimezone(clinic_tz()).strftime("%I:%M %p").lstrip("0")


# --- Pharmacist access -----------------------------------------------------------------------------------------


def require_pharmacist(conn: DbConn, user: CurrentUser) -> User:
    if user.role != "staff":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Pharmacist access required")
    row = conn.execute(
        "SELECT 1 FROM pharmacy_staff WHERE user_id = %s AND organization_id = %s",
        (user.id, user.organization_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Pharmacist access required")
    return user


Pharmacist = Annotated[User, Depends(require_pharmacist)]


# --- Patient profile and lines for the checks ------------------------------------------------------------------


def patient_age(birth: date, today: date) -> int:
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def patient_profile(conn: Connection, patient_id: str) -> PatientProfile:
    p = conn.execute("SELECT birth_date, allergies FROM patients WHERE id = %s", (patient_id,)).fetchone()
    meds = []
    for m in conn.execute(
        """
        SELECT id::text, drug_code, drug_name, strength FROM medication_requests
        WHERE patient_id = %s AND status = 'active' ORDER BY authored_at
        """,
        (patient_id,),
    ).fetchall():
        prof = rx_profile(m["drug_code"])
        meds.append(Med(id=m["id"], code=m["drug_code"], name=f"{m['drug_name']} {m['strength']}",
                        classes=prof["classes"], ingredients=prof["ingredients"]))
    high_bp = conn.execute(
        """
        SELECT 1 FROM observations
        WHERE patient_id = %s AND loinc_code = '8480-6' AND value >= 140 AND effective_at > now() - interval '365 days'
        LIMIT 1
        """,
        (patient_id,),
    ).fetchone()
    bp_meds = [m.name for m in meds if "antihypertensive" in m.classes]
    reason = (f"you take {', '.join(bp_meds)} for blood pressure" if bp_meds
              else "a high blood pressure reading in the last year" if high_bp else "")
    return PatientProfile(age=patient_age(p["birth_date"], clinic_today()), allergies=list(p["allergies"] or []),
                          meds=meds, hypertension=bool(reason), hypertension_reason=reason)


PRODUCT_COLS = """
    id::text, sku, name, generic_name, category, form, pack_size, price_cents, ingredients, drug_classes, allergens,
    pharmacist_only, min_age, max_qty_per_order, controlled_schedule, requires_refrigeration, warnings
"""


def product_line(prod: dict, quantity: int, key: str) -> Line:
    return Line(
        key=key, kind="otc", name=prod["name"], quantity=quantity,
        ingredients=[{"code": i["code"], "name": i["name"]} for i in prod["ingredients"]],
        classes=list(prod["drug_classes"]), allergens=list(prod["allergens"]),
        pharmacist_only=prod["pharmacist_only"], min_age=prod["min_age"], max_qty=prod["max_qty_per_order"],
        controlled_schedule=prod["controlled_schedule"], refrigerated=prod["requires_refrigeration"],
    )


def rx_line(rx: dict, key: str) -> Line:
    prof = rx_profile(rx["drug_code"])
    return Line(
        key=key, kind="rx", name=f"{rx['drug_name']} {rx['strength']}", quantity=1,
        ingredients=prof["ingredients"], classes=prof["classes"], max_qty=1,
        controlled_schedule=prof["schedule"], refrigerated=prof["refrigerated"], medication_request_id=rx["id"],
    )


# --- Prescriptions that can be ordered ---------------------------------------------------------------------------

RX_SELECT = """
    SELECT m.id::text, m.patient_id::text, m.drug_code, m.drug_name, m.strength, m.sig, m.quantity,
           m.refills_remaining, m.status, pr.name AS prescriber_name,
           d.id::text AS dispense_id, d.status AS dispense_status, dph.name AS dispense_pharmacy,
           EXISTS (SELECT 1 FROM refill_requests r
                   WHERE r.medication_request_id = m.id AND r.status = 'pending_approval') AS pending_refill,
           (SELECT o.number FROM pharmacy_order_items i JOIN pharmacy_orders o ON o.id = i.order_id
             WHERE i.medication_request_id = m.id
               AND o.status IN ('placed', 'pharmacist_review', 'approved', 'packed', 'out_for_delivery',
                                'ready_for_pickup')
             ORDER BY o.placed_at DESC LIMIT 1) AS open_order
    FROM medication_requests m
    JOIN practitioners pr ON pr.id = m.prescriber_id
    LEFT JOIN LATERAL (
        SELECT * FROM medication_dispenses x WHERE x.medication_request_id = m.id ORDER BY x.fill_number DESC LIMIT 1
    ) d ON true
    LEFT JOIN pharmacies dph ON dph.id = d.pharmacy_id
"""


def rx_estimate(code: str, coverage: dict | None) -> dict:
    cash = RX_CASH_PRICE_CENTS.get(code, RX_DEFAULT_CASH_CENTS)
    allowed = cash * RX_ALLOWED_PCT // 100
    est = calculate_estimate(allowed_cents=allowed, category="pharmacy", coverage=coverage, in_network=True,
                             price_cents=cash)
    basis = f"Estimate with {coverage['plan_name']}" if coverage else "Cash price: no active coverage found"
    return {"patient_cents": est["patient_cents"], "cash_cents": cash, "basis": basis, "steps": est["steps"]}


def rx_eligibility(row: dict, ignore_open_order: bool = False) -> tuple[str | None, str | None]:
    """(mode, reason): mode is 'ready_fill' or 'refill' when orderable, else None with the reason."""
    if row["status"] != "active":
        return None, "This prescription isn't active."
    if row["open_order"] and not ignore_open_order:
        return None, f"Already in order {row['open_order']}."
    if row["dispense_status"] == "ready":
        return "ready_fill", None
    if row["dispense_status"] in ("sent", "received"):
        return None, "Your pharmacy is filling this now. You can order it once it's ready."
    if row["pending_refill"]:
        return None, "A refill request is waiting for your prescriber."
    if row["refills_remaining"] > 0:
        return "refill", None
    return None, "No refills left. Ask your prescriber for a refill on the Pharmacy page."


def rx_option(row: dict, coverage: dict | None) -> dict:
    """One active prescription as the shop shows it: orderable or not, how, and the price estimate."""
    mode, reason = rx_eligibility(row)
    prof = rx_profile(row["drug_code"])
    if mode == "ready_fill":
        how = f"Your fill is ready at {row['dispense_pharmacy']}. We'll deliver it or hold it at the clinic pharmacy."
    elif mode == "refill":
        n = row["refills_remaining"] - 1
        how = f"Uses one of your refills ({n} left after this one)."
    else:
        how = reason
    return {
        "medication_request_id": row["id"], "drug_code": row["drug_code"],
        "name": f"{row['drug_name']} {row['strength']}", "sig": row["sig"], "quantity": row["quantity"],
        "prescriber_name": row["prescriber_name"], "refills_remaining": row["refills_remaining"],
        "orderable": mode is not None, "mode": mode, "reason": reason, "how": how,
        "controlled_schedule": prof["schedule"], "requires_refrigeration": prof["refrigerated"],
        "estimate": rx_estimate(row["drug_code"], coverage),
    }


def _coverage(conn: Connection, patient_id: str) -> dict | None:
    return _active_coverage(conn, patient_id, clinic_today())


def rx_options(conn: Connection, patient_id: str) -> list[dict]:
    cov = _coverage(conn, patient_id)
    rows = conn.execute(RX_SELECT + " WHERE m.patient_id = %s AND m.status = 'active' ORDER BY m.authored_at DESC",
                        (patient_id,)).fetchall()
    return [rx_option(r, cov) for r in rows]


# --- Catalog ------------------------------------------------------------------------------------------------------

CATEGORIES = [
    ("pain_relief", "Pain relief"), ("allergy", "Allergy"), ("cold_flu", "Cold and flu"),
    ("digestive", "Digestive health"), ("first_aid", "First aid"), ("vitamins", "Vitamins"),
    ("sleep", "Sleep"), ("devices", "Health devices"),
]


def _product_out(p: dict) -> dict:
    p["ingredient_text"] = ", ".join(f"{i['name']} {i.get('strength', '')}".strip() for i in p["ingredients"])
    p["deliverable"] = p["controlled_schedule"] is None
    return p


@router.get("/catalog")
def catalog(conn: Conn, user: Patient, q: str | None = None, category: str | None = None) -> dict:
    q = (q or "").strip()[:80] or None
    rows = conn.execute(
        f"""
        SELECT {PRODUCT_COLS} FROM otc_products
        WHERE active AND (%(c)s::text IS NULL OR category = %(c)s)
          AND (%(q)s::text IS NULL OR name ILIKE '%%' || %(q)s || '%%' OR generic_name ILIKE '%%' || %(q)s || '%%'
               OR ingredients::text ILIKE '%%' || %(q)s || '%%')
        ORDER BY category, name
        """,
        {"c": category, "q": q},
    ).fetchall()
    return {"products": [_product_out(r) for r in rows], "categories": [{"code": c, "label": lbl} for c, lbl in CATEGORIES],
            "notice": CATALOG_NOTICE}


@router.get("/catalog/{product_id}")
def product(product_id: str, conn: Conn, user: Patient) -> dict:
    row = conn.execute(f"SELECT {PRODUCT_COLS} FROM otc_products WHERE id = %s AND active",
                       (_valid_id(product_id, "Product"),)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return _product_out(row) | {"notice": CATALOG_NOTICE}


@router.get("/rx-items")
def rx_items(conn: Conn, user: Patient) -> dict:
    items = rx_options(conn, user.patient_id)
    audit.record(conn, action="pharmacy_order_rx_items_viewed", entity_type="medication_request", actor=user,
                 patient_id=user.patient_id)
    return {"items": items, "notice": RX_PRICE_NOTICE}


# --- Cart ---------------------------------------------------------------------------------------------------------


def _cart_rows(conn: Connection, patient_id: str, lock: bool = False) -> list[dict]:
    return conn.execute(
        """
        SELECT id::text, product_id::text, medication_request_id::text, quantity, added_at
        FROM pharmacy_cart_items WHERE patient_id = %s ORDER BY added_at
        """ + (" FOR UPDATE" if lock else ""),
        (patient_id,),
    ).fetchall()


def build_cart(conn: Connection, patient_id: str, fulfillment: str | None = None, lock: bool = False) -> dict:
    """The cart with prices and the safety checks. Prescriptions that can no longer be ordered are marked."""
    cov = _coverage(conn, patient_id)
    profile = patient_profile(conn, patient_id)
    items, lines = [], []
    for c in _cart_rows(conn, patient_id, lock):
        key = f"cart:{c['id']}"
        if c["product_id"]:
            prod = conn.execute(f"SELECT {PRODUCT_COLS} FROM otc_products WHERE id = %s", (c["product_id"],)).fetchone()
            line = product_line(prod, c["quantity"], key)
            items.append({
                "id": c["id"], "key": key, "kind": "otc", "product_id": c["product_id"], "name": prod["name"],
                "detail": f"{prod['generic_name']} · {prod['pack_size']}", "quantity": c["quantity"],
                "max_quantity": prod["max_qty_per_order"], "unit_price_cents": prod["price_cents"],
                "line_total_cents": prod["price_cents"] * c["quantity"], "price_note": None,
                "requires_refrigeration": prod["requires_refrigeration"], "controlled_schedule": prod["controlled_schedule"],
                "pharmacist_only": prod["pharmacist_only"], "available": prod is not None, "_product": prod,
            })
            lines.append(line)
        else:
            rx = conn.execute(RX_SELECT + " WHERE m.id = %s", (c["medication_request_id"],)).fetchone()
            mode, reason = rx_eligibility(rx)
            est = rx_estimate(rx["drug_code"], cov)
            prof = rx_profile(rx["drug_code"])
            items.append({
                "id": c["id"], "key": key, "kind": "rx", "medication_request_id": rx["id"],
                "name": f"{rx['drug_name']} {rx['strength']}", "detail": f"Prescription · {rx['sig']}", "quantity": 1,
                "max_quantity": 1, "unit_price_cents": est["patient_cents"], "line_total_cents": est["patient_cents"],
                "price_note": est["basis"], "requires_refrigeration": prof["refrigerated"],
                "controlled_schedule": prof["schedule"], "pharmacist_only": True, "available": mode is not None,
                "unavailable_reason": reason, "rx_mode": mode, "dispense_id": rx["dispense_id"] if mode == "ready_fill" else None,
                "_rx": rx,
            })
            if mode is not None:
                lines.append(rx_line(rx, key))
    checks = run_checks(lines, profile, fulfillment)
    subtotal = sum(i["line_total_cents"] for i in items if i["available"])
    fee = 0 if subtotal >= FREE_DELIVERY_OVER_CENTS else DELIVERY_FEE_CENTS
    return {
        "items": items, "subtotal_cents": subtotal, "delivery_fee_cents": fee,
        "free_delivery_over_cents": FREE_DELIVERY_OVER_CENTS, "checks": checks, "cold_chain": checks["cold_chain"],
        "deliverable": checks["deliverable"], "profile": profile,
    }


def _public_cart(cart: dict) -> dict:
    out = {k: v for k, v in cart.items() if k != "profile"}
    out["items"] = [{k: v for k, v in i.items() if not k.startswith("_")} for i in cart["items"]]
    out["notices"] = {"catalog": CATALOG_NOTICE, "rx_price": RX_PRICE_NOTICE}
    return out


@router.get("/cart")
def get_cart(conn: Conn, user: Patient, fulfillment: Literal["delivery", "pickup"] | None = None) -> dict:
    return _public_cart(build_cart(conn, user.patient_id, fulfillment))


class CartAddIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str | None = None
    medication_request_id: str | None = None
    quantity: StrictInt = Field(default=1, ge=1, le=20)


def _blocked_for(cart: dict, key: str) -> list[dict]:
    return [f for f in cart["checks"]["blocks"] if key in f["lines"]]


@router.post("/cart/items", status_code=status.HTTP_201_CREATED)
def add_to_cart(body: CartAddIn, conn: Conn, user: Patient) -> dict:
    if (body.product_id is None) == (body.medication_request_id is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Add either a product or a prescription")
    pid = user.patient_id
    if body.product_id:
        prod_id = _valid_id(body.product_id, "Product")
        prod = conn.execute("SELECT id FROM otc_products WHERE id = %s AND active", (prod_id,)).fetchone()
        if prod is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
        row = conn.execute(
            """
            INSERT INTO pharmacy_cart_items (patient_id, product_id, quantity) VALUES (%s, %s, %s)
            ON CONFLICT (patient_id, product_id) WHERE product_id IS NOT NULL
            DO UPDATE SET quantity = LEAST(pharmacy_cart_items.quantity + EXCLUDED.quantity, 20)
            RETURNING id::text
            """,
            (pid, prod_id, body.quantity),
        ).fetchone()
        ref = {"product_id": prod_id}
    else:
        rx_id = _valid_id(body.medication_request_id, "Prescription")
        rx = conn.execute(RX_SELECT + " WHERE m.id = %s", (rx_id,)).fetchone()
        if rx is None or rx["patient_id"] != pid:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Prescription not found")
        if body.quantity != 1:
            raise _err(422, "rx_quantity", "Prescriptions are ordered one fill at a time.")
        mode, reason = rx_eligibility(rx)
        if mode is None:
            raise _err(409, "rx_not_orderable", reason)
        row = conn.execute(
            """
            INSERT INTO pharmacy_cart_items (patient_id, medication_request_id, quantity) VALUES (%s, %s, 1)
            ON CONFLICT (patient_id, medication_request_id) WHERE medication_request_id IS NOT NULL DO NOTHING
            RETURNING id::text
            """,
            (pid, rx_id),
        ).fetchone()
        if row is None:
            raise _err(409, "already_in_cart", "This prescription is already in your cart.")
        ref = {"medication_request_id": rx_id}
    key = f"cart:{row['id']}"
    cart = build_cart(conn, pid)
    blocked = _blocked_for(cart, key)
    if blocked:
        # Roll back the add: the request fails, so the transaction is not committed.
        raise _err(422, blocked[0]["code"], blocked[0]["message"], findings=blocked)
    new = [f for f in cart["checks"]["findings"] if key in f["lines"]]
    audit.record(conn, action="pharmacy_cart_item_added", entity_type="pharmacy_cart_item", entity_id=row["id"],
                 actor=user, patient_id=pid,
                 detail={**ref, "quantity": body.quantity, "findings": [f["code"] for f in new]})
    return {"item_id": row["id"], "key": key, "findings": new, "cart": _public_cart(cart)}


class CartQtyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quantity: StrictInt = Field(ge=1, le=20)


def _own_cart_item(conn: Connection, user: User, item_id: str) -> dict:
    row = conn.execute(
        "SELECT id::text, patient_id::text, product_id::text, medication_request_id::text, quantity "
        "FROM pharmacy_cart_items WHERE id = %s FOR UPDATE",
        (_valid_id(item_id, "Cart item"),),
    ).fetchone()
    if row is None or row["patient_id"] != user.patient_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cart item not found")
    return row


@router.patch("/cart/items/{item_id}")
def update_cart_item(item_id: str, body: CartQtyIn, conn: Conn, user: Patient) -> dict:
    row = _own_cart_item(conn, user, item_id)
    if row["medication_request_id"] and body.quantity != 1:
        raise _err(422, "rx_quantity", "Prescriptions are ordered one fill at a time.")
    conn.execute("UPDATE pharmacy_cart_items SET quantity = %s WHERE id = %s", (body.quantity, row["id"]))
    cart = build_cart(conn, user.patient_id)
    blocked = _blocked_for(cart, f"cart:{row['id']}")
    if blocked:
        raise _err(422, blocked[0]["code"], blocked[0]["message"], findings=blocked)
    audit.record(conn, action="pharmacy_cart_item_updated", entity_type="pharmacy_cart_item", entity_id=row["id"],
                 actor=user, patient_id=user.patient_id, detail={"quantity": body.quantity})
    return _public_cart(cart)


@router.delete("/cart/items/{item_id}")
def remove_cart_item(item_id: str, conn: Conn, user: Patient) -> dict:
    row = _own_cart_item(conn, user, item_id)
    conn.execute("DELETE FROM pharmacy_cart_items WHERE id = %s", (row["id"],))
    audit.record(conn, action="pharmacy_cart_item_removed", entity_type="pharmacy_cart_item", entity_id=row["id"],
                 actor=user, patient_id=user.patient_id)
    return _public_cart(build_cart(conn, user.patient_id))


# --- Addresses ----------------------------------------------------------------------------------------------------

ADDRESS_COLS = """id::text, label, recipient_name, line1, line2, city, state, postal_code, phone, instructions,
                  is_default, created_at"""
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _clean(v: str | None, lo: int, hi: int, what: str, required: bool = True) -> str | None:
    if v is None or not v.strip():
        if required:
            raise ValueError(f"{what} is required")
        return None
    v = re.sub(r"\s+", " ", v.strip())
    if _CONTROL.search(v):
        raise ValueError(f"{what} has characters that aren't allowed")
    if not lo <= len(v) <= hi:
        raise ValueError(f"{what} must be {lo} to {hi} characters")
    return v


class AddressIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = "Home"
    recipient_name: str
    line1: str
    line2: str | None = None
    city: str
    state: str
    postal_code: str
    phone: str | None = None
    instructions: str | None = None
    make_default: StrictBool = False

    @field_validator("label")
    @classmethod
    def _label(cls, v):
        return _clean(v, 1, 40, "Label")

    @field_validator("recipient_name")
    @classmethod
    def _recipient(cls, v):
        return _clean(v, 2, 120, "Recipient name")

    @field_validator("line1")
    @classmethod
    def _line1(cls, v):
        v = _clean(v, 3, 200, "Street address")
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("Street address needs a street name")
        return v

    @field_validator("line2")
    @classmethod
    def _line2(cls, v):
        return _clean(v, 1, 200, "Apartment or unit", required=False)

    @field_validator("city")
    @classmethod
    def _city(cls, v):
        v = _clean(v, 2, 80, "City")
        if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", v):
            raise ValueError("City can contain letters, spaces, apostrophes and hyphens")
        return v

    @field_validator("state")
    @classmethod
    def _state(cls, v):
        v = (v or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", v):
            raise ValueError("State must be a two-letter code, like NY")
        return v

    @field_validator("postal_code")
    @classmethod
    def _zip(cls, v):
        v = (v or "").strip()
        if not re.fullmatch(r"\d{5}(-\d{4})?", v):
            raise ValueError("ZIP code must be 5 digits, like 10027")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        if v is None or not v.strip():
            return None
        digits = re.sub(r"\D", "", v)
        if not re.fullmatch(r"[\d\s()+.-]+", v.strip()) or not 10 <= len(digits) <= 15:
            raise ValueError("Phone number must have 10 to 15 digits")
        return ("+" if v.strip().startswith("+") else "") + digits

    @field_validator("instructions")
    @classmethod
    def _instructions(cls, v):
        v = _clean(v, 1, 200, "Delivery instructions", required=False)
        if v and CARD_LIKE.search(v):
            raise ValueError("Don't put card numbers in delivery instructions")
        return v


def _addresses(conn: Connection, patient_id: str) -> list[dict]:
    return conn.execute(
        f"""
        SELECT {ADDRESS_COLS} FROM pharmacy_delivery_addresses
        WHERE patient_id = %s AND archived_at IS NULL ORDER BY is_default DESC, created_at
        """,
        (patient_id,),
    ).fetchall()


@router.get("/addresses")
def list_addresses(conn: Conn, user: Patient) -> list[dict]:
    return _addresses(conn, user.patient_id)


@router.post("/addresses", status_code=status.HTTP_201_CREATED)
def add_address(body: AddressIn, conn: Conn, user: Patient) -> dict:
    existing = _addresses(conn, user.patient_id)
    if len(existing) >= MAX_ADDRESSES:
        raise _err(409, "too_many_addresses", f"You can save up to {MAX_ADDRESSES} addresses. Remove one first.")
    make_default = body.make_default or not existing
    if make_default:
        conn.execute(
            "UPDATE pharmacy_delivery_addresses SET is_default = false WHERE patient_id = %s AND archived_at IS NULL",
            (user.patient_id,),
        )
    row = conn.execute(
        f"""
        INSERT INTO pharmacy_delivery_addresses (patient_id, label, recipient_name, line1, line2, city, state,
                                                 postal_code, phone, instructions, is_default)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {ADDRESS_COLS}
        """,
        (user.patient_id, body.label, body.recipient_name, body.line1, body.line2, body.city, body.state,
         body.postal_code, body.phone, body.instructions, make_default),
    ).fetchone()
    audit.record(conn, action="delivery_address_added", entity_type="pharmacy_delivery_address", entity_id=row["id"],
                 actor=user, patient_id=user.patient_id)
    return row


@router.delete("/addresses/{address_id}")
def remove_address(address_id: str, conn: Conn, user: Patient) -> list[dict]:
    row = conn.execute(
        """
        UPDATE pharmacy_delivery_addresses SET archived_at = now(), is_default = false
        WHERE id = %s AND patient_id = %s AND archived_at IS NULL RETURNING id::text, is_default
        """,
        (_valid_id(address_id, "Address"), user.patient_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Address not found")
    rest = _addresses(conn, user.patient_id)
    if rest and not any(a["is_default"] for a in rest):
        conn.execute("UPDATE pharmacy_delivery_addresses SET is_default = true WHERE id = %s", (rest[0]["id"],))
    audit.record(conn, action="delivery_address_removed", entity_type="pharmacy_delivery_address",
                 entity_id=row["id"], actor=user, patient_id=user.patient_id)
    return _addresses(conn, user.patient_id)


# --- Delivery windows ---------------------------------------------------------------------------------------------


def delivery_windows(fulfillment: str, now: datetime | None = None) -> list[dict]:
    tz = clinic_tz()
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    today, tomorrow = now.date(), now.date() + timedelta(days=1)

    def at(d: date, hh: int, mm: int = 0) -> datetime:
        return datetime.combine(d, time(hh, mm), tzinfo=tz)

    out = []
    if fulfillment == "delivery":
        if now.hour < 14:
            out.append(("today_evening", "Today, 5 to 8 pm", at(today, 17), at(today, 20)))
        out += [
            ("tomorrow_morning", "Tomorrow, 9 am to 12 pm", at(tomorrow, 9), at(tomorrow, 12)),
            ("tomorrow_afternoon", "Tomorrow, 1 to 5 pm", at(tomorrow, 13), at(tomorrow, 17)),
            ("tomorrow_evening", "Tomorrow, 5 to 8 pm", at(tomorrow, 17), at(tomorrow, 20)),
        ]
    else:
        ready = now + timedelta(hours=2)
        if ready.date() == today and ready < at(today, 19):
            ready = ready.replace(minute=(ready.minute // 15) * 15, second=0, microsecond=0) + timedelta(minutes=15)
            out.append(("today_pickup", f"Today, from {_local_time(ready)} to 8 pm", ready, at(today, 20)))
        out.append(("tomorrow_pickup", "Tomorrow, 9 am to 8 pm", at(tomorrow, 9), at(tomorrow, 20)))
    return [{"code": c, "label": lbl, "start": s, "end": e} for c, lbl, s, e in out]


@router.get("/checkout-options")
def checkout_options(conn: Conn, user: Patient) -> dict:
    ph = conn.execute("SELECT id::text, name, address, phone, hours FROM pharmacies WHERE id = %s",
                      (CLINIC_PHARMACY_ID,)).fetchone()
    return {
        "windows": {"delivery": delivery_windows("delivery"), "pickup": delivery_windows("pickup")},
        "addresses": _addresses(conn, user.patient_id),
        "pickup_pharmacy": ph,
        "demo_cards": [{"token": t, "brand": b, "last4": l4, "label": f"Demo {b} ending {l4}"}
                       for t, (b, l4) in DEMO_CARDS.items()] + [
            {"token": "demo_tok_declined", "brand": "Demo", "last4": "0002", "label": "Demo card that is declined"}],
        "delivery_fee_cents": DELIVERY_FEE_CENTS, "free_delivery_over_cents": FREE_DELIVERY_OVER_CENTS,
        "payment_notice": PAYMENT_NOTICE, "courier_notice": COURIER_NOTICE,
    }


# --- Status machine -----------------------------------------------------------------------------------------------

ORDER_COLS = """
    o.id::text, o.number, o.patient_id::text, o.organization_id::text, o.status, o.fulfillment,
    o.pharmacy_id::text, o.address_id::text, o.address, o.window_code, o.window_label, o.window_start, o.window_end,
    o.cold_chain, o.requires_review, o.review_reasons, o.checks, o.patient_note, o.subtotal_cents,
    o.delivery_fee_cents, o.total_cents, o.counseling_note, o.rejection_reason, o.cancel_reason, o.courier_name,
    o.eta, o.delivery_proof, o.completed_at, o.reviewed_by::text, o.reviewed_at, o.placed_at, o.updated_at
"""

SETTABLE = {"counseling_note", "rejection_reason", "cancel_reason", "courier_name", "eta", "delivery_proof",
            "completed_at", "reviewed_by", "reviewed_at"}


def _notification(order: dict, to: str, conn: Connection) -> tuple[str, str, str]:
    n = order["number"]
    title = {
        "placed": f"Order {n} received",
        "pharmacist_review": f"A pharmacist is checking order {n}",
        "approved": f"Order {n} approved",
        "rejected": f"Order {n} couldn't be approved",
        "packed": f"Order {n} is packed",
        "out_for_delivery": f"Order {n} is out for delivery",
        "delivered": f"Order {n} was delivered",
        "ready_for_pickup": f"Order {n} is ready for pickup",
        "picked_up": f"Order {n} was picked up",
        "cancelled": f"Order {n} was cancelled",
    }[to]
    body = {
        "placed": "We've received your order.",
        "pharmacist_review": "A pharmacist checks some orders before they're packed. We'll let you know when it's done.",
        "approved": "Your pharmacist added a note for you. Open the order to read it."
        if order.get("counseling_note") else "Your order is approved and will be packed next.",
        "rejected": "Open the order to see why and what to do next. Your demo card was not charged.",
        "packed": "Your order is packed.",
        "out_for_delivery": (f"{order.get('courier_name') or 'The courier'} is on the way. Estimated arrival "
                             f"{_local_time(order['eta'])}." if order.get("eta") else "Your order is on the way."),
        "delivered": "Open the order for the delivery details.",
        "ready_for_pickup": "Collect it at the clinic pharmacy. Bring photo ID.",
        "picked_up": "Thanks for collecting your order.",
        "cancelled": "Your order was cancelled and your demo card was not charged.",
    }[to]
    return title, body, "high" if to == "rejected" else "normal"


def transition(conn: Connection, order: dict, to: str, *, actor: User | None, agent: str | None = None,
               note: str | None = None, sets: dict | None = None, now: datetime | None = None) -> dict:
    """Move an order to `to`. Illegal moves raise 409. Every move is recorded, audited and notified."""
    frm = order["status"]
    if to not in TRANSITIONS.get(frm, set()):
        raise _err(409, "illegal_transition",
                   f"An order that is {STATUS_LABELS[frm].lower()} can't become {STATUS_LABELS[to].lower()}.",
                   status=frm)
    if to in DELIVERY_ONLY and order["fulfillment"] != "delivery":
        raise _err(409, "illegal_transition", "This order is for pickup, not delivery.", status=frm)
    if to in PICKUP_ONLY and order["fulfillment"] != "pickup":
        raise _err(409, "illegal_transition", "This order is for delivery, not pickup.", status=frm)
    sets = dict(sets or {})
    bad = set(sets) - SETTABLE
    if bad:
        raise ValueError(f"not settable: {bad}")
    when = now or datetime.now(timezone.utc)
    if to in ("delivered", "picked_up"):
        sets.setdefault("completed_at", when)
    params = {**{k: (Jsonb(v) if isinstance(v, (dict, list)) else v) for k, v in sets.items()},
              "id": order["id"], "frm": frm, "to": to}
    assignments = "".join(f", {k} = %({k})s" for k in sets)
    row = conn.execute(
        f"""
        UPDATE pharmacy_orders SET status = %(to)s, updated_at = clock_timestamp(){assignments}
        WHERE id = %(id)s AND status = %(frm)s RETURNING id
        """,
        params,
    ).fetchone()
    if row is None:
        raise _err(409, "stale", "This order changed while you were looking at it. Refresh and try again.")
    conn.execute(
        """
        INSERT INTO pharmacy_order_events (order_id, patient_id, from_status, to_status, actor_user_id, actor_role,
                                           agent, note, at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, coalesce(%s, clock_timestamp()))
        """,
        (order["id"], order["patient_id"], frm, to, actor.id if actor else None,
         actor.role if actor else "system", agent, note, now),
    )
    if to in ("cancelled", "rejected"):
        conn.execute("UPDATE pharmacy_order_payments SET status = 'voided', updated_at = clock_timestamp() "
                     "WHERE order_id = %s AND status = 'authorized'", (order["id"],))
    elif to in ("delivered", "picked_up"):
        conn.execute("UPDATE pharmacy_order_payments SET status = 'captured', updated_at = clock_timestamp() "
                     "WHERE order_id = %s AND status = 'authorized'", (order["id"],))
        _complete_rx_fills(conn, order["id"], sets["completed_at"])
    audit.record(conn, action=f"pharmacy_order_{to}", entity_type="pharmacy_order", entity_id=order["id"],
                 actor=actor, agent=agent, patient_id=order["patient_id"],
                 detail={"number": order["number"], "from": frm, "to": to, "note": note,
                         **{k: v for k, v in sets.items() if k in ("courier_name", "eta", "delivery_proof")}})
    order = {**order, **sets, "status": to}
    uid = patient_user(conn, order["patient_id"])
    if uid:
        title, body, priority = _notification(order, to, conn)
        notify(conn, user_id=uid, kind="order_update", title=title, body=body, link=f"/shop/orders/{order['id']}",
               patient_id=order["patient_id"], priority=priority, channels=["in_app", "push"],
               dedupe_key=f"pharmacy_order:{order['id']}:{to}", created_by=agent or "pharmacy_orders")
    return order


def _load_order(conn: Connection, order_id: str, lock: bool = False) -> dict | None:
    return conn.execute(
        f"SELECT {ORDER_COLS} FROM pharmacy_orders o WHERE o.id = %s" + (" FOR UPDATE" if lock else ""),
        (_valid_id(order_id, "Order"),),
    ).fetchone()


def _patient_order(conn: Connection, user: User, order_id: str, lock: bool = False) -> dict:
    order = _load_order(conn, order_id, lock)
    if order is None or order["patient_id"] != user.patient_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return order


def _staff_order(conn: Connection, user: User, order_id: str, lock: bool = False) -> dict:
    order = _load_order(conn, order_id, lock)
    if order is None or order["organization_id"] != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return order


# --- Prescription fills ---------------------------------------------------------------------------------------------


def _fill_rx_items(conn: Connection, order: dict, now: datetime) -> list[str]:
    """At packing: use the fill already waiting, or create the refill at the clinic pharmacy."""
    made = []
    items = conn.execute(
        """
        SELECT id::text, medication_request_id::text, rx_mode, dispense_id::text, name
        FROM pharmacy_order_items WHERE order_id = %s AND kind = 'rx'
        """,
        (order["id"],),
    ).fetchall()
    for it in items:
        conn.execute("SELECT 1 FROM medication_requests WHERE id = %s FOR UPDATE", (it["medication_request_id"],))
        rx = conn.execute(RX_SELECT + " WHERE m.id = %s", (it["medication_request_id"],)).fetchone()
        if it["rx_mode"] == "ready_fill":
            if rx["dispense_id"] != it["dispense_id"] or rx["dispense_status"] != "ready":
                raise _err(409, "rx_changed", f"{it['name']}: the fill is no longer waiting at the pharmacy.")
            continue
        mode, reason = rx_eligibility(rx, ignore_open_order=True)
        if mode != "refill":
            raise _err(409, "rx_changed", f"{it['name']} can't be filled now: {reason}")
        dispense = conn.execute(
            """
            INSERT INTO medication_dispenses (medication_request_id, patient_id, pharmacy_id, fill_number, status,
                                              sent_at, ready_at)
            VALUES (%s, %s, %s,
                    (SELECT coalesce(max(fill_number), 0) + 1 FROM medication_dispenses WHERE medication_request_id = %s),
                    'ready', %s, %s)
            RETURNING id::text
            """,
            (rx["id"], order["patient_id"], order["pharmacy_id"], rx["id"], now, now),
        ).fetchone()["id"]
        conn.execute("UPDATE medication_requests SET refills_remaining = refills_remaining - 1 WHERE id = %s", (rx["id"],))
        conn.execute("UPDATE pharmacy_order_items SET dispense_id = %s WHERE id = %s", (dispense, it["id"]))
        made.append(dispense)
    return made


def _complete_rx_fills(conn: Connection, order_id: str, at: datetime) -> None:
    conn.execute(
        """
        UPDATE medication_dispenses SET status = 'picked_up', picked_up_at = %s
        WHERE status = 'ready' AND id IN (SELECT dispense_id FROM pharmacy_order_items
                                          WHERE order_id = %s AND dispense_id IS NOT NULL)
        """,
        (at, order_id),
    )


# --- Order views ----------------------------------------------------------------------------------------------------


def _items(conn: Connection, order_id: str) -> list[dict]:
    return conn.execute(
        """
        SELECT i.id::text, i.kind, i.product_id::text, i.medication_request_id::text, i.rx_mode, i.name, i.detail,
               i.quantity, i.unit_price_cents, i.line_total_cents, i.price_note, i.requires_refrigeration,
               'item:' || i.id::text AS key
        FROM pharmacy_order_items i WHERE i.order_id = %s ORDER BY i.kind DESC, i.name
        """,
        (order_id,),
    ).fetchall()


def _progress(order: dict, events: list[dict]) -> list[dict]:
    reached = {e["to_status"]: e["at"] for e in events}
    path = ["placed"]
    if order["requires_review"] or "pharmacist_review" in reached:
        path.append("pharmacist_review")
    path += ["approved", "packed"]
    path += ["out_for_delivery", "delivered"] if order["fulfillment"] == "delivery" else ["ready_for_pickup", "picked_up"]
    if order["status"] in ("rejected", "cancelled"):
        path = [s for s in path if s in reached] + [order["status"]]
    current = order["status"]
    out = []
    idx = path.index(current) if current in path else -1
    for i, s in enumerate(path):
        state = "done" if i < idx or (i == idx and current in TERMINAL) else "current" if i == idx else "upcoming"
        out.append({"status": s, "label": STATUS_LABELS[s], "at": reached.get(s), "state": state})
    return out


def order_view(conn: Connection, order: dict, *, staff: bool = False) -> dict:
    items = _items(conn, order["id"])
    events = conn.execute(
        """
        SELECT e.from_status, e.to_status, e.actor_role, e.agent, e.note, e.at, u.display_name AS actor_name
        FROM pharmacy_order_events e LEFT JOIN users u ON u.id = e.actor_user_id
        WHERE e.order_id = %s ORDER BY e.at, e.id
        """,
        (order["id"],),
    ).fetchall()
    for e in events:
        e["label"] = STATUS_LABELS[e["to_status"]]
        if not staff:
            e.pop("actor_name")  # patients see what happened, not staff names
    payment = conn.execute(
        """
        SELECT amount_cents, method, card_brand, card_last4, status, receipt_number, created_at
        FROM pharmacy_order_payments WHERE order_id = %s
        """,
        (order["id"],),
    ).fetchone()
    pharmacy = conn.execute("SELECT id::text, name, address, phone, hours FROM pharmacies WHERE id = %s",
                            (order["pharmacy_id"],)).fetchone()
    out = {
        **order,
        "status_label": STATUS_LABELS[order["status"]],
        "items": items, "events": events, "payment": payment, "pharmacy": pharmacy,
        "progress": _progress(order, events),
        "can_cancel": order["status"] in CANCELLABLE,
        "is_open": order["status"] in OPEN_STATUSES,
        "notices": {"payment": PAYMENT_NOTICE, "courier": COURIER_NOTICE},
    }
    if not staff:
        out.pop("reviewed_by", None)
    return out


# --- Checkout -----------------------------------------------------------------------------------------------------


class CheckoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fulfillment: Literal["delivery", "pickup"]
    address_id: str | None = None
    window_code: str = Field(max_length=40)
    payment: dict[str, Any]
    acknowledge_warnings: StrictBool = False
    note: str | None = Field(default=None, max_length=300)


def _payment_card(payment: dict[str, Any]) -> tuple[str, str]:
    """Only {"token": "<demo token>"}. Never echo what was sent: it might be a real card number."""
    if set(payment) != {"token"} or not isinstance(payment.get("token"), str) or len(payment["token"]) > 64:
        # A card number, CVV or expiry in any other field ends up here without being read or stored.
        if any(isinstance(v, str) and CARD_LIKE.search(v) for v in payment.values()):
            raise _err(422, "card_number_rejected", "That looks like a card number. This is a demo: never enter real "
                                                    "card details. Choose a demo card instead.")
        raise _err(422, "demo_token_only", "Payment accepts a demo card token only.")
    try:
        return parse_demo_token(payment["token"])
    except PaymentTokenError as e:
        raise _err(402 if e.code == "payment_declined" else 422, e.code, e.message) from None


@router.post("/checkout", status_code=status.HTTP_201_CREATED)
def checkout(body: CheckoutIn, conn: Conn, user: Patient) -> dict:
    pid = user.patient_id
    # One checkout at a time per patient: lock the patient row, then the cart.
    conn.execute("SELECT 1 FROM patients WHERE id = %s FOR UPDATE", (pid,))
    note = (body.note or "").strip() or None
    if note and CARD_LIKE.search(note):
        raise _err(422, "card_number_rejected", "Don't put card numbers in the note. This demo never takes card details.")
    cart = build_cart(conn, pid, body.fulfillment, lock=True)
    if not cart["items"]:
        raise _err(409, "empty_cart", "Your cart is empty.")
    gone = [i for i in cart["items"] if not i["available"]]
    if gone:
        raise _err(409, "rx_not_orderable", f"{gone[0]['name']}: {gone[0]['unavailable_reason']} Remove it to continue.")
    checks = cart["checks"]
    if checks["blocks"]:
        b = checks["blocks"][0]
        raise _err(422, b["code"], b["message"], findings=checks["blocks"])
    if checks["needs_acknowledgement"] and not body.acknowledge_warnings:
        raise _err(409, "acknowledge_warnings", "Please read the safety notes and confirm before you place the order.",
                   findings=[f for f in checks["findings"] if f["severity"] in ("high", "moderate")])

    address = address_id = None
    if body.fulfillment == "delivery":
        if not body.address_id:
            raise _err(422, "address_required", "Choose a delivery address.")
        a = conn.execute(
            f"SELECT {ADDRESS_COLS} FROM pharmacy_delivery_addresses WHERE id = %s AND patient_id = %s AND archived_at IS NULL",
            (_valid_id(body.address_id, "Address"), pid),
        ).fetchone()
        if a is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Address not found")
        address_id = a["id"]
        address = {k: a[k] for k in ("label", "recipient_name", "line1", "line2", "city", "state", "postal_code",
                                     "phone", "instructions")}
    elif body.address_id:
        raise _err(422, "address_not_needed", "Pickup orders don't need an address.")

    window = next((w for w in delivery_windows(body.fulfillment) if w["code"] == body.window_code), None)
    if window is None:
        raise _err(422, "invalid_window", "That time is no longer available. Choose another.")
    brand, last4 = _payment_card(body.payment)

    subtotal = cart["subtotal_cents"]
    fee = cart["delivery_fee_cents"] if body.fulfillment == "delivery" else 0
    order = conn.execute(
        f"""
        INSERT INTO pharmacy_orders (number, patient_id, organization_id, status, fulfillment, pharmacy_id, address_id,
                                     address, window_code, window_label, window_start, window_end, cold_chain,
                                     requires_review, review_reasons, patient_note, subtotal_cents, delivery_fee_cents,
                                     total_cents)
        VALUES ('BO-' || nextval('pharmacy_order_number_seq'), %s, %s, 'placed', %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s)
        RETURNING id::text
        """,
        (pid, user.organization_id, body.fulfillment, CLINIC_PHARMACY_ID, address_id,
         Jsonb(address) if address else None, window["code"], window["label"], window["start"], window["end"],
         checks["cold_chain"], checks["requires_review"], Jsonb(checks["review_reasons"]), note, subtotal, fee,
         subtotal + fee),
    ).fetchone()
    oid = order["id"]
    for it in cart["items"]:
        conn.execute(
            """
            INSERT INTO pharmacy_order_items (order_id, kind, product_id, medication_request_id, rx_mode, dispense_id,
                                              name, detail, quantity, unit_price_cents, line_total_cents, price_note,
                                              requires_refrigeration)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (oid, it["kind"], it.get("product_id"), it.get("medication_request_id"), it.get("rx_mode"),
             it.get("dispense_id"), it["name"], it["detail"], it["quantity"], it["unit_price_cents"],
             it["line_total_cents"], it["price_note"], it["requires_refrigeration"]),
        )
    # Snapshot of the checks as they apply to the order's own lines.
    snapshot = order_checks(conn, oid, pid, body.fulfillment)
    conn.execute("UPDATE pharmacy_orders SET checks = %s WHERE id = %s", (Jsonb(_strip_checks(snapshot)), oid))
    receipt = conn.execute(
        """
        INSERT INTO pharmacy_order_payments (order_id, patient_id, amount_cents, card_brand, card_last4, status,
                                             receipt_number)
        VALUES (%s, %s, %s, %s, %s, 'authorized', 'PO-' || nextval('pharmacy_order_receipt_seq'))
        RETURNING receipt_number
        """,
        (oid, pid, subtotal + fee, brand, last4),
    ).fetchone()["receipt_number"]
    conn.execute("DELETE FROM pharmacy_cart_items WHERE patient_id = %s", (pid,))

    order = _load_order(conn, oid)
    conn.execute(
        """
        INSERT INTO pharmacy_order_events (order_id, patient_id, from_status, to_status, actor_user_id, actor_role)
        VALUES (%s, %s, NULL, 'placed', %s, %s)
        """,
        (oid, pid, user.id, user.role),
    )
    audit.record(conn, action="pharmacy_order_placed", entity_type="pharmacy_order", entity_id=oid, actor=user,
                 patient_id=pid,
                 detail={"number": order["number"], "fulfillment": body.fulfillment, "items": len(cart["items"]),
                         "total_cents": subtotal + fee, "review_reasons": checks["review_reasons"],
                         "payment": {"method": "demo_card", "brand": brand, "last4": last4, "receipt": receipt}})
    title, text, _ = _notification(order, "placed", conn)
    notify(conn, user_id=user.id, kind="order_update", title=title, body=text, link=f"/shop/orders/{oid}",
           patient_id=pid, channels=["in_app", "push"], dedupe_key=f"pharmacy_order:{oid}:placed",
           created_by="pharmacy_orders")
    nxt = "pharmacist_review" if checks["requires_review"] else "approved"
    order = transition(conn, order, nxt, actor=None, agent="pharmacy-order-checks",
                       note=", ".join(checks["review_reasons"]) or "No flags: approved automatically")
    return order_view(conn, _load_order(conn, oid))


def _strip_checks(checks: dict) -> dict:
    return {k: checks[k] for k in ("findings", "requires_review", "review_reasons", "cold_chain", "deliverable", "notice")}


def order_checks(conn: Connection, order_id: str, patient_id: str, fulfillment: str | None) -> dict:
    """The checks re-run over an order's lines against the patient's record as it is now."""
    lines = []
    for it in _items(conn, order_id):
        if it["kind"] == "otc":
            prod = conn.execute(f"SELECT {PRODUCT_COLS} FROM otc_products WHERE id = %s", (it["product_id"],)).fetchone()
            lines.append(product_line(prod, it["quantity"], it["key"]))
        else:
            rx = conn.execute("SELECT id::text, drug_code, drug_name, strength FROM medication_requests WHERE id = %s",
                              (it["medication_request_id"],)).fetchone()
            lines.append(rx_line(rx, it["key"]))
    return run_checks(lines, patient_profile(conn, patient_id), fulfillment)


# --- Patient: orders -----------------------------------------------------------------------------------------------


@router.get("/orders")
def my_orders(conn: Conn, user: Patient) -> list[dict]:
    rows = conn.execute(
        f"""
        SELECT {ORDER_COLS},
               (SELECT count(*) FROM pharmacy_order_items i WHERE i.order_id = o.id)::int AS item_count,
               (SELECT string_agg(i.name, ', ' ORDER BY i.name) FROM pharmacy_order_items i WHERE i.order_id = o.id)
                   AS item_names
        FROM pharmacy_orders o WHERE o.patient_id = %s ORDER BY o.placed_at DESC LIMIT 50
        """,
        (user.patient_id,),
    ).fetchall()
    for r in rows:
        r["status_label"] = STATUS_LABELS[r["status"]]
        r["is_open"] = r["status"] in OPEN_STATUSES
        r.pop("reviewed_by")
    audit.record(conn, action="pharmacy_orders_viewed", entity_type="pharmacy_order", actor=user,
                 patient_id=user.patient_id)
    return rows


@router.get("/orders/{order_id}")
def my_order(order_id: str, conn: Conn, user: Patient) -> dict:
    order = _patient_order(conn, user, order_id)
    audit.record(conn, action="pharmacy_order_viewed", entity_type="pharmacy_order", entity_id=order["id"],
                 actor=user, patient_id=user.patient_id)
    return order_view(conn, order)


class CancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=300)


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str, body: CancelIn, conn: Conn, user: Patient) -> dict:
    order = _patient_order(conn, user, order_id, lock=True)
    if order["status"] not in CANCELLABLE:
        raise _err(409, "not_cancellable", "This order is already packed or finished, so it can't be cancelled here. "
                                           "Call the clinic pharmacy if you need help.")
    reason = (body.reason or "").strip() or None
    transition(conn, order, "cancelled", actor=user, note=reason, sets={"cancel_reason": reason})
    return order_view(conn, _load_order(conn, order["id"]))


# --- Pharmacist workspace -------------------------------------------------------------------------------------------


@router.get("/staff/queue")
def staff_queue(conn: Conn, user: Pharmacist, stage: Literal["review", "fulfil", "transit", "done"] = "review") -> dict:
    rows = conn.execute(
        f"""
        SELECT {ORDER_COLS}, p.name AS patient_name, p.birth_date,
               (SELECT count(*) FROM pharmacy_order_items i WHERE i.order_id = o.id)::int AS item_count,
               EXISTS (SELECT 1 FROM pharmacy_order_items i WHERE i.order_id = o.id AND i.kind = 'rx') AS has_rx
        FROM pharmacy_orders o JOIN patients p ON p.id = o.patient_id
        WHERE o.organization_id = %s AND o.status = ANY(%s)
        ORDER BY {"o.updated_at DESC" if stage == "done" else "o.placed_at"}
        LIMIT 100
        """,
        (user.organization_id, list(STAGES[stage])),
    ).fetchall()
    today = clinic_today()
    for r in rows:
        r["status_label"] = STATUS_LABELS[r["status"]]
        r["patient_age"] = patient_age(r.pop("birth_date"), today)
        r["flags"] = [f for f in r["checks"].get("findings", []) if f["severity"] in ("block", "high", "moderate")]
        r.pop("checks")
    counts = conn.execute(
        "SELECT status, count(*)::int AS n FROM pharmacy_orders WHERE organization_id = %s GROUP BY status",
        (user.organization_id,),
    ).fetchall()
    by_status = {c["status"]: c["n"] for c in counts}
    return {"stage": stage, "orders": rows,
            "counts": {s: sum(by_status.get(x, 0) for x in sts) for s, sts in STAGES.items() if s != "done"}}


@router.get("/staff/orders/{order_id}")
def staff_order(order_id: str, conn: Conn, user: Pharmacist) -> dict:
    order = _staff_order(conn, user, order_id)
    pid = order["patient_id"]
    patient = conn.execute("SELECT id::text, name, birth_date, allergies, pronouns FROM patients WHERE id = %s",
                           (pid,)).fetchone()
    patient["age"] = patient_age(patient["birth_date"], clinic_today())
    meds = conn.execute(
        """
        SELECT m.id::text, m.drug_name, m.strength, m.sig, pr.name AS prescriber_name, m.authored_at
        FROM medication_requests m JOIN practitioners pr ON pr.id = m.prescriber_id
        WHERE m.patient_id = %s AND m.status = 'active' ORDER BY m.authored_at DESC
        """,
        (pid,),
    ).fetchall()
    live = _strip_checks(order_checks(conn, order["id"], pid, order["fulfillment"]))
    audit.record(conn, action="pharmacy_order_viewed", entity_type="pharmacy_order", entity_id=order["id"],
                 actor=user, patient_id=pid, detail={"number": order["number"], "workspace": "pharmacist"})
    view = order_view(conn, order, staff=True)
    return {**view, "patient": patient, "current_meds": meds, "live_checks": live,
            "next_actions": sorted(TRANSITIONS.get(order["status"], set()) - {"cancelled", "pharmacist_review"})}


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    counseling_note: str | None = Field(default=None, max_length=1000)


@router.post("/staff/orders/{order_id}/approve")
def approve_order(order_id: str, body: ApproveIn, conn: Conn, user: Pharmacist) -> dict:
    order = _staff_order(conn, user, order_id, lock=True)
    if order["status"] != "pharmacist_review":
        raise _err(409, "illegal_transition", "Only orders waiting for a pharmacist check can be approved.",
                   status=order["status"])
    note = (body.counseling_note or "").strip() or None
    transition(conn, order, "approved", actor=user, note="Counseling note added" if note else None,
               sets={"counseling_note": note, "reviewed_by": user.id, "reviewed_at": datetime.now(timezone.utc)})
    return order_view(conn, _load_order(conn, order["id"]), staff=True)


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(max_length=1000)


@router.post("/staff/orders/{order_id}/reject")
def reject_order(order_id: str, body: RejectIn, conn: Conn, user: Pharmacist) -> dict:
    order = _staff_order(conn, user, order_id, lock=True)
    reason = body.reason.strip()
    if len(reason) < 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give the patient a reason")
    if order["status"] != "pharmacist_review":
        raise _err(409, "illegal_transition", "Only orders waiting for a pharmacist check can be rejected.",
                   status=order["status"])
    transition(conn, order, "rejected", actor=user, note=reason,
               sets={"rejection_reason": reason, "reviewed_by": user.id, "reviewed_at": datetime.now(timezone.utc)})
    return order_view(conn, _load_order(conn, order["id"]), staff=True)


@router.post("/staff/orders/{order_id}/pack")
def pack_order(order_id: str, conn: Conn, user: Pharmacist) -> dict:
    order = _staff_order(conn, user, order_id, lock=True)
    if order["status"] != "approved":
        raise _err(409, "illegal_transition", "Only approved orders can be packed.", status=order["status"])
    fills = _fill_rx_items(conn, order, datetime.now(timezone.utc))
    transition(conn, order, "packed", actor=user,
               note=f"{len(fills)} prescription fill(s) prepared at the clinic pharmacy" if fills else None)
    return order_view(conn, _load_order(conn, order["id"]), staff=True)


class DispatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    courier_name: str = Field(max_length=80)
    eta: datetime


@router.post("/staff/orders/{order_id}/dispatch")
def dispatch_order(order_id: str, body: DispatchIn, conn: Conn, user: Pharmacist) -> dict:
    order = _staff_order(conn, user, order_id, lock=True)
    courier = re.sub(r"\s+", " ", body.courier_name).strip()
    if len(courier) < 2 or _CONTROL.search(courier):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter the courier's name")
    if body.eta.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "ETA needs a time zone")
    now = datetime.now(timezone.utc)
    if not now - timedelta(minutes=5) <= body.eta <= now + timedelta(hours=48):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "ETA must be within the next 48 hours")
    if order["status"] != "packed" or order["fulfillment"] != "delivery":
        raise _err(409, "illegal_transition", "Only packed delivery orders can be sent out.", status=order["status"])
    transition(conn, order, "out_for_delivery", actor=user, note=f"Courier: {courier}",
               sets={"courier_name": courier, "eta": body.eta})
    return order_view(conn, _load_order(conn, order["id"]), staff=True)


@router.post("/staff/orders/{order_id}/ready-for-pickup")
def ready_for_pickup(order_id: str, conn: Conn, user: Pharmacist) -> dict:
    order = _staff_order(conn, user, order_id, lock=True)
    transition(conn, order, "ready_for_pickup", actor=user)
    return order_view(conn, _load_order(conn, order["id"]), staff=True)


class DeliverIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proof: Literal["recipient", "left_at_door"]
    recipient_name: str | None = Field(default=None, max_length=120)
    at: datetime | None = None


@router.post("/staff/orders/{order_id}/deliver")
def mark_delivered(order_id: str, body: DeliverIn, conn: Conn, user: Pharmacist) -> dict:
    order = _staff_order(conn, user, order_id, lock=True)
    now = datetime.now(timezone.utc)
    at = body.at or now
    if at.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Delivery time needs a time zone")
    if at > now + timedelta(minutes=5) or at < order["placed_at"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Delivery time must be between the order and now")
    if body.proof == "recipient":
        name = re.sub(r"\s+", " ", body.recipient_name or "").strip()
        if len(name) < 2:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter who received the order")
        proof = {"type": "recipient", "recipient_name": name, "at": at.isoformat()}
    else:
        if order["cold_chain"]:
            raise _err(422, "cold_chain_handover", "Cold-chain orders must be handed to someone, not left at the door.")
        proof = {"type": "left_at_door", "at": at.isoformat()}
    if order["status"] != "out_for_delivery":
        raise _err(409, "illegal_transition", "Only orders out for delivery can be marked delivered.",
                   status=order["status"])
    transition(conn, order, "delivered", actor=user, sets={"delivery_proof": proof, "completed_at": at})
    return order_view(conn, _load_order(conn, order["id"]), staff=True)


class PickupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient_name: str = Field(max_length=120)
    id_checked: StrictBool = False


@router.post("/staff/orders/{order_id}/picked-up")
def mark_picked_up(order_id: str, body: PickupIn, conn: Conn, user: Pharmacist) -> dict:
    order = _staff_order(conn, user, order_id, lock=True)
    name = re.sub(r"\s+", " ", body.recipient_name).strip()
    if len(name) < 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter who collected the order")
    controlled = any(f["code"] == "controlled_substance" for f in order["checks"].get("findings", []))
    if controlled and not body.id_checked:
        raise _err(422, "id_required", "This order has a controlled medicine: check photo ID before handing it over.")
    now = datetime.now(timezone.utc)
    transition(conn, order, "picked_up", actor=user,
               sets={"delivery_proof": {"type": "pickup", "recipient_name": name, "id_checked": body.id_checked,
                                        "at": now.isoformat()}})
    return order_view(conn, _load_order(conn, order["id"]), staff=True)
