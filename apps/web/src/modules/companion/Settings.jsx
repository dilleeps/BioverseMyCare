import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { Check } from "../../icons.jsx";

const TOGGLES = [
  ["medication_reminders", "Medicine reminders", "A nudge when each dose is due"],
  ["appointment_reminders", "Visit reminders", "A day before and two hours before, with what to bring"],
  ["checkins", "Check-ins", "The day after a visit, and a few days into a new medicine"],
  ["results_ready", "Results ready", "When your care team has reviewed a result"],
  ["care_gap_nudges", "Preventive care", "A gentle weekly nudge when a screening or vaccine may be due"],
  ["daily_brief", "Morning summary", "Today's doses, visits and a health tip"],
];
const SLOT_LABEL = { morning: "Morning", midday: "Midday", evening: "Evening", bedtime: "Bedtime" };

export default function Settings({ onSaved }) {
  const { data, error, loading, reload } = useApi("/companion/settings");
  const [form, setForm] = useState(null);
  const [custom, setCustom] = useState({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!data) return;
    setForm({
      ...Object.fromEntries(TOGGLES.map(([k]) => [k, data[k]])),
      daily_brief_time: data.daily_brief_time,
      dose_times: { ...data.dose_times },
    });
    setCustom(Object.fromEntries(data.medications.filter((m) => m.custom).map((m) => [m.rx_id, m.times.join(", ")])));
  }, [data]);

  if (error) return <div className="error-box small">{error.message}</div>;
  if ((loading && !data) || !form) return <div className="skeleton" />;

  const set = (k, v) => { setSaved(false); setForm((f) => ({ ...f, [k]: v })); };

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setSaved(false);
    try {
      const medication_times = Object.fromEntries(
        Object.entries(custom)
          .map(([rx, text]) => [rx, text.split(/[,\s]+/).map((t) => t.trim()).filter(Boolean)])
          .filter(([, times]) => times.length > 0),
      );
      await api("/companion/settings", { method: "PUT", body: { ...form, medication_times } });
      await reload();
      setSaved(true);
      onSaved?.();
    } catch (e2) {
      setErr(e2.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="stack cp-settings" onSubmit={save}>
      <fieldset className="stack" style={{ gap: 8 }}>
        <legend className="small strong">Messages</legend>
        {TOGGLES.map(([k, label, hint]) => (
          <div key={k} className="toggle-row">
            <input id={`cp-${k}`} type="checkbox" checked={form[k]} onChange={(e) => set(k, e.target.checked)} />
            <label htmlFor={`cp-${k}`}>
              <span className="strong">{label}</span>
              <span className="tiny muted cp-hint">{hint}</span>
            </label>
          </div>
        ))}
        {form.daily_brief && (
          <div className="cp-time-row">
            <label htmlFor="cp-brief-time" className="small">Send my morning summary at</label>
            <input id="cp-brief-time" type="time" className="cp-time" value={form.daily_brief_time}
                   onChange={(e) => set("daily_brief_time", e.target.value)} required />
          </div>
        )}
      </fieldset>

      <fieldset className="stack" style={{ gap: 8 }}>
        <legend className="small strong">When you take your medicines</legend>
        <p className="tiny muted">Your usual time for each part of the day. Reminders follow your prescription's directions.</p>
        <div className="cp-slots">
          {Object.entries(SLOT_LABEL).map(([slot, label]) => (
            <div key={slot} className="cp-time-row">
              <label htmlFor={`cp-slot-${slot}`} className="small">{label}</label>
              <input id={`cp-slot-${slot}`} type="time" className="cp-time" value={form.dose_times[slot]} required
                     onChange={(e) => set("dose_times", { ...form.dose_times, [slot]: e.target.value })} />
            </div>
          ))}
        </div>
        {data.medications.map((m) => (
          <div key={m.rx_id} className="cp-med-times stack" style={{ gap: 6 }}>
            <span className="small"><span className="strong">{m.medication}</span> · {m.schedule}</span>
            <span className="tiny muted">
              {m.times.length ? `Reminders at ${m.times.join(", ")}` : "No reminders yet"}
              {!m.started && " · starts after pickup"}
            </span>
            <label htmlFor={`cp-own-${m.rx_id}`} className="tiny strong">My own times for this medicine (optional)</label>
            <input id={`cp-own-${m.rx_id}`} className="cp-text" inputMode="numeric" placeholder="For example 07:30, 19:30"
                   value={custom[m.rx_id] || ""}
                   onChange={(e) => { setSaved(false); setCustom((c) => ({ ...c, [m.rx_id]: e.target.value })); }} />
          </div>
        ))}
      </fieldset>

      {err && <div className="error-box small">{err}</div>}
      {saved && <div className="banner ok small" role="status"><Check size={14} /> Saved. Reminders will follow your new choices.</div>}
      <button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Save my choices"}</button>
      <p className="tiny muted">
        Times are on your clock ({data.timezone.replace(/_/g, " ")}). Choose email, text or quiet hours in{" "}
        <Link to="/notifications">notification settings</Link>.
      </p>
    </form>
  );
}
