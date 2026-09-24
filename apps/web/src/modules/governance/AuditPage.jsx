import { useCallback, useEffect, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { Check, Shield, Warning } from "../../icons.jsx";
import { PageHeader, download, fmtStamp, humanize } from "./shared.jsx";

const EMPTY = {
  date_from: "", date_to: "", actor: "", patient: "", action: "", entity_type: "", q: "",
  agent_only: false, break_glass_only: false,
};

function toQuery(filters, extra = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries({ ...filters, ...extra })) {
    if (v === "" || v === false || v === null || v === undefined) continue;
    qs.set(k, String(v));
  }
  return qs.toString();
}

function ChainCard() {
  const status = useApi("/governance/audit/chain");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function verify() {
    setBusy(true);
    setError(null);
    try {
      setResult(await api("/governance/audit/verify", { method: "POST" }));
      status.reload();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const s = status.data;
  return (
    <article className="card stack" aria-labelledby="chain-title">
      <div className="row between wrap">
        <span id="chain-title" className="card-title row" style={{ gap: 8 }}><Shield size={18} /> Tamper evidence</span>
        <button className="btn sm dark" onClick={verify} disabled={busy}>{busy ? "Verifying…" : "Verify and extend chain"}</button>
      </div>
      <p className="small muted">
        Each audit event is linked into a SHA-256 hash chain kept beside the append-only trail. Verifying
        recomputes every link and reports the first event whose contents no longer match.
      </p>
      {status.error && <div className="error-box">{status.error.message}</div>}
      {s && (
        <div className="gv-kv">
          <span>Chained events</span><strong>{s.chained.toLocaleString()}</strong>
          <span>Not yet chained</span><strong>{s.unchained.toLocaleString()}</strong>
          <span>Head hash</span><code className="gv-hash">{s.head_hash ? s.head_hash.slice(0, 16) + "…" : "none yet"}</code>
          <span>Last verified</span><strong>{s.last_verification ? fmtStamp(s.last_verification.occurred_at) : "never"}</strong>
        </div>
      )}
      <div aria-live="polite">
        {error && <div className="error-box">{error}</div>}
        {result && result.ok && (
          <div className="banner ok"><Check size={16} /> Chain intact: {result.checked.toLocaleString()} links checked, {result.appended.toLocaleString()} added.</div>
        )}
        {result && !result.ok && (
          <div className="banner warn">
            <Warning size={16} /> Mismatch at event {result.first_mismatch.event_id}: {result.first_mismatch.reason}.
            Nothing was added to the chain.
          </div>
        )}
      </div>
    </article>
  );
}

function EventRow({ e }) {
  return (
    <tr className={e.break_glass ? "gv-flag" : undefined}>
      <td className="gv-nowrap">{fmtStamp(e.occurred_at)}<div className="tiny muted">#{e.id}</div></td>
      <td>
        <div className="strong">{e.actor_name || (e.agent ? "Automated" : "System")}</div>
        <div className="tiny muted">{humanize(e.actor_role || "system")}</div>
      </td>
      <td>
        <div className="row wrap" style={{ gap: 6 }}>
          <span>{humanize(e.action)}</span>
          {e.break_glass && <span className="chip warn"><Warning size={12} /> Break-glass</span>}
        </div>
        {e.detail?.reason && <div className="tiny muted">Reason: {e.detail.reason}</div>}
      </td>
      <td>
        <div>{humanize(e.entity_type)}</div>
        {e.entity_id && <code className="tiny muted gv-id">{e.entity_id.slice(0, 8)}</code>}
      </td>
      <td>{e.patient_name || <span className="muted">—</span>}</td>
      <td>
        {e.agent ? <span className="chip">{e.agent}</span> : <span className="muted">—</span>}
        {e.model && <div className="tiny muted">{e.model}</div>}
      </td>
      <td>
        <details className="gv-details">
          <summary className="tiny">Detail</summary>
          <pre className="gv-pre">{JSON.stringify(e.detail, null, 2)}</pre>
        </details>
      </td>
    </tr>
  );
}

export default function AuditPage() {
  const facets = useApi("/governance/audit/facets");
  const [draft, setDraft] = useState(EMPTY);
  const [filters, setFilters] = useState(EMPTY);
  const [items, setItems] = useState([]);
  const [next, setNext] = useState(null);
  const [state, setState] = useState({ loading: true, error: null });
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async (f, before) => {
    setState({ loading: true, error: null });
    try {
      const page = await api(`/governance/audit?${toQuery(f, { limit: 50, before_id: before || "" })}`);
      setItems((prev) => (before ? [...prev, ...page.items] : page.items));
      setNext(page.next_before_id);
      setState({ loading: false, error: null });
    } catch (e) {
      setState({ loading: false, error: e });
    }
  }, []);

  useEffect(() => {
    load(filters, null);
  }, [filters, load]);

  const set = (k) => (e) => setDraft((d) => ({ ...d, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  async function exportCsv() {
    setExporting(true);
    try {
      await download(`/governance/audit/export.csv?${toQuery(filters)}`, "bioverse-audit.csv");
    } catch (e) {
      setState((s) => ({ ...s, error: e }));
    } finally {
      setExporting(false);
    }
  }

  const f = facets.data;
  return (
    <WorkspaceLayout>
      <PageHeader eyebrow="Trust and safety" title="Compliance audit"
                  sub="Every read and write of patient data, every AI action and every review decision.">
        <button className="btn" onClick={exportCsv} disabled={exporting}>{exporting ? "Exporting…" : "Export CSV"}</button>
      </PageHeader>

      <div className="stack" style={{ gap: 18 }}>
        <ChainCard />

        <form className="card gv-filters" onSubmit={(e) => { e.preventDefault(); setFilters(draft); }}
              aria-label="Audit filters">
          <div className="field gv-field"><label htmlFor="f-from">From</label>
            <input id="f-from" type="date" value={draft.date_from} onChange={set("date_from")} /></div>
          <div className="field gv-field"><label htmlFor="f-to">To</label>
            <input id="f-to" type="date" value={draft.date_to} onChange={set("date_to")} /></div>
          <div className="field gv-field"><label htmlFor="f-actor">Actor</label>
            <select id="f-actor" value={draft.actor} onChange={set("actor")}>
              <option value="">Anyone</option>
              {f?.actors.map((a) => <option key={a.id} value={a.id}>{a.display_name} ({a.role})</option>)}
            </select></div>
          <div className="field gv-field"><label htmlFor="f-patient">Patient</label>
            <select id="f-patient" value={draft.patient} onChange={set("patient")}>
              <option value="">Any patient</option>
              {f?.patients.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select></div>
          <div className="field gv-field"><label htmlFor="f-action">Action</label>
            <select id="f-action" value={draft.action} onChange={set("action")}>
              <option value="">Any action</option>
              {f?.actions.map((a) => <option key={a} value={a}>{humanize(a)}</option>)}
            </select></div>
          <div className="field gv-field"><label htmlFor="f-entity">Entity type</label>
            <select id="f-entity" value={draft.entity_type} onChange={set("entity_type")}>
              <option value="">Any type</option>
              {f?.entity_types.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
            </select></div>
          <div className="field gv-field gv-span2"><label htmlFor="f-q">Search</label>
            <input id="f-q" type="search" placeholder="Name, action, agent, id or detail" value={draft.q} onChange={set("q")} /></div>
          <div className="toggle-row"><input id="f-ai" type="checkbox" checked={draft.agent_only} onChange={set("agent_only")} />
            <label htmlFor="f-ai">AI and agent actions only</label></div>
          <div className="toggle-row"><input id="f-bg" type="checkbox" checked={draft.break_glass_only} onChange={set("break_glass_only")} />
            <label htmlFor="f-bg">Break-glass only</label></div>
          <div className="row gv-actions">
            <button className="btn primary" type="submit">Apply filters</button>
            <button className="btn" type="button" onClick={() => { setDraft(EMPTY); setFilters(EMPTY); }}>Clear</button>
          </div>
        </form>

        <article className="card">
          {state.error && <div className="error-box" style={{ marginBottom: 12 }}>{state.error.message}</div>}
          {!state.error && !state.loading && items.length === 0 && <div className="empty">No audit events match these filters.</div>}
          {items.length === 0 && state.loading && <div className="skeleton" />}
          {items.length > 0 && (
            <div className="gv-table-wrap" style={{ opacity: state.loading ? 0.6 : 1 }}>
              <table className="gv-table">
                <caption className="sr-only">Audit events, newest first</caption>
                <thead>
                  <tr><th scope="col">When</th><th scope="col">Who</th><th scope="col">Action</th><th scope="col">Entity</th>
                    <th scope="col">Patient</th><th scope="col">Agent / model</th><th scope="col"><span className="sr-only">Detail</span></th></tr>
                </thead>
                <tbody>{items.map((e) => <EventRow key={e.id} e={e} />)}</tbody>
              </table>
            </div>
          )}
          {next && (
            <button className="btn block" style={{ marginTop: 12 }} disabled={state.loading} onClick={() => load(filters, next)}>
              {state.loading ? "Loading…" : "Load older events"}
            </button>
          )}
        </article>
      </div>
    </WorkspaceLayout>
  );
}
