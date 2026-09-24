import { useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { fmtDateTime } from "../../format.js";
import { Check, Warning } from "../../icons.jsx";

const SUITES = [
  { id: "red_flags", label: "Red-flag screen", blurb: "The deterministic red-flag rules over labelled patient messages." },
  { id: "intent_routing", label: "Intent routing (rules triage)", blurb: "The rules triage path: intent and specialty for one-message requests." },
];

function pct(v) {
  return v == null ? "—" : `${(Number(v) * 100).toFixed(Number(v) === 1 || Number(v) === 0 ? 0 : 1)}%`;
}

function Summary({ run, suite }) {
  const failures = run.failures?.failures ?? run.failures ?? [];
  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className={`banner ${run.gate_passed ? "ok" : "warn"}`}>
        {run.gate_passed ? <Check size={16} /> : <Warning size={16} />}
        {run.gate_passed
          ? `Release gate passed: no regressions${suite === "red_flags" ? ", every emergency and crisis outside the known gaps caught" : ""}.`
          : `Release gate failed: ${run.regressions} regression${run.regressions === 1 ? "" : "s"}.`}
        <span className="muted" style={{ fontWeight: 500 }}> · ruleset {run.ruleset_version} · {fmtDateTime(run.created_at)}</span>
      </div>
      <div className="aip-stats">
        <div className="stat aip-stat"><div className="tiny muted">Pass rate</div><div className="aip-stat-n">{pct(run.pass_rate)}</div>
          <div className="tiny muted">{run.passed} of {run.total} cases</div></div>
        {suite === "red_flags" && (
          <>
            <div className="stat aip-stat"><div className="tiny muted">Emergency + crisis sensitivity</div>
              <div className="aip-stat-n">{pct(run.sensitivity)}</div><div className="tiny muted">all cases, known gaps included</div></div>
            <div className="stat aip-stat"><div className="tiny muted">Sensitivity, release gate</div>
              <div className="aip-stat-n">{pct(run.sensitivity_gated)}</div><div className="tiny muted">must be 100%</div></div>
          </>
        )}
        <div className={`stat aip-stat ${run.regressions ? "alert" : ""}`}><div className="tiny muted">Regressions</div>
          <div className="aip-stat-n">{run.regressions}</div></div>
        <div className="stat aip-stat"><div className="tiny muted">Known gaps failing</div>
          <div className="aip-stat-n">{run.known_gap_failures}</div></div>
      </div>
      {failures.length > 0 && (
        <div className="aip-table-wrap">
          <table className="aip-table">
            <caption className="aip-caption">Cases the rules got wrong</caption>
            <thead><tr><th scope="col">Message</th><th scope="col">Expected</th><th scope="col">Got</th><th scope="col">Status</th></tr></thead>
            <tbody>
              {failures.map((f) => (
                <tr key={f.case_id}>
                  <td>“{f.text}”{f.note && <div className="tiny muted">{f.note}</div>}</td>
                  <td>{f.expected}{f.expected_detail ? ` · ${f.expected_detail}` : ""}</td>
                  <td>{f.got}{f.got_detail ? ` · ${f.got_detail}` : ""}</td>
                  <td>{f.known_gap ? <span className="chip">Known gap</span> : <span className="chip warn"><Warning size={12} /> Regression</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function EvalsTab() {
  const [suite, setSuite] = useState("red_flags");
  const cases = useApi(`/ai/evals/cases?suite=${suite}`);
  const runs = useApi(`/ai/evals/runs?suite=${suite}`);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const [fresh, setFresh] = useState(null);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      setFresh(await api("/ai/evals/run", { method: "POST", body: { suite } }));
      runs.reload();
    } catch (e) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  }

  const latest = fresh?.suite === suite ? fresh : runs.data?.[0];
  const info = SUITES.find((s) => s.id === suite);

  return (
    <div className="stack" style={{ gap: 18 }}>
      <div className="row between wrap aip-filter-row">
        <div className="aip-seg" role="group" aria-label="Evaluation suite">
          {SUITES.map((s) => (
            <button key={s.id} className="btn sm" aria-pressed={suite === s.id}
                    onClick={() => { setSuite(s.id); setFresh(null); setError(null); }}>{s.label}</button>
          ))}
        </div>
        <button className="btn primary" onClick={run} disabled={running}>{running ? "Running…" : "Run evaluation"}</button>
      </div>
      <p className="small muted">{info.blurb} A known gap is a case the current rules miss on purpose-built wording; it
        stays in the set until the rules catch it. Only the clinician-owned ruleset changes the outcome.</p>

      <article className="card stack" aria-live="polite">
        <h3 className="card-title">Latest run</h3>
        {error && <div className="error-box">{error}</div>}
        {runs.error && <div className="error-box">{runs.error.message}</div>}
        {!latest && !runs.loading && <p className="small muted">This suite has not been run yet.</p>}
        {latest && <Summary run={latest} suite={suite} />}
      </article>

      {runs.data?.length > 0 && (
        <article className="card stack">
          <h3 className="card-title">Run history</h3>
          <div className="aip-table-wrap">
            <table className="aip-table">
              <caption className="sr-only">Previous runs</caption>
              <thead><tr><th scope="col">When</th><th scope="col">Ruleset</th><th scope="col" className="aip-num">Pass rate</th>
                {suite === "red_flags" && <th scope="col" className="aip-num">Sensitivity</th>}
                <th scope="col" className="aip-num">Regressions</th><th scope="col">Gate</th><th scope="col">By</th></tr></thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.id}>
                    <td className="aip-nowrap">{fmtDateTime(r.created_at)}</td>
                    <td><code className="tiny">{r.ruleset_version}</code></td>
                    <td className="aip-num">{pct(r.pass_rate)}</td>
                    {suite === "red_flags" && <td className="aip-num">{pct(r.sensitivity)}</td>}
                    <td className="aip-num">{r.regressions}</td>
                    <td><span className={`chip ${r.gate_passed ? "ok" : "warn"}`}>{r.gate_passed ? "Passed" : "Failed"}</span></td>
                    <td>{r.run_by || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      )}

      <article className="card stack">
        <details className="aip-details">
          <summary className="card-title">Labelled cases ({cases.data?.length ?? "…"})</summary>
          {cases.error && <div className="error-box">{cases.error.message}</div>}
          {cases.data && (
            <div className="aip-table-wrap" style={{ marginTop: 12 }}>
              <table className="aip-table">
                <caption className="sr-only">Labelled evaluation cases</caption>
                <thead><tr><th scope="col">Category</th><th scope="col">Message</th><th scope="col">Expected</th><th scope="col">Note</th></tr></thead>
                <tbody>
                  {cases.data.map((c) => (
                    <tr key={c.id}>
                      <td>{c.category}{c.known_gap && <div><span className="chip">Known gap</span></div>}</td>
                      <td>“{c.text}”</td>
                      <td>{suite === "red_flags"
                        ? `${c.expected_level}${c.expected_topic ? ` · ${c.expected_topic}` : ""}`
                        : `${c.expected_intent}${c.expected_specialty ? ` · ${c.expected_specialty}` : ""}`}</td>
                      <td className="tiny muted">{c.note || ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </details>
      </article>
    </div>
  );
}
