import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";
import { PatientPage } from "../../layouts.jsx";
import { fmtDate, fmtDateTime } from "../../format.js";
import { Calendar, Check, Chevron, Close, Phone, Pin, Plus, Warning } from "../../icons.jsx";
import { fmtTime, usePoll } from "./poll.js";

function Checklist({ visit, onChange }) {
  const [pending, setPending] = useState({});
  const [error, setError] = useState(null);
  const done = visit.checklist.filter((i) => (pending[i.id] ?? i.done)).length;

  async function toggle(item) {
    const next = !(pending[item.id] ?? item.done);
    setPending((p) => ({ ...p, [item.id]: next }));
    setError(null);
    try {
      await api(`/visits/checklist/${item.id}`, { method: "PATCH", body: { done: next } });
      await onChange();
    } catch (e) {
      setError(`Couldn't save "${item.label}". ${e.message}`);
    } finally {
      setPending((p) => {
        const { [item.id]: _, ...rest } = p;
        return rest;
      });
    }
  }

  return (
    <section className="stack" style={{ gap: 10 }} aria-labelledby={`cl-${visit.id}`}>
      <div className="row between">
        <span id={`cl-${visit.id}`} className="strong">Before your visit</span>
        <span className="small muted">{done} of {visit.checklist.length} done</span>
      </div>
      <div className="progress" role="progressbar" aria-label="Checklist progress" aria-valuemin={0}
           aria-valuemax={visit.checklist.length} aria-valuenow={done}>
        <div style={{ width: `${(100 * done) / Math.max(visit.checklist.length, 1)}%` }} />
      </div>
      {error && <div className="error-box small">{error}</div>}
      <ul className="vx-checklist">
        {visit.checklist.map((item) => {
          const checked = pending[item.id] ?? item.done;
          const id = `ck-${item.id}`;
          return (
            <li key={item.id} className={`task ${checked ? "done" : ""}`}>
              <input id={id} type="checkbox" checked={checked} onChange={() => toggle(item)} />
              <label htmlFor={id} className="stack" style={{ gap: 2 }}>
                <span className="task-title">{item.label}</span>
                {item.detail && <span className="small muted">{item.detail}</span>}
              </label>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Emergency({ detail }) {
  return (
    <section className="emergency stack" role="alert">
      <div className="row strong" style={{ color: "var(--alert-strong)" }}><Warning size={20} /> Get help now</div>
      <p style={{ color: "var(--alert-strong)" }}>{detail.message}</p>
      <a className="call" href={`tel:${detail.emergency_number}`}><Phone size={20} /> Call {detail.emergency_number}</a>
      {detail.crisis_line && (
        <a className="call" href={`tel:${detail.crisis_line}`}><Phone size={20} /> Call or text {detail.crisis_line}</a>
      )}
    </section>
  );
}

function Questions({ visit, onChange }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [emergency, setEmergency] = useState(null);
  const inputId = `q-${visit.id}`;

  async function add(value) {
    const q = value.trim();
    if (!q) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const r = await api(`/visits/${visit.id}/questions`, { method: "POST", body: { text: q } });
      setNotice(r.safety_notice);
      if (value === text) setText("");
      await onChange();
    } catch (e) {
      if (e.status === 409 && e.detail?.code === "emergency") setEmergency(e.detail);
      else setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(q) {
    setError(null);
    try {
      await api(`/visits/questions/${q.id}`, { method: "DELETE" });
      await onChange();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <section className="stack" style={{ gap: 10 }} aria-labelledby={`qs-${visit.id}`}>
      <span id={`qs-${visit.id}`} className="strong">Questions to ask</span>
      {emergency && <Emergency detail={emergency} />}
      {visit.clinician_questions.length > 0 && (
        <div className="vx-note stack" style={{ gap: 6 }}>
          <span className="small strong">{visit.practitioner.name} would like to know</span>
          <ul className="vx-bullets">
            {visit.clinician_questions.map((q) => <li key={q}>{q}</li>)}
          </ul>
        </div>
      )}
      {visit.questions.length === 0 && <p className="small muted">Nothing written yet. Your clinician will see what you add here.</p>}
      {visit.questions.length > 0 && (
        <ul className="vx-questions">
          {visit.questions.map((q) => (
            <li key={q.id} className="row between">
              <span>{q.text}</span>
              <button className="icon-btn vx-icon-sm" aria-label={`Remove question: ${q.text}`} onClick={() => remove(q)}>
                <Close size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <form className="row" style={{ gap: 8 }} onSubmit={(e) => { e.preventDefault(); add(text); }}>
        <label htmlFor={inputId} className="sr-only">Add a question</label>
        <input id={inputId} className="vx-input" value={text} maxLength={500} placeholder="Add a question"
               onChange={(e) => setText(e.target.value)} disabled={busy} />
        <button className="btn primary" disabled={busy || !text.trim()}>Add</button>
      </form>
      {visit.suggested_questions.length > 0 && (
        <div className="stack" style={{ gap: 6 }}>
          <span className="tiny muted">Suggested from your latest results</span>
          <div className="row wrap" style={{ gap: 6 }}>
            {visit.suggested_questions.map((q) => (
              <button key={q} className="btn sm vx-suggest" disabled={busy} onClick={() => add(q)}>
                <Plus size={14} /> {q}
              </button>
            ))}
          </div>
        </div>
      )}
      {notice && <div className="banner warn"><Warning size={15} /> {notice}</div>}
      {error && <div className="error-box small">{error}</div>}
    </section>
  );
}

function Location({ visit }) {
  const loc = visit.location || {};
  if (loc.mode === "virtual") {
    return (
      <section className="stack" style={{ gap: 8 }}>
        <span className="strong">Joining your video visit</span>
        {loc.join_url && (
          <a className="btn dark" href={loc.join_url} target="_blank" rel="noreferrer">Open the video visit link</a>
        )}
        <span className="tiny muted">The link works from 15 minutes before your visit.</span>
        {loc.tech_check?.length > 0 && (
          <ul className="vx-bullets">{loc.tech_check.map((t) => <li key={t}>{t}</li>)}</ul>
        )}
        {loc.accessibility?.length > 0 && (
          <div className="row wrap" style={{ gap: 6 }}>{loc.accessibility.map((a) => <span key={a} className="chip">{a}</span>)}</div>
        )}
        {loc.phone && <span className="small">Trouble joining? Call <a href={`tel:${loc.phone}`}>{loc.phone}</a></span>}
      </section>
    );
  }
  return (
    <section className="stack" style={{ gap: 8 }}>
      <span className="strong row" style={{ gap: 6 }}><Pin size={16} /> {loc.name}</span>
      {!loc.address && <span className="small muted">Directions for this location aren't available yet. Call the clinic if you need help.</span>}
      {loc.address && (
        <dl className="vx-dl">
          <dt>Address</dt>
          <dd>
            {loc.address}{" "}
            <a href={`https://www.openstreetmap.org/search?query=${encodeURIComponent(loc.address)}`} target="_blank" rel="noreferrer">
              Map
            </a>
          </dd>
          {loc.directions && (<><dt>Finding us</dt><dd>{loc.directions}</dd></>)}
          {loc.parking && (<><dt>Parking</dt><dd>{loc.parking}</dd></>)}
          {loc.phone && (<><dt>Phone</dt><dd><a href={`tel:${loc.phone}`}>{loc.phone}</a></dd></>)}
        </dl>
      )}
      {loc.accessibility?.length > 0 && (
        <div className="row wrap" style={{ gap: 6 }} aria-label="Accessibility">
          {loc.accessibility.map((a) => <span key={a} className="chip">{a}</span>)}
        </div>
      )}
    </section>
  );
}

function DayOf({ visit, onChange }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const live = visit.live;
  const video = visit.mode === "video";

  async function checkIn() {
    setBusy(true);
    setError(null);
    try {
      await api(`/visits/${visit.id}/check-in`, { method: "POST" });
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (live.status === "booked") {
    if (visit.check_in.allowed) {
      return (
        <div className="vx-dayof stack">
          <span className="strong">{video ? "Ready when you are" : "Arrived at the clinic?"}</span>
          <span className="small">{video ? "Let the team know you're ready to join." : "Check in here instead of at the desk."}</span>
          <button className="btn primary block" onClick={checkIn} disabled={busy}>
            {busy ? "Checking in…" : video ? "I'm ready" : "I'm here"}
          </button>
          {error && <div className="error-box small" role="alert">{error}</div>}
        </div>
      );
    }
    if (visit.check_in.code === "too_early") {
      return (
        <div className="vx-dayof muted small row" style={{ gap: 8 }}>
          <Calendar size={16} /> You can check in here from {fmtTime(visit.check_in.opens_at)}.
        </div>
      );
    }
    return null;
  }

  let headline;
  let detail = null;
  if (live.status === "arrived") {
    headline = "You're checked in";
    detail = live.wait_minutes === 0
      ? "You're next. We'll call you shortly."
      : "Take a seat. We'll call your name, and this page will tell you which room to go to.";
  } else if (live.status === "roomed") {
    headline = live.room ? `Please go to ${live.room}` : "Your room is ready";
    detail = "Your clinician will be with you soon.";
  } else if (live.status === "in_progress") {
    headline = "Your visit is under way";
  }
  return (
    <div className="vx-dayof live stack" role="status" aria-live="polite">
      <span className="row strong" style={{ gap: 8 }}><Check size={16} /> {headline}</span>
      {live.status === "arrived" && live.position && (
        <div className="row wrap" style={{ gap: 8 }}>
          <span className="chip ok">{live.position === 1 ? "First in line" : `Number ${live.position} in line`}</span>
          {live.wait_minutes > 0 && <span className="chip">About {live.wait_minutes} min</span>}
        </div>
      )}
      {detail && <span className="small">{detail}</span>}
      <span className="tiny muted">This updates by itself.</span>
    </div>
  );
}

function VisitCard({ visit, onChange }) {
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const video = visit.mode === "video";
  const started = visit.live.status !== "booked";

  async function cancel() {
    setBusy(true);
    setError(null);
    try {
      await api(`/appointments/${visit.id}/cancel`, { method: "POST" });
      await onChange();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <article className={`card stack ${visit.is_today ? "highlight" : ""}`} aria-labelledby={`v-${visit.id}`}>
      <header className="stack" style={{ gap: 4 }}>
        <div className="row between wrap" style={{ alignItems: "flex-start" }}>
          <div>
            <div id={`v-${visit.id}`} className="strong" style={{ fontSize: 17 }}>{visit.practitioner.name}</div>
            <div className="small muted">{visit.practitioner.specialty}{visit.reason ? ` · ${visit.reason}` : ""}</div>
          </div>
          <div className="row" style={{ gap: 6 }}>
            {visit.is_today && <span className="chip ok">Today</span>}
            {video && <span className="chip">Video</span>}
          </div>
        </div>
        <div className="row strong" style={{ gap: 8 }}><Calendar size={16} /> {fmtDateTime(visit.starts_at)}</div>
      </header>

      {visit.is_today && <DayOf visit={visit} onChange={onChange} />}

      <Checklist visit={visit} onChange={onChange} />

      <details className="vx-details">
        <summary>{video ? "How to join" : "Getting there"} <Chevron size={16} /></summary>
        <Location visit={visit} />
      </details>

      <details className="vx-details" open={visit.questions.length > 0 || undefined}>
        <summary>Questions to ask{visit.questions.length ? ` (${visit.questions.length})` : ""} <Chevron size={16} /></summary>
        <Questions visit={visit} onChange={onChange} />
      </details>

      {error && <div className="error-box small">{error}</div>}
      {!started && (
        confirmCancel ? (
          <div className="vx-confirm stack" style={{ gap: 8 }} role="group" aria-label="Confirm cancellation">
            <span className="small strong">Cancel this visit? The time will be offered to someone else.</span>
            <div className="row wrap" style={{ gap: 8 }}>
              <button className="btn danger sm" onClick={cancel} disabled={busy}>{busy ? "Cancelling…" : "Yes, cancel it"}</button>
              <button className="btn sm" onClick={() => setConfirmCancel(false)} disabled={busy}>Keep it</button>
            </div>
          </div>
        ) : (
          <div className="row wrap" style={{ gap: 8 }}>
            <Link className="btn sm" to={visit.reschedule_to}>Find another time</Link>
            <button className="btn sm ghost" onClick={() => setConfirmCancel(true)}>Cancel visit</button>
          </div>
        )
      )}
    </article>
  );
}

function PastVisit({ v }) {
  const s = v.summary;
  return (
    <article className="card stack" style={{ gap: 8 }}>
      <div className="row between wrap" style={{ alignItems: "flex-start" }}>
        <div>
          <div className="strong">{v.title}</div>
          <div className="small muted">
            {fmtDate(v.at)}{v.practitioner_name ? ` · ${v.practitioner_name}` : ""}{v.location_name ? ` · ${v.location_name}` : ""}
          </div>
        </div>
        {v.kind === "missed" && <span className="chip warn">Missed</span>}
        {s && <span className="chip ok">Summary ready</span>}
      </div>
      {v.kind === "missed" && (
        <p className="small">
          We didn't see you at this visit. <Link to={`/care/find?specialty=${encodeURIComponent(v.specialty)}`}>Book a new time</Link>
        </p>
      )}
      {s ? (
        <details className="vx-details">
          <summary>After-visit summary <Chevron size={16} /></summary>
          <dl className="vx-dl">
            <dt>What to do</dt><dd className="vx-pre">{s.instructions}</dd>
            {s.follow_up && (<><dt>Follow-up</dt><dd className="vx-pre">{s.follow_up}</dd></>)}
            {s.prescriptions && (<><dt>Prescriptions</dt><dd className="vx-pre">{s.prescriptions}</dd></>)}
          </dl>
          <span className="tiny muted">Written by {s.author || v.practitioner_name} on {fmtDate(s.published_at)}.</span>
        </details>
      ) : v.kind === "visit" && (
        <p className="small muted">{v.note}</p>
      )}
    </article>
  );
}

export default function Visits() {
  // On the day of a visit, refresh every 20 seconds so check-in status, queue position and room stay current.
  const [live, setLive] = useState(false);
  const { data, error, loading, reload } = usePoll("/visits", live ? 20000 : 0);
  const upcoming = data?.upcoming || [];
  useEffect(() => {
    setLive(upcoming.some((v) => v.is_today));
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <PatientPage>
      <div className="stack" style={{ gap: 2, marginBottom: 16 }}>
        <span className="eyebrow">Visits</span>
        <h1 className="page-title">Your visits</h1>
        <span className="page-sub">Get ready, find your way, check in, and read what your clinician wrote afterwards.</span>
      </div>

      {error && !data && <div className="error-box">{error.message}</div>}
      {error && data && <div className="banner warn" role="status">Couldn't refresh just now. Showing what we had.</div>}
      {loading && !data && (
        <div className="stack">{[0, 1].map((i) => <div key={i} className="card"><div className="skeleton" /></div>)}</div>
      )}

      {data && (
        <div className="stack" style={{ gap: 24 }}>
          <section className="stack" aria-labelledby="upcoming-h">
            <h2 id="upcoming-h" className="eyebrow">Coming up</h2>
            {upcoming.length === 0 && (
              <div className="card empty stack" style={{ alignItems: "center" }}>
                <span>You have no visits booked.</span>
                <Link className="btn primary" to="/app">Ask Bioverse to find care</Link>
              </div>
            )}
            {upcoming.map((v) => <VisitCard key={v.id} visit={v} onChange={reload} />)}
          </section>

          <section className="stack" aria-labelledby="past-h">
            <h2 id="past-h" className="eyebrow">Past visits</h2>
            {data.past.length === 0 && <div className="card small muted">No past visits yet.</div>}
            {data.past.map((v) => <PastVisit key={`${v.kind}-${v.id}`} v={v} />)}
          </section>
        </div>
      )}
    </PatientPage>
  );
}
