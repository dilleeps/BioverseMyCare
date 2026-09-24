import { useEffect, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { fmtDate } from "../../format.js";
import { Check, Warning } from "../../icons.jsx";

const FILTERS = [
  ["pending", "Pending"],
  ["expiring", "Expiring soon"],
  ["attention", "Needs attention"],
  ["verified", "Verified"],
  ["all", "All"],
];

function expiryText(c) {
  if (c.days_to_expiry < 0) return `Expired ${fmtDate(c.expires_on)}`;
  if (c.days_to_expiry === 0) return "Expires today";
  return `Expires ${fmtDate(c.expires_on)} (${c.days_to_expiry} days)`;
}

function statusTone(c) {
  if (c.status === "verified" && !c.lapsed && !c.expiring_soon) return "ok";
  if (c.status === "pending") return "";
  return "warn";
}

function Decision({ cred, onDone }) {
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function run(action, body) {
    setBusy(true);
    setErr(null);
    try {
      const r = await api(`/credentialing/credentials/${cred.id}/${action}`, { method: "POST", body });
      onDone(r, action);
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  }

  if (cred.status === "pending") {
    return (
      <div className="stack" style={{ gap: 10 }}>
        <div className="field">
          <label htmlFor={`n-${cred.id}`} className="small strong">Verification note (optional)</label>
          <input id={`n-${cred.id}`} value={notes} maxLength={1000} onChange={(e) => setNotes(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor={`r-${cred.id}`} className="small strong">Reason (required to reject)</label>
          <input id={`r-${cred.id}`} value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)} />
        </div>
        {err && <div className="error-box small">{err}</div>}
        <div className="row wrap" style={{ gap: 8 }}>
          <button className="btn primary" disabled={busy || !cred.npi_valid}
                  onClick={() => run("verify", { notes: notes.trim() || null })}>Run checks and verify</button>
          <button className="btn" disabled={busy || reason.trim().length < 3} onClick={() => run("reject", { reason: reason.trim() })}>Reject</button>
        </div>
      </div>
    );
  }
  if (cred.status === "verified") {
    return (
      <details className="cred-more">
        <summary className="small strong">Suspend this license</summary>
        <div className="stack" style={{ gap: 8, marginTop: 8 }}>
          <div className="field">
            <label htmlFor={`s-${cred.id}`} className="small strong">Reason</label>
            <input id={`s-${cred.id}`} value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)} />
          </div>
          {err && <div className="error-box small">{err}</div>}
          <button className="btn danger" disabled={busy || reason.trim().length < 3}
                  onClick={() => run("suspend", { reason: reason.trim() })}>Suspend: remove from online consults now</button>
        </div>
      </details>
    );
  }
  return null;
}

function CredentialCard({ c, onDone }) {
  return (
    <article className="card stack" aria-labelledby={`cred-${c.id}`}>
      <div className="row between wrap" style={{ alignItems: "flex-start" }}>
        <div className="stack" style={{ gap: 2, minWidth: 0 }}>
          <h2 id={`cred-${c.id}`} className="card-title">{c.practitioner_name}</h2>
          <span className="small muted">{c.specialty} · {c.license_type} license {c.license_number} ({c.jurisdiction})</span>
        </div>
        <span className={`chip ${statusTone(c)}`}>{c.lapsed ? "Lapsed" : c.status_label}</span>
      </div>
      <dl className="cred-facts">
        <div><dt>NPI</dt><dd>{c.npi} {c.npi_valid
          ? <span className="chip ok"><Check size={12} /> check digit ok</span>
          : <span className="chip warn"><Warning size={12} /> check digit fails</span>}</dd></div>
        <div><dt>Board certification</dt><dd>{c.board_certification || "None given"}</dd></div>
        <div><dt>Dates</dt><dd>{c.issued_on ? `Issued ${fmtDate(c.issued_on)} · ` : ""}<span className={c.expiring_soon || c.lapsed ? "alert-text" : ""}>{expiryText(c)}</span></dd></div>
        <div><dt>Source</dt><dd>{c.source_label}</dd></div>
      </dl>
      {c.verified_at && <p className="small muted">Verified {fmtDate(c.verified_at)} by {c.verified_by_name || "an administrator"}.</p>}
      {c.decision_reason && <p className="small"><span className="strong">{c.status === "suspended" ? "Suspended" : "Rejected"}: </span>{c.decision_reason}</p>}
      {c.notes && <p className="small muted">Note: {c.notes}</p>}
      {c.verification_checks?.length > 0 && (
        <details>
          <summary className="small strong">What was checked</summary>
          <ul className="cred-checks small">
            {c.verification_checks.map((k) => (
              <li key={k.check}><span className="strong">{k.check}</span>: {k.result}. {k.detail}</li>
            ))}
          </ul>
        </details>
      )}
      <Decision cred={c} onDone={onDone} />
    </article>
  );
}

export default function Credentials() {
  const [filter, setFilter] = useState("pending");
  const { data, error, loading, reload } = useApi(`/credentialing/credentials?filter=${filter}`);
  const summary = useApi("/credentialing/summary");
  const [toast, setToast] = useState(null);

  useEffect(() => { document.title = "Credentialing · Bioverse"; }, []);
  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  const counts = summary.data || {};
  return (
    <WorkspaceLayout>
      <div className="cred-page">
        <div className="page-head">
          <div>
            <h1 className="page-title">Clinician credentialing</h1>
            <p className="page-sub">Only clinicians with a verified, in-date license appear in online consults.</p>
          </div>
        </div>
        <div className="stats" style={{ marginBottom: 14 }}>
          <div className="stat"><div className="n">{counts.pending ?? "–"}</div><div className="tiny muted">Pending</div></div>
          <div className={`stat ${counts.expiring ? "alert" : ""}`}><div className="n">{counts.expiring ?? "–"}</div><div className="tiny muted">Expiring in 60 days</div></div>
          <div className="stat"><div className="n">{counts.verified ?? "–"}</div><div className="tiny muted">Verified</div></div>
          <div className={`stat ${counts.attention ? "alert" : ""}`}><div className="n">{counts.attention ?? "–"}</div><div className="tiny muted">Needs attention</div></div>
        </div>
        <div className="banner info small" style={{ marginBottom: 14 }}>
          {data?.notice || "Demo verification: registry lookups are simulated."}
        </div>
        <div className="row wrap" role="group" aria-label="Filter credentials" style={{ gap: 6, marginBottom: 14 }}>
          {FILTERS.map(([k, label]) => (
            <button key={k} className={`btn ${filter === k ? "dark" : ""}`} aria-pressed={filter === k} onClick={() => setFilter(k)}>{label}</button>
          ))}
        </div>
        {error && <div className="error-box">{error.message}</div>}
        {loading && !data && <div className="card"><div className="skeleton" /></div>}
        {data?.credentials.length === 0 && <div className="card empty">Nothing here. All caught up.</div>}
        <div className="stack">
          {data?.credentials.map((c) => (
            <CredentialCard key={c.id} c={c} onDone={(r, action) => {
              setToast(action === "verify" ? `Verified ${r.practitioner_name}` : action === "reject" ? "License rejected" : "License suspended");
              reload();
              summary.reload();
            }} />
          ))}
        </div>
      </div>
      {toast && <div className="toast" role="status">{toast}</div>}
    </WorkspaceLayout>
  );
}
