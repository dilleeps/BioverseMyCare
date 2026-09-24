import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { fmtDateTime } from "../../format.js";
import { Warning } from "../../icons.jsx";

const REPLY = { better: "Better", same: "About the same", worse: "Worse" };

function Escalation({ item, onDone }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const open = item.status === "open";
  const urgent = item.priority === "urgent";

  async function resolve() {
    setBusy(true);
    setErr(null);
    try {
      await api(`/companion/clinician/escalations/${item.review_item_id}/resolve`, {
        method: "POST", body: { note: note.trim() || null },
      });
      await onDone();
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  }

  return (
    <article className={`card stack ${urgent && open ? "alert" : ""}`} aria-label={`${item.patient_name}: ${item.title}`}>
      <div className="row between wrap">
        <span className="strong">{item.patient_name}</span>
        <span className="row" style={{ gap: 6 }}>
          {urgent && <span className="chip warn"><Warning size={12} /> Urgent</span>}
          <span className={`chip ${open ? "" : "ok"}`}>{open ? "Open" : "Reviewed"}</span>
        </span>
      </div>
      <div className="small">{item.title}</div>
      <dl className="cp-facts small">
        <div><dt>Check-in</dt><dd>{item.checkin_kind === "post_visit" ? `After ${item.subject}` : `New medicine · ${item.subject}`}</dd></div>
        <div><dt>Answer</dt><dd>{REPLY[item.response] || "—"}</dd></div>
        {item.note && <div><dt>They wrote</dt><dd>"{item.note}"</dd></div>}
        <div><dt>Why flagged</dt><dd>{item.escalation_reason}</dd></div>
        <div><dt>When</dt><dd>{fmtDateTime(item.answered_at)}</dd></div>
      </dl>
      {open ? (
        <div className="stack" style={{ gap: 8 }}>
          <label htmlFor={`cp-res-${item.review_item_id}`} className="small strong">Note (optional)</label>
          <textarea id={`cp-res-${item.review_item_id}`} className="edit" style={{ minHeight: 56 }} maxLength={1000}
                    value={note} onChange={(e) => setNote(e.target.value)} placeholder="For example: called the patient" />
          {err && <div className="error-box small">{err}</div>}
          <div><button className="btn dark" onClick={resolve} disabled={busy}>{busy ? "Saving…" : "Mark reviewed"}</button></div>
        </div>
      ) : (
        <p className="tiny muted">{item.resolution} · {fmtDateTime(item.resolved_at)}</p>
      )}
    </article>
  );
}

export default function ClinicianCompanion() {
  const [state, setState] = useState("open");
  const [params] = useSearchParams();
  const only = params.get("patient");
  const { data, error, loading, reload } = useApi(`/companion/clinician/escalations?state=${state}`);
  const items = (data?.items || []).filter((i) => !only || i.patient_id === only);

  return (
    <WorkspaceLayout>
      <div className="stack cp-ws">
        <div>
          <span className="eyebrow">Between visits</span>
          <h1 className="page-title">Check-in escalations</h1>
          <p className="page-sub">Patients who told the companion they feel worse, mentioned a possible side effect, or described warning signs.</p>
        </div>
        <div className="row wrap" role="group" aria-label="Show">
          {[["open", "Open"], ["all", "All"]].map(([k, label]) => (
            <button key={k} className={`btn ${state === k ? "dark" : ""}`} aria-pressed={state === k} onClick={() => setState(k)}>
              {label}
            </button>
          ))}
        </div>
        {error && <div className="error-box">{error.message}</div>}
        {loading && !data && <div className="card"><div className="skeleton" /></div>}
        {data && items.length === 0 && (
          <div className="card empty">{state === "open" ? "Nothing waiting. Escalations from check-ins will appear here." : "No escalations yet."}</div>
        )}
        {items.map((i) => <Escalation key={i.review_item_id} item={i} onDone={reload} />)}
      </div>
    </WorkspaceLayout>
  );
}
