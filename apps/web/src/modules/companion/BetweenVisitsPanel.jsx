import { Link } from "react-router-dom";
import { useApi } from "../../hooks.js";
import { fmtShortDate } from "../../format.js";
import { pct } from "./format.js";

// Clinician patient view: what happened between visits, from the patient's companion.
export default function BetweenVisitsPanel({ patientId }) {
  const { data, error, loading } = useApi(`/companion/patients/${patientId}/between-visits`);
  if (error) return <div className="error-box small">{error.message}</div>;
  if (loading && !data) return <div className="skeleton" />;
  const a = data.adherence;
  const tracked = a.medications.filter((m) => m.tracking);
  const missed7 = a.last_7.missed + a.last_7.skipped;
  const low = a.last_7.pct != null && a.last_7.pct < a.target_pct;
  const answered = data.checkins.filter((c) => c.status === "answered");
  const openEsc = data.escalations.filter((e) => e.status === "open");

  if (tracked.length === 0 && data.checkins.length === 0) {
    return <p className="small muted">Nothing from the companion yet: no tracked doses or check-ins in the last 30 days.</p>;
  }
  return (
    <div className="stack" style={{ gap: 10 }}>
      <dl className="cp-mini-stats">
        <div className={low ? "alert" : ""}><dt>Adherence, 7 days</dt><dd>{pct(a.last_7.pct)}</dd></div>
        <div><dt>30 days</dt><dd>{pct(a.last_30.pct)}</dd></div>
        <div className={missed7 ? "alert" : ""}><dt>Doses not taken, 7 days</dt><dd>{missed7}</dd></div>
        <div className={openEsc.length ? "alert" : ""}><dt>Open escalations</dt><dd>{openEsc.length}</dd></div>
      </dl>
      {tracked.map((m) => (
        <div key={m.rx_id} className="small cp-line">
          <span className="strong">{m.medication}</span>
          <span className="muted"> · took {m.last_7.taken} of {m.last_7.expected} this week
            {m.last_7.skipped ? ` · ${m.last_7.skipped} skipped` : ""}{m.last_7.missed ? ` · ${m.last_7.missed} not recorded` : ""}</span>
        </div>
      ))}
      {answered.length > 0 && (
        <ul className="stack cp-panel-list" style={{ gap: 6 }} aria-label="Check-in responses">
          {answered.slice(0, 4).map((c) => (
            <li key={c.id} className={`small cp-line ${c.response === "worse" || c.escalation ? "warn" : ""}`}>
              <span className="tiny muted">{fmtShortDate(c.answered_at)} · </span>
              {c.sentence}{c.note ? `: "${c.note}"` : "."}
            </li>
          ))}
        </ul>
      )}
      {openEsc.map((e) => (
        <div key={e.checkin_id} className={`queue-item ${e.priority === "urgent" ? "urgent" : ""}`}>
          <span className="small strong">{e.priority === "urgent" ? "Urgent: " : ""}{e.reason.charAt(0).toUpperCase() + e.reason.slice(1)}</span>
          <Link className="small" to={`/clinician/companion?patient=${patientId}`}>Review escalation</Link>
        </div>
      ))}
      <span className="tiny muted">Doses and answers are what the patient marked in Bioverse One.</span>
    </div>
  );
}
