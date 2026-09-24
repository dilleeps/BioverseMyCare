import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { useSession } from "../../session.jsx";
import { fmtDate } from "../../format.js";
import { Arrow, Lock, Phone, Shield, Sparkle, Warning } from "../../icons.jsx";

const SUGGESTIONS = [
  "When was my last cholesterol test?",
  "What vaccines have I had?",
  "When is my next appointment?",
  "What's overdue?",
];

function ModeChip({ mode }) {
  if (mode === "claude") return <span className="chip ok ha-mode"><Sparkle size={12} /> AI answer from your record</span>;
  if (mode === "rules") return <span className="chip ha-mode">Found in your record</span>;
  return null;
}

function Sources({ items, anchorPrefix }) {
  if (!items?.length) return null;
  return (
    <ul className="ha-sources" aria-label="Sources from your record">
      {items.map((f) => (
        <li key={f.id} id={anchorPrefix ? `${anchorPrefix}-${f.id}` : undefined} className="ha-source">
          <span className="ref" aria-label={`Source ${f.id}`}>{f.id}</span>
          <span>
            {f.date && <span className="tiny muted" style={{ display: "block" }}>{fmtDate(f.date)}</span>}
            {f.href ? <Link to={f.href}>{f.text}</Link> : f.text}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Cites({ ids, anchorPrefix }) {
  if (!ids?.length) return null;
  return (
    <span className="ha-cite">
      {ids.map((id) => (
        <a key={id} href={`#${anchorPrefix}-${id}`} aria-label={`Source ${id}`}>{id}</a>
      ))}
    </span>
  );
}

function Gate({ gate, onGo }) {
  if (gate.kind === "emergency") {
    return (
      <section className="card alert stack" role="alert">
        <div className="row strong" style={{ color: "var(--alert-strong)" }}>
          <Warning size={20} /> {gate.crisis_line ? "Support is available now" : "Get emergency help now"}
        </div>
        <p style={{ color: "var(--alert-strong)" }}>{gate.message}</p>
        {gate.crisis_line && <a className="btn danger" href={`tel:${gate.crisis_line}`}><Phone size={18} /> Call or text {gate.crisis_line}</a>}
        <a className="btn danger" href={`tel:${gate.emergency_number}`}><Phone size={18} /> Call {gate.emergency_number}</a>
        {gate.care_team_notified && <p className="small" style={{ color: "var(--alert-strong)" }}>Your care team has been notified.</p>}
      </section>
    );
  }
  return (
    <section className="card stack">
      <p>{gate.message}</p>
      <button className="btn primary" onClick={() => onGo(gate)}>{gate.label} <Arrow size={16} /></button>
    </section>
  );
}

function Ask({ patientId }) {
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState(null);
  const [answer, setAnswer] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  async function ask(q) {
    const text = (q ?? question).trim();
    if (text.length < 2) return;
    setBusy(true);
    setError(null);
    setAsked(text);
    try {
      setAnswer(await api(`/health-ai/patients/${patientId}/ask`, { method: "POST", body: { question: text } }));
    } catch (e) {
      setAnswer(null);
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="ha-section" aria-labelledby="ha-ask">
      <h2 id="ha-ask" className="ha-section-title">Ask a question</h2>
      <p className="page-sub" style={{ marginBottom: 12 }}>
        Answers come only from your own record, and show exactly where they came from. It can't diagnose or give medical advice.
      </p>
      <form className="ask" style={{ minHeight: 56 }} onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <label htmlFor="ha-q" className="sr-only">Your question</label>
        <input id="ha-q" value={question} maxLength={500} placeholder="e.g. When was my last flu shot?"
               onChange={(e) => setQuestion(e.target.value)} />
        <button className="send" aria-label="Ask" disabled={busy || question.trim().length < 2}><Arrow size={20} /></button>
      </form>
      <div className="suggestions">
        {SUGGESTIONS.map((s) => (
          <button key={s} type="button" className="suggestion" onClick={() => { setQuestion(s); ask(s); }} disabled={busy}>{s}</button>
        ))}
      </div>

      <div aria-live="polite" style={{ marginTop: 16 }}>
        {busy && <div className="card"><div className="skeleton" /></div>}
        {error && <div className="error-box">{error}</div>}
        {!busy && answer && (
          <div className="stack">
            <div className="bubble user" style={{ alignSelf: "flex-end" }}>{asked}</div>
            {answer.gate ? (
              <Gate gate={answer.gate} onGo={(g) => navigate(g.to, { state: g.initial ? { initial: g.initial } : undefined })} />
            ) : (
              <section className="card stack">
                <div className="row between wrap">
                  <ModeChip mode={answer.mode} />
                  {!answer.ai_consent && <span className="tiny muted row" style={{ gap: 4 }}><Lock size={12} /> AI is off for your record</span>}
                </div>
                {/* In rules mode the answer is the facts themselves; show the lead and let the sources carry them. */}
                <p className="ha-answer">{answer.lead || answer.answer}</p>
                {answer.note && <p className="small muted">{answer.note}</p>}
                <Sources items={answer.citations} />
              </section>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function YearInReview({ patientId }) {
  const { data, error, loading } = useApi(`/health-ai/patients/${patientId}/year-in-review`);
  const navigate = useNavigate();
  return (
    <section className="ha-section" aria-labelledby="ha-year">
      <h2 id="ha-year" className="ha-section-title">{data ? `Your ${data.year} in review` : "Your year in review"}</h2>
      <p className="page-sub" style={{ marginBottom: 12 }}>What happened with your health this year, from your record.</p>
      {error && <div className="error-box">{error.message}</div>}
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {data && (
        <div className="stack">
          <section className="card stack ha-review">
            <ModeChip mode={data.mode} />
            <div>
              {data.summary.map((line, i) => (
                <p key={i}>{line.text}<Cites ids={line.fact_ids} anchorPrefix="yr" /></p>
              ))}
            </div>
            {data.note && <p className="small muted">{data.note}</p>}
          </section>
          {data.questions.length > 0 && (
            <section className="card stack">
              <div className="card-title">Questions to discuss with your doctor</div>
              <ol className="ha-questions">
                {data.questions.map((q, i) => (
                  <li key={i}>{q.text}<Cites ids={q.fact_ids} anchorPrefix="yr" /></li>
                ))}
              </ol>
              <button className="btn" style={{ alignSelf: "flex-start" }}
                      onClick={() => navigate("/app", { state: { initial: "Help me prepare questions for my next visit" } })}>
                Prepare for my next visit
              </button>
            </section>
          )}
          {data.sources.length > 0 && (
            <details className="card">
              <summary className="strong" style={{ cursor: "pointer", minHeight: 32, display: "flex", alignItems: "center" }}>
                Sources ({data.sources.length})
              </summary>
              <div style={{ marginTop: 10 }}><Sources items={data.sources} anchorPrefix="yr" /></div>
            </details>
          )}
        </div>
      )}
    </section>
  );
}

function WhatICanSee({ patientId }) {
  const [open, setOpen] = useState(false);
  const facts = useApi(open ? `/health-ai/patients/${patientId}/facts` : null);
  return (
    <section className="ha-section">
      <details className="card" onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary className="strong row" style={{ cursor: "pointer", minHeight: 32, gap: 8 }}>
          <Shield size={16} /> What the assistant can see
        </summary>
        <div className="stack" style={{ marginTop: 10 }}>
          <p className="small muted">
            Only these facts from your own record. Result explanations appear only after a clinician has reviewed them.
          </p>
          {facts.error && <div className="error-box">{facts.error.message}</div>}
          {facts.loading && <div className="skeleton" />}
          {facts.data && (facts.data.facts.length === 0
            ? <div className="empty">Your record is empty so far.</div>
            : <Sources items={facts.data.facts} />)}
        </div>
      </details>
    </section>
  );
}

export default function HealthAI() {
  const { me } = useSession();
  return (
    <main className="column">
      <div className="stack" style={{ gap: 2 }}>
        <span className="eyebrow">Records</span>
        <h1 className="page-title">Ask about my health</h1>
        <span className="page-sub">Your record, in plain language.</span>
      </div>
      <Ask patientId={me.patient_id} />
      <YearInReview patientId={me.patient_id} />
      <WhatICanSee patientId={me.patient_id} />
    </main>
  );
}
