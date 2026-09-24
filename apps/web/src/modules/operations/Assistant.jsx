import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { Back, Sparkle } from "../../icons.jsx";
import { fmtHours, fmtPct } from "../analytics/kit.jsx";
import "../analytics/charts.css";

const SUGGESTIONS = [
  "Where are we short on capacity next week?",
  "Which clinician has the biggest review backlog?",
  "How many red-flag escalations today?",
  "What is our referral leakage?",
  "How are intakes trending?",
];

// The values each metric contributed, in a line or two. The full result stays one click away.
function summarize(m) {
  const r = m.result;
  switch (m.name) {
    case "get_demand_vs_capacity":
      return r.rows.map((x) => `${x.specialty}: ${x.demand_last_7_days} routed vs ${x.free_next_7_days} free (${x.status})`);
    case "get_capacity":
      return [`${r.window === "today" ? "Today" : "Next 7 days"}: ${r.totals.booked} of ${r.totals.capacity} booked (${fmtPct(r.totals.utilization_pct)})`,
        ...r.rows.filter((x) => x.capacity).map((x) => `${x.specialty}: ${x.booked}/${x.capacity} (${fmtPct(x.utilization_pct)}), ${x.free} free`)];
    case "get_clinician_workload":
      return r.rows.filter((x) => x.open_items).map((x) => `${x.name}: ${x.open_items} open, oldest ${fmtHours(x.oldest_open_hours)}`);
    case "get_intakes_today":
      return [`${r.total} intakes today`, ...r.by_specialty.map((x) => `${x.specialty}: ${x.total}`)];
    case "get_red_flag_escalations_today":
      return [`${r.count} escalations, ${r.acknowledged} acknowledged, ${r.waiting} waiting`];
    case "get_referral_leakage":
      return [`${fmtPct(r.rate_pct)} overall (${r.leaked} of ${r.eligible})`, ...r.by_specialty.map((x) => `${x.specialty}: ${fmtPct(x.rate_pct)}`)];
    case "get_weekly_trends": {
      const last = r.weeks[r.weeks.length - 1];
      return [`Last 7 days: ${last.intakes} intakes, ${last.bookings} bookings`,
        `13 weeks: ${r.totals.intakes} intakes, escalation rate ${fmtPct(r.totals.escalation_rate_pct)}, median turnaround ${fmtHours(r.totals.review_turnaround_median_hours)}`];
    }
    default:
      return [];
  }
}

function MetricsUsed({ metrics }) {
  if (!metrics.length) return <p className="tiny muted">No metrics were used for this answer.</p>;
  return (
    <div className="stack" style={{ gap: 8 }}>
      <span className="eyebrow">Metrics used</span>
      {metrics.map((m, i) => (
        <details key={`${m.name}-${i}`} className="queue-item" style={{ gap: 4 }}>
          <summary className="small strong" style={{ cursor: "pointer", minHeight: 28, display: "flex", alignItems: "center" }}>
            {m.label}{m.args && Object.keys(m.args).length ? <span className="muted" style={{ fontWeight: 500 }}>&nbsp;· {Object.values(m.args).join(", ").replaceAll("_", " ")}</span> : null}
          </summary>
          <ul className="small" style={{ margin: "4px 0 0", paddingLeft: 18, color: "var(--ink-2)" }}>
            {summarize(m).map((line) => <li key={line}>{line}</li>)}
          </ul>
          {m.result.definition && <p className="tiny muted">{m.result.definition}</p>}
        </details>
      ))}
    </div>
  );
}

export default function Assistant() {
  const tools = useApi("/ops/assistant/metrics");
  const [question, setQuestion] = useState("");
  const [thread, setThread] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [thread.length]);

  async function ask(text) {
    const q = text.trim();
    if (q.length < 3 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const out = await api("/ops/assistant", { method: "POST", body: { question: q } });
      setThread((t) => [...t, out]);
      setQuestion("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <WorkspaceLayout>
      <header className="ops-header">
        <div>
          <Link to="/ops" className="small row" style={{ gap: 4, marginBottom: 6 }}><Back size={14} /> Operations</Link>
          <h1 className="page-title">Hospital Agent</h1>
          <p className="page-sub">Ask about capacity, demand, backlogs, escalations and trends. Answers use only the metrics listed, and show the values they used.</p>
        </div>
      </header>

      <div className="ws-grid">
        <section className="span-8 stack" aria-label="Conversation">
          {thread.length === 0 && (
            <div className="card stack">
              <span className="card-title">Try asking</span>
              <div className="row wrap" style={{ gap: 8 }}>
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" className="suggestion" style={{ minHeight: 44 }} onClick={() => ask(s)} disabled={busy}>{s}</button>
                ))}
              </div>
            </div>
          )}
          {thread.map((t, i) => (
            <div key={i} className="qa">
              <div className="q">{t.question}</div>
              <div className="a">
                <div className="row between wrap" style={{ gap: 8 }}>
                  <span className="chip ok"><Sparkle size={12} /> {t.produced_by.endsWith("claude") ? `AI${t.model ? ` · ${t.model}` : ""}` : "Rules mode"}</span>
                </div>
                <p style={{ whiteSpace: "pre-wrap", lineHeight: 1.55 }}>{t.answer}</p>
                <MetricsUsed metrics={t.metrics_used} />
              </div>
            </div>
          ))}
          {busy && <div className="card small muted" role="status"><span className="typing" aria-hidden="true"><i /><i /><i /></span> Looking at the numbers…</div>}
          {error && <div className="error-box" role="alert">{error}</div>}
          <form className="composer" onSubmit={(e) => { e.preventDefault(); ask(question); }}>
            <label htmlFor="ops-q" className="sr-only">Your question</label>
            <input id="ops-q" value={question} maxLength={500} onChange={(e) => setQuestion(e.target.value)}
                   placeholder="Ask an operations question" autoComplete="off" />
            <button type="submit" className="btn primary" disabled={busy || question.trim().length < 3}>Ask</button>
          </form>
          <div ref={endRef} />
        </section>

        <aside className="span-4 card stack" aria-labelledby="tools-title">
          <h2 id="tools-title" className="card-title">What the agent can look at</h2>
          <p className="small muted">Read-only metrics over live data. The agent cannot run its own queries or see patient names. Every question is recorded in the audit log.</p>
          {tools.error && <div className="error-box small">{tools.error.message}</div>}
          {tools.loading && <div className="skeleton" />}
          <ul className="list" style={{ margin: 0, padding: 0, listStyle: "none" }}>
            {tools.data?.map((t) => (
              <li key={t.name} style={{ padding: "10px 0" }}>
                <div className="small strong">{t.label}</div>
                <div className="tiny muted">{t.description}</div>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </WorkspaceLayout>
  );
}
