import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { PatientPage } from "../../layouts.jsx";
import { Back, Lock } from "../../icons.jsx";
import { Address, Findings, money } from "./shared.jsx";

const EMPTY_ADDRESS = { label: "Home", recipient_name: "", line1: "", line2: "", city: "", state: "", postal_code: "", phone: "", instructions: "" };

function AddressForm({ onSaved, onCancel }) {
  const [a, setA] = useState(EMPTY_ADDRESS);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setA((s) => ({ ...s, [k]: e.target.value }));

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const body = Object.fromEntries(Object.entries(a).map(([k, v]) => [k, v.trim() === "" && k !== "label" ? null : v]));
      onSaved(await api("/pharmacy-orders/addresses", { method: "POST", body }));
    } catch (e2) {
      setErr(Array.isArray(e2.detail) ? e2.detail.map((d) => d.msg.replace(/^Value error, /, "")).join(". ") : e2.message);
      setBusy(false);
    }
  }

  const field = (k, label, props = {}) => (
    <div className="po-field">
      <label htmlFor={`addr-${k}`} className="small strong">{label}</label>
      <input id={`addr-${k}`} value={a[k]} onChange={set(k)} {...props} />
    </div>
  );
  return (
    <form className="stack po-address-form" onSubmit={save} aria-label="New address">
      <div className="po-form-grid">
        {field("recipient_name", "Recipient name", { required: true, autoComplete: "name", maxLength: 120 })}
        {field("label", "Label", { maxLength: 40, placeholder: "Home, Work" })}
        {field("line1", "Street address", { required: true, autoComplete: "address-line1", maxLength: 200 })}
        {field("line2", "Apartment or unit (optional)", { autoComplete: "address-line2", maxLength: 200 })}
        {field("city", "City", { required: true, autoComplete: "address-level2", maxLength: 80 })}
        {field("state", "State", { required: true, autoComplete: "address-level1", maxLength: 2, placeholder: "NY" })}
        {field("postal_code", "ZIP code", { required: true, autoComplete: "postal-code", inputMode: "numeric", maxLength: 10 })}
        {field("phone", "Phone for the courier (optional)", { autoComplete: "tel", inputMode: "tel", maxLength: 20 })}
      </div>
      {field("instructions", "Delivery instructions (optional)", { maxLength: 200, placeholder: "Buzzer, gate code, where to leave it" })}
      {err && <div className="error-box small">{err}</div>}
      <div className="row wrap" style={{ gap: 8 }}>
        <button className="btn dark" disabled={busy}>{busy ? "Saving…" : "Save address"}</button>
        <button type="button" className="btn ghost" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function Choice({ name, value, checked, onChange, disabled, children }) {
  return (
    <label className={`po-choice ${checked ? "on" : ""} ${disabled ? "off" : ""}`}>
      <input type="radio" name={name} value={value} checked={checked} disabled={disabled} onChange={() => onChange(value)} />
      <span className="stack" style={{ gap: 2, minWidth: 0 }}>{children}</span>
    </label>
  );
}

export default function Checkout() {
  const navigate = useNavigate();
  const options = useApi("/pharmacy-orders/checkout-options");
  const [fulfillment, setFulfillment] = useState("delivery");
  const cart = useApi(`/pharmacy-orders/cart?fulfillment=${fulfillment}`);
  const [addresses, setAddresses] = useState(null);
  const [addressId, setAddressId] = useState(null);
  const [adding, setAdding] = useState(false);
  const [windowCode, setWindowCode] = useState(null);
  const [token, setToken] = useState("demo_tok_visa");
  const [ack, setAck] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    document.title = "Checkout · Bioverse";
  }, []);
  useEffect(() => {
    if (options.data && addresses === null) {
      setAddresses(options.data.addresses);
      setAddressId(options.data.addresses.find((a) => a.is_default)?.id || options.data.addresses[0]?.id || null);
    }
  }, [options.data, addresses]);
  useEffect(() => {
    if (cart.data && !cart.data.deliverable && fulfillment === "delivery") setFulfillment("pickup");
  }, [cart.data, fulfillment]);
  const windows = options.data?.windows[fulfillment] || [];
  useEffect(() => {
    if (windows.length && !windows.some((w) => w.code === windowCode)) setWindowCode(windows[0].code);
  }, [windows, windowCode]);

  const c = cart.data;
  const fee = fulfillment === "delivery" ? c?.delivery_fee_cents || 0 : 0;
  const needsAck = c?.checks.needs_acknowledgement;
  const blocks = c?.checks.blocks || [];

  async function place() {
    setBusy(true);
    setErr(null);
    try {
      const order = await api("/pharmacy-orders/checkout", {
        method: "POST",
        body: {
          fulfillment, window_code: windowCode, address_id: fulfillment === "delivery" ? addressId : null,
          payment: { token }, acknowledge_warnings: ack, note: note.trim() || null,
        },
      });
      navigate(`/shop/orders/${order.id}`, { replace: true });
    } catch (e) {
      setErr(e.message);
      setBusy(false);
      cart.reload();
    }
  }

  if (options.error || cart.error) {
    return <PatientPage><div className="error-box">{(options.error || cart.error).message}</div></PatientPage>;
  }
  if (!options.data || !c) {
    return <PatientPage><div className="card" aria-busy="true"><div className="skeleton" /></div></PatientPage>;
  }
  if (c.items.length === 0) {
    return (
      <PatientPage>
        <div className="card empty stack">
          <span>Your cart is empty.</span>
          <Link to="/shop" className="btn primary">Browse medicines</Link>
        </div>
      </PatientPage>
    );
  }

  const ready = windowCode && (fulfillment === "pickup" || addressId) && !blocks.length && (!needsAck || ack);
  return (
    <PatientPage wide>
      <div className="page-head">
        <Link to="/shop" className="icon-btn" aria-label="Back to the shop"><Back size={18} /></Link>
        <div>
          <h1 className="page-title">Checkout</h1>
          <p className="page-sub">{c.items.length} item{c.items.length === 1 ? "" : "s"} · {money(c.subtotal_cents + fee)}</p>
        </div>
      </div>
      <div className="po-shop">
        <div className="stack" style={{ minWidth: 0 }}>
          <section className="card stack" aria-labelledby="po-how">
            <h2 id="po-how" className="card-title">How do you want it?</h2>
            <div className="po-choices two">
              <Choice name="fulfillment" value="delivery" checked={fulfillment === "delivery"} onChange={setFulfillment}
                      disabled={!c.deliverable}>
                <span className="strong">Home delivery</span>
                <span className="small muted">
                  {!c.deliverable ? "Not available: a controlled medicine is in your cart"
                    : c.delivery_fee_cents ? `${money(c.delivery_fee_cents)}, free over ${money(c.free_delivery_over_cents)}`
                      : "Free for this order"}
                </span>
              </Choice>
              <Choice name="fulfillment" value="pickup" checked={fulfillment === "pickup"} onChange={setFulfillment}>
                <span className="strong">Pickup at the clinic pharmacy</span>
                <span className="small muted">{options.data.pickup_pharmacy?.name} · free</span>
              </Choice>
            </div>
            {c.cold_chain && (
              <div className="banner info">Something in your order must stay cold. It's packed with an ice pack and handed to a person, not left at the door.</div>
            )}
          </section>

          {fulfillment === "delivery" ? (
            <section className="card stack" aria-labelledby="po-where">
              <h2 id="po-where" className="card-title">Deliver to</h2>
              {addresses?.length === 0 && !adding && <p className="small muted">Add an address to get deliveries.</p>}
              <div className="po-choices">
                {addresses?.map((a) => (
                  <Choice key={a.id} name="address" value={a.id} checked={addressId === a.id} onChange={setAddressId}>
                    <span className="strong small">{a.label}{a.is_default ? " · default" : ""}</span>
                    <Address a={a} />
                  </Choice>
                ))}
              </div>
              {adding ? (
                <AddressForm
                  onCancel={() => setAdding(false)}
                  onSaved={(a) => { setAddresses((s) => [...(s || []), a]); setAddressId(a.id); setAdding(false); }}
                />
              ) : (
                <button className="btn" onClick={() => setAdding(true)}>Add a new address</button>
              )}
            </section>
          ) : (
            <section className="card stack" aria-labelledby="po-pickup">
              <h2 id="po-pickup" className="card-title">Pick up at</h2>
              <p className="small"><strong>{options.data.pickup_pharmacy?.name}</strong>, {options.data.pickup_pharmacy?.address}</p>
              <p className="small muted">{options.data.pickup_pharmacy?.hours} · {options.data.pickup_pharmacy?.phone}</p>
              <p className="small muted">Bring photo ID. We'll tell you when it's ready.</p>
            </section>
          )}

          <section className="card stack" aria-labelledby="po-when">
            <h2 id="po-when" className="card-title">{fulfillment === "delivery" ? "Delivery window" : "Pickup time"}</h2>
            <div className="po-choices two">
              {windows.map((w) => (
                <Choice key={w.code} name="window" value={w.code} checked={windowCode === w.code} onChange={setWindowCode}>
                  <span className="strong small">{w.label}</span>
                </Choice>
              ))}
            </div>
            <p className="tiny muted">Orders that need a pharmacist check may take a little longer.</p>
          </section>

          <section className="card stack" aria-labelledby="po-pay">
            <div className="row between wrap">
              <h2 id="po-pay" className="card-title row" style={{ gap: 8 }}><Lock size={16} /> Payment</h2>
              <span className="chip warn">Demo payment</span>
            </div>
            <p className="small">{options.data.payment_notice}</p>
            <div className="po-choices">
              {options.data.demo_cards.map((card) => (
                <Choice key={card.token} name="card" value={card.token} checked={token === card.token} onChange={setToken}>
                  <span className="strong small">{card.label}</span>
                </Choice>
              ))}
            </div>
            <p className="tiny muted">You'll only be charged (in the demo) when your order is delivered or picked up.</p>
          </section>
        </div>

        <aside className="stack po-summary">
          <section className="card stack" aria-labelledby="po-sum">
            <h2 id="po-sum" className="card-title">Order summary</h2>
            <ul className="po-cart-items">
              {c.items.map((i) => (
                <li key={i.id} className="row between" style={{ gap: 8, alignItems: "flex-start" }}>
                  <span className="small">{i.quantity > 1 ? `${i.quantity} × ` : ""}{i.name}</span>
                  <span className="small strong">{money(i.line_total_cents)}</span>
                </li>
              ))}
            </ul>
            <dl className="po-totals">
              <div><dt>Subtotal</dt><dd>{money(c.subtotal_cents)}</dd></div>
              <div><dt>{fulfillment === "delivery" ? "Delivery" : "Pickup"}</dt><dd>{fee ? money(fee) : "Free"}</dd></div>
              <div className="total"><dt>Total</dt><dd>{money(c.subtotal_cents + fee)}</dd></div>
            </dl>
          </section>
          {c.checks.findings.length > 0 && (
            <section className="card stack" aria-labelledby="po-safety">
              <h2 id="po-safety" className="card-title">Safety notes</h2>
              <Findings findings={c.checks.findings} />
              {needsAck && !blocks.length && (
                <label className="toggle-row po-ack">
                  <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                  <span className="small">I've read these notes. A pharmacist will check my order before it's packed.</span>
                </label>
              )}
              <p className="tiny muted">{c.checks.notice}</p>
            </section>
          )}
          <div className="po-field">
            <label htmlFor="po-note" className="small strong">Note for the pharmacist (optional)</label>
            <textarea id="po-note" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)}
                      placeholder="Anything they should know. Never card details." />
          </div>
          {err && <div className="error-box small" role="alert">{err}</div>}
          <button className="btn primary block" disabled={!ready || busy} onClick={place}>
            {busy ? "Placing order…" : `Place order · ${money(c.subtotal_cents + fee)}`}
          </button>
        </aside>
      </div>
    </PatientPage>
  );
}
