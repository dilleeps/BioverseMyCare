import { useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { fmtDateTime } from "../../format.js";
import { Check } from "../../icons.jsx";
import { Disclosure, STATUS, TONES } from "./shared.jsx";

function AgentReview({ agent, onDone }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const st = STATUS[agent.status] || { label: agent.status, cls: "" };
  const pending = agent.status === "pending_approval";

  async function decide(decision) {
    setBusy(true);
    setError(null);
    try {
      await api(`/specialists/admin/agents/${agent.id}/decision`, { method: "POST", body: { decision, note: note || null } });
      setNote("");
      onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const active = agent.guidance.filter((g) => g.status === "active");
  return (
    <article className={`card stack ${pending ? "highlight" : ""}`} aria-labelledby={`ap-${agent.id}`}>
      <div className="row between wrap">
        <div className="stack" style={{ gap: 2, minWidth: 0 }}>
          <h2 id={`ap-${agent.id}`} className="card-title">{agent.display_name}</h2>
          <span className="small muted">{agent.specialty} · Tone: {TONES.find((t) => t.id === agent.tone)?.label || agent.tone}</span>
        </div>
        <span className="row wrap" style={{ gap: 6 }}>
          {agent.paused && <span className="chip">Paused</span>}
          <span className={`chip ${st.cls}`}>{st.label}</span>
        </span>
      </div>
      {agent.headline && <p className="small strong">{agent.headline}</p>}
      {agent.bio && <p className="small">{agent.bio}</p>}
      <div className="row wrap" style={{ gap: 6 }}>
        {agent.topics.map((t) => <span key={t} className="chip">{t}</span>)}
      </div>
      <Disclosure text={agent.disclosure} />
      {agent.submitted_at && <span className="tiny muted">Submitted {fmtDateTime(agent.submitted_at)}</span>}

      <details className="ap-details" open={pending}>
        <summary className="small strong">Sample answers ({agent.samples.length}, {agent.samples.filter((s) => s.approved).length} approved by the clinician)</summary>
        <ul className="list ap-list">
          {agent.samples.map((s) => (
            <li key={s.id} className="stack" style={{ gap: 4 }}>
              <span className="small strong">Q: {s.question}</span>
              <p className="small ap-answer">{s.answer}</p>
              <span className="tiny muted">{s.citations.length} {s.citations.length === 1 ? "source" : "sources"}{s.approved ? " · approved" : " · not approved"}</span>
            </li>
          ))}
        </ul>
      </details>
      <details className="ap-details">
        <summary className="small strong">Guidance notes ({active.length})</summary>
        <ul className="list ap-list">
          {active.map((g) => (
            <li key={g.id} className="stack" style={{ gap: 4 }}>
              <span className="small strong">{g.title} <span className="chip">{g.topic}</span></span>
              <p className="small ap-answer">{g.body}</p>
            </li>
          ))}
        </ul>
      </details>

      {(pending || agent.status === "approved") && (
        <div className="stack" style={{ gap: 8 }}>
          <label className="stack" style={{ gap: 4 }}>
            <span className="small strong">{pending ? "Note to the clinician (required to send back)" : "Reason to withdraw approval"}</span>
            <textarea className="edit" value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
          </label>
          {error && <div className="error-box small" role="alert">{error}</div>}
          <div className="row wrap">
            {pending && (
              <button className="btn primary" disabled={busy} onClick={() => decide("approve")}><Check size={16} /> Approve and list</button>
            )}
            <button className="btn danger" disabled={busy || !note.trim()} onClick={() => decide("reject")}>
              {pending ? "Send back" : "Withdraw approval"}
            </button>
          </div>
        </div>
      )}
      {agent.review_note && !pending && <p className="tiny muted">Last review note: {agent.review_note}</p>}
    </article>
  );
}

export default function AdminApprovals() {
  const { data, error, loading, reload } = useApi("/specialists/admin/agents");
  const pending = data?.filter((a) => a.status === "pending_approval").length || 0;
  return (
    <WorkspaceLayout>
      <div className="page-head">
        <div>
          <h1 className="page-title">Public AI agents</h1>
          <p className="page-sub">
            Clinicians' public education assistants. Nothing is listed for patients until you approve it.
          </p>
        </div>
      </div>
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {error && <div className="error-box row between wrap"><span>{error.message}</span><button className="btn sm" onClick={reload}>Try again</button></div>}
      {data && (
        <div className="stack">
          <div className="banner info">{pending} waiting for approval · {data.filter((a) => a.listed).length} listed</div>
          {data.length === 0 && <div className="card empty">No clinician has set up a public agent yet.</div>}
          {data.map((a) => <AgentReview key={a.id} agent={a} onDone={reload} />)}
        </div>
      )}
    </WorkspaceLayout>
  );
}
