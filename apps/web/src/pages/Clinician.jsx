import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { WorkspaceLayout } from "../layouts.jsx";
import { workspacePanels } from "../modules/registry.js";
import { api } from "../api.js";
import { useApi } from "../hooks.js";
import { useSession } from "../session.jsx";
import { fmtDateTime, fmtShortDate, initials } from "../format.js";
import { Inbox, Person, Sparkle, Warning } from "../icons.jsx";

// Kept for existing imports; the shared layout owns the side navigation now.
export { WorkspaceNav as ClinicianNav } from "../layouts.jsx";

function Brief({ patientId }) {
  const { data, error, loading } = useApi(`/clinician/patients/${patientId}/brief`);
  const [acceptedAt, setAcceptedAt] = useState(null);
  const [acceptError, setAcceptError] = useState(null);
  const [showSources, setShowSources] = useState(false);
  const accepted = Boolean(acceptedAt || data?.accepted_at);

  useEffect(() => {
    setAcceptedAt(null);
    setAcceptError(null);
    setShowSources(false);
  }, [patientId]);

  async function accept() {
    setAcceptError(null);
    try {
      const r = await api(`/clinician/patients/${patientId}/brief/accept`, { method: "POST" });
      setAcceptedAt(r.accepted_at);
    } catch (e) {
      setAcceptError(e.message);
    }
  }

  if (error) return <div className="error-box">{error.message}</div>;
  if (loading || !data) return <div className="card"><div className="skeleton" /></div>;
  const p = data.patient;

  return (
    <>
      <header className="row between wrap" style={{ marginBottom: 18 }}>
        <div className="row" style={{ gap: 14 }}>
          <span className="avatar">{initials(p.name)}</span>
          <div>
            <div className="page-title" style={{ fontSize: 26 }}>{p.name}</div>
            <div className="page-sub">
              {p.age} · {p.pronouns || "pronouns not recorded"} · prefers {p.preferred_language}
              {data.next_visit ? ` · next visit ${fmtDateTime(data.next_visit.starts_at)}` : ""}
            </div>
          </div>
        </div>
        <div className="row wrap" style={{ gap: 6 }}>
          {p.allergies.map((a) => <span key={a} className="chip warn"><Warning size={12} /> Allergy: {a}</span>)}
        </div>
      </header>

      <div className="ws-grid">
        <section className="span-7 stack">
          <article className="card stack">
            <div className="row between wrap">
              <span className="card-title">Pre-visit brief</span>
              <span className="chip"><Sparkle size={12} /> {accepted ? "Accepted by you" : "Drafted by Bioverse · review before use"}</span>
            </div>
            {data.bullets.length === 0 && <p className="small muted">Nothing new since the last visit.</p>}
            <ul style={{ margin: 0, paddingLeft: 18, color: "var(--ink-2)", fontSize: 14, lineHeight: 1.55 }}>
              {data.bullets.map((b, i) => (
                <li key={i} style={{ marginBottom: 6 }}>
                  {b.text}
                  {showSources && <span className="tiny muted"> [{b.source.type}{b.source.id ? ` ${b.source.id.slice(-6)}` : ` ${b.source.loinc}`}]</span>}
                </li>
              ))}
            </ul>
            {data.attention_flags.length > 0 && (
              <div className="row wrap" style={{ gap: 6 }}>
                {data.attention_flags.map((f) => <span key={f} className="chip warn">Attention: {f}</span>)}
              </div>
            )}
            {acceptError && <div className="error-box small">{acceptError}</div>}
            <div className="row wrap" style={{ gap: 8 }}>
              <button className="btn dark sm" onClick={accept} disabled={accepted}>{accepted ? "Accepted" : "Accept brief"}</button>
              <button className="btn sm" onClick={() => setShowSources((s) => !s)}>{showSources ? "Hide sources" : "View sources"}</button>
            </div>
          </article>

          {data.patient_questions.length > 0 && (
            <article className="card stack" style={{ gap: 8 }}>
              <span className="card-title">Patient's questions</span>
              {data.patient_questions.map((q) => (
                <div key={q} className="small" style={{ padding: "10px 12px", borderRadius: 12, background: "var(--ground)" }}>{q}</div>
              ))}
            </article>
          )}

          {workspacePanels().map(({ id, title, component: Panel }) => (
            <article key={id} className="card stack" aria-label={title}>
              <span className="card-title">{title}</span>
              <Panel patientId={patientId} />
            </article>
          ))}

        </section>

        <section className="span-5 card">
          <div className="row between" style={{ marginBottom: 6 }}>
            <span className="card-title">Timeline</span>
          </div>
          {data.timeline.map((e) => (
            <div key={`${e.type}-${e.ref_id}`} className="tl-item">
              <div className="tl-rail"><span className={`tl-dot ${e.tone}`} /><span className="tl-line" /></div>
              <div className="stack" style={{ gap: 1 }}>
                <span className="tiny muted">{fmtShortDate(e.at)}</span>
                {e.type === "report"
                  ? <Link to={`/results/${e.ref_id}`} className="strong small" style={{ color: "var(--ink)" }}>{e.title}</Link>
                  : <span className="strong small">{e.title}</span>}
                {e.detail && <span className="tiny muted">{e.detail}</span>}
              </div>
            </div>
          ))}
        </section>
      </div>
    </>
  );
}

function QueueItem({ item, onDone }) {
  const [mode, setMode] = useState(null); // "edit" | "reply"
  const [text, setText] = useState(item.kind === "result_explanation" ? item.body : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function resolve(action, withText) {
    setBusy(true);
    setError(null);
    try {
      await api(`/clinician/review-items/${item.id}/resolve`, {
        method: "POST",
        body: { action, text: withText ? text : null },
      });
      onDone(action);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <div className={`queue-item ${item.priority === "urgent" ? "urgent" : ""}`}>
      <span className="tiny strong" style={{ color: item.priority === "urgent" ? "var(--alert-strong)" : "var(--muted)" }}>
        {item.title} · {item.patient_name}
      </span>
      {mode ? (
        <>
          <label htmlFor={`edit-${item.id}`} className="sr-only">{mode === "edit" ? "Edit explanation" : "Reply"}</label>
          <textarea id={`edit-${item.id}`} className="edit" value={text} onChange={(e) => setText(e.target.value)} />
        </>
      ) : (
        <span className="small" style={{ lineHeight: 1.45 }}>{item.body}</span>
      )}
      {error && <div className="error-box small">{error}</div>}
      <div className="row wrap" style={{ gap: 6 }}>
        {item.kind === "result_explanation" && (
          <>
            <button className="btn primary sm" disabled={busy} onClick={() => resolve("approve", mode === "edit")}>
              {mode === "edit" ? "Approve edit" : "Approve"}
            </button>
            {!mode && <button className="btn sm" disabled={busy} onClick={() => setMode("edit")}>Edit</button>}
            <button className="btn sm" disabled={busy} onClick={() => resolve("reject", false)}>Reject</button>
          </>
        )}
        {item.kind === "agent_escalation" && item.link && (
          <>
            {/* The conversation lives in the inbox: replying there reaches the patient and resolves this item. */}
            <Link className="btn dark sm" to={item.link}>Open conversation</Link>
            <button className="btn sm" disabled={busy} onClick={() => resolve("forward_to_staff", false)}>To staff</button>
          </>
        )}
        {item.kind === "agent_escalation" && !item.link && (
          <>
            {mode === "reply" ? (
              <button className="btn dark sm" disabled={busy || !text.trim()} onClick={() => resolve("reply", true)}>Send reply</button>
            ) : (
              <button className="btn dark sm" disabled={busy} onClick={() => setMode("reply")}>Reply</button>
            )}
            <button className="btn sm" disabled={busy} onClick={() => resolve("forward_to_staff", false)}>To staff</button>
          </>
        )}
        {item.kind === "red_flag" && (
          <>
            {item.link && <Link className="btn dark sm" to={item.link}>Open</Link>}
            <button className="btn danger sm" disabled={busy} onClick={() => resolve("acknowledge", false)}>Acknowledge</button>
          </>
        )}
        {/* Module-owned items (refills, referrals...) are decided in their own screen, which resolves them.
            Acknowledging here would close the item and leave the decision undone. */}
        {!["result_explanation", "agent_escalation", "red_flag"].includes(item.kind) && (
          item.link
            ? <Link className="btn dark sm" to={item.link}>Open</Link>
            : <button className="btn sm" disabled={busy} onClick={() => resolve("acknowledge", false)}>Acknowledge</button>
        )}
      </div>
    </div>
  );
}

function ReviewQueue({ onChanged }) {
  const { data, error, reload } = useApi("/clinician/review-queue");
  const [toast, setToast] = useState(null);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2600);
    return () => clearTimeout(t);
  }, [toast]);

  const labels = { approve: "Approved and sent to the patient", reject: "Draft rejected", reply: "Reply sent",
    forward_to_staff: "Forwarded to staff", acknowledge: "Acknowledged" };

  return (
    <article className="card stack" aria-labelledby="queue-title">
      <div className="row between">
        <span id="queue-title" className="card-title row" style={{ gap: 8 }}><Inbox size={18} /> Review queue</span>
        <span className="small muted">{data ? `${data.length} waiting` : ""}</span>
      </div>
      {error && <div className="error-box">{error.message}</div>}
      {data?.length === 0 && <p className="small muted">All caught up.</p>}
      {data?.map((item) => (
        <QueueItem
          key={item.id}
          item={item}
          onDone={(action) => {
            setToast(labels[action]);
            reload();
            onChanged?.();
          }}
        />
      ))}
      {toast && <div className="toast" role="status">{toast}</div>}
    </article>
  );
}

export default function Clinician() {
  const patients = useApi("/clinician/patients");
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    if (!selected && patients.data?.length) setSelected(patients.data[0].id);
  }, [patients.data, selected]);

  return (
    <WorkspaceLayout patients={patients.data} selected={selected} onSelect={setSelected}>
        <div className="ws-grid">
          <div className="span-8">
            {patients.error && <div className="error-box">{patients.error.message}</div>}
            {patients.data?.length === 0 && (
              <div className="card empty"><Person size={20} /> No patients on your list yet.</div>
            )}
            {selected && <Brief key={selected} patientId={selected} />}
          </div>
          <div className="span-4">
            <ReviewQueue onChanged={patients.reload} />
          </div>
        </div>
    </WorkspaceLayout>
  );
}
