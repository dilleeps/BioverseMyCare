import { useCallback, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { Plus } from "../../icons.jsx";
import { Check, Field, LoadingCard, Toast, useSave } from "../analytics/kit.jsx";
import TaskEditor, { KIND_LABEL, taskPayload, tempKey } from "./TaskEditor.jsx";
import "../analytics/charts.css";

const BLANK = { name: "", specialty: "", description: "", active: true,
  actions: [{ _key: "first", kind: "checkin", title: "", detail: "", specialty: "", due_offset_days: 0 }] };

function Editor({ initial, isNew, onSaved, onCancel }) {
  const [form, setForm] = useState(() => ({
    ...initial,
    description: initial.description || "",
    actions: initial.actions.map((a) => ({ ...a, _key: a.id || a._key || tempKey(), detail: a.detail || "", specialty: a.specialty || "" })),
  }));
  const save = useSave();
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));

  async function submit() {
    const body = { name: form.name, specialty: form.specialty, description: form.description || null, active: form.active,
      actions: form.actions.map((a) => taskPayload(a, "offset")) };
    const out = await save.run(() => api(isNew ? "/pathways/templates" : `/pathways/templates/${initial.id}`,
      { method: isNew ? "POST" : "PUT", body }));
    if (out) onSaved(isNew ? "Pathway created" : "Pathway saved");
  }

  return (
    <form className="card stack" onSubmit={(e) => { e.preventDefault(); submit(); }} aria-label={isNew ? "New care pathway" : `Edit ${initial.name}`}>
      <span className="card-title">{isNew ? "New care pathway" : `Edit ${initial.name}`}</span>
      <div className="form-grid">
        <Field id="pw-name" label="Name" value={form.name} onChange={set("name")} required minLength={2} maxLength={160} />
        <Field id="pw-spec" label="Specialty" value={form.specialty} onChange={set("specialty")} required minLength={2} maxLength={80} />
      </div>
      <div className="fld">
        <label htmlFor="pw-desc">Description (optional)</label>
        <textarea id="pw-desc" value={form.description} maxLength={400} onChange={(e) => set("description")(e.target.value)} />
      </div>
      <Check id="pw-active" label="Available to clinicians" checked={form.active} onChange={set("active")} />
      <div className="stack" style={{ gap: 6 }}>
        <span className="small strong" style={{ color: "var(--ink-2)" }}>Tasks, in order</span>
        <span className="tiny muted">Each task is due a number of days after the clinician starts the plan. Clinicians can adjust dates for each patient.</span>
        <TaskEditor tasks={form.actions} onChange={set("actions")} mode="offset" idPrefix="pw" defaultSpecialty={form.specialty} />
      </div>
      {save.error && <div className="error-box" role="alert">{save.error}</div>}
      <div className="row wrap" style={{ gap: 8 }}>
        <button type="submit" className="btn primary" disabled={save.busy}>{save.busy ? "Saving…" : "Save pathway"}</button>
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

export default function PathwaysAdmin() {
  const list = useApi("/pathways/templates");
  const [editing, setEditing] = useState(null);
  const [toast, setToast] = useState(null);
  const clearToast = useCallback(() => setToast(null), []);

  return (
    <WorkspaceLayout>
      <header className="ops-header">
        <div>
          <h1 className="page-title">Care pathways</h1>
          <p className="page-sub">Templates clinicians start care plans from. Changes apply to new plans only; plans already started keep their tasks.</p>
        </div>
        {!editing && <button type="button" className="btn primary" onClick={() => setEditing("new")}><Plus size={16} /> New pathway</button>}
      </header>

      {editing && (
        <div style={{ marginBottom: 16 }}>
          <Editor key={editing === "new" ? "new" : editing.id} initial={editing === "new" ? BLANK : editing} isNew={editing === "new"}
                  onCancel={() => setEditing(null)}
                  onSaved={(m) => { setEditing(null); setToast(m); list.reload(); }} />
        </div>
      )}

      {list.error && <div className="error-box" role="alert">{list.error.message}</div>}
      {list.loading && !list.data && <LoadingCard />}
      {list.data?.length === 0 && <div className="card empty">No care pathways yet. Create one to give clinicians a starting point.</div>}
      <div className="hub-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}>
        {list.data?.map((p) => (
          <article key={p.id} className="card stack" style={{ margin: 0 }} aria-labelledby={`pw-${p.id}`}>
            <div className="row between wrap" style={{ gap: 8 }}>
              <div>
                <h2 id={`pw-${p.id}`} className="card-title">{p.name}</h2>
                <span className="small muted">{p.specialty} · {p.actions.length} tasks · {p.plans_started} plan{p.plans_started === 1 ? "" : "s"} started</span>
              </div>
              {p.active ? <span className="chip ok">Available</span> : <span className="chip">Hidden</span>}
            </div>
            {p.description && <p className="small" style={{ color: "var(--ink-2)" }}>{p.description}</p>}
            <ol className="small" style={{ margin: 0, paddingLeft: 18, color: "var(--ink-2)", lineHeight: 1.6 }}>
              {p.actions.map((a) => (
                <li key={a.id}>{a.title} <span className="muted">· {KIND_LABEL[a.kind]} · {a.due_offset_days === 0 ? "at start" : `day ${a.due_offset_days}`}</span></li>
              ))}
            </ol>
            <div><button type="button" className="btn sm" onClick={() => setEditing(p)} disabled={Boolean(editing)}>Edit</button></div>
          </article>
        ))}
      </div>
      <Toast message={toast} onDone={clearToast} />
    </WorkspaceLayout>
  );
}
