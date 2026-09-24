import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { PatientPage } from "../../layouts.jsx";
import { Back, Check, Phone, Warning } from "../../icons.jsx";
import { Address, Findings, OrderProgress, ProofText, StatusChip, fmtWhen, money } from "./shared.jsx";
import { Truck } from "./icons.jsx";

export function Orders() {
  const { data, error, loading } = useApi("/pharmacy-orders/orders");
  useEffect(() => {
    document.title = "My medicine orders · Bioverse";
  }, []);
  return (
    <PatientPage>
      <div className="page-head">
        <Link to="/shop" className="icon-btn" aria-label="Back to the shop"><Back size={18} /></Link>
        <div>
          <h1 className="page-title">My orders</h1>
          <p className="page-sub">Medicine orders for delivery or pickup.</p>
        </div>
      </div>
      {error && <div className="error-box">{error.message}</div>}
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {data?.length === 0 && (
        <div className="card empty stack">
          <span>No orders yet.</span>
          <Link to="/shop" className="btn primary">Order medicines</Link>
        </div>
      )}
      <ul className="po-order-list">
        {data?.map((o) => (
          <li key={o.id}>
            <Link to={`/shop/orders/${o.id}`} className="card po-order-row">
              <span className="stack" style={{ gap: 2, minWidth: 0, flexGrow: 1 }}>
                <span className="row between wrap" style={{ gap: 6 }}>
                  <span className="strong">Order {o.number}</span>
                  <StatusChip status={o.status} label={o.status_label} />
                </span>
                <span className="small muted po-ellipsis">{o.item_names}</span>
                <span className="tiny muted">
                  Placed {fmtWhen(o.placed_at)} · {o.fulfillment === "delivery" ? "Delivery" : "Pickup"} · {money(o.total_cents)}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </PatientPage>
  );
}

function Tracking({ o }) {
  if (o.status === "out_for_delivery") {
    return (
      <section className="card stack po-tracking" aria-labelledby="po-track">
        <h2 id="po-track" className="card-title row" style={{ gap: 8 }}><Truck size={18} /> On the way</h2>
        <p className="po-eta">{o.eta ? <>Arriving around <strong>{fmtWhen(o.eta)}</strong></> : "Arriving today"}</p>
        <p className="small">Courier: {o.courier_name}</p>
        {o.cold_chain && <p className="small">Someone needs to be there to take it: it must stay cold.</p>}
        <p className="tiny muted">{o.notices.courier}</p>
      </section>
    );
  }
  if (o.status === "delivered" || o.status === "picked_up") {
    return (
      <section className="card stack po-tracking done" aria-labelledby="po-track">
        <h2 id="po-track" className="card-title row" style={{ gap: 8 }}><Check size={18} /> {o.status === "delivered" ? "Delivered" : "Picked up"}</h2>
        <p className="small"><ProofText proof={o.delivery_proof} /></p>
        {o.courier_name && <p className="small muted">Courier: {o.courier_name}</p>}
        <p className="small muted">Something wrong or missing? Call {o.pharmacy?.name} on <a href={`tel:${o.pharmacy?.phone.replace(/[^\d+]/g, "")}`}>{o.pharmacy?.phone}</a>.</p>
      </section>
    );
  }
  if (o.status === "ready_for_pickup") {
    return (
      <section className="card stack po-tracking" aria-labelledby="po-track">
        <h2 id="po-track" className="card-title">Ready for pickup</h2>
        <p className="small">Collect it at <strong>{o.pharmacy?.name}</strong>, {o.pharmacy?.address}. Bring photo ID.</p>
        <p className="small muted">{o.window_label} · {o.pharmacy?.hours}</p>
      </section>
    );
  }
  return null;
}

export function OrderDetail() {
  const { orderId } = useParams();
  const { data: o, error, loading, reload } = useApi(`/pharmacy-orders/orders/${orderId}`);
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    document.title = "Order tracking · Bioverse";
  }, []);
  useEffect(() => {
    if (!o?.is_open) return undefined;
    const t = setInterval(reload, 60000);
    return () => clearInterval(t);
  }, [o?.is_open, reload]);

  async function cancel() {
    setBusy(true);
    setErr(null);
    try {
      await api(`/pharmacy-orders/orders/${orderId}/cancel`, { method: "POST", body: { reason: reason.trim() || null } });
      setCancelling(false);
      await reload();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return <PatientPage><div className="error-box">{error.status === 404 ? "We couldn't find that order." : error.message}</div></PatientPage>;
  }
  if (loading && !o) return <PatientPage><div className="card" aria-busy="true"><div className="skeleton" /></div></PatientPage>;

  const flags = (o.checks.findings || []).filter((f) => f.severity !== "info" || f.review);
  return (
    <PatientPage wide>
      <div className="page-head po-head">
        <Link to="/shop/orders" className="icon-btn" aria-label="Back to my orders"><Back size={18} /></Link>
        <div style={{ flexGrow: 1, minWidth: 0 }}>
          <h1 className="page-title">Order {o.number}</h1>
          <p className="page-sub">Placed {fmtWhen(o.placed_at)} · {o.fulfillment === "delivery" ? "Home delivery" : "Pickup at the clinic pharmacy"}</p>
        </div>
        <StatusChip status={o.status} label={o.status_label} />
      </div>
      <div className="po-shop">
        <div className="stack" style={{ minWidth: 0 }}>
          <Tracking o={o} />
          {o.status === "pharmacist_review" && (
            <div className="banner info">A pharmacist is checking your order before it's packed. We'll let you know when it's done.</div>
          )}
          {o.status === "rejected" && (
            <section className="card alert stack" aria-labelledby="po-rej">
              <h2 id="po-rej" className="card-title row" style={{ gap: 8 }}><Warning size={18} /> Your pharmacist couldn't approve this order</h2>
              <p className="small">{o.rejection_reason}</p>
              <p className="small">Your demo card was not charged. Questions? Call {o.pharmacy?.name} on {o.pharmacy?.phone}.</p>
            </section>
          )}
          {o.counseling_note && (
            <section className="card stack po-counsel" aria-labelledby="po-cn">
              <h2 id="po-cn" className="card-title">A note from your pharmacist</h2>
              <p className="small">{o.counseling_note}</p>
            </section>
          )}
          {o.status === "cancelled" && (
            <div className="banner info">You cancelled this order{o.cancel_reason ? `: ${o.cancel_reason}` : ""}. Your demo card was not charged.</div>
          )}
          <section className="card stack" aria-labelledby="po-prog">
            <h2 id="po-prog" className="card-title">Progress</h2>
            <OrderProgress progress={o.progress} />
          </section>
          <section className="card stack" aria-labelledby="po-items">
            <h2 id="po-items" className="card-title">Items</h2>
            <ul className="po-cart-items">
              {o.items.map((i) => (
                <li key={i.id} className="row between" style={{ gap: 8, alignItems: "flex-start" }}>
                  <span className="stack" style={{ gap: 2, minWidth: 0 }}>
                    <span className="small strong">{i.quantity > 1 ? `${i.quantity} × ` : ""}{i.name}</span>
                    <span className="tiny muted">{i.kind === "rx" ? "Prescription" : i.detail}</span>
                  </span>
                  <span className="small strong">{money(i.line_total_cents)}</span>
                </li>
              ))}
            </ul>
            <dl className="po-totals">
              <div><dt>Subtotal</dt><dd>{money(o.subtotal_cents)}</dd></div>
              <div><dt>Delivery</dt><dd>{o.delivery_fee_cents ? money(o.delivery_fee_cents) : "Free"}</dd></div>
              <div className="total"><dt>Total</dt><dd>{money(o.total_cents)}</dd></div>
            </dl>
          </section>
        </div>
        <aside className="stack">
          <section className="card stack" aria-labelledby="po-del">
            <h2 id="po-del" className="card-title">{o.fulfillment === "delivery" ? "Delivery" : "Pickup"}</h2>
            {o.fulfillment === "delivery" ? <Address a={o.address} /> : (
              <p className="small"><strong>{o.pharmacy?.name}</strong><br />{o.pharmacy?.address}</p>
            )}
            <p className="small muted">{o.window_label}</p>
            {o.pharmacy && (
              <a className="small row" style={{ gap: 6 }} href={`tel:${o.pharmacy.phone.replace(/[^\d+]/g, "")}`}>
                <Phone size={14} /> {o.pharmacy.name} · {o.pharmacy.phone}
              </a>
            )}
          </section>
          {o.payment && (
            <section className="card stack" aria-labelledby="po-paid">
              <div className="row between wrap">
                <h2 id="po-paid" className="card-title">Payment</h2>
                <span className="chip warn">Demo</span>
              </div>
              <p className="small">
                Demo {o.payment.card_brand} ending {o.payment.card_last4} ·{" "}
                {o.payment.status === "captured" ? "charged" : o.payment.status === "voided" ? "not charged" : "charged when it's delivered or picked up"}
              </p>
              <p className="tiny muted">Receipt {o.payment.receipt_number}. {o.notices.payment}</p>
            </section>
          )}
          {flags.length > 0 && (
            <section className="card stack" aria-labelledby="po-notes">
              <h2 id="po-notes" className="card-title">Safety notes from your order</h2>
              <Findings findings={flags} showReview={false} />
            </section>
          )}
          {o.can_cancel && !cancelling && (
            <button className="btn" onClick={() => setCancelling(true)}>Cancel order</button>
          )}
          {cancelling && (
            <section className="card stack" aria-labelledby="po-cancel">
              <h2 id="po-cancel" className="card-title">Cancel this order?</h2>
              <p className="small">You can cancel until it's packed. Your demo card won't be charged.</p>
              <label htmlFor="po-reason" className="small strong">Reason (optional)</label>
              <textarea id="po-reason" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
              {err && <div className="error-box small">{err}</div>}
              <div className="row wrap" style={{ gap: 8 }}>
                <button className="btn danger" disabled={busy} onClick={cancel}>{busy ? "Cancelling…" : "Cancel order"}</button>
                <button className="btn ghost" onClick={() => setCancelling(false)}>Keep order</button>
              </div>
            </section>
          )}
        </aside>
      </div>
    </PatientPage>
  );
}
