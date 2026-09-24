import { useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { useSession } from "../../session.jsx";
import { WorkspaceLayout } from "../../layouts.jsx";
import { Warning } from "../../icons.jsx";
import { PageHeader, SEVERITY_CHIP, STATUS_CHIP, fmtStamp, humanize } from "./shared.jsx";

const CATEGORIES = [
  ["ai_safety", "AI safety"],
  ["privacy", "Privacy"],
  ["security", "Security"],
  ["clinical_safety", "Clinical safety"],
];
const CATEGORY_LABEL = Object.fromEntries(CATEGORIES);
const SEVERITIES =["low", "moderate", "high", "critical"];
const NEXT = {
  open: [["investigating", "Start investigating"], ["resolved", "Resolve"]],
  investigating: [["resolved", "Resolve"], ["open", "Move back to open"]],
  resolved: [["investigating", "Reopen"]],
};
const BLANK = { category: "ai_safety", severity: "moderate", title: "", description: "", patient_id: "",
                linked_entity_type: "", linked_entity_id: "" };

function ReportForm({ onCreated }) {
  const [form, setForm] = useState(BLANK);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const body = { ...form };
      for (const k of ["patient_id", "linked_entity_type", "linked_entity_id"]) if (!body[k].trim()) body[k] = null;
      const created = await api("/governance/incidents", { method: "POST", body });
      setForm(BLANK);
      setDone(created.title);
      onCreated();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card stack" onSubmit={submit} aria-labelledby="report-title">
      <span id="report-title" className="card-title">Report an incident</span>
      <p className="small muted">For AI behaviour that could harm a patient, privacy concerns, and security events.
        If a patient is in danger now, act first and report after.</p>
      <div className="gv-form-grid">
        <div className="field gv-field"><label htmlFor="i-cat">Category</label>
          <select id="i-cat" value={form.category} onChange={set("category")}>
            {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select></div>
        <div className="field gv-field"><label htmlFor="i-sev">Severity</label>
          <select id="i-sev" value={form.severity} onChange={set("severity")}>
            {SEVERITIES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </select></div>
        <div className="field gv-field gv-span2"><label htmlFor="i-title">Short title</label>
          <input id="i-title" required minLength={3} maxLength={200} value={form.title} onChange={set("title")} /></div>
        <div className="field gv-field gv-span2"><label htmlFor="i-desc">What happened</label>
          <textarea id="i-desc" className="edit" required minLength={10} maxLength={5000} value={form.description}
                    onChange={set("description")} /></div>
        <div className="field gv-field"><label htmlFor="i-pat">Patient id (optional)</label>
          <input id="i-pat" value={form.patient_id} onChange={set("patient_id")} placeholder="If a patient is involved" /></div>
        <div className="field gv-field"><label htmlFor="i-etype">Linked item type (optional)</label>
          <input id="i-etype" value={form.linked_entity_type} onChange={set("linked_entity_type")} placeholder="conversation, report…" /></div>
        <div className="field gv-field gv-span2"><label htmlFor="i-eid">Linked item id (optional)</label>
          <input id="i-eid" value={form.linked_entity_id} onChange={set("linked_entity_id")} /></div>
      </div>
      <div aria-live="polite">
        {error && <div className="error-box">{error}</div>}
        {done && <div className="banner ok">Reported: {done}. An administrator will triage it.</div>}
      </div>
      <button className="btn primary" type="submit" disabled={busy} style={{ alignSelf: "flex-start" }}>
        {busy ? "Sending…" : "Report incident"}
      </button>
    </form>
  );
}

function Incident({ incident, isAdmin, onChanged }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function move(status) {
    setBusy(true);
    setError(null);
    try {
      await api(`/governance/incidents/${incident.id}/transition`, { method: "POST", body: { status, note } });
      setNote("");
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const noteId = `note-${incident.id}`;
  return (
    <article className={`card stack ${incident.severity === "critical" && incident.status !== "resolved" ? "alert" : ""}`}>
      <div className="row between wrap" style={{ alignItems: "flex-start" }}>
        <div className="stack" style={{ gap: 4 }}>
          <span className="card-title">{incident.title}</span>
          <span className="tiny muted">
            {CATEGORY_LABEL[incident.category] || humanize(incident.category)} · reported by {incident.reported_by_name} · {fmtStamp(incident.created_at)}
          </span>
        </div>
        <div className="row wrap" style={{ gap: 6 }}>
          <span className={`chip ${SEVERITY_CHIP[incident.severity]}`}>
            {(incident.severity === "high" || incident.severity === "critical") && <Warning size={12} />} {humanize(incident.severity)}
          </span>
          <span className={`chip ${STATUS_CHIP[incident.status]}`}>{humanize(incident.status)}</span>
        </div>
      </div>
      <p className="small">{incident.description}</p>
      {(incident.patient_name || incident.linked_entity_type) && (
        <p className="tiny muted">
          {incident.patient_name && <>Patient: {incident.patient_name}. </>}
          {incident.linked_entity_type && <>Linked: {humanize(incident.linked_entity_type)} {incident.linked_entity_id}</>}
        </p>
      )}
      {incident.resolution && <p className="small"><strong>Resolution:</strong> {incident.resolution}</p>}
      <details className="gv-details">
        <summary className="small">History ({incident.history.length})</summary>
        <ol className="gv-history">
          {incident.history.map((h, i) => (
            <li key={i} className="small">
              <strong>{humanize(h.status)}</strong> · {h.by} · {fmtStamp(h.at)}{h.note ? ` · ${h.note}` : ""}
            </li>
          ))}
        </ol>
      </details>
      {isAdmin && (
        <div className="stack" style={{ gap: 8 }}>
          <label htmlFor={noteId} className="small strong">Triage note{incident.status !== "resolved" ? " (required to resolve)" : ""}</label>
          <textarea id={noteId} className="edit" style={{ minHeight: 64 }} maxLength={2000} value={note}
                    onChange={(e) => setNote(e.target.value)} />
          <div className="row wrap" style={{ gap: 8 }}>
            {NEXT[incident.status].map(([s, label]) => (
              <button key={s} className={`btn sm ${s === "resolved" ? "primary" : ""}`} disabled={busy || (s === "resolved" && !note.trim())}
                      onClick={() => move(s)}>{label}</button>
            ))}
          </div>
          {error && <div className="error-box" role="alert">{error}</div>}
        </div>
      )}
    </article>
  );
}

export default function IncidentsPage() {
  const { me } = useSession();
  const isAdmin = me?.role === "admin";
  const [filter, setFilter] = useState("");
  const list = useApi(`/governance/incidents${filter ? `?status=${filter}` : ""}`);

  return (
    <WorkspaceLayout>
      <PageHeader eyebrow="Trust and safety" title="Safety incidents"
                  sub={isAdmin ? "Report, investigate and resolve AI safety and privacy incidents." : "Report AI safety and privacy incidents, and follow the ones you reported."} />
      <div className="ws-grid">
        <section className="span-5 stack">
          <ReportForm onCreated={list.reload} />
        </section>
        <section className="span-7 stack" aria-labelledby="inc-list">
          <div className="row between wrap">
            <h2 id="inc-list" className="card-title">{isAdmin ? "All incidents" : "Incidents I reported"}</h2>
            <div className="field gv-field" style={{ minWidth: 180 }}>
              <label htmlFor="inc-status" className="sr-only">Status</label>
              <select id="inc-status" value={filter} onChange={(e) => setFilter(e.target.value)}>
                <option value="">All statuses</option>
                <option value="open">Open</option>
                <option value="investigating">Investigating</option>
                <option value="resolved">Resolved</option>
              </select>
            </div>
          </div>
          {list.error && <div className="error-box">{list.error.message}</div>}
          {list.loading && !list.data && <div className="card"><div className="skeleton" /></div>}
          {list.data && list.data.length === 0 && <div className="card empty">No incidents here.</div>}
          {list.data?.map((i) => <Incident key={i.id} incident={i} isAdmin={isAdmin} onChanged={list.reload} />)}
        </section>
      </div>
    </WorkspaceLayout>
  );
}
