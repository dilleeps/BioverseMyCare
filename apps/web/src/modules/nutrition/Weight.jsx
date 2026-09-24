import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { useSession } from "../../session.jsx";
import { Check, Chevron, Phone } from "../../icons.jsx";
import { DataTable, LineChart, Loading, Meter, localDay, num, shortDay } from "./charts.jsx";

const LB = 0.45359237;

export function WeightChart({ data, compact = false }) {
  if (!data.weigh_ins.length) return <p className="small muted">No weigh-ins yet.</p>;
  const points = data.weigh_ins.map((w) => ({ at: w.effective_at, value: w.value, note: `${shortDay(w.effective_at)} · ${w.source}` }));
  // A week's average sits mid-week, never before the first weigh-in.
  const first = points[0].at;
  const weekly = data.weekly.map((w) => {
    const mid = localDay(w.week_start);
    mid.setDate(mid.getDate() + 3);
    return { at: mid < new Date(first) ? first : mid.toISOString(), value: w.average };
  });
  const goal = data.goal && data.goal.status === "active" ? data.goal : null;
  return (
    <>
      <LineChart
        label={`Weight over time, latest ${num(data.latest.value)} kg${goal ? `, goal ${num(goal.target_weight_kg)} kg` : ""}`}
        unit="kg" height={compact ? 140 : 190}
        series={[
          { id: "weekly", label: "Weekly average", points: weekly, dashed: true },
          { id: "weigh-ins", label: "Weigh-ins", points, dots: true, strong: true },
        ]}
        refs={goal ? [{ value: goal.target_weight_kg, label: `Goal ${num(goal.target_weight_kg)} kg` }] : []}
      />
      {!compact && (
        <>
          <p className="tiny muted">Dots are weigh-ins; the dashed line is your weekly average{goal ? "; the flat line is your goal" : ""}.</p>
          <DataTable caption="Weigh-ins" columns={["Date", "Weight (kg)", "Source"]}
                     rows={[...data.weigh_ins].reverse().map((w) => [shortDay(w.effective_at), num(w.value), w.source])} />
        </>
      )}
    </>
  );
}

function SupportStrip() {
  return (
    <div className="wb-support-strip">
      <span>Struggling right now? Call or text <strong>988</strong>, any time.</span>
      <a className="btn sm" href="tel:988"><Phone size={14} /> Call 988</a>
    </div>
  );
}

function LogWeight({ pid, onDone }) {
  const [unit, setUnit] = useState("kg");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const kg = unit === "kg" ? Number(value) : Number(value) * LB;
      onDone(await api(`/weight/patients/${pid}/weigh-ins`, { method: "POST", body: { weight_kg: Math.round(kg * 10) / 10 } }), "Weigh-in saved.");
      setValue("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="card stack" onSubmit={save} aria-label="Log a weigh-in">
      <h2 className="card-title">Log a weigh-in</h2>
      <div className="wb-inline">
        <div className="wb-field">
          <label htmlFor="w-value">Weight ({unit})</label>
          <input id="w-value" type="number" step="0.1" min="20" max="800" inputMode="decimal" required value={value}
                 onChange={(e) => setValue(e.target.value)} />
        </div>
        <div className="wb-seg" role="group" aria-label="Unit">
          {["kg", "lb"].map((u) => <button key={u} type="button" aria-pressed={unit === u} onClick={() => setUnit(u)}>{u}</button>)}
        </div>
        <button className="btn primary" disabled={busy || !value}>{busy ? "Saving…" : "Save"}</button>
      </div>
      <p className="tiny muted">Once a week, at the same time of day, is plenty. Readings from a connected scale appear here too.</p>
      {error && <div className="error-box">{error}</div>}
    </form>
  );
}

function AddHeight({ pid, onDone }) {
  const [cm, setCm] = useState("");
  const [error, setError] = useState(null);
  async function save(e) {
    e.preventDefault();
    setError(null);
    try {
      onDone(await api(`/weight/patients/${pid}/height`, { method: "POST", body: { height_cm: Number(cm) } }), "Height saved.");
    } catch (err) {
      setError(err.message);
    }
  }
  return (
    <form className="card stack" onSubmit={save}>
      <h2 className="card-title">Add your height</h2>
      <p className="small muted">We need it to work out BMI and a safe goal range.</p>
      <div className="wb-inline">
        <div className="wb-field">
          <label htmlFor="h-cm">Height (cm)</label>
          <input id="h-cm" type="number" min="100" max="250" step="0.5" required value={cm} onChange={(e) => setCm(e.target.value)} />
        </div>
        <button className="btn primary" disabled={!cm}>Save</button>
      </div>
      {error && <div className="error-box">{error}</div>}
    </form>
  );
}

function Screening({ pid, onPassed, onRouted }) {
  const def = useApi("/weight/screening");
  const [answers, setAnswers] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  if (def.error) return <div className="error-box">{def.error.message}</div>;
  if (!def.data) return <Loading />;
  const done = def.data.questions.every((q) => answers[q.id] !== undefined);
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api(`/weight/patients/${pid}/screening`, { method: "POST", body: { answers } });
      if (r.positive) onRouted(r);
      else onPassed(r.id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="card wb-form" onSubmit={submit} aria-labelledby="scr-h">
      <div>
        <h3 id="scr-h" className="card-title">{def.data.title}</h3>
        <p className="small muted">{def.data.intro}</p>
      </div>
      {def.data.questions.map((q) => (
        <fieldset key={q.id} className="wb-field">
          <legend>{q.text}</legend>
          <div className="wb-choices">
            {[["No", false], ["Yes", true]].map(([label, v]) => (
              <label key={label} className="wb-choice">
                <input type="radio" name={`scoff-${q.id}`} checked={answers[q.id] === v}
                       onChange={() => setAnswers((a) => ({ ...a, [q.id]: v }))} />
                {label}
              </label>
            ))}
          </div>
        </fieldset>
      ))}
      <p className="tiny muted">{def.data.source}</p>
      {error && <div className="error-box">{error}</div>}
      <button className="btn primary" disabled={busy || !done}>{busy ? "Checking…" : "Continue"}</button>
    </form>
  );
}

function GoalForm({ pid, data, screeningId, onDone }) {
  const g = data.guardrails;
  const [target, setTarget] = useState("");
  const [pace, setPace] = useState(0.5);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const t = Number(target);
  const tooLow = target && g.min_target_kg && t < g.min_target_kg;
  const weeks = target && data.latest && t < data.latest.value ? Math.ceil((data.latest.value - t) / pace) : null;
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onDone(await api(`/weight/patients/${pid}/goal`, {
        method: "POST", body: { screening_id: screeningId, target_weight_kg: t, pace_kg_week: pace },
      }), "Your goal is set.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="card wb-form" onSubmit={save} aria-labelledby="goal-h">
      <h3 id="goal-h" className="card-title">Set your goal</h3>
      <div className="wb-field">
        <label htmlFor="g-target">Goal weight (kg)</label>
        <input id="g-target" type="number" step="0.1" min={g.min_target_kg || 30} required value={target}
               onChange={(e) => setTarget(e.target.value)} aria-describedby="g-target-help" />
        <span id="g-target-help" className="tiny muted">
          The lowest goal the coach can set for your height is {num(g.min_target_kg)} kg (a BMI of {g.min_bmi}).
        </span>
        {tooLow && <span className="tiny" style={{ color: "var(--alert-strong)" }}>That's below the healthy range for your height.</span>}
      </div>
      <fieldset className="wb-field">
        <legend>Pace</legend>
        <div className="wb-choices">
          {g.paces.map((p) => (
            <label key={p} className="wb-choice">
              <input type="radio" name="pace" checked={pace === p} onChange={() => setPace(p)} />
              {p} kg a week{p === 0.5 ? " (steady)" : ""}
            </label>
          ))}
        </div>
        <span className="tiny muted">The coach never goes faster than {g.max_pace_kg_week} kg a week.</span>
      </fieldset>
      {weeks != null && !tooLow && <p className="small">At this pace, about {weeks} weeks.</p>}
      {error && <div className="error-box">{error}</div>}
      <button className="btn primary" disabled={busy || !target || tooLow}>{busy ? "Saving…" : "Set goal"}</button>
    </form>
  );
}

function ActiveGoal({ pid, data, onDone }) {
  const g = data.goal;
  const [error, setError] = useState(null);
  async function stop() {
    setError(null);
    try {
      onDone(await api(`/weight/patients/${pid}/goal/stop`, { method: "POST" }), "Goal stopped.");
    } catch (err) {
      setError(err.message);
    }
  }
  return (
    <div className="card stack">
      <div className="row between wrap">
        <h3 className="card-title">Goal: {num(g.target_weight_kg)} kg</h3>
        <span className="chip">{g.pace_kg_week} kg a week</span>
      </div>
      <div className="stack" style={{ gap: 6 }}>
        <div className="row between small"><span className="strong">{g.percent}% of the way</span>
          <span className="muted">{g.remaining_kg > 0 ? `${num(g.remaining_kg)} kg to go` : "Reached"}</span></div>
        <Meter value={g.percent} max={100} label={`${g.percent}% of the way to your goal`} />
      </div>
      <p className="small">Started at {num(g.start_weight_kg)} kg on {shortDay(g.created_at)}
        {g.weeks_left > 0 ? `. At your pace, around ${shortDay(g.expected_by)}.` : "."}</p>
      <div className="wb-muted-box small"><span className="strong">This week: </span>{data.this_week.message}</div>
      {data.checkins.length > 0 && (
        <details className="wb-table-wrap">
          <summary>Weekly check-ins</summary>
          {data.checkins.map((c) => (
            <p key={c.week_start} className="small" style={{ padding: "6px 0" }}>
              <span className="strong">Week of {shortDay(c.week_start)}: </span>{c.message}
            </p>
          ))}
        </details>
      )}
      {error && <div className="error-box">{error}</div>}
      <button className="btn ghost sm" style={{ alignSelf: "flex-start" }} onClick={stop}>Stop this goal</button>
    </div>
  );
}

export default function Weight() {
  const { me } = useSession();
  const pid = me.patient_id;
  const res = useApi(`/weight/patients/${pid}`);
  const [data, setData] = useState(null);
  const [screeningId, setScreeningId] = useState(null);
  const [routed, setRouted] = useState(null);
  const [msg, setMsg] = useState(null);
  useEffect(() => {
    if (res.data) setData(res.data);
  }, [res.data]);

  function done(next, text) {
    setData(next);
    setMsg(text);
    setScreeningId(null);
  }

  return (
    <main className="column">
      <div className="wb-head">
        <span className="eyebrow">Wellbeing</span>
        <h1 className="page-title">Weight coach</h1>
        <span className="page-sub">Steady, safe progress. Your trend matters more than any one day.</span>
      </div>
      {res.error && !data && <div className="error-box" style={{ marginTop: 16 }}>{res.error.message}</div>}
      {!data && res.loading && <div style={{ marginTop: 16 }}><Loading /></div>}
      {data && (
        <>
          {msg && <div className="banner ok" role="status" style={{ marginTop: 14 }}><Check size={16} /> {msg}</div>}
          <section className="wb-section card stack" aria-label="Your weight">
            <div className="wb-stats">
              <div className="wb-stat"><div className="v">{data.latest ? `${num(data.latest.value)} kg` : "—"}</div>
                <div className="l">{data.latest ? `Latest, ${shortDay(data.latest.effective_at)}` : "No weigh-ins yet"}</div></div>
              <div className="wb-stat"><div className="v">{data.bmi ?? "—"}</div><div className="l">BMI{data.bmi_label ? ` · ${data.bmi_label}` : ""}</div></div>
              <div className="wb-stat"><div className="v">{data.goal?.status === "active" ? `${data.goal.percent}%` : "—"}</div>
                <div className="l">To your goal</div></div>
            </div>
            <WeightChart data={data} />
            {data.height && <p className="tiny muted">BMI uses your latest height, {num(data.height.value)} cm. It's a rough guide and doesn't account for muscle, age or build.</p>}
          </section>

          <div className="wb-section stack">
            <LogWeight pid={pid} onDone={done} />
            {!data.height && <AddHeight pid={pid} onDone={done} />}
          </div>

          <section className="wb-section" aria-labelledby="goal-sec">
            <div className="wb-section-head"><h2 id="goal-sec" className="wb-section-title">Your goal</h2></div>
            {data.goal?.status === "active" && <ActiveGoal pid={pid} data={data} onDone={done} />}
            {data.goal?.status !== "active" && (routed || data.routed_message) && (
              <div className="card stack">
                <h3 className="card-title">Your care team will be in touch</h3>
                <p className="small">{routed?.message || data.routed_message}</p>
                <Link className="small strong" to="/nutrition">Go to your food log <Chevron size={14} /></Link>
                <SupportStrip />
              </div>
            )}
            {data.goal?.status !== "active" && !routed && !data.routed_message && data.height && data.latest && (
              screeningId || data.can_set_goal
                ? <GoalForm pid={pid} data={data} screeningId={screeningId || data.screening.id} onDone={done} />
                : <Screening pid={pid} onPassed={setScreeningId} onRouted={setRouted} />
            )}
            {data.goal?.status !== "active" && (!data.height || !data.latest) && !data.routed_message && (
              <p className="card small muted">Add a weigh-in{data.height ? "" : " and your height"} to set a goal.</p>
            )}
          </section>
        </>
      )}
    </main>
  );
}
