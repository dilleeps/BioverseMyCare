import { useEffect, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { fmtDateTime } from "../../format.js";
import { Check, Close, Plus, Warning } from "../../icons.jsx";
import { CitationList, Disclosure, KIND, STATUS, TONES } from "./shared.jsx";

function useAction(onDone) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function run(fn) {
    setBusy(true);
    setError(null);
    try {
      const out = await fn();
      onDone?.(out);
      return out;
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, run };
}

function ProfileForm({ agent, defaults, onSaved }) {
  const source = agent || { display_name: defaults.display_name, headline: "", bio: "", topics: [], tone: "warm" };
  const [form, setForm] = useState({ ...source, topics: [...source.topics] });
  const [topic, setTopic] = useState("");
  const [saved, setSaved] = useState(false);
  const act = useAction((out) => { onSaved(out); setSaved(true); });
  useEffect(() => setSaved(false), [form]);

  function addTopic(e) {
    e.preventDefault();
    const t = topic.trim();
    if (t && !form.topics.some((x) => x.toLowerCase() === t.toLowerCase()) && form.topics.length < 8) {
      setForm({ ...form, topics: [...form.topics, t] });
    }
    setTopic("");
  }

  const live = agent && (agent.status === "approved" || agent.status === "pending_approval");
  return (
    <section className="card stack" aria-labelledby="pa-profile">
      <h2 id="pa-profile" className="card-title">{agent ? "Public profile and scope" : "Set up your public agent"}</h2>
      {!agent && (
        <p className="small muted">
          Your public agent answers general education questions from patients, in your chosen topics, using only your
          guidance notes and the evidence library. It never gives personal advice and always says it is not you.
          An administrator approves it before it is listed.
        </p>
      )}
      <div className="pa-fields">
        <label className="stack pa-field">
          <span className="small strong">Name shown to the public</span>
          <input value={form.display_name} maxLength={120} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
        </label>
        <label className="stack pa-field">
          <span className="small strong">Tone</span>
          <select value={form.tone} onChange={(e) => setForm({ ...form, tone: e.target.value })}>
            {TONES.map((t) => <option key={t.id} value={t.id}>{t.label}: {t.hint}</option>)}
          </select>
        </label>
        <label className="stack pa-field wide">
          <span className="small strong">Headline</span>
          <input value={form.headline} maxLength={200} placeholder="For example: Blood pressure, cholesterol and heart-healthy living"
                 onChange={(e) => setForm({ ...form, headline: e.target.value })} />
        </label>
        <label className="stack pa-field wide">
          <span className="small strong">Short bio</span>
          <textarea className="edit" value={form.bio} maxLength={1500} onChange={(e) => setForm({ ...form, bio: e.target.value })} />
        </label>
      </div>
      <div className="stack" style={{ gap: 6 }}>
        <span className="small strong">Topics it may answer (scope)</span>
        <div className="row wrap" style={{ gap: 6 }}>
          {form.topics.length === 0 && <span className="tiny muted">No topics yet. Questions outside these topics are politely declined.</span>}
          {form.topics.map((t) => (
            <span key={t} className="chip pa-topic">
              {t}
              <button type="button" className="pa-x" aria-label={`Remove ${t}`}
                      onClick={() => setForm({ ...form, topics: form.topics.filter((x) => x !== t) })}>
                <Close size={12} />
              </button>
            </span>
          ))}
        </div>
        <form className="row wrap pa-add" onSubmit={addTopic}>
          <label htmlFor="pa-topic" className="sr-only">New topic</label>
          <input id="pa-topic" value={topic} maxLength={60} placeholder="Add a topic, e.g. Heart failure basics"
                 onChange={(e) => setTopic(e.target.value)} />
          <button className="btn sm" type="submit" disabled={!topic.trim()}><Plus size={14} /> Add topic</button>
        </form>
      </div>
      {live && (
        <div className="banner warn"><Warning size={15} /> Saving changes takes your agent off the list until an administrator approves it again.</div>
      )}
      {act.error && <div className="error-box small" role="alert">{act.error}</div>}
      <div className="row wrap">
        <button className="btn primary" disabled={act.busy || form.display_name.trim().length < 3}
                onClick={() => act.run(() => api("/specialists/clinician/agent", {
                  method: "PUT",
                  body: { display_name: form.display_name, headline: form.headline, bio: form.bio, topics: form.topics, tone: form.tone },
                }))}>
          {act.busy ? "Saving..." : agent ? "Save profile" : "Create my public agent"}
        </button>
        {saved && <span className="small muted" role="status">Saved.</span>}
      </div>
    </section>
  );
}

function GuidanceEditor({ initial, onSubmit, onCancel, submitLabel }) {
  const [g, setG] = useState(initial || { topic: "", title: "", body: "" });
  return (
    <div className="stack pa-guidance-form">
      <div className="pa-fields">
        <label className="stack pa-field"><span className="small strong">Topic</span>
          <input value={g.topic} maxLength={80} onChange={(e) => setG({ ...g, topic: e.target.value })} /></label>
        <label className="stack pa-field"><span className="small strong">Title</span>
          <input value={g.title} maxLength={160} onChange={(e) => setG({ ...g, title: e.target.value })} /></label>
        <label className="stack pa-field wide"><span className="small strong">Guidance</span>
          <textarea className="edit" value={g.body} maxLength={2000} onChange={(e) => setG({ ...g, body: e.target.value })} /></label>
      </div>
      <div className="row wrap">
        <button className="btn sm primary" type="button" disabled={g.topic.trim().length < 2 || g.title.trim().length < 2 || g.body.trim().length < 10}
                onClick={() => onSubmit(g)}>{submitLabel}</button>
        {onCancel && <button className="btn sm ghost" type="button" onClick={onCancel}>Cancel</button>}
      </div>
    </div>
  );
}

function GuidanceSection({ agent, onChange }) {
  const [editing, setEditing] = useState(null);
  const [adding, setAdding] = useState(false);
  const act = useAction((out) => { onChange(out); setEditing(null); setAdding(false); });
  const active = agent.guidance.filter((g) => g.status === "active");
  const retired = agent.guidance.filter((g) => g.status === "retired");
  return (
    <section className="card stack" aria-labelledby="pa-guidance">
      <div className="row between wrap">
        <h2 id="pa-guidance" className="card-title">Guidance notes</h2>
        {!adding && <button className="btn sm" onClick={() => setAdding(true)}><Plus size={14} /> Add a note</button>}
      </div>
      <p className="tiny muted">The only clinical voice your agent may quote. Keep each note general: no advice for a specific person.</p>
      {adding && (
        <GuidanceEditor submitLabel="Add note" onCancel={() => setAdding(false)}
                        onSubmit={(g) => act.run(() => api("/specialists/clinician/guidance", { method: "POST", body: g }))} />
      )}
      {active.length === 0 && !adding && <div className="empty small">No guidance notes yet.</div>}
      <ul className="list pa-list">
        {active.map((g) => (
          <li key={g.id} className="stack" style={{ gap: 6 }}>
            {editing === g.id ? (
              <GuidanceEditor initial={g} submitLabel="Save note" onCancel={() => setEditing(null)}
                              onSubmit={(v) => act.run(() => api(`/specialists/clinician/guidance/${g.id}`, { method: "PUT", body: v }))} />
            ) : (
              <>
                <div className="row between wrap">
                  <span className="strong small">{g.title}</span>
                  <span className="chip">{g.topic}</span>
                </div>
                <p className="small pa-body">{g.body}</p>
                <div className="row wrap">
                  <button className="btn sm" onClick={() => setEditing(g.id)}>Edit</button>
                  <button className="btn sm ghost" onClick={() => act.run(() => api(`/specialists/clinician/guidance/${g.id}`, { method: "DELETE" }))}>Retire</button>
                </div>
              </>
            )}
          </li>
        ))}
      </ul>
      {retired.length > 0 && <p className="tiny muted">{retired.length} retired {retired.length === 1 ? "note" : "notes"} no longer used.</p>}
      {act.error && <div className="error-box small" role="alert">{act.error}</div>}
    </section>
  );
}

function SampleItem({ s, locked, onChange }) {
  const [answer, setAnswer] = useState(s.answer);
  const act = useAction(onChange);
  useEffect(() => setAnswer(s.answer), [s.answer]);
  const edited = answer !== s.answer;
  return (
    <li className="stack" style={{ gap: 8 }}>
      <div className="row between wrap">
        <span className="strong small">Q: {s.question}</span>
        <span className={`chip ${s.approved ? "ok" : "warn"}`}>{s.approved ? "Approved" : "Needs your approval"}</span>
      </div>
      <label className="sr-only" htmlFor={`pa-s-${s.id}`}>Answer</label>
      <textarea id={`pa-s-${s.id}`} className="edit" value={answer} onChange={(e) => setAnswer(e.target.value)} disabled={locked} />
      <CitationList citations={s.citations} />
      <div className="row wrap">
        {(!s.approved || edited) && (
          <button className="btn sm primary" disabled={act.busy || locked}
                  onClick={() => act.run(() => api(`/specialists/clinician/samples/${s.id}`, {
                    method: "PUT", body: { approved: true, answer: edited ? answer : null },
                  }))}>
            <Check size={14} /> {edited ? "Save and approve" : "Approve"}
          </button>
        )}
        {s.approved && !edited && (
          <button className="btn sm" disabled={act.busy || locked}
                  onClick={() => act.run(() => api(`/specialists/clinician/samples/${s.id}`, { method: "PUT", body: { approved: false } }))}>
            Withdraw approval
          </button>
        )}
        {!locked && (
          <button className="btn sm ghost" disabled={act.busy}
                  onClick={() => act.run(() => api(`/specialists/clinician/samples/${s.id}`, { method: "DELETE" }))}>Delete</button>
        )}
      </div>
      {act.error && <div className="error-box small" role="alert">{act.error}</div>}
    </li>
  );
}

function SamplesSection({ agent, onChange }) {
  const [question, setQuestion] = useState("");
  const act = useAction((out) => { onChange(out); setQuestion(""); });
  const locked = agent.status === "approved" || agent.status === "pending_approval";
  return (
    <section className="card stack" aria-labelledby="pa-samples">
      <h2 id="pa-samples" className="card-title">Sample questions and answers</h2>
      <p className="tiny muted">
        Bioverse drafts each answer exactly as the public would see it. Edit if needed, then approve. Every sample must be
        approved before you submit.
      </p>
      {!locked && (
        <form className="row wrap pa-add" onSubmit={(e) => { e.preventDefault(); act.run(() => api("/specialists/clinician/samples", { method: "POST", body: { question } })); }}>
          <label htmlFor="pa-q" className="sr-only">Sample question</label>
          <input id="pa-q" value={question} maxLength={500} placeholder="A question a patient might ask" onChange={(e) => setQuestion(e.target.value)} />
          <button className="btn sm" type="submit" disabled={act.busy || question.trim().length < 5}>
            {act.busy ? "Drafting..." : "Draft an answer"}
          </button>
        </form>
      )}
      {locked && <p className="tiny muted">Samples are locked while your agent is submitted or published.</p>}
      {act.error && <div className="error-box small" role="alert">{act.error}</div>}
      {agent.samples.length === 0 && <div className="empty small">No samples yet. Add at least two.</div>}
      <ul className="list pa-list">
        {agent.samples.map((s) => <SampleItem key={s.id} s={s} locked={locked} onChange={onChange} />)}
      </ul>
    </section>
  );
}

function FlagForm({ message, guidance, onDone, onCancel }) {
  const [note, setNote] = useState("");
  const [target, setTarget] = useState(message.guidance_ids?.[0] || "none");
  const existing = guidance.find((g) => g.id === target);
  const [g, setG] = useState(existing ? { topic: existing.topic, title: existing.title, body: existing.body } : { topic: "", title: "", body: "" });
  const act = useAction(onDone);

  useEffect(() => {
    const e = guidance.find((x) => x.id === target);
    setG(e ? { topic: e.topic, title: e.title, body: e.body } : { topic: "", title: "", body: "" });
  }, [target, guidance]);

  const correcting = target !== "none";
  const canSend = note.trim().length >= 3 && (!correcting || (g.topic.trim() && g.title.trim() && g.body.trim().length >= 10));
  return (
    <div className="stack pa-flag">
      <label className="stack" style={{ gap: 4 }}>
        <span className="small strong">What was wrong with this answer?</span>
        <textarea className="edit" value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
      </label>
      <label className="stack" style={{ gap: 4 }}>
        <span className="small strong">Correct your guidance</span>
        <select value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="none">Just flag it, no guidance change</option>
          <option value="new">Add a new guidance note</option>
          {guidance.filter((x) => x.status === "active").map((x) => <option key={x.id} value={x.id}>Edit: {x.title}</option>)}
        </select>
      </label>
      {correcting && (
        <div className="pa-fields">
          <label className="stack pa-field"><span className="small strong">Topic</span>
            <input value={g.topic} onChange={(e) => setG({ ...g, topic: e.target.value })} /></label>
          <label className="stack pa-field"><span className="small strong">Title</span>
            <input value={g.title} onChange={(e) => setG({ ...g, title: e.target.value })} /></label>
          <label className="stack pa-field wide"><span className="small strong">Guidance</span>
            <textarea className="edit" value={g.body} onChange={(e) => setG({ ...g, body: e.target.value })} /></label>
        </div>
      )}
      {act.error && <div className="error-box small" role="alert">{act.error}</div>}
      <div className="row wrap">
        <button className="btn sm primary" disabled={!canSend || act.busy}
                onClick={() => act.run(() => api(`/specialists/clinician/messages/${message.id}/flag`, {
                  method: "POST",
                  body: { note, guidance_id: target !== "none" && target !== "new" ? target : null, guidance: correcting ? g : null },
                }))}>
          {correcting ? "Flag and update guidance" : "Flag answer"}
        </button>
        <button className="btn sm ghost" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function ConversationLog({ agent, onChange }) {
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const log = useApi(`/specialists/clinician/messages${flaggedOnly ? "?flagged=true" : ""}`);
  const [open, setOpen] = useState(null);
  return (
    <section className="card stack" aria-labelledby="pa-log">
      <div className="row between wrap">
        <h2 id="pa-log" className="card-title">Conversations</h2>
        <div className="toggle-row pa-toggle">
          <input id="pa-flagged" type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />
          <label htmlFor="pa-flagged">Flagged only</label>
        </div>
      </div>
      <p className="tiny muted">What people asked and what your agent said. You never see who asked.</p>
      {log.loading && !log.data && <div className="skeleton" />}
      {log.error && <div className="error-box small">{log.error.message}</div>}
      {log.data?.length === 0 && <div className="empty small">{flaggedOnly ? "No flagged answers." : "No conversations yet."}</div>}
      <ul className="list pa-list">
        {log.data?.map((m) => (
          <li key={m.id} className="stack" style={{ gap: 6 }}>
            <div className="row between wrap">
              <span className="strong small">“{m.question}”</span>
              <span className="row wrap" style={{ gap: 6 }}>
                {m.flagged && <span className="chip warn">Flagged</span>}
                <span className={`chip ${KIND[m.kind]?.cls || ""}`}>{KIND[m.kind]?.label || m.kind}</span>
              </span>
            </div>
            <p className="small pa-body pa-answer">{m.answer}</p>
            <span className="tiny muted">{fmtDateTime(m.created_at)} · {m.mode === "ai" ? "AI" : "Rules"} · {m.citations.length} sources</span>
            {m.flag_note && <p className="tiny"><span className="strong">Your note:</span> {m.flag_note}</p>}
            {open === m.id ? (
              <FlagForm message={m} guidance={agent.guidance} onCancel={() => setOpen(null)}
                        onDone={(out) => { setOpen(null); onChange(out.agent); log.reload(); }} />
            ) : (
              <div><button className="btn sm" onClick={() => setOpen(m.id)}>{m.flagged ? "Flag again" : "Flag and correct"}</button></div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function StatusCard({ agent, onChange }) {
  const act = useAction(onChange);
  const st = STATUS[agent.status] || { label: agent.status, cls: "" };
  return (
    <section className="card stack" aria-labelledby="pa-status">
      <div className="row between wrap">
        <h2 id="pa-status" className="card-title">Status</h2>
        <span className={`chip ${st.cls}`}>{st.label}</span>
      </div>
      <p className="small">
        {agent.listed ? "Listed: patients can find and ask your agent."
          : agent.status === "approved" && agent.paused ? "Approved, but paused: hidden from patients."
          : agent.status === "pending_approval" ? "An administrator is reviewing it. It isn't listed yet."
          : "Not listed."}
      </p>
      {agent.review_note && <div className="banner warn"><Warning size={15} /> Administrator's note: {agent.review_note}</div>}
      <div className="toggle-row">
        <input id="pa-pause" type="checkbox" checked={agent.paused} disabled={act.busy}
               onChange={(e) => act.run(() => api("/specialists/clinician/pause", { method: "POST", body: { paused: e.target.checked } }))} />
        <label htmlFor="pa-pause">Pause my agent{agent.paused ? " (paused)" : ""}</label>
      </div>
      <ul className="pa-checks">
        {agent.ready.checks.map((c) => (
          <li key={c.id} className={c.done ? "done" : ""}>
            <span aria-hidden="true">{c.done ? <Check size={14} /> : <Close size={14} />}</span>
            <span className="small">{c.label}</span>
            <span className="sr-only">{c.done ? "done" : "not done"}</span>
          </li>
        ))}
      </ul>
      {(agent.status === "draft" || agent.status === "rejected") && (
        <button className="btn primary" disabled={!agent.ready.can_submit || act.busy}
                onClick={() => act.run(() => api("/specialists/clinician/submit", { method: "POST" }))}>
          Submit for approval
        </button>
      )}
      {act.error && <div className="error-box small" role="alert">{act.error}</div>}
      <div className="stats pa-stats">
        <div className="stat"><div className="n">{agent.stats.total}</div><div className="tiny muted">Questions, 30 days</div></div>
        <div className="stat"><div className="n">{agent.stats.answered}</div><div className="tiny muted">Answered</div></div>
        <div className="stat"><div className="n">{agent.stats.declined}</div><div className="tiny muted">Declined</div></div>
        <div className={`stat ${agent.stats.emergencies ? "alert" : ""}`}><div className="n">{agent.stats.emergencies}</div><div className="tiny muted">Emergencies</div></div>
      </div>
    </section>
  );
}

export default function PublicAgentSettings() {
  const { data, error, loading, reload } = useApi("/specialists/clinician/agent");
  const [local, setLocal] = useState(null);
  // The latest agent from an action, or what the page loaded with.
  const agent = local || data?.agent || null;
  const setAgent = setLocal;

  function onChange(next) {
    if (next?.agent !== undefined) setAgent(next.agent);
    else if (next) setAgent(next);
  }

  return (
    <WorkspaceLayout>
      <div className="page-head">
        <div>
          <h1 className="page-title">Public AI agent</h1>
          <p className="page-sub">A public education assistant in your voice, grounded in your guidance and cited evidence.</p>
        </div>
      </div>
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {error && (
        <div className="error-box row between wrap"><span>{error.message}</span><button className="btn sm" onClick={reload}>Try again</button></div>
      )}
      {data && !agent && data.defaults && (
        <div className="ws-grid"><div className="span-8"><ProfileForm agent={null} defaults={data.defaults} onSaved={onChange} /></div></div>
      )}
      {agent && (
        <div className="ws-grid">
          <div className="span-8 stack">
            <Disclosure text={agent.disclosure} />
            <ProfileForm key={agent.updated_at} agent={agent} defaults={data?.defaults} onSaved={onChange} />
            <GuidanceSection agent={agent} onChange={onChange} />
            <SamplesSection agent={agent} onChange={onChange} />
            <ConversationLog agent={agent} onChange={onChange} />
          </div>
          <div className="span-4 stack">
            <StatusCard agent={agent} onChange={onChange} />
          </div>
        </div>
      )}
    </WorkspaceLayout>
  );
}
