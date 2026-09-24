import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { fmtDateTime } from "../../format.js";
import { Shield, Warning } from "../../icons.jsx";
import { MODE_LABEL, ModeIcon, StatusChip, useToast } from "./shared.jsx";

function Item({ c, action, busy }) {
  return (
    <div className={`queue-item ${c.flagged ? "urgent" : ""}`}>
      <div className="row between wrap" style={{ alignItems: "flex-start" }}>
        <div className="stack" style={{ gap: 2, minWidth: 0 }}>
          <Link to={`/clinician/consults/${c.id}`} className="strong">{c.patient.name}, {c.patient.age}</Link>
          <span className="small muted">
            <ModeIcon mode={c.mode} size={14} /> {MODE_LABEL[c.mode]} · {c.specialty}
            {c.scheduled_at ? ` · ${fmtDateTime(c.scheduled_at)}` : ` · asked ${fmtDateTime(c.created_at)}`}
          </span>
        </div>
        <StatusChip status={c.status} label={c.status_label} />
      </div>
      {c.flagged && <span className="small strong" style={{ color: "var(--alert-strong)" }}><Warning size={14} /> Red flag raised</span>}
      <p className="small">"{c.reason}"</p>
      <div className="row wrap" style={{ gap: 8 }}>
        <Link className="btn sm" to={`/clinician/consults/${c.id}`}>Open</Link>
        {action && <button className="btn sm primary" disabled={busy} onClick={action.run}>{action.label}</button>}
      </div>
    </div>
  );
}

function Section({ title, items, empty, action }) {
  return (
    <section className="card stack" aria-label={title}>
      <h2 className="card-title">{title} {items.length > 0 && <span className="chip">{items.length}</span>}</h2>
      {items.length === 0 ? <p className="small muted">{empty}</p> : (
        <div className="stack" style={{ gap: 8 }}>{items.map((c) => <Item key={c.id} c={c} {...(action ? action(c) : {})} />)}</div>
      )}
    </section>
  );
}

export default function ClinicianQueue() {
  const { data, error, loading, reload } = useApi("/consultations/clinician/queue");
  const navigate = useNavigate();
  const [busy, setBusy] = useState(null);
  const [toast, setToast] = useToast();

  useEffect(() => { document.title = "Online consults · Bioverse"; }, []);
  useEffect(() => {
    const t = setInterval(() => document.visibilityState !== "hidden" && reload(), 20000);
    return () => clearInterval(t);
  }, [reload]);

  async function claim(c) {
    setBusy(c.id);
    try {
      await api(`/consultations/${c.id}/claim`, { method: "POST" });
      navigate(`/clinician/consults/${c.id}`);
    } catch (e) {
      setToast(e.message);
      setBusy(null);
      reload();
    }
  }

  return (
    <WorkspaceLayout>
      <div className="consult-ws">
        <div className="page-head">
          <div>
            <h1 className="page-title">Online consults</h1>
            <p className="page-sub">Requests to you, unclaimed requests in {data?.specialty || "your specialty"}, and consults under way.</p>
          </div>
        </div>
        {error && <div className="error-box">{error.message}</div>}
        {loading && !data && <div className="card"><div className="skeleton" /></div>}
        {data && (
          <div className="stack">
            <div className={`banner ${data.credential.credentialed ? "ok" : "warn"} small`} role="status">
              <Shield size={15} /> <span>{data.credential.message}</span>
            </div>
            <div className="consult-queue-grid">
              <Section title="Requests to you" items={data.requests} empty="No requests waiting for you." />
              <Section title={`Unclaimed in ${data.specialty || "your specialty"}`} items={data.unclaimed}
                       empty={data.credential.credentialed ? "Nothing unclaimed right now." : "Available once your license is verified."}
                       action={(c) => ({ action: { label: "Claim", run: () => claim(c) }, busy: busy === c.id })} />
              <Section title="Accepted and in progress" items={data.active} empty="No consults under way." />
              <Section title="Recently closed" items={data.recent} empty="None yet." />
            </div>
          </div>
        )}
      </div>
      {toast}
    </WorkspaceLayout>
  );
}
