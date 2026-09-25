import { useState } from "react";
import { api } from "../../api.js";
import { ErrorBox, TrashIcon, addDays, fmtDay } from "./shared.jsx";

function span(t) {
  const long = { weekday: "short", day: "numeric", month: "short", year: "numeric" };
  return t.starts_on === t.ends_on ? fmtDay(t.starts_on, long) : `${fmtDay(t.starts_on)} – ${fmtDay(t.ends_on, long)}`;
}

function days(t) {
  const [a, b] = [t.starts_on, t.ends_on].map((d) => new Date(`${d}T12:00:00`));
  return Math.round((b - a) / 86400000) + 1;
}

// Whole days away. Free slots on those days are withdrawn; booked visits stay and are listed for rebooking.
export default function TimeOff({ data, base, onChanged }) {
  const today = data.today;
  const [form, setForm] = useState({ starts_on: addDays(today, 1), ends_on: addDays(today, 1), reason: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  async function add(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await api(`${base}/availability/time-off`, {
        method: "POST", body: { ...form, reason: form.reason.trim() || null },
      });
      setResult(res);
      setForm({ starts_on: form.ends_on, ends_on: form.ends_on, reason: "" });
      onChanged();
    } catch (ex) {
      setError(ex);
    }
    setBusy(false);
  }

  async function remove(t) {
    setError(null);
    setResult(null);
    try {
      await api(`${base}/availability/time-off/${t.id}`, { method: "DELETE" });
      onChanged();
    } catch (ex) {
      setError(ex);
    }
  }

  return (
    <section className="card stack" aria-labelledby="av-off-title">
      <div>
        <h2 id="av-off-title" className="card-title">Time off</h2>
        <p className="small muted">No new slots open on these days, and free ones are withdrawn. Booked visits are kept.</p>
      </div>

      {data.time_off.length === 0 && <p className="small muted">No time off planned.</p>}
      {data.time_off.length > 0 && (
        <ul className="av-off-list">
          {data.time_off.map((t) => (
            <li key={t.id} className="av-off">
              <div className="stack" style={{ gap: 2, minWidth: 0 }}>
                <span className="strong small">{span(t)}</span>
                <span className="tiny muted">{days(t)} day{days(t) === 1 ? "" : "s"}{t.reason ? ` · ${t.reason}` : ""}</span>
              </div>
              <button type="button" className="icon-btn" onClick={() => remove(t)} aria-label={`Remove time off ${span(t)}`}>
                <TrashIcon />
              </button>
            </li>
          ))}
        </ul>
      )}

      <form className="stack av-off-form" onSubmit={add} aria-label="Add time off">
        <div className="row wrap">
          <label className="av-f"><span className="tiny muted">First day off</span>
            <input type="date" min={today} value={form.starts_on} required
                   onChange={(e) => setForm({ ...form, starts_on: e.target.value,
                                               ends_on: form.ends_on < e.target.value ? e.target.value : form.ends_on })} /></label>
          <label className="av-f"><span className="tiny muted">Last day off</span>
            <input type="date" min={form.starts_on || today} value={form.ends_on} required
                   onChange={(e) => setForm({ ...form, ends_on: e.target.value })} /></label>
          <label className="av-f av-grow"><span className="tiny muted">Reason (optional)</span>
            <input value={form.reason} maxLength={200} placeholder="Vacation, conference…"
                   onChange={(e) => setForm({ ...form, reason: e.target.value })} /></label>
        </div>
        <div><button className="btn" disabled={busy}>{busy ? "Adding…" : "Add time off"}</button></div>
      </form>

      <ErrorBox error={error} />
      {result && (
        <div className={`banner ${result.booked_in_range.length ? "warn" : "ok"} small av-result`} role="status">
          <div className="stack" style={{ gap: 4 }}>
            <span>
              Time off added. {result.sync.removed} free slot{result.sync.removed === 1 ? "" : "s"} withdrawn.
            </span>
            {result.booked_in_range.length > 0 && (
              <>
                <span>These booked visits are still on your calendar. Contact the patients to rebook:</span>
                <ul className="av-booked-list">
                  {result.booked_in_range.map((b) => (
                    <li key={b.appointment_id}>
                      {new Date(b.starts_at).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: data.timezone })}
                      {" · "}{b.patient_name}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
