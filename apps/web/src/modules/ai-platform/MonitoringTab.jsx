import { useEffect, useState } from "react";
import { useApi } from "../../hooks.js";
import ColumnChart, { SERIES_COLORS } from "./ColumnChart.jsx";

const PATHS = [
  { key: "claude", label: "Claude", color: SERIES_COLORS[0] },
  { key: "claude_fallback", label: "Claude with fallback model", color: SERIES_COLORS[1] },
  { key: "rules", label: "Rules only", color: SERIES_COLORS[2] },
];

function pct(v) {
  return v == null ? "—" : `${(v * 100).toFixed(v === 0 || v === 1 ? 0 : 1)}%`;
}

function Tile({ label, value, sub }) {
  return (
    <div className="stat aip-stat">
      <div className="tiny muted">{label}</div>
      <div className="aip-stat-n">{value}</div>
      {sub && <div className="tiny muted">{sub}</div>}
    </div>
  );
}

export default function MonitoringTab() {
  const [days, setDays] = useState(30);
  const { data, error, loading } = useApi(`/ai/monitoring?days=${days}`);
  const [view, setView] = useState(null);
  const [showTable, setShowTable] = useState(false);

  // Refetch keeps the previous render (dimmed) instead of flashing a skeleton.
  useEffect(() => {
    if (data) setView(data);
  }, [data]);

  const m = view;
  return (
    <div className="stack" style={{ gap: 18 }}>
      <div className="row wrap aip-filter-row">
        <div className="field">
          <label htmlFor="mon-days" className="tiny strong">Time range</label>
          <select id="mon-days" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </div>
        <button className="btn sm" onClick={() => setShowTable((s) => !s)} aria-pressed={showTable}>
          {showTable ? "Hide table view" : "Show table view"}
        </button>
      </div>

      {error && <div className="error-box">{error.message}</div>}
      {!m && loading && <div className="card"><div className="skeleton" /></div>}

      {m && (
        <div className="stack" style={{ gap: 18, opacity: loading ? 0.6 : 1, transition: "opacity .15s" }}>
          <div className="aip-stats">
            <Tile label="Requests triaged" value={m.totals.triaged.toLocaleString()} sub={`last ${m.days} days`} />
            <Tile label="Handled by rules only" value={pct(m.totals.rules_share)} sub="AI off, opted out or unavailable" />
            <Tile label="Needed fallback model" value={pct(m.totals.fallback_share)} />
            <Tile label="Red-flag escalations" value={m.totals.escalations.toLocaleString()}
                  sub={m.totals.escalation_rate == null ? "" : `${pct(m.totals.escalation_rate)} of routed requests`} />
            <Tile label="Guardrail triggers" value={m.guardrails.safety_checks_requested.toLocaleString()} sub="safety checks asked" />
            <Tile label="Review rejection rate" value={pct(m.review.rejection_rate)}
                  sub={`${m.review.rejected} of ${m.review.reviewed} reviewed · ${m.review.pending} waiting`} />
            <Tile label="Model refusals" value={m.refusals.recorded ? m.refusals.count.toLocaleString() : "Not recorded"} />
          </div>

          <article className="card stack">
            <div>
              <h3 className="card-title">Triage by path, per day</h3>
              <p className="tiny muted">Which engine sorted each patient request. Days in {m.timezone.replace("_", " ")}.</p>
            </div>
            <ColumnChart data={m.daily} series={PATHS} height={220} label={`Triage by path per day, last ${m.days} days`} />
          </article>

          <div className="ws-grid">
            <article className="card stack aip-half">
              <div>
                <h3 className="card-title">Red-flag escalations per day</h3>
                <p className="tiny muted">Emergency or crisis guidance given, from rules or the intake agent.</p>
              </div>
              <ColumnChart data={m.daily} series={[{ key: "escalations", label: "Escalations" }]} height={160}
                           label="Red-flag escalations per day" />
            </article>
            <article className="card stack aip-half">
              <div>
                <h3 className="card-title">Safety checks per day</h3>
                <p className="tiny muted">Structured safety questions asked before routine flow continued.</p>
              </div>
              <ColumnChart data={m.daily} series={[{ key: "safety_checks", label: "Safety checks" }]} height={160}
                           label="Safety checks per day" />
            </article>
          </div>

          {showTable && (
            <article className="card">
              <div className="aip-table-wrap">
                <table className="aip-table">
                  <caption className="sr-only">Daily AI monitoring counts</caption>
                  <thead>
                    <tr><th scope="col">Day</th><th scope="col" className="aip-num">Claude</th><th scope="col" className="aip-num">Fallback</th>
                      <th scope="col" className="aip-num">Rules</th><th scope="col" className="aip-num">Escalations</th>
                      <th scope="col" className="aip-num">Safety checks</th></tr>
                  </thead>
                  <tbody>
                    {[...m.daily].reverse().map((d) => (
                      <tr key={d.day}>
                        <th scope="row">{new Date(`${d.day}T12:00:00`).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })}</th>
                        <td className="aip-num">{d.claude}</td><td className="aip-num">{d.claude_fallback}</td>
                        <td className="aip-num">{d.rules}</td><td className="aip-num">{d.escalations}</td>
                        <td className="aip-num">{d.safety_checks}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </article>
          )}

          <article className="card stack">
            <h3 className="card-title">What these numbers can and can't tell you</h3>
            <ul className="small aip-notes">
              <li>{m.refusals.note}</li>
              <li>{m.guardrails.note}</li>
              <li>Escalations by source: {m.escalations_by_source.length
                ? m.escalations_by_source.map((s) => `${s.source} ${s.n}`).join(", ")
                : "none in this period"}.</li>
              <li>Review rejection rate covers result explanations reviewed in this period ({m.review.edited} approved with edits).</li>
              <li>Bias monitoring across demographic groups is not measured yet.</li>
            </ul>
          </article>
        </div>
      )}
    </div>
  );
}
