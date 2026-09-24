import { Link } from "react-router-dom";
import { useApi } from "../../hooks.js";
import { fmtShortDate } from "../../format.js";
import { MODE_LABEL, StatusChip } from "./shared.jsx";

// Clinician patient view: this patient's online consults, newest and open first.
export default function ConsultsPanel({ patientId }) {
  const { data, error, loading } = useApi(`/consultations?patient_id=${patientId}`);
  if (error) return <div className="error-box small">{error.message}</div>;
  if (loading && !data) return <div className="skeleton" />;
  if (!data.length) return <p className="small muted">No online consults.</p>;
  return (
    <div className="stack" style={{ gap: 8 }}>
      {data.slice(0, 5).map((c) => {
        const head = (
          <span className="strong">{c.specialty} · {MODE_LABEL[c.mode]}</span>
        );
        return (
          <div key={c.id} className="consult-panel-row small">
            <div className="row between wrap" style={{ gap: 6 }}>
              {c.can_open ? <Link to={`/clinician/consults/${c.id}`}>{head}</Link> : head}
              <StatusChip status={c.status} label={c.status_label} />
            </div>
            <span className="muted">
              {c.practitioner?.name || "Unclaimed"} · {fmtShortDate(c.scheduled_at || c.completed_at || c.created_at)}
            </span>
            {c.flagged && <span className="alert-note">Red flag raised during this consult</span>}
            {c.summary && <span>{c.summary.length > 160 ? `${c.summary.slice(0, 157)}...` : c.summary}</span>}
          </div>
        );
      })}
    </div>
  );
}
