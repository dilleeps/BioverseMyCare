import { useEffect, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { fmtShortDate } from "../../format.js";
import { Check } from "../../icons.jsx";
import { fmtMoney } from "./money.js";

const FILTERS = [
  ["submitted", "Waiting"],
  ["approved", "Approved"],
  ["denied", "Denied"],
  ["all", "All"],
];

function Decision({ app, onDone }) {
  const [pct, setPct] = useState(String(app.suggested_discount_pct || ""));
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const pctNum = Number(pct);
  const pctValid = Number.isInteger(pctNum) && pctNum >= 1 && pctNum <= 100;
  const preview = pctValid ? Math.min(app.open_balance_cents, Math.round((app.open_balance_cents * pctNum) / 100)) : 0;

  async function decide(decision) {
    setBusy(true);
    setErr(null);
    try {
      const body = { decision, note: note.trim() || null };
      if (decision === "approve") body.discount_pct = pctNum;
      const r = await api(`/billing/admin/assistance-applications/${app.id}/decision`, { method: "POST", body });
      onDone(r);
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
        <div className="field" style={{ width: 150 }}>
          <label htmlFor={`pct-${app.id}`} className="small strong">Discount %</label>
          <input id={`pct-${app.id}`} type="number" min="1" max="100" value={pct} onChange={(e) => setPct(e.target.value)}
                 aria-describedby={`pct-help-${app.id}`} />
        </div>
        <span id={`pct-help-${app.id}`} className="small muted">
          Policy suggests {app.suggested_discount_pct}%.{pctValid ? ` Reduces open bills by about ${fmtMoney(preview)}.` : ""}
        </span>
      </div>
      <div className="field">
        <label htmlFor={`note-${app.id}`} className="small strong">Note to the patient (required to deny)</label>
        <textarea id={`note-${app.id}`} className="edit" style={{ minHeight: 64 }} value={note} maxLength={1000}
                  onChange={(e) => setNote(e.target.value)} />
      </div>
      {err && <div className="error-box small">{err}</div>}
      <div className="row wrap" style={{ gap: 8 }}>
        <button className="btn primary" disabled={busy || !pctValid} onClick={() => decide("approve")}>
          Approve {pctValid ? `${pctNum}% discount` : ""}
        </button>
        <button className="btn" disabled={busy || !note.trim()} onClick={() => decide("deny")}>Deny</button>
      </div>
    </div>
  );
}

export default function AdminBilling() {
  const [filter, setFilter] = useState("submitted");
  const { data, error, loading, reload } = useApi(`/billing/admin/assistance-applications?status_filter=${filter}`);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    document.title = "Financial assistance · Bioverse";
  }, []);
  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(null), 3200);
    return () => clearTimeout(t);
  }, [toast]);

  return (
    <WorkspaceLayout>
      <div className="admin-billing">
      <div className="page-head">
        <div>
          <h1 className="page-title">Financial assistance</h1>
          <p className="page-sub">Review patient applications. Approval discounts every open balance for that patient.</p>
        </div>
      </div>
      <div className="banner info" style={{ marginBottom: 14 }}>
        Demo billing: balances come from the demo payer. Approving here changes demo statements only.
      </div>
      <div className="row wrap" role="group" aria-label="Filter applications" style={{ gap: 6, marginBottom: 14 }}>
        {FILTERS.map(([k, label]) => (
          <button key={k} className={`btn ${filter === k ? "dark" : ""}`} aria-pressed={filter === k} onClick={() => setFilter(k)}>
            {label}
          </button>
        ))}
      </div>
      {error && <div className="error-box">{error.message}</div>}
      {loading && !data && <div className="card" aria-busy="true"><div className="skeleton" /></div>}
      {data?.length === 0 && <div className="card empty">No applications here.</div>}
      <div className="stack">
        {data?.map((a) => (
          <article key={a.id} className="card stack" aria-labelledby={`app-${a.id}`}>
            <div className="row between wrap">
              <div>
                <h2 id={`app-${a.id}`} className="card-title">{a.patient_name}</h2>
                <div className="small muted">Applied {fmtShortDate(a.created_at)}</div>
              </div>
              <span className={`chip ${a.status === "approved" ? "ok" : a.status === "denied" ? "warn" : ""}`}>
                {a.status === "submitted" ? "Waiting for review" : a.status === "approved" ? `Approved · ${a.discount_pct}%` : "Denied"}
              </span>
            </div>
            <dl className="kv">
              <div><dt>Household</dt><dd>{a.household_size} {a.household_size === 1 ? "person" : "people"}</dd></div>
              <div><dt>Income</dt><dd>{a.income_band_label}</dd></div>
              <div><dt>Open balance</dt><dd>{fmtMoney(a.open_balance_cents)}</dd></div>
              <div><dt>Attestations</dt><dd>
                {Object.values(a.attestations || {}).every(Boolean) ? <span className="row" style={{ gap: 4 }}><Check size={14} /> All confirmed</span> : "Incomplete"}
              </dd></div>
            </dl>
            {a.status === "submitted" ? (
              <Decision app={a} onDone={(r) => {
                const total = (r.adjustments || []).reduce((s, x) => s + x.amount_cents, 0);
                setToast(r.status === "approved" ? `Approved. ${fmtMoney(total)} taken off ${a.patient_name}'s bills.` : "Application denied.");
                reload();
              }} />
            ) : (
              <p className="small muted">
                Decided {fmtShortDate(a.decided_at)}{a.decided_by_name ? ` by ${a.decided_by_name}` : ""}.
                {a.decision_note ? ` Note: ${a.decision_note}` : ""}
              </p>
            )}
          </article>
        ))}
      </div>
      {toast && <div className="toast" role="status">{toast}</div>}
      </div>
    </WorkspaceLayout>
  );
}
