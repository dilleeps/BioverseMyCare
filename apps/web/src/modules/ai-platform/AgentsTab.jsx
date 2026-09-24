import { useApi } from "../../hooks.js";
import { fmtDateTime } from "../../format.js";

function pct(v) {
  return v == null ? "—" : `${(Number(v) * 100).toFixed(1)}%`;
}

function Agent({ a }) {
  return (
    <article className="card stack aip-agent">
      <div className="row between wrap" style={{ alignItems: "flex-start" }}>
        <div className="stack" style={{ gap: 2 }}>
          <h3 className="card-title">{a.name}</h3>
          <code className="tiny muted">{a.id}</code>
        </div>
        <div className="row wrap" style={{ gap: 6 }}>
          <span className={`chip ${a.status === "active" ? "ok" : ""}`}>{a.status === "active" ? "Active" : "Planned"}</span>
          {a.status === "planned" && a.implementation_detected && <span className="chip">Implementation detected</span>}
        </div>
      </div>
      <p className="small">{a.purpose}</p>
      <dl className="aip-dl">
        <dt>Owner</dt><dd>{a.owner}</dd>
        <dt>Model</dt><dd>{a.live_model}{a.live_model !== a.model ? <span className="muted"> · registered: {a.model}</span> : null}</dd>
        <dt>Prompt version</dt>
        <dd>
          {a.prompt ? (
            <>
              <code className="aip-hash" title={a.prompt.hash}>{a.prompt.hash.slice(0, 12)}</code>
              <span className="tiny muted"> sha256 of {a.prompt.ref} ({a.prompt.length.toLocaleString()} chars)</span>
              {a.prompt_versions.length > 1 && (
                <span className="tiny muted"> · {a.prompt_versions.length} versions seen</span>
              )}
            </>
          ) : a.ruleset_version ? (
            <span>Ruleset {a.ruleset_version} <span className="tiny muted">(no prompt: deterministic)</span></span>
          ) : (
            <span className="muted">{a.prompt_refs.length ? "Prompt not in this build" : "No prompt"}</span>
          )}
        </dd>
        <dt>Human review</dt><dd>{a.human_review}</dd>
        <dt>Activity</dt>
        <dd>
          {a.events ? `${a.events.toLocaleString()} audited actions · last ${fmtDateTime(a.last_active_at)}` : "No recorded actions"}
          {a.paths.length > 0 && a.paths[0] !== "default" && <span className="tiny muted"> · paths: {a.paths.join(", ")}</span>}
        </dd>
        {a.evaluation_suite && (
          <>
            <dt>Evaluation</dt>
            <dd>
              {a.evaluation ? (
                <>
                  <span className={`chip ${a.evaluation.gate_passed ? "ok" : "warn"}`}>
                    {a.evaluation.gate_passed ? "Gate passed" : "Gate failed"}
                  </span>{" "}
                  {pct(a.evaluation.pass_rate)} of {a.evaluation.total} cases · {fmtDateTime(a.evaluation.created_at)}
                </>
              ) : (
                <span className="muted">Not run yet (Evaluations tab)</span>
              )}
            </dd>
          </>
        )}
      </dl>
      <div className="row wrap" style={{ gap: 6 }} aria-label="Permitted tools">
        {a.permitted_tools.map((t) => <span key={t} className="chip">{t}</span>)}
      </div>
    </article>
  );
}

export default function AgentsTab() {
  const { data, error, loading } = useApi("/ai/agents");
  if (error) return <div className="error-box">{error.message}</div>;
  if (loading && !data) return <div className="card"><div className="skeleton" /></div>;
  if (!data?.length) return <div className="card empty">No agents are registered.</div>;
  const active = data.filter((a) => a.status === "active");
  const planned = data.filter((a) => a.status !== "active");
  return (
    <div className="stack" style={{ gap: 18 }}>
      <p className="small muted">
        Every agent declares its model, tools and review rules. The prompt version is the SHA-256 of the prompt text
        the running code would send, fingerprinted live; the registry remembers each fingerprint the first time it
        appears.
      </p>
      <section className="stack" aria-labelledby="agents-active">
        <h2 id="agents-active" className="eyebrow">Active ({active.length})</h2>
        <div className="aip-grid">{active.map((a) => <Agent key={a.id} a={a} />)}</div>
      </section>
      <section className="stack" aria-labelledby="agents-planned">
        <h2 id="agents-planned" className="eyebrow">Planned ({planned.length})</h2>
        <div className="aip-grid">{planned.map((a) => <Agent key={a.id} a={a} />)}</div>
      </section>
    </div>
  );
}
