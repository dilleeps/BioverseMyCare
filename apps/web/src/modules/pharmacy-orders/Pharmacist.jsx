import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { Back } from "../../icons.jsx";
import { Address, Findings, OrderProgress, ProofText, StatusChip, fmtWhen, money } from "./shared.jsx";

const STAGES = [
  ["review", "To verify"],
  ["fulfil", "To pack"],
  ["transit", "Out and ready"],
  ["done", "Done"],
];

function NotPharmacist({ error }) {
  if (error?.status === 403) {
    return <div className="card empty">This workspace is for pharmacists. Switch to Lena Marsh, PharmD, to verify and fulfil orders.</div>;
  }
  return <div className="error-box">{error.message}</div>;
}

export function PharmacistQueue() {
  const [stage, setStage] = useState("review");
  const { data, error, loading } = useApi(`/pharmacy-orders/staff/queue?stage=${stage}`);
  useEffect(() => {
    document.title = "Pharmacy orders · Bioverse";
  }, []);

  return (
    <WorkspaceLayout>
      <div className="page-head">
        <div>
          <h1 className="page-title">Pharmacy orders</h1>
          <p className="page-sub">Verify flagged orders and prescriptions, then pack, send out and hand over.</p>
        </div>
      </div>
      <div className="row wrap" role="group" aria-label="Queue" style={{ gap: 6, marginBottom: 14 }}>
        {STAGES.map(([k, label]) => (
          <button key={k} className={`btn ${stage === k ? "dark" : ""}`} aria-pressed={stage === k} onClick={() => setStage(k)}>
            {label}{data?.counts?.[k] ? ` · ${data.counts[k]}` : ""}
          </button>
        ))}
      </div>
      {error && <NotPharmacist error={error} />}
      {loading && !data && <div className="card" aria-busy="true"><div className="skeleton" /></div>}
      {data?.orders.length === 0 && (
        <div className="card empty">{stage === "review" ? "Nothing waiting for verification. All caught up." : "No orders here right now."}</div>
      )}
      <ul className="po-order-list">
        {data?.orders.map((o) => (
          <li key={o.id}>
            <Link to={`/pharmacy-orders/${o.id}`} className="card po-order-row">
              <span className="stack" style={{ gap: 4, minWidth: 0, flexGrow: 1 }}>
                <span className="row between wrap" style={{ gap: 6 }}>
                  <span className="strong">{o.number} · {o.patient_name}, {o.patient_age}</span>
                  <StatusChip status={o.status} label={o.status_label} />
                </span>
                <span className="small muted">
                  {o.item_count} item{o.item_count === 1 ? "" : "s"}{o.has_rx ? " incl. prescription" : ""} ·{" "}
                  {o.fulfillment === "delivery" ? "Delivery" : "Pickup"} · {o.window_label} · placed {fmtWhen(o.placed_at)}
                </span>
                {(o.flags.length > 0 || o.cold_chain) && (
                  <span className="row wrap" style={{ gap: 4 }}>
                    {o.cold_chain && <span className="chip">Cold chain</span>}
                    {o.flags.map((f, i) => <span key={i} className="chip warn">{f.title}</span>)}
                  </span>
                )}
                {o.status === "out_for_delivery" && o.eta && <span className="tiny muted">{o.courier_name} · ETA {fmtWhen(o.eta)}</span>}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </WorkspaceLayout>
  );
}

function localInput(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function Actions({ o, onDone }) {
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [courier, setCourier] = useState("Northside Demo Courier");
  const [eta, setEta] = useState(localInput(new Date(Date.now() + 60 * 60000)));
  const [proof, setProof] = useState(o.cold_chain ? "recipient" : "left_at_door");
  const [recipient, setRecipient] = useState(o.address?.recipient_name || "");
  const [leftAt, setLeftAt] = useState(localInput(new Date()));
  const [idChecked, setIdChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function run(action, body = {}) {
    setBusy(true);
    setErr(null);
    try {
      await api(`/pharmacy-orders/staff/orders/${o.id}/${action}`, { method: "POST", body });
      await onDone();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  const error = err && <div className="error-box small" role="alert">{err}</div>;
  if (o.status === "pharmacist_review" || o.status === "placed") {
    return (
      <div className="stack">
        <div className="po-field">
          <label htmlFor="cn" className="small strong">Counseling note for the patient (optional)</label>
          <textarea id="cn" maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)}
                    placeholder="Shown to the patient with their order" />
        </div>
        <button className="btn primary" disabled={busy} onClick={() => run("approve", { counseling_note: note.trim() || null })}>
          Approve order
        </button>
        <div className="po-divider" />
        <div className="po-field">
          <label htmlFor="rr" className="small strong">Reason for rejecting (shown to the patient)</label>
          <textarea id="rr" maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        <button className="btn danger" disabled={busy || reason.trim().length < 3} onClick={() => run("reject", { reason: reason.trim() })}>
          Reject order
        </button>
        {error}
      </div>
    );
  }
  if (o.status === "approved") {
    const rx = o.items.some((i) => i.kind === "rx");
    return (
      <div className="stack">
        {rx && <p className="small muted">Packing fills the prescription at the clinic pharmacy (or uses the fill already waiting).</p>}
        <button className="btn primary" disabled={busy} onClick={() => run("pack")}>Mark packed</button>
        {error}
      </div>
    );
  }
  if (o.status === "packed" && o.fulfillment === "delivery") {
    return (
      <div className="stack">
        <div className="po-field">
          <label htmlFor="cour" className="small strong">Courier</label>
          <input id="cour" maxLength={80} value={courier} onChange={(e) => setCourier(e.target.value)} />
        </div>
        <div className="po-field">
          <label htmlFor="eta" className="small strong">Estimated arrival</label>
          <input id="eta" type="datetime-local" value={eta} onChange={(e) => setEta(e.target.value)} />
        </div>
        <button className="btn primary" disabled={busy || courier.trim().length < 2 || !eta}
                onClick={() => run("dispatch", { courier_name: courier.trim(), eta: new Date(eta).toISOString() })}>
          Send out for delivery
        </button>
        {error}
      </div>
    );
  }
  if (o.status === "packed") {
    return (
      <div className="stack">
        <button className="btn primary" disabled={busy} onClick={() => run("ready-for-pickup")}>Ready for pickup</button>
        {error}
      </div>
    );
  }
  if (o.status === "out_for_delivery") {
    return (
      <div className="stack">
        <fieldset className="po-fieldset">
          <legend className="small strong">Proof of delivery</legend>
          <label className="toggle-row">
            <input type="radio" name="proof" checked={proof === "recipient"} onChange={() => setProof("recipient")} />
            <span className="small">Handed to someone</span>
          </label>
          <label className="toggle-row">
            <input type="radio" name="proof" checked={proof === "left_at_door"} disabled={o.cold_chain}
                   onChange={() => setProof("left_at_door")} />
            <span className="small">Left at the door{o.cold_chain ? " (not allowed for cold-chain orders)" : ""}</span>
          </label>
        </fieldset>
        {proof === "recipient" ? (
          <div className="po-field">
            <label htmlFor="rcpt" className="small strong">Received by</label>
            <input id="rcpt" maxLength={120} value={recipient} onChange={(e) => setRecipient(e.target.value)} />
          </div>
        ) : (
          <div className="po-field">
            <label htmlFor="left" className="small strong">Left at</label>
            <input id="left" type="datetime-local" value={leftAt} onChange={(e) => setLeftAt(e.target.value)} />
          </div>
        )}
        <button className="btn primary" disabled={busy || (proof === "recipient" && recipient.trim().length < 2)}
                onClick={() => run("deliver", proof === "recipient"
                  ? { proof, recipient_name: recipient.trim() }
                  : { proof, at: new Date(leftAt).toISOString() })}>
          Mark delivered
        </button>
        {error}
      </div>
    );
  }
  if (o.status === "ready_for_pickup") {
    return (
      <div className="stack">
        <div className="po-field">
          <label htmlFor="coll" className="small strong">Collected by</label>
          <input id="coll" maxLength={120} value={recipient} onChange={(e) => setRecipient(e.target.value)} />
        </div>
        <label className="toggle-row">
          <input type="checkbox" checked={idChecked} onChange={(e) => setIdChecked(e.target.checked)} />
          <span className="small">Photo ID checked</span>
        </label>
        <button className="btn primary" disabled={busy || recipient.trim().length < 2}
                onClick={() => run("picked-up", { recipient_name: recipient.trim(), id_checked: idChecked })}>
          Mark picked up
        </button>
        {error}
      </div>
    );
  }
  return <p className="small muted">Nothing more to do on this order.</p>;
}

export function PharmacistOrder() {
  const { orderId } = useParams();
  const { data: o, error, loading, reload } = useApi(`/pharmacy-orders/staff/orders/${orderId}`);
  useEffect(() => {
    document.title = "Verify order · Bioverse";
  }, []);

  return (
    <WorkspaceLayout>
      <div className="page-head po-head">
        <Link to="/pharmacy-orders" className="icon-btn" aria-label="Back to the queue"><Back size={18} /></Link>
        <div style={{ flexGrow: 1, minWidth: 0 }}>
          <h1 className="page-title">{o ? `Order ${o.number}` : "Order"}</h1>
          {o && <p className="page-sub">{o.patient.name}, {o.patient.age} · placed {fmtWhen(o.placed_at)}</p>}
        </div>
        {o && <StatusChip status={o.status} label={o.status_label} />}
      </div>
      {error && <NotPharmacist error={error} />}
      {loading && !o && <div className="card" aria-busy="true"><div className="skeleton" /></div>}
      {o && (
        <div className="po-verify">
          <div className="stack" style={{ minWidth: 0 }}>
            <section className="card stack" aria-labelledby="v-checks">
              <h2 id="v-checks" className="card-title">Check results</h2>
              {o.live_checks.findings.length === 0 ? (
                <div className="banner ok">No flags from the demo checks.</div>
              ) : <Findings findings={o.live_checks.findings} showReview={false} />}
              <p className="tiny muted">Re-run now against the patient's current record. The demo tables are short: use your own references.</p>
            </section>
            <section className="card stack" aria-labelledby="v-items">
              <h2 id="v-items" className="card-title">Items</h2>
              <ul className="po-cart-items">
                {o.items.map((i) => (
                  <li key={i.id} className="stack" style={{ gap: 4 }}>
                    <div className="row between" style={{ gap: 8, alignItems: "flex-start" }}>
                      <span className="stack" style={{ gap: 2, minWidth: 0 }}>
                        <span className="small strong">{i.quantity} × {i.name}</span>
                        <span className="tiny muted">{i.kind === "rx" ? `Prescription · ${i.rx_mode === "ready_fill" ? "fill waiting at pharmacy" : "new refill"}` : i.detail}</span>
                      </span>
                      <span className="small">{money(i.line_total_cents)}</span>
                    </div>
                    <Findings findings={o.live_checks.findings} only={[i.key]} compact />
                  </li>
                ))}
              </ul>
              {o.patient_note && <blockquote className="po-quote small">"{o.patient_note}"</blockquote>}
            </section>
            <section className="card stack" aria-labelledby="v-hist">
              <h2 id="v-hist" className="card-title">History</h2>
              <OrderProgress progress={o.progress} />
              <ul className="po-events">
                {o.events.map((e, i) => (
                  <li key={i} className="small">
                    <span className="strong">{e.label}</span> · {fmtWhen(e.at)} · {e.actor_name || (e.agent === "demo-courier" ? "Demo courier (simulation)" : "System")}
                    {e.note && <span className="muted"> · {e.note}</span>}
                  </li>
                ))}
              </ul>
            </section>
          </div>
          <aside className="stack" style={{ minWidth: 0 }}>
            <section className="card stack" aria-labelledby="v-act">
              <h2 id="v-act" className="card-title">Next step</h2>
              <Actions key={o.status} o={o} onDone={reload} />
            </section>
            <section className="card stack" aria-labelledby="v-pt">
              <h2 id="v-pt" className="card-title">Patient</h2>
              <p className="small"><strong>{o.patient.name}</strong>, {o.patient.age}{o.patient.pronouns ? ` · ${o.patient.pronouns}` : ""}</p>
              <div className="stack" style={{ gap: 4 }}>
                <span className="small strong">Allergies</span>
                {o.patient.allergies.length ? (
                  <span className="row wrap" style={{ gap: 4 }}>{o.patient.allergies.map((a) => <span key={a} className="chip warn">{a}</span>)}</span>
                ) : <span className="small muted">None recorded</span>}
              </div>
              <div className="stack" style={{ gap: 4 }}>
                <span className="small strong">Current medicines</span>
                {o.current_meds.length === 0 && <span className="small muted">No active prescriptions</span>}
                <ul className="po-meds">
                  {o.current_meds.map((m) => (
                    <li key={m.id} className="small"><strong>{m.drug_name} {m.strength}</strong><br /><span className="muted">{m.sig} · {m.prescriber_name}</span></li>
                  ))}
                </ul>
              </div>
            </section>
            <section className="card stack" aria-labelledby="v-del">
              <h2 id="v-del" className="card-title">{o.fulfillment === "delivery" ? "Delivery" : "Pickup"}</h2>
              {o.fulfillment === "delivery" ? <Address a={o.address} /> : <p className="small">{o.pharmacy?.name}</p>}
              <p className="small muted">{o.window_label}{o.cold_chain ? " · cold chain" : ""}</p>
              {o.courier_name && <p className="small">Courier: {o.courier_name}{o.eta ? ` · ETA ${fmtWhen(o.eta)}` : ""}</p>}
              {o.delivery_proof && <p className="small"><ProofText proof={o.delivery_proof} /></p>}
              {o.payment && <p className="tiny muted">Demo {o.payment.card_brand} ending {o.payment.card_last4} · {o.payment.status} · {money(o.total_cents)}</p>}
            </section>
          </aside>
        </div>
      )}
    </WorkspaceLayout>
  );
}
