import { useEffect, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { api } from "../api.js";
import { useApi } from "../hooks.js";
import { useSession } from "../session.jsx";
import { fmtDateTime, fmtShortDate, initials } from "../format.js";
import { Book, Calendar, Gear, Inbox, Person, Sparkle, Warning } from "../icons.jsx";

export function ClinicianNav({ patients, selected, onSelect }) {
  const { me } = useSession();
  return (
    <nav className="sidenav" aria-label="Clinician">
      <NavLink to="/clinician" end><Calendar size={18} /> Today</NavLink>
      <NavLink to="/clinician/agent"><Gear size={18} /> My agent</NavLink>
      {patients && (
        <>
          <div className="section">My patients</div>
          {patients.map((p) => (
            <button key={p.id} className="patient-pick" aria-current={p.id === selected} onClick={() => onSelect(p.id)}>
              <div className="who">{p.name}{p.open_items > 0 ? ` · ${p.open_items}` : ""}</div>
              <div className="meta">
                {p.age} · {p.pronouns || "—"}
                {p.next_appointment ? ` · ${fmtDateTime(p.next_appointment)}` : ""}
              </div>
            </button>
          ))}
        </>
      )}
      <div style={{ flexGrow: 1 }} />
      <div className="row" style={{ padding: "12px 8px", borderTop: "1px solid rgba(255,255,255,.12)" }}>
        <span className="avatar" style={{ width: 34, height: 34, background: "var(--accent-soft)", color: "var(--accent-strong)", fontSize: 13 }}>
          {initials(me.display_name)}
        </span>
        <span className="small strong">{me.display_name}</span>
      </div>
    </nav>
  );
}

function Brief({ patientId }) {
  const { data, error, loading } = useApi(`/clinician/patients/${patientId}/brief`);
  const [accepted, setAccepted] = useState(false);
  const [showSources, setShowSources] = useState(false);

  useEffect(() => {
    setAccepted(false);
    setShowSources(false);
  }, [patientId]);

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
            <div className="row wrap" style={{ gap: 8 }}>
              <button className="btn dark sm" onClick={() => setAccepted(true)} disabled={accepted}>Accept brief</button>
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

          <article className="card stack" style={{ gap: 8 }}>
            <span className="card-title">Evidence</span>
            <div className="banner info"><Book size={15} /> No evidence source connected.</div>
            <p className="small muted">
              Bioverse answers clinical questions only with cited sources. Connect a licensed guideline and drug-label
              index to enable cited answers here.
            </p>
          </article>
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
        {item.kind === "agent_escalation" && (
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
          <button className="btn danger sm" disabled={busy} onClick={() => resolve("acknowledge", false)}>Acknowledge</button>
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
    <div className="workspace">
      <ClinicianNav patients={patients.data} selected={selected} onSelect={setSelected} />
      <main className="ws-main">
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
      </main>
    </div>
  );
}
