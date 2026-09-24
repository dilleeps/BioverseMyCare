import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { fmtDateTime } from "../../format.js";
import { useSession } from "../../session.jsx";

const KIND_LABEL = {
  welcome: "Welcome",
  medication_reminder: "Medication reminders",
  vital_alert: "Vital sign alerts",
  appointment_reminder: "Appointment reminders",
  companion: "Check-ins from Bioverse One",
  consultation: "Online consultations",
  order_update: "Pharmacy orders",
  challenge: "Challenges and rewards",
  vital_reminder: "Reminders to take a reading",
  results_ready: "New results",
  care_gap_nudge: "Screenings and checkups due",
  daily_brief: "Morning summary",
  weight_coach: "Weight coach check-ins",
  mind_retest: "Mood and anxiety check reminders",
  companion_escalation: "Check-in follow-ups for my patients",
  insurance_coverage_flag: "Coverage problems before visits",
  credential_expiry: "License expiry",
};

// What a patient can expect to receive, listed even before the first one arrives.
const PATIENT_KINDS = ["medication_reminder", "appointment_reminder", "vital_alert", "vital_reminder", "results_ready",
  "companion", "consultation", "order_update", "care_gap_nudge", "weight_coach", "challenge"];

function kindLabel(k) {
  return KIND_LABEL[k] || k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, " ");
}
const CHANNEL_LABEL = { in_app: "In the app", email: "Email", sms: "Text message", push: "Phone push" };

function refreshBell() {
  window.dispatchEvent(new Event("bioverse:notifications"));
}

function Inbox() {
  const { data, error, loading, reload } = useApi("/notifications?limit=100");
  const [busy, setBusy] = useState(false);

  async function open(n) {
    if (!n.read_at) {
      try { await api(`/notifications/${n.id}/read`, { method: "POST" }); } catch { /* opening still works */ }
      refreshBell();
    }
  }

  async function readAll() {
    setBusy(true);
    try { await api("/notifications/read-all", { method: "POST" }); await reload(); refreshBell(); }
    finally { setBusy(false); }
  }

  if (loading && !data) return <div className="card"><div className="skeleton" /></div>;
  if (error) return <div className="error-box">{error.message}</div>;
  return (
    <section className="card stack" aria-labelledby="inbox-h">
      <div className="row between wrap">
        <h2 id="inbox-h" className="card-title">Inbox</h2>
        {data.unread > 0 && (
          <button className="btn sm" onClick={readAll} disabled={busy}>Mark all as read</button>
        )}
      </div>
      {data.items.length === 0 ? (
        <p className="muted small">Nothing here yet. Reminders, results and messages will appear here.</p>
      ) : (
        <ul className="notif-list">
          {data.items.map((n) => {
            const inner = (
              <>
                <span className={`notif-dot ${n.read_at ? "read" : ""} ${n.priority}`} aria-hidden="true" />
                <span className="stack" style={{ gap: 2, minWidth: 0 }}>
                  <span className="strong">{n.title}{!n.read_at && <span className="sr-only"> (unread)</span>}</span>
                  {n.body && <span className="small muted">{n.body}</span>}
                  <span className="small muted">{fmtDateTime(n.due_at)}</span>
                </span>
              </>
            );
            return (
              <li key={n.id} className={n.read_at ? "" : "unread"}>
                {n.link ? (
                  <Link to={n.link} onClick={() => open(n)} className="notif-item">{inner}</Link>
                ) : (
                  <button type="button" onClick={async () => { await open(n); reload(); }} className="notif-item">{inner}</button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {data.upcoming > 0 && (
        <p className="small muted">{data.upcoming} scheduled {data.upcoming === 1 ? "reminder" : "reminders"} coming up.</p>
      )}
    </section>
  );
}

function BrowserAlerts() {
  const supported = typeof window !== "undefined" && "Notification" in window;
  const [perm, setPerm] = useState(supported ? Notification.permission : "unsupported");
  if (!supported) return null;
  return (
    <div className="toggle-row">
      <div>
        <div className="strong">Alerts on this device</div>
        <div className="small muted">
          {perm === "granted" ? "On. Important items pop up while Bioverse One is open."
            : perm === "denied" ? "Blocked in your browser settings."
            : "Show important items as a pop-up while Bioverse One is open."}
        </div>
      </div>
      {perm === "default" && (
        <button className="btn sm" onClick={async () => setPerm(await Notification.requestPermission())}>Turn on</button>
      )}
    </div>
  );
}

function Preferences() {
  const { me } = useSession();
  const { data, error, loading } = useApi("/notifications/preferences");
  const [form, setForm] = useState(null);
  const [state, setState] = useState({ saving: false, saved: false, error: null });

  useEffect(() => {
    if (data) setForm({
      email: data.email || "", phone: data.phone || "", channels: data.channels || {},
      quiet_start: data.quiet_start?.slice(0, 5) || "", quiet_end: data.quiet_end?.slice(0, 5) || "",
      timezone: data.timezone || "America/New_York",
    });
  }, [data]);

  if (loading && !form) return <div className="card"><div className="skeleton" /></div>;
  if (error) return <div className="error-box">{error.message}</div>;
  if (!form) return null;

  const kinds = Array.from(new Set([...(me?.role === "patient" ? PATIENT_KINDS : []), ...(data.known_kinds || [])]))
    .filter((k) => k !== "welcome" && k !== "test");
  const channelsFor = (k) => form.channels[k] || ["in_app"];
  function toggle(kind, ch) {
    const cur = new Set(channelsFor(kind));
    if (cur.has(ch)) cur.delete(ch); else cur.add(ch);
    cur.add("in_app");
    setForm({ ...form, channels: { ...form.channels, [kind]: Array.from(cur) } });
    setState({ saving: false, saved: false, error: null });
  }

  async function save(e) {
    e.preventDefault();
    setState({ saving: true, saved: false, error: null });
    try {
      await api("/notifications/preferences", {
        method: "PUT",
        body: { ...form, quiet_start: form.quiet_start || null, quiet_end: form.quiet_end || null,
                email: form.email || null, phone: form.phone || null },
      });
      setState({ saving: false, saved: true, error: null });
    } catch (err) {
      setState({ saving: false, saved: false, error: err.message });
    }
  }

  const set = (k) => (e) => { setForm({ ...form, [k]: e.target.value }); setState({ saving: false, saved: false, error: null }); };
  return (
    <form className="card stack" onSubmit={save} aria-labelledby="prefs-h">
      <h2 id="prefs-h" className="card-title">How to reach you</h2>
      <p className="small muted">
        Emails and texts only say that something is waiting, never health details. You sign in to read them.
      </p>
      <BrowserAlerts />
      <div className="notif-fields">
        <label className="stack" style={{ gap: 4 }}>
          <span className="small strong">Email</span>
          <input type="email" value={form.email} onChange={set("email")} autoComplete="email" />
        </label>
        <label className="stack" style={{ gap: 4 }}>
          <span className="small strong">Mobile number</span>
          <input type="tel" value={form.phone} onChange={set("phone")} placeholder="+1 555 555 0123" autoComplete="tel" />
        </label>
      </div>
      {kinds.length === 0 ? (
        <p className="small muted">Once you start receiving notifications, you can choose here how each type reaches you.</p>
      ) : (
        <fieldset className="notif-matrix">
          <legend className="small strong">What to send where</legend>
          <table>
            <thead>
              <tr><th scope="col">Type</th>{["email", "sms", "push"].map((c) => <th scope="col" key={c}>{CHANNEL_LABEL[c]}</th>)}</tr>
            </thead>
            <tbody>
              {kinds.map((k) => (
                <tr key={k}>
                  <th scope="row">{kindLabel(k)}</th>
                  {["email", "sms", "push"].map((c) => (
                    <td key={c}>
                      <input type="checkbox" checked={channelsFor(k).includes(c)} onChange={() => toggle(k, c)}
                             aria-label={`${kindLabel(k)} by ${CHANNEL_LABEL[c]}`} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </fieldset>
      )}
      <div className="notif-fields">
        <label className="stack" style={{ gap: 4 }}>
          <span className="small strong">Quiet hours from</span>
          <input type="time" value={form.quiet_start} onChange={set("quiet_start")} />
        </label>
        <label className="stack" style={{ gap: 4 }}>
          <span className="small strong">Until</span>
          <input type="time" value={form.quiet_end} onChange={set("quiet_end")} />
        </label>
      </div>
      <p className="small muted">During quiet hours only urgent alerts are sent. Everything else waits until morning.</p>
      {state.error && <div className="error-box" role="alert">{state.error}</div>}
      <div className="row">
        <button className="btn primary" disabled={state.saving}>{state.saving ? "Saving…" : "Save"}</button>
        {state.saved && <span className="small" role="status">Saved.</span>}
      </div>
    </form>
  );
}

export default function Notifications() {
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Notifications</div>
          <h1 className="page-title">What's new for you</h1>
        </div>
      </div>
      <div className="notif-grid">
        <Inbox />
        <Preferences />
      </div>
    </div>
  );
}
