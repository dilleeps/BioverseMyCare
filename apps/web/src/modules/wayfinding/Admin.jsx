import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { fmtDateTime } from "../../format.js";
import { Warning } from "../../icons.jsx";
import FloorMap, { KIND_NAMES } from "./FloorMap.jsx";

const TABS = [["closures", "Closures"], ["floors", "Floors and areas"], ["signs", "Signs"]];
const REASONS = ["Out of service", "Cleaning in progress", "Maintenance", "Blocked by equipment"];
const GROUPS = [
  ["Elevators, escalator and stairs", (s) => s.kind !== "walk"],
  ["Corridors and walkways", (s) => s.kind === "walk"],
];

function StatusChip({ status }) {
  if (status === "closed") return <span className="chip warn">Closed</span>;
  if (status === "partly_closed") return <span className="chip warn">Partly closed</span>;
  return <span className="chip ok">Open</span>;
}

function CloseForm({ segment, onDone, onCancel }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/wayfinding/closures", { method: "POST", body: { segment, reason } });
      onDone(`${segment} closed. Routes now avoid it.`);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <form className="wf-close-form stack" onSubmit={submit} aria-label={`Close ${segment}`}>
      <label htmlFor={`reason-${segment}`} className="small strong">Why is {segment} closed? Patients see this.</label>
      <input id={`reason-${segment}`} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={160}
             placeholder={`For example: ${segment} out of service`} required minLength={3} />
      <div className="row wrap" style={{ gap: 6 }}>
        {REASONS.map((r) => (
          <button key={r} type="button" className="suggestion" onClick={() => setReason(r)}>{r}</button>
        ))}
      </div>
      {error && <div className="error-box" role="alert">{error}</div>}
      <div className="row wrap" style={{ gap: 8 }}>
        <button type="submit" className="btn danger" disabled={busy || reason.trim().length < 3}>{busy ? "Closing…" : `Close ${segment}`}</button>
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function Closures({ data, reload, toast }) {
  const [closing, setClosing] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const active = data.closures.filter((c) => c.active);

  async function reopen(c) {
    setBusy(c.id);
    setError(null);
    try {
      await api(`/wayfinding/closures/${c.id}/reopen`, { method: "POST" });
      toast(`${c.segment || "Corridor"} reopened.`);
      reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="stack" style={{ gap: 18 }}>
      {error && <div className="error-box" role="alert">{error}</div>}
      {active.length === 0 ? (
        <div className="banner ok">Everything is open. Patients get the fastest routes.</div>
      ) : (
        <div className="card stack">
          <div className="card-title">Closed now</div>
          {active.map((c) => (
            <div key={c.id} className="wf-active">
              <Warning size={18} />
              <div className="wf-grow">
                <div className="strong">{c.segment || `${c.edges} corridor section${c.edges > 1 ? "s" : ""}`}</div>
                <div className="small muted">{c.reason} · closed by {c.closed_by} · {fmtDateTime(c.closed_at)}</div>
              </div>
              {data.can_edit && (
                <button type="button" className="btn sm" disabled={busy === c.id} onClick={() => reopen(c)}>
                  {busy === c.id ? "Reopening…" : "Reopen"}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      {!data.can_edit && <div className="banner info">Only staff and administrators can close or reopen routes.</div>}

      {GROUPS.map(([title, pick]) => (
        <section key={title} className="card stack">
          <div className="card-title">{title}</div>
          <ul className="wf-seglist">
            {data.segments.filter(pick).map((s) => (
              <li key={s.segment} className="wf-seg">
                <div className="wf-seg-row">
                  <div className="wf-grow">
                    <div className="strong">{s.segment}</div>
                    <div className="small muted">
                      {s.kind === "walk" ? `${s.meters} m` : KIND_NAMES[s.kind]} · Level{s.floors.length > 1 ? "s" : ""} {s.floors.join(", ")}
                      {s.closure ? ` · ${s.closure.reason}` : ""}
                    </div>
                  </div>
                  <StatusChip status={s.status} />
                  {data.can_edit && !s.closure && closing !== s.segment && (
                    <button type="button" className="btn sm" onClick={() => setClosing(s.segment)}>Close</button>
                  )}
                  {data.can_edit && s.closure && (
                    <button type="button" className="btn sm" disabled={busy === s.closure.id}
                            onClick={() => reopen({ ...s.closure, segment: s.segment })}>Reopen</button>
                  )}
                </div>
                {closing === s.segment && (
                  <CloseForm segment={s.segment} onCancel={() => setClosing(null)}
                             onDone={(msg) => { setClosing(null); toast(msg); reload(); }} />
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}

      <section className="card stack">
        <div className="card-title">Closure log</div>
        <div className="wf-table-wrap">
          <table className="wf-table">
            <thead><tr><th>Closed</th><th>What</th><th>Reason</th><th>By</th><th>Reopened</th></tr></thead>
            <tbody>
              {data.closures.map((c) => (
                <tr key={c.id}>
                  <td>{fmtDateTime(c.closed_at)}</td>
                  <td>{c.segment || `${c.edges} section${c.edges > 1 ? "s" : ""}`}</td>
                  <td>{c.reason}</td>
                  <td>{c.closed_by || "—"}</td>
                  <td>{c.reopened_at ? `${fmtDateTime(c.reopened_at)} · ${c.reopened_by || ""}` : <span className="chip warn">Still closed</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted">Every closure and reopening is also in the compliance audit trail.</p>
      </section>
    </div>
  );
}

function Floors({ data, building }) {
  const [level, setLevel] = useState(1);
  const floor = building.floors.find((f) => f.level === level) || building.floors[0];
  const summary = data.floors.find((f) => f.level === floor.level);
  const areas = summary.areas.filter((a) => a.kind !== "corridor");
  return (
    <div className="stack" style={{ gap: 18 }}>
      <section className="card stack">
        <div className="wf-floors" role="tablist" aria-label="Floors">
          {building.floors.map((f) => (
            <button key={f.level} type="button" role="tab" aria-selected={f.level === floor.level}
                    className={`wf-floor${f.level === floor.level ? " on" : ""}`} onClick={() => setLevel(f.level)}
                    aria-label={f.name}>{f.short_name}</button>
          ))}
          <span className="wf-floor-name">{floor.name} · {summary.width_m} × {summary.height_m} m · {summary.nodes} map points</span>
        </div>
        <FloorMap floor={floor} closed={building.closed.filter((c) => c.floor_level === floor.level)} />
      </section>
      <section className="card stack">
        <div className="card-title">Areas on {floor.name}</div>
        <div className="wf-table-wrap">
          <table className="wf-table">
            <thead><tr><th>Name</th><th>Kind</th><th>Search</th><th>Sign code</th></tr></thead>
            <tbody>
              {areas.map((a) => (
                <tr key={a.id}>
                  <td className="strong">{a.name}</td>
                  <td>{KIND_NAMES[a.kind]}</td>
                  <td>{a.searchable && a.slug ? <code>{a.slug}</code> : <span className="muted">Not listed</span>}</td>
                  <td>{a.code ? <code>{a.code}</code> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function Signs({ data }) {
  return (
    <section className="card stack">
      <div className="row between wrap">
        <div>
          <div className="card-title">“You are here” signs</div>
          <p className="small muted">Each sign opens Find your way from that spot. Anyone signed in can use it.</p>
        </div>
        <Link to="/wayfinding/signs" className="btn primary">Print sign sheet</Link>
      </div>
      <div className="wf-table-wrap">
        <table className="wf-table">
          <thead><tr><th>Code</th><th>Where</th><th>Floor</th><th>Opens</th></tr></thead>
          <tbody>
            {data.signs.map((s) => (
              <tr key={s.code}>
                <td><code>{s.code}</code></td>
                <td>{s.name}</td>
                <td>{s.floor_name}</td>
                <td><Link to={s.path}>{s.path}</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function WayfindingAdmin() {
  const admin = useApi("/wayfinding/admin");
  const building = useApi("/wayfinding/building");
  const [tab, setTab] = useState("closures");
  const [message, setMessage] = useState("");

  function toast(msg) {
    setMessage(msg);
    setTimeout(() => setMessage(""), 3500);
  }
  function reload() {
    admin.reload();
    building.reload();
  }

  const data = admin.data;
  return (
    <WorkspaceLayout>
      <div className="page-head">
        <div>
          <div className="eyebrow">{data ? `${data.building.campus} · ${data.building.name}` : "Wayfinding"}</div>
          <h1 className="page-title">Wayfinding</h1>
          <div className="page-sub">Close a corridor or an elevator and every patient route changes straight away.</div>
        </div>
      </div>
      <div className="wf-tabs" role="tablist" aria-label="Wayfinding sections">
        {TABS.map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} className={`wf-tab${tab === id ? " on" : ""}`}
                  onClick={() => setTab(id)}>{label}</button>
        ))}
      </div>
      {(admin.error || building.error) && <div className="error-box" role="alert">{(admin.error || building.error).message}</div>}
      {(!data || !building.data) && !admin.error && !building.error && (
        <div className="card stack"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>
      )}
      {data && building.data && tab === "closures" && <Closures data={data} reload={reload} toast={toast} />}
      {data && building.data && tab === "floors" && <Floors data={data} building={building.data} />}
      {data && tab === "signs" && <Signs data={data} />}
      {message && <div className="toast" role="status">{message}</div>}
    </WorkspaceLayout>
  );
}
