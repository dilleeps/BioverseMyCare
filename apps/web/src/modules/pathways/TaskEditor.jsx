// Ordered task list editor. mode "offset": due N days after the plan starts (templates).
// mode "date": a due date (a patient's care plan). Completed tasks are shown locked.
import { Close, Down, Lock, Plus, Up } from "../../icons.jsx";

export const KINDS = [
  { value: "lab", label: "Lab test" },
  { value: "medication", label: "Medication" },
  { value: "appointment", label: "Appointment" },
  { value: "referral", label: "Referral" },
  { value: "checkin", label: "Check-in" },
  { value: "lifestyle", label: "Lifestyle" },
];
export const KIND_LABEL = Object.fromEntries(KINDS.map((k) => [k.value, k.label]));

let seq = 0;
export const tempKey = () => `new-${Date.now()}-${++seq}`;

export default function TaskEditor({ tasks, onChange, mode, idPrefix = "t", defaultSpecialty = "" }) {
  function update(i, patch) {
    onChange(tasks.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  }
  function move(i, delta) {
    const next = [...tasks];
    const [item] = next.splice(i, 1);
    next.splice(i + delta, 0, item);
    onChange(next);
  }
  function remove(i) {
    onChange(tasks.filter((_, j) => j !== i));
  }
  function add() {
    const base = { _key: tempKey(), kind: "checkin", title: "", detail: "", specialty: "" };
    onChange([...tasks, mode === "offset" ? { ...base, due_offset_days: 7 } : { ...base, due_on: "" }]);
  }

  return (
    <div className="stack" style={{ gap: 8 }}>
      <ol className="stack" style={{ gap: 8, margin: 0, padding: 0, listStyle: "none" }} aria-label="Tasks">
        {tasks.map((t, i) => {
          const key = t.id || t._key;
          const done = t.status === "done";
          const id = `${idPrefix}-${key}`;
          const needsSpecialty = t.kind === "appointment" || t.kind === "referral";
          return (
            <li key={key} className={`task-edit ${done ? "done" : ""}`}>
              <span className="num-badge" aria-hidden="true">{i + 1}</span>
              <div className="task-fields">
                {done ? (
                  <div className="wide stack" style={{ gap: 2 }}>
                    <span className="strong">{t.title}</span>
                    <span className="small muted row" style={{ gap: 6 }}><Lock size={12} /> Done{t.due_on ? ` · was due ${t.due_on}` : ""}. Completed tasks stay as recorded.</span>
                  </div>
                ) : (
                  <>
                    <div className="fld">
                      <label htmlFor={`${id}-kind`}>Type</label>
                      <select id={`${id}-kind`} value={t.kind} onChange={(e) => update(i, { kind: e.target.value,
                        specialty: (e.target.value === "appointment" || e.target.value === "referral") && !t.specialty ? defaultSpecialty : t.specialty })}>
                        {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                      </select>
                    </div>
                    <div className="fld">
                      <label htmlFor={`${id}-title`}>Task</label>
                      <input id={`${id}-title`} value={t.title} maxLength={160} required minLength={2}
                             onChange={(e) => update(i, { title: e.target.value })} />
                    </div>
                    {mode === "offset" ? (
                      <div className="fld">
                        <label htmlFor={`${id}-due`}>Due after (days)</label>
                        <input id={`${id}-due`} type="number" min={0} max={730} value={t.due_offset_days}
                               onChange={(e) => update(i, { due_offset_days: e.target.value === "" ? "" : Number(e.target.value) })} required />
                      </div>
                    ) : (
                      <div className="fld">
                        <label htmlFor={`${id}-due`}>Due date</label>
                        <input id={`${id}-due`} type="date" value={t.due_on || ""} onChange={(e) => update(i, { due_on: e.target.value })} />
                      </div>
                    )}
                    <div className="fld">
                      <label htmlFor={`${id}-spec`}>Specialty{needsSpecialty ? "" : " (optional)"}</label>
                      <input id={`${id}-spec`} value={t.specialty || ""} maxLength={80} required={needsSpecialty}
                             onChange={(e) => update(i, { specialty: e.target.value })} />
                    </div>
                    <div className="fld wide">
                      <label htmlFor={`${id}-detail`}>Detail for the patient (optional)</label>
                      <input id={`${id}-detail`} value={t.detail || ""} maxLength={400} onChange={(e) => update(i, { detail: e.target.value })} />
                    </div>
                  </>
                )}
              </div>
              <div className="task-actions">
                <button type="button" className="icon-sq" onClick={() => move(i, -1)} disabled={i === 0} aria-label={`Move task ${i + 1} up`}><Up size={16} /></button>
                <button type="button" className="icon-sq" onClick={() => move(i, 1)} disabled={i === tasks.length - 1} aria-label={`Move task ${i + 1} down`}><Down size={16} /></button>
                <button type="button" className="icon-sq" onClick={() => remove(i)} disabled={done || tasks.length === 1}
                        aria-label={done ? `Task ${i + 1} is done and can't be removed` : `Remove task ${i + 1}`}><Close size={16} /></button>
              </div>
            </li>
          );
        })}
      </ol>
      <button type="button" className="btn sm" style={{ alignSelf: "flex-start" }} onClick={add}><Plus size={14} /> Add task</button>
    </div>
  );
}

// Strip editor-only fields before sending.
export function taskPayload(t, mode) {
  const out = { kind: t.kind, title: t.title.trim(), detail: t.detail?.trim() || null, specialty: t.specialty?.trim() || null };
  if (mode === "offset") return { ...out, due_offset_days: Number(t.due_offset_days) || 0 };
  return { ...out, id: t.id || null, due_on: t.due_on || null };
}
