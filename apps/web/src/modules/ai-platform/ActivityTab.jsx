import { useCallback, useEffect, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { fmtDateTime } from "../../format.js";
import { Check, Close } from "../../icons.jsx";

function humanize(v) {
  if (!v) return "";
  const s = String(v).replaceAll("_", " ");
  return s[0].toUpperCase() + s.slice(1);
}

function Trace({ eventId, onClose }) {
  const { data, error, loading } = useApi(`/ai/activity/${eventId}/trace`);
  return (
    <article className="card stack aip-trace" aria-labelledby="trace-title" aria-live="polite">
      <div className="row between">
        <h3 id="trace-title" className="card-title">Trace of event #{eventId}</h3>
        <button className="icon-btn" onClick={onClose} aria-label="Close trace"><Close size={16} /></button>
      </div>
      {error && <div className="error-box">{error.message}</div>}
      {loading && !data && <div className="skeleton" />}
      {data && (
        <>
          <p className="tiny muted">
            {humanize(data.event.action)} · {fmtDateTime(data.event.occurred_at)}
            {data.event.patient_name ? ` · ${data.event.patient_name}` : ""}
          </p>
          <ol className="aip-answers">
            {data.answers.map((a) => (
              <li key={a.question}>
                <div className="row" style={{ gap: 6 }}>
                  <span className={`aip-mark ${a.recorded ? "ok" : ""}`} aria-hidden="true">
                    {a.recorded ? <Check size={12} /> : "–"}
                  </span>
                  <span className="small strong">{a.question}</span>
                </div>
                <p className="small">{a.answer}</p>
                {!a.recorded && <p className="tiny muted">Not recorded by the platform for this event.</p>}
              </li>
            ))}
          </ol>
          {data.patient_saw?.text && (
            <div className="stack" style={{ gap: 4 }}>
              <span className="tiny strong">What the patient saw</span>
              <blockquote className="aip-quote small">{data.patient_saw.text}</blockquote>
            </div>
          )}
          {data.prompt?.hash && (
            <p className="tiny muted">Prompt fingerprint <code className="aip-hash">{data.prompt.hash}</code></p>
          )}
          <p className="tiny muted">Opening a trace is recorded in the audit trail.</p>
        </>
      )}
    </article>
  );
}

export default function ActivityTab() {
  const agents = useApi("/ai/agents");
  const [agent, setAgent] = useState("");
  const [items, setItems] = useState([]);
  const [next, setNext] = useState(null);
  const [state, setState] = useState({ loading: true, error: null });
  const [selected, setSelected] = useState(null);

  const load = useCallback(async (a, before) => {
    setState({ loading: true, error: null });
    try {
      const qs = new URLSearchParams({ limit: "40" });
      if (a) qs.set("agent", a);
      if (before) qs.set("before_id", before);
      const page = await api(`/ai/activity?${qs}`);
      setItems((prev) => (before ? [...prev, ...page.items] : page.items));
      setNext(page.next_before_id);
      setState({ loading: false, error: null });
    } catch (e) {
      setState({ loading: false, error: e });
    }
  }, []);

  useEffect(() => {
    load(agent, null);
  }, [agent, load]);

  return (
    <div className="stack" style={{ gap: 18 }}>
      <div className="row wrap aip-filter-row">
        <div className="field" style={{ minWidth: 240 }}>
          <label htmlFor="act-agent" className="tiny strong">Agent</label>
          <select id="act-agent" value={agent} onChange={(e) => { setAgent(e.target.value); setSelected(null); }}>
            <option value="">All agents</option>
            {agents.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
      </div>
      <div className="ws-grid">
        <section className={selected ? "span-7" : "span-12"} aria-label="AI activity">
          <article className="card">
            {state.error && <div className="error-box">{state.error.message}</div>}
            {!state.error && !state.loading && items.length === 0 && <div className="empty">No AI activity recorded.</div>}
            {items.length === 0 && state.loading && <div className="skeleton" />}
            {items.length > 0 && (
              <div className="aip-table-wrap" style={{ opacity: state.loading ? 0.6 : 1 }}>
                <table className="aip-table">
                  <caption className="sr-only">AI actions, newest first</caption>
                  <thead>
                    <tr><th scope="col">When</th><th scope="col">Agent</th><th scope="col">Action</th>
                      <th scope="col">Patient</th><th scope="col">Model</th><th scope="col"><span className="sr-only">Trace</span></th></tr>
                  </thead>
                  <tbody>
                    {items.map((e) => (
                      <tr key={e.id} aria-selected={selected === e.id} className={selected === e.id ? "aip-selected" : undefined}>
                        <td className="aip-nowrap">{fmtDateTime(e.occurred_at)}</td>
                        <td>
                          <div className="strong">{e.agent_name || e.agent}</div>
                          <code className="tiny muted">{e.agent}</code>
                        </td>
                        <td>{humanize(e.action)}<div className="tiny muted">{humanize(e.entity_type)}</div></td>
                        <td>{e.patient_name || <span className="muted">—</span>}</td>
                        <td>{e.model || <span className="muted">{e.path === "rules" || !e.path ? "rules" : "—"}</span>}</td>
                        <td>
                          <button className="btn sm" onClick={() => setSelected(e.id)}
                                  aria-label={`Trace ${humanize(e.action)} at ${fmtDateTime(e.occurred_at)}`}>Trace</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {next && (
              <button className="btn block" style={{ marginTop: 12 }} disabled={state.loading} onClick={() => load(agent, next)}>
                {state.loading ? "Loading…" : "Load older"}
              </button>
            )}
          </article>
        </section>
        {selected && (
          <section className="span-5">
            <Trace key={selected} eventId={selected} onClose={() => setSelected(null)} />
          </section>
        )}
      </div>
    </div>
  );
}
