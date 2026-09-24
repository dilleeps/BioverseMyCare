import { useEffect, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { fmtDateTime } from "../../format.js";
import { Warning } from "../../icons.jsx";
import { fmtDay, fmtShortDay } from "./format.js";

const FILTERS = [
  ["pending_approval", "Waiting"],
  ["decided", "Decided"],
];
const SEVERITY_LABEL = { major: "Serious", moderate: "Caution", advisory: "Advice" };

function age(birth) {
  const [y, m, d] = birth.split("-").map(Number);
  const now = new Date();
  return now.getFullYear() - y - (now.getMonth() + 1 < m || (now.getMonth() + 1 === m && now.getDate() < d) ? 1 : 0);
}

function DecisionForm({ req, onDone }) {
  const [extra, setExtra] = useState("0");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function decide(decision) {
    setBusy(true);
    setErr(null);
    try {
      const body = { decision, note: note.trim() || null };
      if (decision === "approve") body.additional_refills = Number(extra);
      const r = await api(`/pharmacy/clinician/refill-requests/${req.id}/decision`, { method: "POST", body });
      onDone(r.status);
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
        <div className="field" style={{ width: 220 }}>
          <label htmlFor={`extra-${req.id}`} className="small strong">Further refills after this one</label>
          <select id={`extra-${req.id}`} value={extra} onChange={(e) => setExtra(e.target.value)}>
            {[0, 1, 2, 3, 5, 11].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
      </div>
      <div className="field">
        <label htmlFor={`rnote-${req.id}`} className="small strong">Note to the patient (required to deny)</label>
        <textarea id={`rnote-${req.id}`} className="edit" style={{ minHeight: 64 }} maxLength={1000} value={note}
                  onChange={(e) => setNote(e.target.value)} />
      </div>
      {err && <div className="error-box small">{err}</div>}
      <div className="row wrap" style={{ gap: 8 }}>
        <button className="btn primary" disabled={busy} onClick={() => decide("approve")}>Approve and send to pharmacy</button>
        <button className="btn" disabled={busy || !note.trim()} onClick={() => decide("deny")}>Deny</button>
      </div>
    </div>
  );
}

export default function ClinicianRefills() {
  const [filter, setFilter] = useState("pending_approval");
  const { data, error, loading, reload } = useApi(`/pharmacy/clinician/refill-requests?status_filter=${filter}`);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    document.title = "Refill requests · Bioverse";
  }, []);
  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(null), 2800);
    return () => clearTimeout(t);
  }, [toast]);

  return (
    <WorkspaceLayout>
      <div className="refills-page">
        <div className="page-head">
          <div>
            <h1 className="page-title">Refill requests</h1>
            <p className="page-sub">Prescriptions of yours with no refills left. Approving sends one fill to the patient's pharmacy.</p>
          </div>
        </div>
        <div className="row wrap" role="group" aria-label="Filter refill requests" style={{ gap: 6, marginBottom: 14 }}>
          {FILTERS.map(([k, label]) => (
            <button key={k} className={`btn ${filter === k ? "dark" : ""}`} aria-pressed={filter === k} onClick={() => setFilter(k)}>
              {label}
            </button>
          ))}
        </div>
        {error && <div className="error-box">{error.message}</div>}
        {loading && !data && <div className="card" aria-busy="true"><div className="skeleton" /></div>}
        {data?.length === 0 && (
          <div className="card empty">{filter === "pending_approval" ? "No refill requests waiting. All caught up." : "No decided requests yet."}</div>
        )}
        <div className="stack">
          {data?.map((r) => {
            const a = r.adherence;
            const low = a?.tracking && a.pct_7 != null && a.days_7 >= 3 && a.pct_7 < a.target_pct;
            return (
              <article key={r.id} className="card stack" aria-labelledby={`req-${r.id}`}>
                <div className="row between wrap" style={{ alignItems: "flex-start" }}>
                  <div>
                    <h2 id={`req-${r.id}`} className="card-title">{r.drug_name} {r.strength} · {r.patient_name}</h2>
                    <div className="small muted">{age(r.birth_date)} · requested {fmtDateTime(r.created_at)} · {r.pharmacy_name}</div>
                  </div>
                  <span className={`chip ${r.status === "approved" ? "ok" : r.status === "denied" ? "warn" : ""}`}>
                    {r.status === "pending_approval" ? "Waiting for you" : r.status === "approved" ? "Approved" : "Denied"}
                  </span>
                </div>
                <dl className="rx-facts">
                  <div><dt>Directions</dt><dd>{r.sig}</dd></div>
                  <div><dt>Quantity</dt><dd>{r.quantity}</dd></div>
                  <div><dt>Refills</dt><dd>{r.refills_remaining} of {r.refills_authorized} left</dd></div>
                  <div><dt>Started</dt><dd>{fmtDay(r.authored_at)}</dd></div>
                  <div><dt>Adherence (patient-logged)</dt><dd className={low ? "alert-text" : ""}>
                    {a?.tracking && a.pct_7 != null ? `${a.pct_7}% over ${a.days_7} days (${a.taken_7} logged)` : "Not tracked"}
                  </dd></div>
                </dl>
                {r.patient_note && <blockquote className="patient-note small">"{r.patient_note}"</blockquote>}
                {r.interactions.length > 0 && (
                  <div className="stack" style={{ gap: 6 }}>
                    <span className="small strong">Curated interaction list</span>
                    {r.interactions.map((w) => (
                      <div key={w.id} className={`banner ${w.severity === "advisory" ? "info" : "warn"}`}>
                        <Warning size={15} /> <span>{SEVERITY_LABEL[w.severity]}: {w.between.join(" + ")}. {w.summary}</span>
                      </div>
                    ))}
                    <span className="tiny muted">Not exhaustive. Check a full interaction reference before prescribing.</span>
                  </div>
                )}
                {r.status === "pending_approval" ? (
                  <DecisionForm req={r} onDone={(s) => { setToast(s === "approved" ? "Approved and sent to the pharmacy" : "Refill denied"); reload(); }} />
                ) : (
                  <p className="small muted">Decided {fmtShortDay(r.decided_at)}.{r.decision_note ? ` Note: ${r.decision_note}` : ""}</p>
                )}
              </article>
            );
          })}
        </div>
        {toast && <div className="toast" role="status">{toast}</div>}
      </div>
    </WorkspaceLayout>
  );
}
