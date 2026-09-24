import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { useSession } from "../../session.jsx";
import { Check, Close, Phone, Warning } from "../../icons.jsx";
import { DataTable, LineChart, Loading, shortDay } from "../nutrition/charts.jsx";
import Breathing from "./Breathing.jsx";
import { CrisisCard, SupportStrip } from "./Crisis.jsx";

const MOODS = [
  { v: 1, label: "Very low" }, { v: 2, label: "Low" }, { v: 3, label: "Okay" }, { v: 4, label: "Good" }, { v: 5, label: "Very good" },
];

export function ScoreTrend({ entry, compact = false }) {
  if (!entry.history.length) return null;
  const points = entry.history.map((h) => ({ at: h.at, value: h.total, note: `${shortDay(h.at)} · ${h.severity_label}`, alert: h.total >= 10 }));
  return (
    <>
      <LineChart label={`${entry.title} scores over time, latest ${points[points.length - 1].value} of ${entry.max}`}
                 unit={`of ${entry.max}`} height={compact ? 120 : 150} yDomain={[0, entry.max]} formatValue={(v) => Math.round(v)}
                 series={[{ id: entry.title, label: entry.title, points, dots: true, strong: true }]}
                 refs={[{ value: 10, label: "10: moderate" }]} />
      {!compact && (
        <DataTable caption={`${entry.title} history`} columns={["Date", "Score", "Meaning"]}
                   rows={[...entry.history].reverse().map((h) => [shortDay(h.at), `${h.total} of ${entry.max}`, h.severity_label])} />
      )}
    </>
  );
}

// --- Questionnaire ----------------------------------------------------------------------------------------------

function Questionnaire({ pid, spec, onDone, onCancel }) {
  const [items, setItems] = useState(() => spec.items.map(() => null));
  const [difficulty, setDifficulty] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const item9 = spec.id === "phq9" ? items[8] : null;
  const answered = items.every((v) => v !== null);
  const anyProblem = items.some((v) => v > 0);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = { instrument: spec.id, items };
      if (difficulty && anyProblem) body.difficulty = difficulty;
      onDone(await api(`/mind/patients/${pid}/responses`, { method: "POST", body }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit} aria-labelledby={`q-${spec.id}`}>
      <div className="row between" style={{ alignItems: "flex-start" }}>
        <div>
          <h2 id={`q-${spec.id}`} className="card-title">{spec.name}</h2>
          <p className="small" style={{ marginTop: 6 }}>{spec.stem}</p>
        </div>
        <button type="button" className="icon-btn" onClick={onCancel} aria-label="Close questionnaire"><Close size={18} /></button>
      </div>
      {spec.items.map((text, i) => (
        <div key={i}>
          <fieldset className="mind-q">
            <legend><span className="num">{i + 1}.</span>{text}</legend>
            <div className="mind-opts">
              {spec.options.map((o) => (
                <label key={o.value} className="mind-opt">
                  <input type="radio" name={`${spec.id}-${i}`} value={o.value} checked={items[i] === o.value} required
                         onChange={() => setItems((all) => all.map((v, j) => (j === i ? o.value : v)))} />
                  {o.label}
                </label>
              ))}
            </div>
          </fieldset>
          {/* Shown the moment item 9 is answered above zero, before anything is submitted. */}
          {spec.id === "phq9" && i === 8 && item9 > 0 && <CrisisCard headingLevel={3} />}
        </div>
      ))}
      {anyProblem && (
        <fieldset className="mind-q">
          <legend>{spec.difficulty} <span className="muted small">(optional)</span></legend>
          <div className="mind-opts">
            {spec.difficulty_options.map((o) => (
              <label key={o} className="mind-opt">
                <input type="radio" name={`${spec.id}-difficulty`} checked={difficulty === o} onChange={() => setDifficulty(o)} />
                {o}
              </label>
            ))}
          </div>
        </fieldset>
      )}
      {error && <div className="error-box" style={{ marginTop: 8 }}>{error}</div>}
      <button className="btn primary block" style={{ marginTop: 12 }} disabled={busy || !answered}>
        {busy ? "Scoring…" : answered ? "See my result" : `Answer all ${spec.items.length} questions`}
      </button>
      <p className="tiny muted" style={{ marginTop: 10 }}>{spec.attribution}</p>
    </form>
  );
}

function Result({ r, onClose }) {
  return (
    <section className="stack" aria-labelledby="result-h">
      {r.crisis && <CrisisCard crisis={r.crisis} notified={r.crisis.care_team_notified} />}
      <div className="card stack">
        <h2 id="result-h" className="card-title">{r.title} result</h2>
        <div className="row" style={{ gap: 14, alignItems: "flex-end" }}>
          <span className="mind-score">{r.total}</span>
          <span className="small muted" style={{ paddingBottom: 6 }}>of {r.max} · <span className="strong" style={{ color: "var(--ink)" }}>{r.severity_label}</span></span>
        </div>
        <p>{r.explanation}</p>
        {r.review_requested && <p className="small"><Check size={14} /> Your care team has your result and will be in touch.</p>}
        {!r.review_requested && !r.crisis && <p className="small muted">Your result is shared with your care team as part of your record.</p>}
        <p className="tiny muted">{r.note}</p>
        <button className="btn sm" style={{ alignSelf: "flex-start" }} onClick={onClose}>Done</button>
      </div>
    </section>
  );
}

function CheckIns({ pid, defs, results }) {
  const [open, setOpen] = useState(null);
  const [result, setResult] = useState(null);
  const data = results.data;

  if (result) return <Result r={result} onClose={() => { setResult(null); results.reload(); }} />;
  if (open) {
    const spec = defs.find((d) => d.id === open);
    return <Questionnaire pid={pid} spec={spec} onCancel={() => setOpen(null)} onDone={(r) => { setOpen(null); setResult(r); }} />;
  }
  return (
    <div className="stack">
      {defs.map((spec) => {
        const entry = data?.instruments[spec.id];
        const latest = entry?.latest;
        return (
          <article key={spec.id} className="card stack" aria-labelledby={`ci-${spec.id}`}>
            <div className="row between wrap">
              <div>
                <h3 id={`ci-${spec.id}`} className="card-title">{spec.name}</h3>
                <p className="small muted">{spec.about} About 2 minutes.</p>
              </div>
              <button className="btn primary sm" onClick={() => setOpen(spec.id)}>{latest ? "Check in again" : "Start"}</button>
            </div>
            {latest && (
              <>
                <p className="small">
                  Last time, {shortDay(latest.at)}: <span className="strong">{latest.total} of {latest.max}, {latest.severity_label.toLowerCase()}</span>. {latest.explanation}
                </p>
                <ScoreTrend entry={entry} />
                {entry.next_due && <p className="tiny muted">Suggested next check-in: {shortDay(entry.next_due)}.</p>}
              </>
            )}
          </article>
        );
      })}
    </div>
  );
}

function Reminders({ pid, prefs, onSaved }) {
  const [on, setOn] = useState(prefs.retest_reminders);
  const [weeks, setWeeks] = useState(prefs.retest_weeks);
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);
  async function save(nextOn, nextWeeks) {
    setError(null);
    setMsg(null);
    try {
      const p = await api(`/mind/patients/${pid}/preferences`, { method: "PUT", body: { retest_reminders: nextOn, retest_weeks: nextWeeks } });
      setOn(p.retest_reminders);
      setWeeks(p.retest_weeks);
      setMsg(p.retest_reminders ? `We'll remind you every ${p.retest_weeks} weeks.` : "Reminders are off.");
      onSaved();
    } catch (e) {
      setError(e.message);
    }
  }
  return (
    <div className="card stack">
      <div className="toggle-row">
        <input id="retest" type="checkbox" checked={on} onChange={(e) => save(e.target.checked, weeks)} />
        <label htmlFor="retest">Remind me to check in again</label>
      </div>
      <div className="wb-field">
        <label htmlFor="retest-weeks">How often</label>
        <select id="retest-weeks" value={weeks} disabled={!on} onChange={(e) => save(on, Number(e.target.value))}>
          {[2, 3, 4].map((w) => <option key={w} value={w}>Every {w} weeks</option>)}
        </select>
      </div>
      {msg && <p className="small" role="status">{msg}</p>}
      {error && <div className="error-box">{error}</div>}
    </div>
  );
}

// --- Mood journal ---------------------------------------------------------------------------------------------

function Journal({ pid }) {
  const res = useApi(`/mind/patients/${pid}/journal`);
  const [entries, setEntries] = useState(null);
  const [mood, setMood] = useState(null);
  const [tags, setTags] = useState([]);
  const [note, setNote] = useState("");
  const [shared, setShared] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [outcome, setOutcome] = useState(null);
  useEffect(() => {
    if (res.data) setEntries(res.data.entries);
  }, [res.data]);

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setOutcome(null);
    try {
      const r = await api(`/mind/patients/${pid}/journal`, { method: "POST", body: { mood, tags, note: note || null, shared } });
      setEntries(r.entries);
      setOutcome(r);
      setMood(null);
      setTags([]);
      setNote("");
      setShared(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  async function remove(id) {
    setError(null);
    try {
      setEntries((await api(`/mind/patients/${pid}/journal/${id}`, { method: "DELETE" })).entries);
    } catch (err) {
      setError(err.message);
    }
  }

  const trend = (entries || []).slice().reverse().map((e) => ({ at: e.created_at, value: e.mood, note: MOODS[e.mood - 1].label }));
  return (
    <div className="stack">
      {outcome?.crisis && <CrisisCard crisis={outcome.crisis} notified={outcome.crisis.care_team_notified} />}
      {outcome?.emergency && (
        <section className="wb-crisis" role="alert">
          <span className="title"><Warning size={20} /> Get help now</span>
          <p>{outcome.emergency.message}</p>
          <a className="btn danger" href={`tel:${outcome.emergency.emergency_number}`}><Phone size={18} /> Call {outcome.emergency.emergency_number}</a>
        </section>
      )}
      {outcome?.symptom_notice && (
        <div className="card alert stack">
          <p className="small strong" style={{ color: "var(--alert-strong)" }}>{outcome.symptom_notice.message}</p>
          <Link className="btn danger" to="/app" state={{ initial: outcome.symptom_notice.initial }}>Tell Bioverse about it</Link>
        </div>
      )}
      {outcome && !outcome.crisis && !outcome.emergency && <div className="banner ok" role="status"><Check size={16} /> Saved to your journal.</div>}
      <form className="card wb-form" onSubmit={save} aria-label="How are you feeling?">
        <fieldset className="wb-field">
          <legend>How are you feeling today?</legend>
          <div className="mind-moods">
            {MOODS.map((m) => (
              <button key={m.v} type="button" aria-pressed={mood === m.v} onClick={() => setMood(m.v)}>
                <span className="n">{m.v}</span>{m.label}
              </button>
            ))}
          </div>
        </fieldset>
        <fieldset className="wb-field">
          <legend>What's affecting your mood? <span className="muted small">(optional)</span></legend>
          <div className="mind-tags">
            {(res.data?.tags || []).map((t) => (
              <label key={t}>
                <input type="checkbox" checked={tags.includes(t)}
                       onChange={(e) => setTags((all) => (e.target.checked ? [...all, t] : all.filter((x) => x !== t)))} />
                {t}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="wb-field">
          <label htmlFor="mood-note">Note <span className="muted small">(optional, private unless you share it)</span></label>
          <textarea id="mood-note" maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <div className="toggle-row">
          <input id="mood-share" type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />
          <label htmlFor="mood-share">Share this note with my care team</label>
        </div>
        {error && <div className="error-box">{error}</div>}
        <button className="btn primary" disabled={busy || !mood}>{busy ? "Saving…" : mood ? "Save" : "Pick how you feel"}</button>
        <p className="tiny muted">Your care team can see your mood ratings. Notes stay private unless you share them. If something in a note sounds urgent, we'll show you where to get help right away.</p>
      </form>
      {res.error && <div className="error-box">{res.error.message}</div>}
      {entries && entries.length > 0 && (
        <div className="card stack">
          <h3 className="card-title">Recent entries</h3>
          {trend.length > 1 && (
            <LineChart label="Mood ratings over the last weeks, 1 very low to 5 very good" yDomain={[0.5, 5.5]} height={120}
                       formatValue={(v) => Math.round(v)} unit="of 5"
                       series={[{ id: "mood", label: "Mood", points: trend, dots: true, strong: true }]} />
          )}
          {entries.slice(0, 8).map((e) => (
            <div key={e.id} className="wb-row">
              <div className="grow small">
                <span className="strong">{MOODS[e.mood - 1].label}</span>
                <span className="muted"> · {shortDay(e.created_at)}{e.tags.length ? ` · ${e.tags.join(", ")}` : ""}</span>
                {e.shared && <span className="chip ok" style={{ marginLeft: 6 }}>Shared</span>}
                {e.note && <p className="small" style={{ marginTop: 2, overflowWrap: "anywhere" }}>{e.note}</p>}
              </div>
              <button className="icon-btn" aria-label={`Delete entry from ${shortDay(e.created_at)}`} onClick={() => remove(e.id)}><Close size={16} /></button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Page -----------------------------------------------------------------------------------------------------

export default function Mind() {
  const { me } = useSession();
  const pid = me.patient_id;
  const defs = useApi("/mind/instruments");
  const results = useApi(`/mind/patients/${pid}/results`);
  const support = useApi("/mind/support");
  return (
    <main className="column">
      <div className="wb-head">
        <span className="eyebrow">Wellbeing</span>
        <h1 className="page-title">Mood & mind</h1>
        <span className="page-sub">Quick check-ins, a mood journal and a breathing exercise. Your results are shared with your care team.</span>
      </div>
      <div style={{ marginTop: 14 }}><SupportStrip /></div>

      <section className="wb-section" aria-labelledby="ci-h">
        <div className="wb-section-head"><h2 id="ci-h" className="wb-section-title">Check-ins</h2></div>
        {defs.error && <div className="error-box">{defs.error.message}</div>}
        {results.error && <div className="error-box">{results.error.message}</div>}
        {(defs.loading || results.loading) && !(defs.data && results.data) && <Loading />}
        {defs.data && results.data && <CheckIns pid={pid} defs={defs.data.instruments} results={results} />}
        {defs.data && <p className="tiny muted" style={{ marginTop: 8 }}>{defs.data.note}</p>}
      </section>

      {results.data && (
        <section className="wb-section" aria-labelledby="rem-h">
          <div className="wb-section-head"><h2 id="rem-h" className="wb-section-title">Reminders</h2></div>
          <Reminders pid={pid} prefs={results.data.preferences} onSaved={results.reload} />
        </section>
      )}

      <section className="wb-section" aria-labelledby="journal-h">
        <div className="wb-section-head"><h2 id="journal-h" className="wb-section-title">Mood journal</h2></div>
        <Journal pid={pid} />
      </section>

      <section className="wb-section" aria-labelledby="breath-h">
        <div className="wb-section-head"><h2 id="breath-h" className="wb-section-title">Box breathing</h2></div>
        <Breathing />
      </section>

      <section className="wb-section" aria-labelledby="res-h">
        <div className="wb-section-head"><h2 id="res-h" className="wb-section-title">Support and resources</h2></div>
        <div className="card list">
          {(support.data?.resources || []).map((r) => (
            <div key={r.title} className="wb-row">
              <div className="grow">
                <a className="strong small" href={r.url} target="_blank" rel="noreferrer">{r.title}</a>
                <p className="tiny muted">{r.detail}</p>
              </div>
            </div>
          ))}
          {support.loading && <div className="skeleton" />}
          {support.error && <p className="small">Call or text 988 for the Suicide & Crisis Lifeline. In an emergency, call 911.</p>}
        </div>
      </section>
    </main>
  );
}
