import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { PatientPage } from "../../layouts.jsx";
import { fmtDateTime } from "../../format.js";
import { Calendar, Check, Gear, Phone, Warning } from "../../icons.jsx";
import { Bulb, Capsule, Heart, Pulse } from "./icons.jsx";
import { clock, greeting, longDay, pct, shortDay, weekdayLetter } from "./format.js";
import Settings from "./Settings.jsx";

const PART_LABEL = { morning: "Morning", afternoon: "Afternoon", evening: "Evening", bedtime: "Bedtime", night: "Night" };
const REPLY_LABEL = { better: "Better", same: "About the same", worse: "Worse" };

function Section({ id, title, icon: Icon, aside, children, className = "" }) {
  return (
    <section className={`card stack ${className}`} aria-labelledby={id}>
      <div className="row between wrap">
        <h2 id={id} className="card-title row" style={{ gap: 8 }}>{Icon && <Icon size={18} />} {title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

// --- Emergency guidance ---------------------------------------------------------------------------

function Emergency({ e }) {
  return (
    <section className="emergency stack" role="alert">
      <div className="row strong" style={{ color: "var(--alert-strong)" }}>
        <Warning size={20} /> {e.crisis_line ? "Support is available now" : "Get emergency help now"}
      </div>
      <p className="small" style={{ color: "var(--alert-strong)" }}>{e.message}</p>
      {e.crisis_line && (
        <a className="call" href={`tel:${e.crisis_line}`}><Phone size={20} /> Call or text {e.crisis_line}</a>
      )}
      <a className="call" href={`tel:${e.emergency_number}`}><Phone size={20} /> Call {e.emergency_number}</a>
      {e.care_team_notified && (
        <p className="small" style={{ color: "var(--alert-strong)" }}>Your care team has been notified.</p>
      )}
    </section>
  );
}

// --- Check-ins ------------------------------------------------------------------------------------

function CheckinCard({ checkin, highlighted, onAnswered }) {
  const [choice, setChoice] = useState(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [result, setResult] = useState(null);
  const ref = useRef(null);

  useEffect(() => {
    if (highlighted) ref.current?.scrollIntoView({ block: "center" });
  }, [highlighted]);

  async function send() {
    setBusy(true);
    setErr(null);
    try {
      const r = await api(`/companion/checkins/${checkin.id}/answer`, {
        method: "POST", body: { response: choice, note: note.trim() || null },
      });
      setResult(r);
      if (!r.emergency) onAnswered();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (result?.emergency) return <Emergency e={result.emergency} />;
  if (result) {
    return (
      <div className={`banner ${result.escalation ? "info" : "ok"}`} role="status">
        <Check size={16} /> {result.message}
      </div>
    );
  }
  const fieldId = `cp-note-${checkin.id}`;
  return (
    <div ref={ref} className={`cp-checkin stack ${highlighted ? "cp-highlight" : ""}`}>
      <p className="cp-prompt">{checkin.prompt}</p>
      <div className="cp-replies" role="group" aria-label="How are you feeling?">
        {Object.entries(REPLY_LABEL).map(([k, label]) => (
          <button key={k} type="button" className={`cp-reply ${k}`} aria-pressed={choice === k} onClick={() => setChoice(k)}>
            {label}
          </button>
        ))}
      </div>
      <label htmlFor={fieldId} className="small strong">Anything you'd like to add? (optional)</label>
      <textarea id={fieldId} className="edit" style={{ minHeight: 64 }} maxLength={1000} value={note}
                onChange={(e) => setNote(e.target.value)} placeholder="For example, how you slept or anything new" />
      <p className="tiny muted">
        This isn't watched around the clock. If you feel very unwell, call your local emergency number.
      </p>
      {err && <div className="error-box small">{err}</div>}
      <button className="btn primary" onClick={send} disabled={!choice || busy}>{busy ? "Sending…" : "Send"}</button>
    </div>
  );
}

// --- Doses ----------------------------------------------------------------------------------------

function DoseRow({ dose, reasons, highlighted, onChanged }) {
  const [skipping, setSkipping] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [note, setNote] = useState(null);
  const ref = useRef(null);

  useEffect(() => {
    if (highlighted) ref.current?.scrollIntoView({ block: "center" });
  }, [highlighted]);

  async function mark(status) {
    setBusy(true);
    setErr(null);
    try {
      const r = await api("/companion/doses", {
        method: "POST",
        body: { medication_request_id: dose.rx_id, local_time: dose.local, status, reason: status === "skipped" ? reason || null : null },
      });
      setNote(r.note);
      setSkipping(false);
      await onChanged();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    setBusy(true);
    setErr(null);
    try {
      await api(`/companion/doses/${dose.dose_id}`, { method: "DELETE" });
      setNote(null);
      await onChanged();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  const done = dose.status === "taken" || dose.status === "skipped";
  const reasonLabel = reasons.find((r) => r.id === dose.reason)?.label;
  return (
    <li ref={ref} className={`cp-dose ${dose.status} ${highlighted ? "cp-highlight" : ""}`}>
      <div className="cp-dose-time">
        <span className="strong">{clock(dose.time)}</span>
        <span className="tiny muted">{PART_LABEL[dose.part_of_day]}</span>
      </div>
      <div className="cp-dose-body">
        <span className="strong">{dose.medication}</span>
        <span className="small muted">
          {dose.status === "taken" && (dose.source === "pharmacy" ? "Logged on the pharmacy page" : "Taken")}
          {dose.status === "skipped" && `Skipped${reasonLabel ? ` · ${reasonLabel}` : ""}`}
          {dose.status === "due" && "Due · not marked yet"}
          {dose.status === "upcoming" && "Coming up"}
          {dose.status === "missed" && "Not marked yet"}
        </span>
        {note && <span className="small cp-note">{note}</span>}
        {err && <span className="error-box small">{err}</span>}
        {skipping && (
          <div className="stack" style={{ gap: 8, marginTop: 6 }}>
            <label htmlFor={`cp-reason-${dose.rx_id}-${dose.local}`} className="small strong">Why are you skipping it? (optional)</label>
            <select id={`cp-reason-${dose.rx_id}-${dose.local}`} className="cp-select" value={reason}
                    onChange={(e) => setReason(e.target.value)}>
              <option value="">Rather not say</option>
              {reasons.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
            </select>
            <div className="row wrap" style={{ gap: 8 }}>
              <button className="btn dark" onClick={() => mark("skipped")} disabled={busy}>Skip this dose</button>
              <button className="btn ghost" onClick={() => setSkipping(false)} disabled={busy}>Cancel</button>
            </div>
          </div>
        )}
      </div>
      <div className="cp-dose-actions">
        {done ? (
          <>
            {dose.status === "taken" ? <span className="chip ok"><Check size={12} /> Taken</span>
              : <span className="chip">Skipped</span>}
            {dose.dose_id && <button className="btn ghost" onClick={undo} disabled={busy}>Undo</button>}
          </>
        ) : !skipping && (
          <>
            <button className="btn primary" onClick={() => mark("taken")} disabled={busy}
                    aria-label={`Mark ${dose.medication} at ${clock(dose.time)} as taken`}>
              Taken
            </button>
            <button className="btn" onClick={() => setSkipping(true)} disabled={busy}
                    aria-label={`Skip ${dose.medication} at ${clock(dose.time)}`}>
              Skip
            </button>
          </>
        )}
      </div>
    </li>
  );
}

function Doses({ today, focus, onChanged }) {
  const isFocus = (d) => focus.rx === d.rx_id && focus.at === d.local;
  const nothing = today.doses.length === 0 && today.earlier.length === 0;
  return (
    <Section id="cp-doses" title="Today's medicines" icon={Capsule}
             aside={<Link className="small" to="/pharmacy">Prescriptions</Link>}>
      {nothing && today.waiting_for_pickup.length === 0 && (
        <p className="small muted">No doses scheduled today. Medicines your care team prescribes will show up here.</p>
      )}
      {today.doses.length > 0 && (
        <ul className="cp-doses" aria-label="Doses today">
          {today.doses.map((d) => (
            <DoseRow key={`${d.rx_id}-${d.local}`} dose={d} reasons={today.skip_reasons} highlighted={isFocus(d)} onChanged={onChanged} />
          ))}
        </ul>
      )}
      {today.earlier.length > 0 && (
        <>
          <h3 className="eyebrow">From yesterday</h3>
          <ul className="cp-doses" aria-label="Doses from yesterday not marked yet">
            {today.earlier.map((d) => (
              <DoseRow key={`${d.rx_id}-${d.local}`} dose={d} reasons={today.skip_reasons} highlighted={isFocus(d)} onChanged={onChanged} />
            ))}
          </ul>
        </>
      )}
      {today.waiting_for_pickup.map((w) => (
        <p key={w.rx_id} className="banner info small">
          <span><strong>{w.medication}</strong> is waiting at the pharmacy. Reminders start once you've picked it up.{" "}
            <Link to="/pharmacy">See pickup details</Link></span>
        </p>
      ))}
      {today.unscheduled.map((u) => (
        <p key={u.rx_id} className="small muted">
          We couldn't read a schedule for {u.medication}. Set your own times in the settings below.
        </p>
      ))}
    </Section>
  );
}

// --- Adherence ------------------------------------------------------------------------------------

function Adherence() {
  const { data, error, loading } = useApi("/companion/adherence");
  if (error) return <Section id="cp-adh" title="How it's going" icon={Pulse}><div className="error-box small">{error.message}</div></Section>;
  if (loading && !data) return <Section id="cp-adh" title="How it's going" icon={Pulse}><div className="skeleton" /></Section>;
  const tracked = data.medications.filter((m) => m.tracking);
  return (
    <Section id="cp-adh" title="How it's going" icon={Pulse}>
      {tracked.length === 0 ? (
        <p className="small muted">Once you start marking doses, you'll see how the last week and month went.</p>
      ) : (
        <>
          <dl className="cp-stats">
            <div><dt>Last 7 days</dt><dd className={data.last_7.pct != null && data.last_7.pct < data.target_pct ? "cp-low" : ""}>{pct(data.last_7.pct)}</dd>
              <span className="tiny muted">{data.last_7.taken} of {data.last_7.expected} doses</span></div>
            <div><dt>Last 30 days</dt><dd>{pct(data.last_30.pct)}</dd>
              <span className="tiny muted">{data.last_30.taken} of {data.last_30.expected} doses</span></div>
          </dl>
          {tracked.map((m) => (
            <div key={m.rx_id} className="stack" style={{ gap: 6 }}>
              <div className="row between wrap small">
                <span className="strong">{m.medication}</span>
                <span className="muted">{m.schedule}</span>
              </div>
              <ul className="cp-strip" aria-label={`${m.medication}, last two weeks`}>
                {m.days.map((d) => {
                  const state = d.expected === 0 ? "none" : d.not_taken > 0 ? "missed" : d.taken === d.expected ? "taken" : "open";
                  const words = { none: "no doses", missed: "not all taken", taken: "all taken", open: "not finished" }[state];
                  return (
                    <li key={d.date} className={state}>
                      <span className="sr-only">{shortDay(d.date)}: {words}</span>
                      <span aria-hidden="true">{weekdayLetter(d.date)}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
          <p className="tiny muted">
            Missed doses happen. If something makes a medicine hard to take, like side effects or cost, tell your care team.
          </p>
        </>
      )}
    </Section>
  );
}

// --- History --------------------------------------------------------------------------------------

function History({ version }) {
  const { data, error, loading, reload } = useApi("/companion/checkins");
  useEffect(() => { if (version) reload(); }, [version, reload]);
  return (
    <Section id="cp-history" title="Your check-ins" icon={Heart}>
      {error && <div className="error-box small">{error.message}</div>}
      {loading && !data && <div className="skeleton" />}
      {data && data.history.length === 0 && <p className="small muted">Your answers to check-ins will appear here.</p>}
      {data && data.history.length > 0 && (
        <ul className="list cp-history">
          {data.history.slice(0, 8).map((c) => (
            <li key={c.id} className="stack" style={{ gap: 2, padding: "10px 0" }}>
              <span className="row between wrap small">
                <span className="strong">{c.status === "expired" ? "No answer" : REPLY_LABEL[c.response]}</span>
                <span className="tiny muted">{fmtDateTime(c.answered_at || c.due_at)}</span>
              </span>
              <span className="small muted">
                {c.kind === "post_visit" ? `After ${c.subject}` : `Started ${c.subject}`}
                {c.escalation && " · shared with your care team"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

// --- Page -----------------------------------------------------------------------------------------

export default function Companion() {
  const { data, error, loading, reload } = useApi("/companion/today");
  const [params] = useSearchParams();
  const [version, setVersion] = useState(0);
  const focus = { rx: params.get("rx"), at: params.get("at"), checkin: params.get("checkin") };

  async function changed() {
    await reload();
    setVersion((v) => v + 1);
  }

  return (
    <PatientPage wide>
      <div className="cp-head">
        <span className="eyebrow">{data ? longDay(data.date) : "Today"}</span>
        <h1 className="page-title">{data ? `${greeting()}, ${data.first_name}` : "Today"}</h1>
        <p className="page-sub">Your medicines, check-ins and visits for today. We'll remind you when something's due.</p>
      </div>
      {error && <div className="error-box">{error.message}</div>}
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {data && (
        <div className="cp-grid">
          <div className="stack">
            {data.checkins.length > 0 && (
              <Section id="cp-checkins" title={data.checkins.length === 1 ? "A quick check-in" : "Quick check-ins"}
                       icon={Heart} className="highlight">
                {data.checkins.map((c) => (
                  <CheckinCard key={c.id} checkin={c} highlighted={focus.checkin === c.id} onAnswered={changed} />
                ))}
              </Section>
            )}
            <Doses today={data} focus={focus} onChanged={changed} />
            <Section id="cp-visits" title="Coming up" icon={Calendar}
                     aside={<Link className="small" to="/visits">All visits</Link>}>
              {data.appointments.length === 0 ? (
                <p className="small muted">No visits in the next two weeks. <Link to="/care/find">Find care</Link> if you need it.</p>
              ) : (
                <ul className="list">
                  {data.appointments.map((a) => (
                    <li key={a.id} className="stack" style={{ gap: 2, padding: "10px 0" }}>
                      <span className="strong">{fmtDateTime(a.starts_at)}</span>
                      <span className="small muted">
                        {a.practitioner_name} · {a.mode === "video" ? "Video visit" : a.location_name}
                      </span>
                      <Link className="small" to="/visits">Checklist and directions</Link>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </div>
          <div className="stack">
            <Adherence key={`adh-${version}`} />
            <section className="card stack cp-tip" aria-labelledby="cp-tip">
              <h2 id="cp-tip" className="card-title row" style={{ gap: 8 }}><Bulb size={18} /> Today's tip</h2>
              <p>{data.tip.text}</p>
              <p className="tiny muted">Source: {data.tip.source}</p>
            </section>
            <History version={version} />
            <Section id="cp-settings" title="What Bioverse One does for you" icon={Gear}>
              <Settings onSaved={changed} />
            </Section>
          </div>
        </div>
      )}
    </PatientPage>
  );
}
