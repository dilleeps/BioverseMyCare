import { Link } from "react-router-dom";
import { useApi } from "../../hooks.js";
import { PatientPage } from "../../layouts.jsx";
import { fmtDate, fmtDateTime } from "../../format.js";
import { Arrow, Calendar, Check } from "../../icons.jsx";

const STEPS = [
  ["sent", "Sent"],
  ["accepted", "Accepted"],
  ["scheduled", "Booked"],
  ["completed", "Done"],
];
const STEP_INDEX = { sent: 0, accepted: 1, scheduled: 2, completed: 3 };
const CLOSED = ["declined", "expired", "cancelled"];

function Steps({ status }) {
  const at = STEP_INDEX[status];
  if (at === undefined) return null;
  return (
    <ol className="rf-steps" aria-label="Referral progress">
      {STEPS.map(([key, label], i) => {
        const state = i < at || status === "completed" ? "done" : i === at ? "current" : "todo";
        return (
          <li key={key} className={state} aria-current={state === "current" ? "step" : undefined}>
            <span className="rf-dot">{state === "done" ? <Check size={12} /> : i + 1}</span>
            <span className="tiny">{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function ReferralCard({ r }) {
  const closed = CLOSED.includes(r.status);
  const action = r.plain.action;
  return (
    <article className={`card stack ${r.status === "accepted" ? "highlight" : ""}`} aria-labelledby={`rf-${r.id}`}>
      <div className="row between wrap" style={{ alignItems: "flex-start" }}>
        <div>
          <div id={`rf-${r.id}`} className="strong" style={{ fontSize: 17 }}>{r.target?.name || r.specialty}</div>
          <div className="small muted">
            {r.specialty} · from {r.requester.name} · {fmtDate(r.sent_at || r.created_at)}
          </div>
        </div>
        <span className={`chip ${closed ? "warn" : r.status === "completed" ? "" : "ok"}`}>{r.status_label}</span>
      </div>
      <Steps status={r.status} />
      <p className="small" style={{ color: "var(--ink-2)" }}>{r.reason}</p>
      <div className={`banner ${closed ? "warn" : r.status === "accepted" ? "ok" : "info"}`} style={{ alignItems: "flex-start" }}>
        <div className="stack" style={{ gap: 2 }}>
          <span>{r.plain.headline}</span>
          {r.plain.next_step && <span style={{ fontWeight: 500 }}>{r.plain.next_step}</span>}
        </div>
      </div>
      {r.appointment && (
        <div className="row small strong" style={{ gap: 8 }}>
          <Calendar size={16} /> {fmtDateTime(r.appointment.starts_at)} · {r.appointment.practitioner_name}
          {r.appointment.location ? ` · ${r.appointment.location}` : ""}
        </div>
      )}
      {action && (
        <Link className={`btn ${action.kind === "book" ? "primary" : ""}`} to={action.to}>
          {action.kind === "book" ? "Book" : action.label} <Arrow size={16} />
        </Link>
      )}
    </article>
  );
}

export default function Referrals() {
  const { data, error, loading } = useApi("/referrals");
  const open = (data || []).filter((r) => !CLOSED.includes(r.status) && r.status !== "completed");
  const past = (data || []).filter((r) => CLOSED.includes(r.status) || r.status === "completed");

  return (
    <PatientPage>
      <div className="stack" style={{ gap: 2, marginBottom: 16 }}>
        <span className="eyebrow">Referrals</span>
        <h1 className="page-title">Your referrals</h1>
        <span className="page-sub">When your clinician sends you to a specialist or service, you can follow it here.</span>
      </div>
      {error && <div className="error-box">{error.message}</div>}
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {data && data.length === 0 && (
        <div className="card empty">You don't have any referrals. If your clinician refers you, it will appear here.</div>
      )}
      {data && data.length > 0 && (
        <div className="stack" style={{ gap: 24 }}>
          {open.length > 0 && (
            <section className="stack" aria-labelledby="rf-open">
              <h2 id="rf-open" className="eyebrow">In progress</h2>
              {open.map((r) => <ReferralCard key={r.id} r={r} />)}
            </section>
          )}
          {past.length > 0 && (
            <section className="stack" aria-labelledby="rf-past">
              <h2 id="rf-past" className="eyebrow">Finished or closed</h2>
              {past.map((r) => <ReferralCard key={r.id} r={r} />)}
            </section>
          )}
        </div>
      )}
    </PatientPage>
  );
}
