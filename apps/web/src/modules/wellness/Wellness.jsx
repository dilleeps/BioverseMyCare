import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { useSession } from "../../session.jsx";
import { Check, Chevron, Phone, Plus, Warning } from "../../icons.jsx";

// Dates from the API are calendar days ("2026-09-24"). Parse them as local days, not UTC midnight.
function day(iso) {
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}
const fmtDay = (iso) => (iso ? day(iso).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" }) : "");
const weekday = (iso) => day(iso).toLocaleDateString([], { weekday: "short" });
const longDay = (iso) => day(iso).toLocaleDateString([], { weekday: "long", day: "numeric", month: "short" });
const fmtValue = (v) => (v == null ? "" : Number(v).toLocaleString([], { maximumFractionDigits: 1 }));
function shiftDay(iso, n) {
  const d = day(iso);
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const STATUS = {
  overdue: { label: "Overdue", chip: "warn" },
  due: { label: "Due", chip: "" },
  up_to_date: { label: "Up to date", chip: "ok" },
};

// --- Preventive checklist ---------------------------------------------------------------------------

function Prevention({ patientId }) {
  const { data, error, loading, reload } = useApi(`/wellness/patients/${patientId}/prevention`);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState(null);
  const [syncErr, setSyncErr] = useState(null);

  async function sync() {
    setSyncing(true);
    setSyncErr(null);
    setSyncMsg(null);
    try {
      const r = await api(`/wellness/patients/${patientId}/prevention/sync`, { method: "POST" });
      const parts = [];
      if (r.opened.length) parts.push(`${r.opened.length} added`);
      if (r.closed.length) parts.push(`${r.closed.length} marked done`);
      setSyncMsg(parts.length ? `Your health story is updated: ${parts.join(", ")}.` : "Your health story was already up to date.");
      await reload();
    } catch (e) {
      setSyncErr(e.message);
    } finally {
      setSyncing(false);
    }
  }

  const due = data?.items.filter((i) => i.status !== "up_to_date") || [];
  return (
    <section className="wl-section" aria-labelledby="wl-prev">
      <div className="wl-section-head">
        <div>
          <h2 id="wl-prev" className="wl-section-title">Preventive care</h2>
          <div className="page-sub">Screenings and vaccines for your age, checked against your record.</div>
        </div>
        {due.length > 0 && (
          <button className="btn sm" onClick={sync} disabled={syncing}>
            {syncing ? "Updating…" : "Add to my health story"}
          </button>
        )}
      </div>
      {error && <div className="error-box">{error.message}</div>}
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {syncMsg && <div className="banner ok" role="status" style={{ marginBottom: 10 }}><Check size={16} /> {syncMsg}</div>}
      {syncErr && <div className="error-box" style={{ marginBottom: 10 }}>{syncErr}</div>}
      {data && (
        <div className="card" style={{ padding: "4px 18px" }}>
          <p className="banner info" style={{ margin: "12px 0 4px" }}>{data.disclaimer}</p>
          {data.items.length === 0 && <div className="empty">Nothing on the checklist for your age yet.</div>}
          {data.items.map((i) => {
            const s = STATUS[i.status];
            return (
              <div key={i.rule_id} className="wl-item">
                <div className="wl-item-body">
                  <div className="row wrap" style={{ gap: 8 }}>
                    <span className="strong">{i.title}</span>
                    <span className={`chip ${s.chip}`}>
                      {i.status === "overdue" && <Warning size={12} />}
                      {i.status === "up_to_date" && <Check size={12} />}
                      {s.label}
                    </span>
                  </div>
                  {i.last_date && (
                    <span className="small muted">
                      Last recorded {fmtDay(i.last_date)}
                      {i.status === "up_to_date" && i.next_due ? ` · next due ${fmtDay(i.next_due)}` : ""}
                      {i.status === "overdue" && i.next_due ? ` · was due ${fmtDay(i.next_due)}` : ""}
                    </span>
                  )}
                  <span className="small">{i.detail}</span>
                  <details>
                    <summary>Why this matters</summary>
                    <p>{i.why}</p>
                    <p>Source: {i.source}. Ruleset {data.ruleset}.</p>
                  </details>
                </div>
                {i.status !== "up_to_date" && (
                  <Link className={`btn sm ${i.status === "overdue" ? "danger" : ""}`}
                        to={`/care/find?specialty=${encodeURIComponent(i.specialty)}`}
                        aria-label={`Book: ${i.title}`}>
                    Book
                  </Link>
                )}
              </div>
            );
          })}
          {data.notes.map((n) => <p key={n} className="small muted" style={{ padding: "8px 0 14px" }}>{n}</p>)}
        </div>
      )}
    </section>
  );
}

// --- Goals ------------------------------------------------------------------------------------------------

// Last 7 days as columns against the target line. Hover or focus a day for its value; the table has them all.
function WeekChart({ goal }) {
  const [active, setActive] = useState(null);
  const series = goal.progress.series;
  const W = 320, H = 144, base = 116, top = 32;
  const max = Math.max(goal.target, ...series.map((s) => s.value || 0)) * 1.12;
  const y = (v) => base - ((base - top) * v) / max;
  const slot = W / series.length;
  const bw = Math.min(24, slot * 0.5);
  const lastLogged = [...series].reverse().find((s) => s.value != null);

  function bar(x, v) {
    const h = base - y(v);
    if (h <= 0) return "";
    const r = Math.min(4, h, bw / 2);
    // Rounded data end, square at the baseline.
    return `M${x},${base} V${base - h + r} Q${x},${base - h} ${x + r},${base - h} H${x + bw - r} Q${x + bw},${base - h} ${x + bw},${base - h + r} V${base} Z`;
  }

  const tip = active != null ? series[active] : null;
  return (
    <div className="wl-chart">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" aria-label={`${goal.title}, last 7 days`} role="group">
        <line x1="0" y1={base} x2={W} y2={base} stroke="var(--line)" strokeWidth="1" />
        <line x1="0" y1={y(goal.target)} x2={W} y2={y(goal.target)} stroke="var(--muted)" strokeWidth="1" />
        {/* Target label sits in the left gutter, above the bars, so it never meets the value label. */}
        <text x={0} y={12} fontSize="11" fontWeight="600" fill="var(--muted)">
          Line: target {fmtValue(goal.target)} {goal.unit}
        </text>
        {series.map((s, i) => {
          const x = i * slot + (slot - bw) / 2;
          return (
            <g key={s.day}>
              {s.value != null
                ? <path className={`bar ${active === i ? "active" : ""}`} d={bar(x, s.value)} fill="var(--accent)" />
                : <line x1={x + 4} x2={x + bw - 4} y1={base - 1} y2={base - 1} stroke="var(--faint)" strokeWidth="2" strokeLinecap="round" />}
              <text x={x + bw / 2} y={base + 16} textAnchor="middle" fontSize="11" fill="var(--muted)">{weekday(s.day)}</text>
              {s === lastLogged && (
                <text x={x + bw / 2} y={y(s.value) - 6} textAnchor="middle" fontSize="11" fontWeight="700" fill="var(--ink)">
                  {fmtValue(s.value)}
                </text>
              )}
              <rect className="hit" x={i * slot} y={0} width={slot} height={base + 20} tabIndex={0}
                    aria-label={`${longDay(s.day)}: ${s.value == null ? "nothing logged" : `${fmtValue(s.value)} ${goal.unit}, ${s.met ? "target met" : "below target"}`}`}
                    onPointerEnter={() => setActive(i)} onPointerLeave={() => setActive(null)}
                    onFocus={() => setActive(i)} onBlur={() => setActive(null)} />
            </g>
          );
        })}
      </svg>
      {tip && (
        <div className="wl-tip" aria-hidden="true" style={{
          // Edge days anchor to the chart edge so the tooltip stays inside the card.
          left: active <= 1 ? 0 : active >= series.length - 2 ? "100%" : `${((active + 0.5) / series.length) * 100}%`,
          top: 44,
          transform: `translate(${active <= 1 ? "0" : active >= series.length - 2 ? "-100%" : "-50%"}, -100%)`,
        }}>
          <strong>{tip.value == null ? "No entry" : `${fmtValue(tip.value)} ${goal.unit}`}</strong>
          {longDay(tip.day)}{tip.value != null ? (tip.met ? " · target met" : " · below target") : ""}
        </div>
      )}
      <details>
        <summary className="small" style={{ cursor: "pointer", color: "var(--accent)", fontWeight: 600, minHeight: 32, display: "inline-flex", alignItems: "center" }}>
          Show as a table
        </summary>
        <table className="wl-table">
          <thead><tr><th scope="col">Day</th><th scope="col">{goal.unit}</th><th scope="col">Target met</th></tr></thead>
          <tbody>
            {series.map((s) => (
              <tr key={s.day}><td>{longDay(s.day)}</td><td>{s.value == null ? "—" : fmtValue(s.value)}</td><td>{s.value == null ? "—" : s.met ? "Yes" : "No"}</td></tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

function GoalCard({ goal, today, onChanged }) {
  const [value, setValue] = useState(goal.logged_today ?? "");
  const [which, setWhich] = useState(today);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const p = goal.progress;
  const inputId = `log-${goal.id}`;
  const dayId = `logday-${goal.id}`;

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/wellness/goals/${goal.id}/entries/${which}`, { method: "PUT", body: { value: Number(value) } });
      await onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function archive() {
    setError(null);
    try {
      await api(`/wellness/goals/${goal.id}`, { method: "PATCH", body: { status: "archived" } });
      await onChanged();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <article className="card stack" aria-labelledby={`goal-${goal.id}`}>
      <div className="row between wrap">
        <div>
          <h3 id={`goal-${goal.id}`} className="card-title">{goal.title}</h3>
          <div className="small muted">Target {fmtValue(goal.target)} {goal.unit} a day</div>
        </div>
        <span className="chip">Reported by you</span>
      </div>

      <div className="stack" style={{ gap: 6 }}>
        <div className="row between small">
          <span className="strong">Target met on {p.last_7.met} of the last 7 days</span>
          <span className="muted">{p.last_7.percent_met}%</span>
        </div>
        <div className="wl-meter" role="meter" aria-valuemin={0} aria-valuemax={7} aria-valuenow={p.last_7.met}
             aria-label={`Target met on ${p.last_7.met} of the last 7 days`}>
          <div style={{ width: `${(100 * p.last_7.met) / 7}%` }} />
        </div>
      </div>

      <WeekChart goal={goal} />

      <div className="wl-stats">
        <div className="wl-stat"><div className="v">{p.current_streak}</div><div className="tiny muted">Day streak</div></div>
        <div className="wl-stat"><div className="v">{p.best_streak}</div><div className="tiny muted">Best streak</div></div>
        <div className="wl-stat">
          <div className="v">{p.last_30.met}/30</div><div className="tiny muted">Days met, last 30</div>
        </div>
      </div>

      <form className="wl-log" onSubmit={save}>
        <div className="wl-field">
          <label htmlFor={dayId}>Day</label>
          <select id={dayId} value={which} onChange={(e) => setWhich(e.target.value)}>
            <option value={today}>Today</option>
            <option value={shiftDay(today, -1)}>Yesterday</option>
          </select>
        </div>
        <div className="wl-field">
          <label htmlFor={inputId}>{goal.unit[0].toUpperCase() + goal.unit.slice(1)}</label>
          <input id={inputId} type="number" min="0" step="any" inputMode="decimal" required value={value}
                 onChange={(e) => setValue(e.target.value)} />
        </div>
        <button className="btn primary" disabled={busy || value === ""}>{busy ? "Saving…" : "Log"}</button>
      </form>
      {error && <div className="error-box">{error}</div>}
      <button className="btn ghost sm" style={{ alignSelf: "flex-start" }} onClick={archive}>Stop tracking this goal</button>
    </article>
  );
}

function AddGoal({ patientId, kinds, onAdded, preset }) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState("steps");
  const [target, setTarget] = useState("");
  const [title, setTitle] = useState("");
  const [unit, setUnit] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function add(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = { kind, target: target ? Number(target) : undefined };
      if (kind === "custom") Object.assign(body, { title, unit });
      await api(`/wellness/patients/${patientId}/goals`, { method: "POST", body });
      setOpen(false);
      setTarget("");
      await onAdded();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button className="btn" onClick={() => setOpen(true)}><Plus size={16} /> Add a goal</button>
    );
  }
  const names = { steps: "Daily steps", sleep_hours: "Sleep", active_minutes: "Active minutes",
                  fruit_veg_servings: "Fruit and vegetables", custom: "Something else" };
  return (
    <form className="card wl-form" onSubmit={add} aria-label="Add a goal">
      <div className="wl-field">
        <label htmlFor="goal-kind">What do you want to work on?</label>
        <select id="goal-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
          {Object.keys(kinds).map((k) => <option key={k} value={k}>{names[k] || k}</option>)}
        </select>
      </div>
      {kind === "custom" && (
        <>
          <div className="wl-field">
            <label htmlFor="goal-title">Name</label>
            <input id="goal-title" type="text" required minLength={2} maxLength={80} value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="wl-field">
            <label htmlFor="goal-unit">Measured in</label>
            <input id="goal-unit" type="text" required maxLength={30} placeholder="e.g. glasses" value={unit} onChange={(e) => setUnit(e.target.value)} />
          </div>
        </>
      )}
      <div className="wl-field">
        <label htmlFor="goal-target">
          Daily target{kinds[kind]?.target ? ` (suggested: ${fmtValue(kinds[kind].target)} ${kinds[kind].unit})` : ""}
        </label>
        <input id="goal-target" type="number" min="0" step="any" inputMode="decimal" required={kind === "custom"}
               value={target} onChange={(e) => setTarget(e.target.value)} />
      </div>
      {error && <div className="error-box">{error}</div>}
      <div className="row">
        <button className="btn primary" disabled={busy}>{busy ? "Adding…" : "Add goal"}</button>
        <button type="button" className="btn ghost" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </form>
  );
}

function Goals({ patientId, goals }) {
  const { data, error, loading, reload } = goals;
  return (
    <section className="wl-section" aria-labelledby="wl-goals">
      <div className="wl-section-head">
        <div>
          <h2 id="wl-goals" className="wl-section-title">My goals</h2>
          <div className="page-sub">Tracked by you, for you. Your care team can see them but they aren't clinical measurements.</div>
        </div>
      </div>
      {error && <div className="error-box">{error.message}</div>}
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {data && (
        <div className="stack">
          {data.goals.length === 0 && <div className="card empty">No goals yet. Pick one small thing to start with.</div>}
          {data.goals.map((g) => <GoalCard key={g.id} goal={g} today={data.today} onChanged={reload} />)}
          <AddGoal patientId={patientId} kinds={data.kinds} onAdded={reload} />
        </div>
      )}
    </section>
  );
}

// --- Assessment ----------------------------------------------------------------------------------------------

function EmergencyCard({ e }) {
  return (
    <section className="card alert stack" role="alert">
      <div className="row strong" style={{ color: "var(--alert-strong)" }}>
        <Warning size={20} /> {e.crisis_line ? "Support is available now" : "Get emergency help now"}
      </div>
      <p style={{ color: "var(--alert-strong)" }}>{e.message}</p>
      {e.crisis_line && <a className="btn danger" href={`tel:${e.crisis_line}`}><Phone size={18} /> Call or text {e.crisis_line}</a>}
      <a className="btn danger" href={`tel:${e.emergency_number}`}><Phone size={18} /> Call {e.emergency_number}</a>
      {e.care_team_notified && <p className="small" style={{ color: "var(--alert-strong)" }}>Your care team has been notified.</p>}
    </section>
  );
}

function Assessment({ patientId, onGoalAdded }) {
  const def = useApi("/wellness/assessment");
  const [answers, setAnswers] = useState({});
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [goalAdded, setGoalAdded] = useState(false);
  const navigate = useNavigate();

  const set = (id, v) => setAnswers((a) => ({ ...a, [id]: v }));

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = { ...answers };
      for (const q of def.data.questions) if (q.type === "number" && body[q.id] !== undefined) body[q.id] = Number(body[q.id]);
      if (!body.notes) delete body.notes;
      setResult(await api(`/wellness/patients/${patientId}/assessments`, { method: "POST", body }));
      setGoalAdded(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function addGoal() {
    const g = result.suggested_goal;
    setError(null);
    try {
      await api(`/wellness/patients/${patientId}/goals`, {
        method: "POST",
        body: { kind: g.kind, target: g.target, assessment_id: result.id },
      });
      setGoalAdded(true);
      await onGoalAdded();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <section className="wl-section" aria-labelledby="wl-check">
      <div className="wl-section-head">
        <div>
          <h2 id="wl-check" className="wl-section-title">{def.data?.title || "Lifestyle check-in"}</h2>
          <div className="page-sub">{def.data?.intro}</div>
        </div>
      </div>
      {def.error && <div className="error-box">{def.error.message}</div>}
      {def.loading && <div className="card"><div className="skeleton" /></div>}

      {result?.emergency && <EmergencyCard e={result.emergency} />}

      {result && !result.emergency && (
        <div className="stack">
          {result.symptom_notice && (
            <div className="card alert stack">
              <p className="small strong" style={{ color: "var(--alert-strong)" }}>{result.symptom_notice.message}</p>
              <button className="btn danger" onClick={() => navigate("/app", { state: { initial: result.symptom_notice.initial } })}>
                Tell Bioverse about it
              </button>
            </div>
          )}
          {result.suggestions.map((s) => (
            <div key={s.id} className="card stack" style={{ gap: 6 }}>
              <div className="strong">{s.title}</div>
              <p className="small">{s.text}</p>
              {s.specialty && (
                <Link className="btn sm" style={{ alignSelf: "flex-start" }} to={`/care/find?specialty=${encodeURIComponent(s.specialty)}`}>
                  Find a time with {s.specialty.toLowerCase()} <Chevron size={14} />
                </Link>
              )}
            </div>
          ))}
          {result.suggested_goal && (
            <div className="card highlight row between wrap">
              <div>
                <div className="strong">Suggested goal</div>
                <div className="small muted">{result.suggested_goal.reason}</div>
              </div>
              {goalAdded
                ? <span className="chip ok"><Check size={12} /> Added to your goals</span>
                : <button className="btn primary sm" onClick={addGoal}>Add this goal</button>}
            </div>
          )}
          <p className="tiny muted">General wellness information, not medical advice.</p>
          <button className="btn ghost sm" style={{ alignSelf: "flex-start" }} onClick={() => setResult(null)}>Take it again</button>
        </div>
      )}

      {def.data && !result && (
        <form className="card wl-form" onSubmit={submit}>
          {def.data.questions.map((q) => {
            const id = `q-${q.id}`;
            if (q.type === "choice") {
              return (
                <fieldset key={q.id} className="wl-field">
                  <legend>{q.label}</legend>
                  <div className="wl-choices">
                    {q.options.map((o) => (
                      <label key={o.id} className="wl-choice">
                        <input type="radio" name={q.id} value={o.id} required checked={answers[q.id] === o.id}
                               onChange={() => set(q.id, o.id)} />
                        {o.label}
                      </label>
                    ))}
                  </div>
                </fieldset>
              );
            }
            if (q.type === "text") {
              return (
                <div key={q.id} className="wl-field">
                  <label htmlFor={id}>{q.label} <span className="muted small">(optional)</span></label>
                  <textarea id={id} maxLength={1000} value={answers[q.id] || ""} onChange={(e) => set(q.id, e.target.value)} />
                </div>
              );
            }
            return (
              <div key={q.id} className="wl-field">
                <label htmlFor={id}>{q.label}</label>
                <input id={id} type="number" inputMode="decimal" min={q.min} max={q.max} step={q.step} required
                       value={answers[q.id] ?? ""} onChange={(e) => set(q.id, e.target.value)} />
              </div>
            );
          })}
          {error && <div className="error-box">{error}</div>}
          <button className="btn primary" disabled={busy}>{busy ? "Checking…" : "See my suggestions"}</button>
        </form>
      )}
      {result && error && <div className="error-box" style={{ marginTop: 10 }}>{error}</div>}
    </section>
  );
}

export default function Wellness() {
  const { me } = useSession();
  const goals = useApi(`/wellness/patients/${me.patient_id}/goals`);
  return (
    <main className="column">
      <div className="stack" style={{ gap: 2 }}>
        <span className="eyebrow">Wellbeing</span>
        <h1 className="page-title">Wellness & prevention</h1>
        <span className="page-sub">Staying well, not just getting better.</span>
      </div>
      <Prevention patientId={me.patient_id} />
      <Goals patientId={me.patient_id} goals={goals} />
      <Assessment patientId={me.patient_id} onGoalAdded={goals.reload} />
    </main>
  );
}
