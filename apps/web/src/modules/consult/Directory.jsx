import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { PatientPage } from "../../layouts.jsx";
import { fmtDateTime, initials } from "../../format.js";
import { Back, Shield } from "../../icons.jsx";
import {
  EmergencyCard, fmtMoney, MODE_LABEL, MODE_LONG, ModeIcon, Rating, SafetyCheck, StatusChip, VerifiedBadge, whenText,
} from "./shared.jsx";

const CONSENT_TEXT =
  "I agree to receive care by telehealth. I understand that a clinician can't examine me in person, that they may " +
  "ask me to be seen in person instead, and that this service is not for emergencies.";

function nextText(c) {
  if (c.available_now) return "Available now";
  if (c.next_available_at) return `Next ${fmtDateTime(c.next_available_at)}`;
  if (c.modes.includes("message")) return `Replies within ${c.reply_hours} h`;
  return "No times in the next two weeks";
}

function MyConsults() {
  const { data, error, loading } = useApi("/consultations");
  if (error) return <div className="error-box">{error.message}</div>;
  if (loading && !data) return <div className="card"><div className="skeleton" /></div>;
  if (!data.length) return null;
  const open = data.filter((c) => ["requested", "accepted", "in_progress"].includes(c.status));
  const past = data.filter((c) => !open.includes(c)).slice(0, 4);
  return (
    <section className="card stack" aria-labelledby="my-consults">
      <h2 id="my-consults" className="card-title">Your consults</h2>
      <div className="list">
        {[...open, ...past].map((c) => (
          <Link key={c.id} to={`/consult/${c.id}`} className="consult-row">
            <span className="consult-row-icon"><ModeIcon mode={c.mode} /></span>
            <span className="stack" style={{ gap: 2, minWidth: 0 }}>
              <span className="strong">{c.practitioner?.name || `First available · ${c.specialty}`}</span>
              <span className="small muted">{c.specialty} · {MODE_LABEL[c.mode]} · {whenText(c) || fmtDateTime(c.created_at)}</span>
            </span>
            <StatusChip status={c.status} label={c.status_label} />
          </Link>
        ))}
      </div>
    </section>
  );
}

function SlotPicker({ slots, value, onChange }) {
  const days = useMemo(() => {
    const out = new Map();
    for (const s of slots) {
      const d = new Date(s);
      const key = d.toDateString();
      if (!out.has(key)) out.set(key, { label: d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" }), times: [] });
      out.get(key).times.push(s);
    }
    return [...out.values()].slice(0, 5);
  }, [slots]);
  if (!slots.length) return <p className="small muted">No open times in the next two weeks. Try a message consult instead.</p>;
  return (
    <div className="stack" style={{ gap: 10 }} role="radiogroup" aria-label="Choose a time">
      {days.map((d) => (
        <div key={d.label} className="stack" style={{ gap: 6 }}>
          <span className="small strong">{d.label}</span>
          <div className="slot-grid">
            {d.times.slice(0, 8).map((t) => (
              <button key={t} type="button" role="radio" aria-checked={value === t}
                      className={`slot ${value === t ? "on" : ""}`} onClick={() => onChange(t)}>
                {new Date(t).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function RequestForm({ target, onBack }) {
  const navigate = useNavigate();
  const clinician = target.clinician;
  const modes = clinician ? clinician.modes : target.specialty.modes;
  const [mode, setMode] = useState(target.mode && modes.includes(target.mode) ? target.mode : modes[0]);
  const [slot, setSlot] = useState(null);
  const [reason, setReason] = useState("");
  const [consented, setConsented] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [check, setCheck] = useState(null);
  const [emergency, setEmergency] = useState(null);
  const top = useRef(null);
  const scheduled = mode !== "message";
  const slotsPath = !scheduled ? null : clinician
    ? `/consultations/clinicians/${clinician.id}`
    : `/consultations/slots?specialty=${encodeURIComponent(target.specialty.specialty)}&mode=${mode}`;
  const slotData = useApi(slotsPath);
  const fee = clinician ? clinician.fee_cents : target.specialty.fee_from_cents;
  const estimate = clinician ? clinician.estimate : slotData.data?.estimate;

  useEffect(() => { top.current?.scrollIntoView({ block: "start" }); }, []);
  useEffect(() => { setSlot(null); }, [mode]);

  async function submit(safety) {
    setBusy(true);
    setErr(null);
    try {
      const body = { mode, reason: reason.trim(), telehealth_consent: consented };
      if (clinician) body.practitioner_id = clinician.id;
      else body.specialty = target.specialty.specialty;
      if (scheduled) body.scheduled_at = slot;
      if (safety) body.safety_check = safety;
      const c = await api("/consultations", { method: "POST", body });
      navigate(`/consult/${c.id}`);
    } catch (e) {
      const d = e.detail;
      if (d?.code === "safety_check") setCheck(d);
      else if (d?.code === "emergency") { setEmergency(d); setCheck(null); }
      else setErr(e.message);
      setBusy(false);
    }
  }

  if (emergency) {
    return (
      <section className="stack" ref={top}>
        <EmergencyCard payload={emergency} />
        <p className="small muted">We haven't sent your request. An online consult isn't the right place for this.</p>
        <button className="btn" onClick={onBack}>Back to online consults</button>
      </section>
    );
  }

  const ready = reason.trim().length >= 3 && consented && (!scheduled || slot);
  return (
    <section className="stack" ref={top} aria-labelledby="req-title">
      <button className="btn ghost sm consult-back" onClick={onBack}><Back size={16} /> All clinicians</button>
      <div className="card stack">
        <div className="row" style={{ alignItems: "flex-start" }}>
          <span className="avatar consult-avatar">{clinician ? initials(clinician.name) : <Shield size={20} />}</span>
          <div className="stack" style={{ gap: 2, minWidth: 0 }}>
            <h2 id="req-title" className="consult-name">
              {clinician ? clinician.name : `First available in ${target.specialty.specialty}`}
            </h2>
            <span className="small muted">
              {clinician ? `${clinician.specialty} · ${clinician.languages.join(", ")}`
                : `${target.specialty.clinicians} verified clinician${target.specialty.clinicians === 1 ? "" : "s"}. Whoever is free first takes it.`}
            </span>
          </div>
        </div>

        <fieldset className="consult-fieldset">
          <legend className="small strong">How would you like to consult?</legend>
          <div className="mode-pick">
            {modes.map((m) => (
              <label key={m} className={`mode-opt ${mode === m ? "on" : ""}`}>
                <input type="radio" name="mode" value={m} checked={mode === m} onChange={() => setMode(m)} />
                <ModeIcon mode={m} size={18} /> {MODE_LONG[m]}
              </label>
            ))}
          </div>
          {mode === "message" && <p className="tiny muted">Write now; the clinician replies here, usually the same day.</p>}
          {mode === "phone" && <p className="tiny muted">The clinician calls the number on your account at the time you choose.</p>}
        </fieldset>

        {scheduled && (
          <div className="stack" style={{ gap: 8 }}>
            <span className="small strong">Choose a time</span>
            {slotData.error && <div className="error-box small">{slotData.error.message}</div>}
            {slotData.loading && !slotData.data && <div className="skeleton" />}
            {slotData.data && <SlotPicker slots={slotData.data.slots || []} value={slot} onChange={setSlot} />}
          </div>
        )}

        <div className="stack" style={{ gap: 6 }}>
          <label htmlFor="reason" className="small strong">What would you like help with?</label>
          <textarea id="reason" className="edit" maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)}
                    placeholder="For example: an itchy patch on my arm for two weeks" />
          <span className="tiny muted">The clinician sees this with a summary of your medicines, allergies and recent results.</span>
        </div>

        <div className="consult-fee small">
          <span><span className="strong">Fee {fmtMoney(fee)}</span>{!clinician && " (standard rate for this specialty)"}</span>
          {estimate && <span className="muted">With {estimate.plan_name}, you'd likely pay about {fmtMoney(estimate.patient_cents)}.</span>}
          <span className="tiny muted">Shown for information. No charge is made in this demo.</span>
        </div>

        <label className="toggle-row consent">
          <input type="checkbox" checked={consented} onChange={(e) => setConsented(e.target.checked)} />
          <span className="small">{CONSENT_TEXT}</span>
        </label>

        {check && <SafetyCheck check={check} busy={busy} onAnswer={(sel) => submit({ topic: check.topic, selected: sel })} />}
        {err && <div className="error-box small">{err}</div>}
        {!check && (
          <button className="btn primary block" disabled={busy || !ready} onClick={() => submit(null)}>
            {busy ? "Sending..." : "Request consult"}
          </button>
        )}
      </div>
    </section>
  );
}

function ClinicianCard({ c, onPick }) {
  return (
    <article className="card stack consult-card" aria-labelledby={`dr-${c.id}`}>
      <div className="row" style={{ alignItems: "flex-start" }}>
        <span className="avatar consult-avatar">{initials(c.name)}</span>
        <div className="stack" style={{ gap: 4, minWidth: 0, flexGrow: 1 }}>
          <h3 id={`dr-${c.id}`} className="consult-name">{c.name}</h3>
          <span className="small muted">{c.specialty} · {c.years_in_practice} years in practice</span>
          <Rating rating={c.rating} />
          <VerifiedBadge verified={c.verified} />
        </div>
      </div>
      {c.bio && <p className="small">{c.bio}</p>}
      <dl className="consult-facts">
        <div><dt>Speaks</dt><dd>{c.languages.join(", ")}</dd></div>
        <div><dt>Consults by</dt><dd>{c.modes.map((m) => MODE_LABEL[m]).join(", ")}</dd></div>
        <div><dt>Fee</dt><dd>{fmtMoney(c.fee_cents)}{c.estimate ? ` · about ${fmtMoney(c.estimate.patient_cents)} with your plan` : ""}</dd></div>
        <div><dt>Availability</dt><dd className={c.available_now ? "now" : ""}>{nextText(c)}</dd></div>
      </dl>
      <button className="btn primary" onClick={() => onPick(c)}>Request a consult</button>
    </article>
  );
}

export default function Directory() {
  const [params, setParams] = useSearchParams();
  const specialty = params.get("specialty") || "";
  const language = params.get("language") || "";
  const mode = params.get("mode") || "";
  const qs = new URLSearchParams(Object.entries({ specialty, language, mode }).filter(([, v]) => v)).toString();
  const { data, error, loading } = useApi(`/consultations/clinicians${qs ? `?${qs}` : ""}`);
  const specs = useApi("/consultations/specialties");
  const [target, setTarget] = useState(null);

  useEffect(() => { document.title = "See a doctor online · Bioverse"; }, []);

  function setFilter(key, value) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  }

  if (target) {
    return (
      <PatientPage wide>
        <div className="consult-page"><RequestForm target={target} onBack={() => setTarget(null)} /></div>
      </PatientPage>
    );
  }

  const filters = data?.filters;
  return (
    <PatientPage wide>
      <div className="consult-page stack" style={{ gap: 18 }}>
        <div>
          <h1 className="page-title">See a doctor online</h1>
          <p className="page-sub">Verified clinicians by secure message, video or phone. Every license is checked before anyone appears here.</p>
        </div>
        <div className="banner warn small" role="note">
          Not for emergencies. If you have chest pain, trouble breathing or signs of a stroke, call 911.
        </div>

        <MyConsults />

        <section className="stack" aria-labelledby="first-avail" style={{ gap: 10 }}>
          <h2 id="first-avail" className="card-title">First available, by specialty</h2>
          {specs.error && <div className="error-box small">{specs.error.message}</div>}
          {specs.loading && !specs.data && <div className="skeleton" />}
          <div className="spec-grid">
            {specs.data?.map((s) => (
              <button key={s.specialty} className="spec-card" onClick={() => setTarget({ specialty: s, mode: mode || null })}>
                <span className="strong">{s.specialty}</span>
                <span className="small muted">From {fmtMoney(s.fee_from_cents)} · {s.modes.map((m) => MODE_LABEL[m]).join(", ")}</span>
                <span className={`small ${s.available_now ? "now" : "muted"}`}>
                  {s.available_now ? "Clinicians available now" : s.next_available_at ? `Next ${fmtDateTime(s.next_available_at)}` : "By message"}
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="stack" aria-labelledby="dir-title" style={{ gap: 12 }}>
          <h2 id="dir-title" className="card-title">Choose a clinician</h2>
          <div className="consult-filters" role="group" aria-label="Filter clinicians">
            <div className="field">
              <label htmlFor="f-spec" className="small strong">Specialty</label>
              <select id="f-spec" value={specialty} onChange={(e) => setFilter("specialty", e.target.value)}>
                <option value="">Any specialty</option>
                {filters?.specialties.map((s) => <option key={s}>{s}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="f-lang" className="small strong">Language</label>
              <select id="f-lang" value={language} onChange={(e) => setFilter("language", e.target.value)}>
                <option value="">Any language</option>
                {filters?.languages.map((s) => <option key={s}>{s}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="f-mode" className="small strong">Consult by</label>
              <select id="f-mode" value={mode} onChange={(e) => setFilter("mode", e.target.value)}>
                <option value="">Any way</option>
                {["message", "video", "phone"].map((m) => <option key={m} value={m}>{MODE_LONG[m]}</option>)}
              </select>
            </div>
          </div>
          {error && <div className="error-box">{error.message}</div>}
          {loading && !data && <div className="card"><div className="skeleton" /></div>}
          {data && data.clinicians.length === 0 && (
            <div className="card empty">No verified clinicians match. Try another language or way to consult.</div>
          )}
          <div className="consult-grid">
            {data?.clinicians.map((c) => <ClinicianCard key={c.id} c={c} onPick={(dr) => setTarget({ clinician: dr, mode: mode || null })} />)}
          </div>
        </section>
      </div>
    </PatientPage>
  );
}
