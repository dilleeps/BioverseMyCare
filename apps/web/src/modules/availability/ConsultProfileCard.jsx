import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { Check, Close, Shield } from "../../icons.jsx";
import { CONSULT_DAYS, CONSULT_MODE_LABELS, ErrorBox, WEEKDAY_SHORT, dollars, fmtDay, toMinutes } from "./shared.jsx";

function toForm(d) {
  const p = d.profile;
  return {
    fee: String((p.fee_cents || 0) / 100),
    modes: p.modes || [],
    accepting: Boolean(p.accepting),
    reply_hours: p.reply_hours || 24,
    years_in_practice: p.years_in_practice ?? "",
    bio: p.bio || "",
    languages: (d.languages || []).join(", "),
    hours: Object.fromEntries(CONSULT_DAYS.map((k) => [k, p.hours?.[k] ? [...p.hours[k]] : null])),
    slot_minutes: p.slot_minutes || 30,
  };
}

function toBody(f) {
  return {
    fee_cents: Math.round(Number(f.fee || 0) * 100),
    modes: f.modes,
    accepting: f.accepting,
    reply_hours: Number(f.reply_hours),
    years_in_practice: f.years_in_practice === "" ? null : Number(f.years_in_practice),
    bio: f.bio,
    languages: f.languages.split(",").map((s) => s.trim()).filter(Boolean),
    hours: Object.fromEntries(Object.entries(f.hours).filter(([, v]) => v)),
    slot_minutes: Number(f.slot_minutes),
  };
}

// Online consult profile (fee, how they consult, whether they take new patients) and the license status that
// decides whether patients can find them at all.
export default function ConsultProfileCard({ base, windows, isSelf }) {
  const { data, error, loading, reload } = useApi(`${base}/consult-profile`);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => { if (data) setForm(toForm(data)); }, [data]);

  if (error) return <section className="card"><ErrorBox error={error} /></section>;
  if (loading && !data) return <section className="card"><div className="skeleton" /></section>;
  if (!data || !form) return null;

  const set = (k) => (e) => { setSaved(false); setForm({ ...form, [k]: e.target.value }); };
  const toggleMode = (m) => {
    setSaved(false);
    setForm({ ...form, modes: form.modes.includes(m) ? form.modes.filter((x) => x !== m) : [...form.modes, m] });
  };
  const setDay = (k, v) => { setSaved(false); setForm({ ...form, hours: { ...form.hours, [k]: v } }); };

  // Consult hours from the video windows in the weekly template: earliest start to latest end per day.
  function fromVideoWindows() {
    const hours = Object.fromEntries(CONSULT_DAYS.map((k) => [k, null]));
    windows.filter((w) => w.mode === "video").forEach((w) => {
      const k = CONSULT_DAYS[w.weekday];
      const cur = hours[k];
      hours[k] = cur ? [toMinutes(w.start) < toMinutes(cur[0]) ? w.start : cur[0], toMinutes(w.end) > toMinutes(cur[1]) ? w.end : cur[1]]
        : [w.start, w.end];
    });
    setSaved(false);
    setForm({ ...form, hours });
  }

  const badHours = CONSULT_DAYS.some((k) => form.hours[k] && toMinutes(form.hours[k][1]) <= toMinutes(form.hours[k][0]));
  const invalid = form.modes.length === 0 || badHours || Number(form.fee) < 0 || !form.languages.trim();

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api(`${base}/consult-profile`, { method: "PATCH", body: toBody(form) });
      setSaved(true);
      reload();
    } catch (ex) {
      setErr(ex);
    }
    setBusy(false);
  }

  const cred = data.credential;
  const hasVideo = windows.some((w) => w.mode === "video");
  return (
    <section className="card stack av-consult" aria-labelledby="av-consult-title">
      <div className="row between wrap">
        <div>
          <h2 id="av-consult-title" className="card-title">Online consult profile</h2>
          <p className="small muted">What patients see in the online consult directory.</p>
        </div>
        <span className={`chip ${data.listed_in_directory ? "ok" : "warn"}`}>
          {data.listed_in_directory ? "Listed in the directory" : "Not listed"}
        </span>
      </div>

      <div className="av-verify stack" aria-label="Verification status">
        <div className={`banner ${cred.credentialed ? "ok" : "warn"} small`}><Shield size={15} /> <span>{cred.message}</span></div>
        {cred.credentials.length > 0 && (
          <div className="row wrap" style={{ gap: 6 }}>
            {cred.credentials.map((c) => (
              <span key={c.id} className={`chip ${c.status === "verified" && !c.lapsed ? "ok" : c.status === "pending" ? "" : "warn"}`}>
                {c.license_type} · {c.jurisdiction} · {c.lapsed ? "Lapsed" : c.status_label}
                {c.status === "verified" && !c.lapsed ? ` to ${fmtDay(c.expires_on, { day: "numeric", month: "short", year: "numeric" })}` : ""}
              </span>
            ))}
          </div>
        )}
        <ul className="av-checks">
          {data.listing_checks.map((c) => (
            <li key={c.key} className={c.ok ? "ok" : "no"}>
              {c.ok ? <Check size={14} /> : <Close size={14} />} <span>{c.label}</span>
            </li>
          ))}
        </ul>
        <p className="tiny muted">
          {data.directory_note}{" "}
          {isSelf && <Link to="/clinician/license">Open My license</Link>}
        </p>
      </div>

      <form className="stack" onSubmit={save}>
        <div className="av-form-grid">
          <label className="av-f"><span className="tiny muted">Consult fee (USD)</span>
            <input type="number" min="0" max="2000" step="1" inputMode="decimal" value={form.fee} onChange={set("fee")} /></label>
          <label className="av-f"><span className="tiny muted">Replies to messages within</span>
            <select value={form.reply_hours} onChange={set("reply_hours")}>
              {[1, 2, 4, 8, 12, 24, 48, 72].map((h) => <option key={h} value={h}>{h} hour{h === 1 ? "" : "s"}</option>)}
            </select></label>
          <label className="av-f"><span className="tiny muted">Years in practice</span>
            <input type="number" min="0" max="70" value={form.years_in_practice} onChange={set("years_in_practice")} /></label>
          <label className="av-f"><span className="tiny muted">Languages (comma separated)</span>
            <input value={form.languages} onChange={set("languages")} maxLength={300} /></label>
        </div>

        <fieldset className="av-fieldset">
          <legend className="tiny muted">Consult by</legend>
          <div className="row wrap">
            {data.mode_options.map((m) => (
              <label key={m} className="av-check">
                <input type="checkbox" checked={form.modes.includes(m)} onChange={() => toggleMode(m)} /> {CONSULT_MODE_LABELS[m]}
              </label>
            ))}
          </div>
          {form.modes.length === 0 && <span className="tiny av-problem">Choose at least one.</span>}
          <p className="tiny muted">{data.in_person_note}</p>
        </fieldset>

        <div className="toggle-row">
          <input id="av-accepting" type="checkbox" checked={form.accepting}
                 onChange={(e) => { setSaved(false); setForm({ ...form, accepting: e.target.checked }); }} />
          <label htmlFor="av-accepting">
            <span className="strong">Accepting new patients</span>
            <span className="tiny muted" style={{ display: "block" }}>Turn off to leave the directory without losing your profile.</span>
          </label>
        </div>

        <label className="av-f"><span className="tiny muted">About you</span>
          <textarea className="edit" value={form.bio} onChange={set("bio")} maxLength={2000} rows={3}
                    placeholder="A sentence or two patients read before they choose you." /></label>

        {form.modes.some((m) => m !== "message") && (
          <fieldset className="av-fieldset">
            <legend className="tiny muted">Hours for scheduled video and phone consults</legend>
            <div className="av-consult-hours">
              {CONSULT_DAYS.map((k, i) => {
                const v = form.hours[k];
                return (
                  <div key={k} className="av-ch-row">
                    <label className="av-check">
                      <input type="checkbox" checked={Boolean(v)} onChange={(e) => setDay(k, e.target.checked ? ["09:00", "17:00"] : null)} />
                      {WEEKDAY_SHORT[i]}
                    </label>
                    {v ? (
                      <>
                        <input type="time" step="300" value={v[0]} aria-label={`${WEEKDAY_SHORT[i]} consults from`}
                               onChange={(e) => setDay(k, [e.target.value, v[1]])} />
                        <span className="tiny muted">to</span>
                        <input type="time" step="300" value={v[1]} aria-label={`${WEEKDAY_SHORT[i]} consults until`}
                               onChange={(e) => setDay(k, [v[0], e.target.value])} />
                        {toMinutes(v[1]) <= toMinutes(v[0]) && <span className="tiny av-problem">End before start</span>}
                      </>
                    ) : <span className="tiny muted">No scheduled consults</span>}
                  </div>
                );
              })}
            </div>
            <div className="row wrap">
              <label className="av-f"><span className="tiny muted">Consult length</span>
                <select value={form.slot_minutes} onChange={set("slot_minutes")}>
                  {[10, 15, 20, 30, 45, 60, 90, 120].map((m) => <option key={m} value={m}>{m} min</option>)}
                </select></label>
              {hasVideo && <button type="button" className="btn sm" onClick={fromVideoWindows}>Use my video hours</button>}
            </div>
          </fieldset>
        )}

        <ErrorBox error={err} />
        {saved && <div className="banner ok small" role="status">Consult profile saved.</div>}
        <div className="row between wrap">
          <span className="tiny muted">Patients see {dollars(Number(form.fee || 0) * 100)} per consult, with an insurance estimate.</span>
          <button className="btn primary" disabled={busy || invalid}>{busy ? "Saving…" : "Save profile"}</button>
        </div>
      </form>
    </section>
  );
}
