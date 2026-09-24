import { useState } from "react";
import { api } from "../../api.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { useSession } from "../../session.jsx";
import { Chat, Check, Person } from "../../icons.jsx";
import { fmtTime, usePoll } from "./poll.js";

const POLL_MS = 15000;

const STAT_ORDER = [
  ["booked", "Booked"],
  ["arrived", "Checked in"],
  ["roomed", "In a room"],
  ["in_progress", "With clinician"],
  ["completed", "Completed"],
  ["no_show", "No-show"],
];

const ACTION_LABEL = {
  arrived: "Mark arrived",
  in_progress: "Start visit",
  completed: "Complete visit",
  no_show: "No-show",
};

const ROOMS = ["Room 1", "Room 2", "Room 3", "Room 4", "Room 5", "Echo 1"];

function StatusChip({ row }) {
  const tone = { arrived: "ok", roomed: "ok", in_progress: "solid", no_show: "warn" }[row.status] || "";
  return <span className={`chip ${tone}`}>{row.label}{row.room && row.status !== "completed" ? ` · ${row.room}` : ""}</span>;
}

function SummaryForm({ row, onSaved }) {
  const [form, setForm] = useState({
    instructions: row.instructions || "",
    follow_up: row.follow_up || "",
    prescriptions: row.prescriptions || "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const set = (k) => (e) => {
    setForm((f) => ({ ...f, [k]: e.target.value }));
    setSaved(false);
  };

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/visits/queue/${row.id}/summary`, { method: "PUT", body: form });
      setSaved(true);
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const id = (k) => `${k}-${row.id}`;
  return (
    <form className="vx-summary stack" onSubmit={save} aria-label={`After-visit summary for ${row.patient_name}`}>
      <div className="row between wrap">
        <span className="strong">After-visit summary</span>
        <span className="tiny muted">Goes to {row.patient_name} as soon as you save. You are the author.</span>
      </div>
      <label htmlFor={id("ins")} className="small strong">Instructions for the patient</label>
      <textarea id={id("ins")} className="edit" required minLength={3} maxLength={4000} value={form.instructions}
                onChange={set("instructions")} placeholder="What to do at home, what to watch for, when to get help" />
      <label htmlFor={id("fu")} className="small strong">Follow-up</label>
      <textarea id={id("fu")} className="edit vx-short" maxLength={2000} value={form.follow_up} onChange={set("follow_up")}
                placeholder="Next appointment, tests, referrals" />
      <label htmlFor={id("rx")} className="small strong">Prescriptions</label>
      <textarea id={id("rx")} className="edit vx-short" maxLength={2000} value={form.prescriptions}
                onChange={set("prescriptions")} placeholder="Medicine, dose, how often, quantity" />
      {error && <div className="error-box small">{error}</div>}
      <div className="row" style={{ gap: 8 }}>
        <button className="btn primary sm" disabled={busy || form.instructions.trim().length < 3}>
          {busy ? "Saving…" : row.has_summary ? "Update summary" : "Publish to patient"}
        </button>
        {saved && <span className="small row" style={{ gap: 4, color: "var(--accent-strong)" }}><Check size={14} /> Sent to the patient</span>}
      </div>
    </form>
  );
}

function QueueRow({ row, canWriteSummary, onChanged, isToday }) {
  const [room, setRoom] = useState(ROOMS[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [showSummary, setShowSummary] = useState(false);

  async function act(status) {
    setBusy(true);
    setError(null);
    try {
      await api(`/visits/queue/${row.id}/status`, {
        method: "POST",
        body: { status, room: status === "roomed" ? room : null },
      });
      await onChanged();
      if (status === "completed" && canWriteSummary) setShowSummary(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const roomId = `room-${row.id}`;
  const waiting = row.status === "arrived" && row.wait;
  return (
    <li className={`vx-qrow ${row.status}`}>
      <div className="vx-qtime">
        <span className="strong">{fmtTime(row.starts_at)}</span>
        <span className="tiny muted">{row.duration_min} min{row.mode === "video" ? " · video" : ""}</span>
      </div>
      <div className="vx-qwho">
        <span className="strong">{row.patient_name}</span>
        <span className="tiny muted">
          {row.age} · {row.pronouns || "pronouns not recorded"}{row.preferred_language !== "English" ? ` · prefers ${row.preferred_language}` : ""}
        </span>
        {row.reason && <span className="small">{row.reason}</span>}
        {row.questions.length > 0 && (
          <details className="vx-details compact">
            <summary><Chat size={14} /> {row.questions.length} question{row.questions.length === 1 ? "" : "s"} from the patient</summary>
            <ul className="vx-bullets small">{row.questions.map((q) => <li key={q}>{q}</li>)}</ul>
          </details>
        )}
      </div>
      <div className="vx-qstatus">
        <StatusChip row={row} />
        {waiting && (
          <span className="tiny muted">
            {row.arrived_at ? `Arrived ${fmtTime(row.arrived_at)} · ` : ""}
            #{row.wait.position} waiting{row.wait.wait_minutes ? ` · ~${row.wait.wait_minutes} min` : " · next"}
          </span>
        )}
        {row.status === "in_progress" && row.started_at && <span className="tiny muted">Started {fmtTime(row.started_at)}</span>}
        {row.status === "completed" && <span className="tiny muted">{row.has_summary ? "Summary sent" : "Summary not written"}</span>}
      </div>
      <div className="vx-qactions">
        {row.actions.includes("roomed") && (
          <div className="row" style={{ gap: 6 }}>
            <label htmlFor={roomId} className="sr-only">Room for {row.patient_name}</label>
            <select id={roomId} className="vx-select" value={room} onChange={(e) => setRoom(e.target.value)} disabled={busy}>
              {ROOMS.map((r) => <option key={r}>{r}</option>)}
            </select>
            <button className="btn dark sm" disabled={busy} onClick={() => act("roomed")}>Room</button>
          </div>
        )}
        {row.actions.filter((a) => a !== "roomed").map((a) => {
          if (a === "arrived" && !isToday) return null;
          if (a === "no_show" && new Date(row.starts_at) > new Date()) return null;
          return (
            <button key={a} className={`btn sm ${a === "completed" || a === "in_progress" ? "primary" : a === "no_show" ? "ghost" : ""}`}
                    disabled={busy} onClick={() => act(a)}>
              {ACTION_LABEL[a]}
            </button>
          );
        })}
        {row.status === "completed" && canWriteSummary && (
          <button className="btn sm" aria-expanded={showSummary} onClick={() => setShowSummary((s) => !s)}>
            {showSummary ? "Close summary" : row.has_summary ? "Edit summary" : "Write summary"}
          </button>
        )}
      </div>
      {error && <div className="error-box small vx-qfull" role="alert">{error}</div>}
      {showSummary && <div className="vx-qfull"><SummaryForm row={row} onSaved={onChanged} /></div>}
    </li>
  );
}

export default function ClinicQueue() {
  const { me } = useSession();
  const [practitionerId, setPractitionerId] = useState("");
  const [day, setDay] = useState("");
  const params = new URLSearchParams();
  if (practitionerId) params.set("practitioner_id", practitionerId);
  if (day) params.set("day", day);
  const { data, error, loading, reload, updatedAt } = usePoll(`/visits/queue?${params}`, POLL_MS);

  const current = data?.practitioner;
  const isToday = data && String(data.day) === String(data.today);
  const canWriteSummary = me?.role === "clinician" && current && me.practitioner_id === current.id;
  const rows = data?.appointments || [];

  return (
    <WorkspaceLayout>
      <header className="row between wrap" style={{ marginBottom: 18, alignItems: "flex-end" }}>
        <div>
          <span className="eyebrow">Clinic queue</span>
          <h1 className="page-title" style={{ fontSize: 26 }}>
            {current ? current.name : "Choose a clinician"}
          </h1>
          <div className="page-sub">
            {data ? new Date(`${data.day}T12:00:00`).toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" }) : ""}
            {updatedAt ? ` · updated ${updatedAt.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}` : ""}
          </div>
        </div>
        <div className="row wrap" style={{ gap: 8 }}>
          {data && (
            <>
              <label htmlFor="queue-clinician" className="sr-only">Clinician</label>
              <select id="queue-clinician" className="vx-select" value={practitionerId || current?.id || ""}
                      onChange={(e) => setPractitionerId(e.target.value)}>
                {!current && <option value="">Choose a clinician</option>}
                {data.practitioners.map((p) => (
                  <option key={p.id} value={p.id}>{p.name} ({p.appointments} visit{p.appointments === 1 ? "" : "s"})</option>
                ))}
              </select>
              <label htmlFor="queue-day" className="sr-only">Day</label>
              <input id="queue-day" type="date" className="vx-select" value={day || data.day}
                     onChange={(e) => setDay(e.target.value)} />
            </>
          )}
          <button className="btn sm" onClick={reload} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>
        </div>
      </header>

      {error && !data && <div className="error-box">{error.message}</div>}
      {error && data && <div className="banner warn" role="status" style={{ marginBottom: 12 }}>Live updates paused: {error.message}</div>}
      {loading && !data && <div className="card"><div className="skeleton" /></div>}

      {data && current && (
        <div className="stack">
          <div className="vx-stats" role="list" aria-label="Today's numbers">
            {STAT_ORDER.map(([k, label]) => (
              <div key={k} role="listitem" className={`stat ${k === "no_show" && data.counts[k] ? "alert" : ""}`}>
                <div className="n">{data.counts[k] || 0}</div>
                <div className="tiny muted">{label}</div>
              </div>
            ))}
          </div>

          <section className="card" aria-label="Appointments">
            {rows.length === 0 ? (
              <div className="empty"><Person size={20} /> No appointments on this day.</div>
            ) : (
              <ul className="vx-queue">
                {rows.map((r) => (
                  <QueueRow key={r.id} row={r} canWriteSummary={canWriteSummary} onChanged={reload} isToday={isToday} />
                ))}
              </ul>
            )}
          </section>
          <p className="tiny muted">
            Updates every {POLL_MS / 1000} seconds. Wait times add each visit ahead of the patient at its booked length.
          </p>
        </div>
      )}
      {data && !current && <div className="card empty">Choose a clinician to see their queue.</div>}
    </WorkspaceLayout>
  );
}
