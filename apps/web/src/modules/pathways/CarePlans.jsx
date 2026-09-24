import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { fmtDate } from "../../format.js";
import { Check as CheckIcon, Plus, Warning } from "../../icons.jsx";
import { Field, LoadingCard, Toast, fmtDay, todayIso, useSave } from "../analytics/kit.jsx";
import TaskEditor, { KIND_LABEL, taskPayload, tempKey } from "./TaskEditor.jsx";
import "../analytics/charts.css";

function progress(p) {
  return `${p.done_count} of ${p.total_count} done${p.overdue_count ? ` · ${p.overdue_count} overdue` : ""}`;
}

function StartPlan({ onStarted, onCancel, onOpenExisting }) {
  const patients = useApi("/pathways/patients");
  const templates = useApi("/pathways/templates");
  const [patientId, setPatientId] = useState(null);
  const [template, setTemplate] = useState(undefined); // undefined: not chosen; null: blank; object: template
  const [title, setTitle] = useState("");
  const [tasks, setTasks] = useState([]);
  const [conflict, setConflict] = useState(null);
  const save = useSave();

  function chooseTemplate(t) {
    setTemplate(t);
    setTitle(t ? t.name : "");
    setTasks(t
      ? t.actions.map((a) => ({ _key: tempKey(), kind: a.kind, title: a.title, detail: a.detail || "", specialty: a.specialty || "", due_on: todayIso(a.due_offset_days) }))
      : [{ _key: tempKey(), kind: "checkin", title: "", detail: "", specialty: "", due_on: todayIso(7) }]);
  }

  async function submit() {
    setConflict(null);
    const out = await save.run(async () => {
      try {
        return await api("/pathways/care-plans", { method: "POST", body: {
          patient_id: patientId, pathway_id: template ? template.id : null, title, tasks: tasks.map((t) => taskPayload(t, "date")),
        } });
      } catch (e) {
        if (e.status === 409 && e.detail?.plan_id) setConflict(e.detail.plan_id);
        throw e;
      }
    });
    if (out) onStarted(out);
  }

  const patient = patients.data?.find((p) => p.id === patientId);

  return (
    <form className="card stack" onSubmit={(e) => { e.preventDefault(); submit(); }} aria-label="Start a care plan">
      <div className="row between wrap">
        <h2 className="card-title">Start a care plan</h2>
        <button type="button" className="btn sm" onClick={onCancel}>Cancel</button>
      </div>

      <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0, gap: 6 }}>
        <legend className="eyebrow" style={{ marginBottom: 6 }}>1. Patient</legend>
        {patients.error && <div className="error-box">{patients.error.message}</div>}
        {patients.loading && <div className="skeleton" />}
        {patients.data?.length === 0 && <p className="small muted">Nobody is on your panel yet.</p>}
        <div className="pick-list">
          {patients.data?.map((p) => (
            <button key={p.id} type="button" className="pick" aria-pressed={patientId === p.id} disabled={Boolean(p.active_plan_id)}
                    onClick={() => setPatientId(p.id)}>
              <span className="strong" style={{ flexGrow: 1 }}>{p.name}</span>
              {p.active_plan_id
                ? <span className="tiny muted">Active plan: {p.active_plan_title}</span>
                : patientId === p.id && <CheckIcon size={16} />}
            </button>
          ))}
        </div>
        <span className="tiny muted">A patient can have one active plan with you. Patients with one are shown but can't be picked.</span>
      </fieldset>

      {patientId && (
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0, gap: 6 }}>
          <legend className="eyebrow" style={{ marginBottom: 6 }}>2. Start from</legend>
          {templates.error && <div className="error-box">{templates.error.message}</div>}
          <div className="pick-list">
            {templates.data?.map((t) => (
              <button key={t.id} type="button" className="pick" aria-pressed={template?.id === t.id} onClick={() => chooseTemplate(t)}>
                <span style={{ flexGrow: 1 }}>
                  <span className="strong" style={{ display: "block" }}>{t.name}</span>
                  <span className="tiny muted">{t.specialty} · {t.actions.length} tasks</span>
                </span>
              </button>
            ))}
            <button type="button" className="pick" aria-pressed={template === null} onClick={() => chooseTemplate(null)}>
              <span className="strong" style={{ flexGrow: 1 }}>Blank plan</span>
            </button>
          </div>
        </fieldset>
      )}

      {patientId && template !== undefined && (
        <div className="stack" style={{ gap: 10 }}>
          <span className="eyebrow">3. Review for {patient?.name}</span>
          <Field id="new-plan-title" label="Plan title (the patient sees this)" value={title} onChange={setTitle} required minLength={2} maxLength={160} />
          <TaskEditor tasks={tasks} onChange={setTasks} mode="date" idPrefix="np" defaultSpecialty={template?.specialty || ""} />
          <p className="tiny muted">Starting the plan is your approval of its content. The patient sees it on their care plan page straight away.</p>
          {save.error && (
            <div className="error-box" role="alert">
              {save.error}
              {conflict && <> <button type="button" className="btn sm" onClick={() => onOpenExisting(conflict)}>Open that plan</button></>}
            </div>
          )}
          <div><button type="submit" className="btn primary" disabled={save.busy}>{save.busy ? "Starting…" : "Start care plan"}</button></div>
        </div>
      )}
    </form>
  );
}

function PlanDetail({ planId, onChanged }) {
  const plan = useApi(`/pathways/care-plans/${planId}`);
  const [title, setTitle] = useState("");
  const [tasks, setTasks] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const save = useSave();

  useEffect(() => {
    if (plan.data) {
      setTitle(plan.data.title);
      setTasks(plan.data.tasks.map((t) => ({ ...t, _key: t.id, detail: t.detail || "", specialty: t.specialty || "", due_on: t.due_on || "" })));
      setDirty(false);
      setConfirming(false);
    }
  }, [plan.data]);

  if (plan.error) return <div className="error-box" role="alert">{plan.error.message}</div>;
  if (plan.loading && !plan.data) return <LoadingCard lines={4} />;
  const p = plan.data;
  const active = p.status === "active";
  const open = p.tasks.filter((t) => t.status === "todo").length;

  async function saveChanges() {
    const out = await save.run(() => api(`/pathways/care-plans/${planId}`, { method: "PUT",
      body: { title, tasks: tasks.map((t) => taskPayload(t, "date")) } }), "Changes saved");
    if (out) { await plan.reload(); onChanged("Changes saved"); }
  }

  async function complete() {
    const out = await save.run(() => api(`/pathways/care-plans/${planId}/complete`, { method: "POST" }), "Plan completed");
    if (out) { await plan.reload(); onChanged("Care plan completed"); }
  }

  return (
    <article className="card stack" aria-labelledby="plan-title">
      <div className="row between wrap" style={{ gap: 8 }}>
        <div>
          <span className="eyebrow">{p.patient_name}</span>
          <h2 id="plan-title" className="page-title" style={{ fontSize: 24 }}>{p.title}</h2>
          <p className="small muted">
            Started {fmtDate(p.started_at)}{p.pathway_name ? ` from "${p.pathway_name}"` : " as a blank plan"}
            {p.completed_at ? ` · completed ${fmtDate(p.completed_at)}` : ""} · {p.done_count} of {p.tasks.length} done
          </p>
        </div>
        {active ? <span className="chip ok">Active</span> : <span className="chip">Completed</span>}
      </div>

      {active ? (
        <form className="stack" onSubmit={(e) => { e.preventDefault(); saveChanges(); }}>
          <Field id="plan-edit-title" label="Plan title" value={title} onChange={(v) => { setTitle(v); setDirty(true); }} required minLength={2} maxLength={160} />
          <TaskEditor tasks={tasks} onChange={(t) => { setTasks(t); setDirty(true); }} mode="date" idPrefix="ed" />
          {save.error && <div className="error-box" role="alert">{save.error}</div>}
          <div className="row wrap" style={{ gap: 8 }}>
            <button type="submit" className="btn primary" disabled={save.busy || !dirty}>{save.busy ? "Saving…" : "Save changes"}</button>
            {dirty && <button type="button" className="btn" onClick={() => plan.reload()}>Discard changes</button>}
          </div>
        </form>
      ) : (
        <ol className="stack" style={{ margin: 0, padding: 0, listStyle: "none", gap: 6 }}>
          {p.tasks.map((t) => (
            <li key={t.id} className="toggle-row">
              <span className={`chip ${t.status === "done" ? "ok" : ""}`}>{t.status === "done" ? "Done" : "Not done"}</span>
              <span className="small" style={{ flexGrow: 1 }}>{t.title} <span className="muted">· {KIND_LABEL[t.kind]}{t.due_on ? ` · due ${fmtDay(t.due_on)}` : ""}</span></span>
            </li>
          ))}
        </ol>
      )}

      {active && (
        <div className="stack" style={{ gap: 8, borderTop: "1px solid var(--line-soft)", paddingTop: 12 }}>
          {!confirming ? (
            <div><button type="button" className="btn" onClick={() => setConfirming(true)} disabled={dirty || save.busy}>Complete plan</button>
              {dirty && <span className="tiny muted" style={{ marginLeft: 8 }}>Save or discard your changes first.</span>}</div>
          ) : (
            <div className="banner warn" role="alert" style={{ flexWrap: "wrap" }}>
              <Warning size={15} />
              {open ? `${open} task${open === 1 ? " is" : "s are"} not done yet. ` : ""}Completing ends the plan for {p.patient_name}; it leaves their care plan page.
              <span className="row" style={{ gap: 6 }}>
                <button type="button" className="btn dark sm" onClick={complete} disabled={save.busy}>Complete plan</button>
                <button type="button" className="btn sm" onClick={() => setConfirming(false)}>Keep it active</button>
              </span>
            </div>
          )}
        </div>
      )}
    </article>
  );
}

export default function CarePlans() {
  const plans = useApi("/pathways/care-plans");
  const [params, setParams] = useSearchParams();
  const selected = params.get("plan");
  const [starting, setStarting] = useState(false);
  const [toast, setToast] = useState(null);
  const clearToast = useCallback(() => setToast(null), []);

  function open(id) {
    setStarting(false);
    setParams(id ? { plan: id } : {});
  }

  const active = plans.data?.filter((p) => p.status === "active") || [];
  const done = plans.data?.filter((p) => p.status !== "active") || [];

  return (
    <WorkspaceLayout>
      <header className="ops-header">
        <div>
          <h1 className="page-title">Care plans</h1>
          <p className="page-sub">Start a plan from a care pathway or from scratch, adjust tasks and dates, and complete it when the journey ends.</p>
        </div>
        {!starting && <button type="button" className="btn primary" onClick={() => { setStarting(true); setParams({}); }}><Plus size={16} /> Start a care plan</button>}
      </header>

      <div className="ws-grid">
        <nav className="span-4 stack" aria-label="Your care plans">
          {plans.error && <div className="error-box" role="alert">{plans.error.message}</div>}
          {plans.loading && !plans.data && <LoadingCard />}
          {plans.data?.length === 0 && <div className="card empty">You haven't started any care plans yet.</div>}
          {active.length > 0 && <span className="eyebrow">Active</span>}
          <div className="pick-list">
            {active.map((p) => (
              <button key={p.id} type="button" className="pick" aria-current={selected === p.id} onClick={() => open(p.id)}>
                <span style={{ flexGrow: 1 }}>
                  <span className="strong" style={{ display: "block" }}>{p.patient_name}</span>
                  <span className="tiny muted">{p.title} · {progress(p)}</span>
                </span>
                {p.overdue_count > 0 && <span className="chip warn">Overdue</span>}
              </button>
            ))}
          </div>
          {done.length > 0 && <span className="eyebrow" style={{ marginTop: 8 }}>Completed in the last 90 days</span>}
          <div className="pick-list">
            {done.map((p) => (
              <button key={p.id} type="button" className="pick" aria-current={selected === p.id} onClick={() => open(p.id)}>
                <span style={{ flexGrow: 1 }}>
                  <span className="strong" style={{ display: "block" }}>{p.patient_name}</span>
                  <span className="tiny muted">{p.title} · {p.done_count} of {p.total_count} done</span>
                </span>
              </button>
            ))}
          </div>
        </nav>

        <section className="span-8">
          {starting && (
            <StartPlan onCancel={() => setStarting(false)} onOpenExisting={open}
                       onStarted={(plan) => { setToast("Care plan started"); plans.reload(); open(plan.id); }} />
          )}
          {!starting && selected && <PlanDetail key={selected} planId={selected} onChanged={(m) => { setToast(m); plans.reload(); }} />}
          {!starting && !selected && plans.data?.length > 0 && (
            <div className="card empty">Choose a plan to review or edit it, or start a new one.</div>
          )}
        </section>
      </div>
      <Toast message={toast} onDone={clearToast} />
    </WorkspaceLayout>
  );
}
