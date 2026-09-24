import { useState } from "react";
import { Link } from "react-router-dom";
import { WorkspaceLayout } from "../../layouts.jsx";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { fmtDate, fmtShortDate } from "../../format.js";
import { Lock, Person } from "../../icons.jsx";
import { CriteriaList, INTEREST_LABELS, MatchChip } from "./shared.jsx";

const ACTION_LABELS = {
  contacted: "Mark contacted",
  screening: "Start screening",
  enrolled: "Mark enrolled",
  not_eligible: "Not eligible",
};
const PIPELINE = ["interested", "contacted", "screening", "enrolled"];

function InterestRow({ interest, transitions, onDone }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const next = interest.contact_permitted ? transitions[interest.status] || [] : [];

  async function move(status) {
    setBusy(true);
    setError(null);
    try {
      await api(`/research/interests/${interest.id}/status`, { method: "POST", body: { status } });
      await onDone(`${interest.short_title}: ${INTEREST_LABELS[status].toLowerCase()}`);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="queue-item">
      <div className="row between wrap">
        <Link to={`/research/studies/${interest.study_id}`} className="strong small">{interest.short_title}</Link>
        <span className={`chip ${interest.status === "enrolled" ? "ok" : ""}`}>{INTEREST_LABELS[interest.status]}</span>
      </div>
      <span className="tiny muted">Updated {fmtShortDate(interest.updated_at)}</span>
      {!interest.contact_permitted && interest.status !== "withdrawn" && (
        <span className="chip warn"><Lock size={12} /> Patient paused contact</span>
      )}
      {error && <div className="error-box small" role="alert">{error}</div>}
      {next.length > 0 && (
        <div className="row wrap" style={{ gap: 6 }}>
          {next.map((s) => (
            <button key={s} className={`btn sm ${s === "not_eligible" ? "" : "dark"}`} disabled={busy} onClick={() => move(s)}>
              {ACTION_LABELS[s]}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function PatientCard({ entry, transitions, onDone }) {
  const p = entry.patient;
  return (
    <article className="card stack" aria-labelledby={`rp-${p.id}`}>
      <div className="row between wrap">
        <div>
          <h2 id={`rp-${p.id}`} className="card-title">{p.name}</h2>
          <span className="tiny muted">{p.age} · opted in {fmtDate(entry.consented_at)}</span>
        </div>
        <span className="chip">{entry.matches.length} {entry.matches.length === 1 ? "match" : "matches"}</span>
      </div>
      <div className="ws-grid" style={{ gap: 12 }}>
        <section className="span-7 stack" style={{ gap: 8 }} aria-label={`Matches for ${p.name}`}>
          <span className="eyebrow">Matches</span>
          {entry.matches.length === 0 && <p className="small muted">No recruiting study matches.</p>}
          {entry.matches.map((m) => (
            <details key={m.study_id} className="rs-details">
              <summary className="row between wrap">
                <span className="small strong">{m.short_title}</span>
                <MatchChip status={m.status} label={m.status_label} />
              </summary>
              <CriteriaList criteria={m.criteria} />
            </details>
          ))}
        </section>
        <section className="span-5 stack" style={{ gap: 8 }} aria-label={`Interest for ${p.name}`}>
          <span className="eyebrow">Interest</span>
          {entry.interests.length === 0 && <p className="small muted">Hasn't asked about a study yet.</p>}
          {entry.interests.map((i) => (
            <InterestRow key={i.id} interest={i} transitions={transitions} onDone={onDone} />
          ))}
        </section>
      </div>
    </article>
  );
}

export default function Coordinator() {
  const { data, error, loading, reload } = useApi("/research/coordinator");
  const [toast, setToast] = useState(null);

  async function done(message) {
    await reload();
    setToast(message);
    setTimeout(() => setToast(null), 2600);
  }

  const counts = {};
  for (const entry of data?.patients || []) {
    for (const i of entry.interests) counts[i.status] = (counts[i.status] || 0) + 1;
  }

  return (
    <WorkspaceLayout>
      <div className="page-head">
        <div>
          <h1 className="page-title">Research</h1>
          <p className="page-sub">Only patients who opted in to research matching appear here. Eligibility is checked by rules against the record.</p>
        </div>
      </div>
      {error && <div className="error-box">{error.message}</div>}
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {data && (
        <div className="stack">
          <div className="stats" aria-label="Interest pipeline">
            {PIPELINE.map((s) => (
              <div key={s} className="stat">
                <div className="n">{counts[s] || 0}</div>
                <div className="tiny muted">{INTEREST_LABELS[s]}</div>
              </div>
            ))}
          </div>
          {data.patients.length === 0 && (
            <div className="card empty"><Person size={20} /> No patients in your organization have opted in to research matching.</div>
          )}
          {data.patients.map((entry) => (
            <PatientCard key={entry.patient.id} entry={entry} transitions={data.transitions} onDone={done} />
          ))}
        </div>
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
    </WorkspaceLayout>
  );
}
