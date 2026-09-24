import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useApi } from "../hooks.js";
import { useSession } from "../session.jsx";
import { fmtDate, fmtDateTime, fmtShortDate } from "../format.js";
import { Calendar, Chevron } from "../icons.jsx";

function dueLabel(t) {
  if (t.status === "done") return t.completed_at ? `Done ${fmtShortDate(t.completed_at)}` : "Done";
  if (!t.due_on) return t.detail || "";
  if (t.overdue) return `Overdue since ${fmtShortDate(t.due_on)}`;
  if (t.due_today) return "Due today";
  return `By ${fmtShortDate(t.due_on)}`;
}

function Task({ task, isNext, onToggle, busy }) {
  const done = task.status === "done";
  const id = `task-${task.id}`;
  return (
    <div className={`card stack ${isNext ? "highlight" : ""}`} style={{ gap: 10 }}>
      <div className={`task ${done ? "done" : ""}`}>
        <input id={id} type="checkbox" checked={done} disabled={busy} onChange={() => onToggle(task)} />
        <label htmlFor={id} className="stack" style={{ gap: 2 }}>
          <span className="task-title">{task.title}</span>
          <span className={`small ${task.overdue || task.due_today ? "strong" : "muted"}`}
                style={{ color: task.overdue || task.due_today ? "var(--alert)" : undefined }}>
            {dueLabel(task)}{task.detail && task.status !== "done" ? ` · ${task.detail}` : ""}
          </span>
        </label>
      </div>
      {!done && task.kind === "appointment" && (
        <div style={{ paddingLeft: 34 }}>
          <Link className="btn sm" to={`/care/find?specialty=${encodeURIComponent(task.specialty || "Primary care")}&task=${task.id}`}>
            Find a time <Chevron size={14} />
          </Link>
        </div>
      )}
      {!done && task.kind === "medication" && (
        <div style={{ paddingLeft: 34 }}>
          <Link className="btn sm" to="/results">Why this medicine?</Link>
        </div>
      )}
    </div>
  );
}

export default function CarePlan() {
  const { me } = useSession();
  const plan = useApi(`/patients/${me.patient_id}/care-plan`);
  const appts = useApi(`/patients/${me.patient_id}/appointments`);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  // Optimistic status per task, shown immediately and cleared once the server confirms.
  const [pending, setPending] = useState({});

  async function toggle(task) {
    const status = task.status === "done" ? "todo" : "done";
    setPending((p) => ({ ...p, [task.id]: status }));
    setBusy(true);
    setError(null);
    try {
      await api(`/care-plan-tasks/${task.id}`, { method: "PATCH", body: { status } });
      await plan.reload();
    } catch (e) {
      setError(`Couldn't update "${task.title}". ${e.message}`);
    } finally {
      setPending((p) => {
        const { [task.id]: _, ...rest } = p;
        return rest;
      });
      setBusy(false);
    }
  }

  async function cancel(id) {
    setError(null);
    try {
      await api(`/appointments/${id}/cancel`, { method: "POST" });
      await appts.reload();
    } catch (e) {
      setError(e.message);
    }
  }

  const p = plan.data;
  const next = p?.tasks.find((t) => t.id === p.next_task_id);

  return (
    <main className="column">
      {plan.error && <div className="error-box">{plan.error.message}</div>}
      {plan.loading && !p && <div className="card"><div className="skeleton" /></div>}
      {!plan.loading && !p && !plan.error && <div className="card empty">You don't have an active care plan.</div>}
      {p && (
        <>
          <div className="stack" style={{ marginBottom: 16 }}>
            <div>
              <div className="page-title">Your care plan</div>
              <div className="page-sub">From {p.practitioner_name}, {p.specialty} · started {fmtDate(p.started_at)}</div>
            </div>
            <div className="stack" style={{ gap: 6 }}>
              <div className="row between small strong">
                <span>{p.done_count} of {p.total_count} done</span>
                {next && <span className="muted">Next: {next.title.toLowerCase()}</span>}
              </div>
              <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={p.total_count} aria-valuenow={p.done_count}>
                <div style={{ width: `${(100 * p.done_count) / p.total_count}%` }} />
              </div>
            </div>
          </div>
          {error && <div className="error-box" style={{ marginBottom: 12 }}>{error}</div>}
          <div className="stack" style={{ gap: 10 }}>
            {p.tasks.map((t) => (
              <Task
                key={t.id}
                task={pending[t.id] ? { ...t, status: pending[t.id] } : t}
                isNext={t.id === p.next_task_id}
                onToggle={() => toggle(t)}
                busy={busy}
              />
            ))}
          </div>
        </>
      )}

      <section style={{ marginTop: 24 }} className="stack">
        <div className="eyebrow">Upcoming appointments</div>
        {appts.data?.length === 0 && <div className="card small muted">Nothing booked yet.</div>}
        {appts.data?.map((a) => (
          <div key={a.id} className="card row between wrap">
            <div>
              <div className="strong">{a.practitioner_name}</div>
              <div className="small muted row" style={{ gap: 6 }}><Calendar size={14} /> {fmtDateTime(a.starts_at)} · {a.location_name}</div>
            </div>
            <button className="btn sm" onClick={() => cancel(a.id)}>Cancel</button>
          </div>
        ))}
      </section>
    </main>
  );
}
