import { useEffect, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { Warning } from "../../icons.jsx";
import { PageHeader, fmtStamp } from "./shared.jsx";

const MIN_REASON = 15;

function PatientSearch({ value, onPick }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (value || q.trim().length < 2) {
      setResults([]);
      return undefined;
    }
    const t = setTimeout(async () => {
      try {
        setResults(await api(`/governance/break-glass/patients?q=${encodeURIComponent(q.trim())}`));
        setError(null);
      } catch (e) {
        setError(e.message);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [q, value]);

  if (value) {
    return (
      <div className="toggle-row">
        <span style={{ flexGrow: 1 }}><strong>{value.name}</strong> <span className="muted small">born {value.birth_year}</span></span>
        <button type="button" className="btn sm" onClick={() => { onPick(null); setQ(""); }}>Change</button>
      </div>
    );
  }
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="field gv-field">
        <label htmlFor="bg-q">Patient name</label>
        <input id="bg-q" type="search" autoComplete="off" value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="Type at least two letters" />
      </div>
      {error && <div className="error-box">{error}</div>}
      {results.length > 0 && (
        <ul className="list gv-picks" aria-label="Matching patients">
          {results.map((p) => (
            <li key={p.id}>
              <button type="button" className="gv-pick" onClick={() => onPick(p)}>
                <strong>{p.name}</strong> <span className="muted small">born {p.birth_year}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {q.trim().length >= 2 && results.length === 0 && !error && <p className="tiny muted">No matching patients.</p>}
    </div>
  );
}

export default function BreakGlassPage() {
  const mine = useApi("/governance/break-glass/mine");
  const [patient, setPatient] = useState(null);
  const [reason, setReason] = useState("");
  const [minutes, setMinutes] = useState(60);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [granted, setGranted] = useState(null);

  const reasonOk = reason.trim().replace(/\s+/g, " ").length >= MIN_REASON;

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setGranted(null);
    try {
      const g = await api("/governance/break-glass", {
        method: "POST", body: { patient_id: patient.id, reason, minutes: Number(minutes) },
      });
      setGranted(g);
      setReason("");
      setPatient(null);
      mine.reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function end(id) {
    try {
      await api(`/governance/break-glass/${id}/end`, { method: "POST" });
      mine.reload();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <WorkspaceLayout>
      <PageHeader eyebrow="Trust and safety" title="Break-glass access"
                  sub="Open a patient's record outside your usual care relationship, for a stated reason." />
      <div className="ws-grid">
        <section className="span-5 stack">
          <form className="card stack" onSubmit={submit} aria-labelledby="bg-title">
            <span id="bg-title" className="card-title row" style={{ gap: 8 }}><Warning size={18} /> Request emergency access</span>
            <p className="small muted">
              Your reason is recorded permanently, shown to compliance, and listed in the patient's own access log.
              Access ends automatically.
            </p>
            <PatientSearch value={patient} onPick={setPatient} />
            <div className="field gv-field">
              <label htmlFor="bg-reason">Reason</label>
              <textarea id="bg-reason" className="edit" required value={reason} maxLength={1000}
                        aria-describedby="bg-reason-hint" onChange={(e) => setReason(e.target.value)} />
              <span id="bg-reason-hint" className="tiny muted">
                {reasonOk ? "Thanks. Be specific: this is reviewed." : `At least ${MIN_REASON} characters. Say why you need access now.`}
              </span>
            </div>
            <div className="field gv-field">
              <label htmlFor="bg-min">Access for</label>
              <select id="bg-min" value={minutes} onChange={(e) => setMinutes(e.target.value)}>
                <option value={15}>15 minutes</option>
                <option value={30}>30 minutes</option>
                <option value={60}>1 hour</option>
                <option value={120}>2 hours</option>
                <option value={240}>4 hours</option>
              </select>
            </div>
            <div aria-live="polite">
              {error && <div className="error-box">{error}</div>}
              {granted && (
                <div className="banner warn">
                  Access to {granted.patient_name} granted until {new Date(granted.expires_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}. Recorded in the audit trail.
                </div>
              )}
            </div>
            <button className="btn danger" type="submit" disabled={busy || !patient || !reasonOk} style={{ alignSelf: "flex-start" }}>
              {busy ? "Recording…" : "Break glass"}
            </button>
          </form>
          <div className="banner info">
            This version records and time-limits grants. Other screens do not yet check them: clinicians in your
            organization already reach its patients through the normal workspace.
          </div>
        </section>

        <section className="span-7 stack" aria-labelledby="bg-mine">
          <h2 id="bg-mine" className="card-title">My recent grants</h2>
          {mine.error && <div className="error-box">{mine.error.message}</div>}
          {mine.loading && !mine.data && <div className="card"><div className="skeleton" /></div>}
          {mine.data && mine.data.length === 0 && <div className="card empty">You haven't used break-glass access.</div>}
          {mine.data?.map((g) => (
            <article key={g.id} className="card stack" style={{ gap: 6 }}>
              <div className="row between wrap">
                <span className="strong">{g.patient_name}</span>
                <span className={`chip ${g.active ? "warn" : ""}`}>{g.active ? "Active" : g.revoked_at ? "Ended early" : "Expired"}</span>
              </div>
              <span className="small">{g.reason}</span>
              <span className="tiny muted">{fmtStamp(g.created_at)} to {fmtStamp(g.revoked_at || g.expires_at)}</span>
              {g.active && <button className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => end(g.id)}>End access now</button>}
            </article>
          ))}
        </section>
      </div>
    </WorkspaceLayout>
  );
}
