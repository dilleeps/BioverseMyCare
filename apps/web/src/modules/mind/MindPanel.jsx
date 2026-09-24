import { Link } from "react-router-dom";
import { useApi } from "../../hooks.js";
import { Warning } from "../../icons.jsx";
import { shortDay } from "../nutrition/charts.jsx";
import { ScoreTrend } from "./Mind.jsx";

// Clinician workspace panel: latest PHQ-9 and GAD-7 with their trend, and anything waiting for follow-up.
export default function MindPanel({ patientId }) {
  const { data, error, loading } = useApi(`/mind/patients/${patientId}/results`);
  if (error) return <div className="error-box small">{error.message}</div>;
  if (loading && !data) return <div className="skeleton" />;
  const entries = Object.values(data.instruments).filter((e) => e.latest);
  const urgent = data.open_items.filter((i) => i.priority === "urgent");
  return (
    <div className="stack" style={{ gap: 8 }}>
      {urgent.length > 0 && (
        <Link to={`/clinician/mind/${patientId}`} className="queue-item urgent small strong" style={{ color: "var(--alert-strong)", textDecoration: "none" }}>
          <span><Warning size={14} /> {urgent[0].title}</span>
        </Link>
      )}
      {entries.length === 0 && <p className="small muted">No mood or anxiety check-ins yet.</p>}
      {entries.map((e) => (
        <div key={e.title} className="stack" style={{ gap: 4 }}>
          <div className="small">
            <span className="strong">{e.title} {e.latest.total}/{e.max}</span>
            <span className="muted"> · {e.latest.severity_label.toLowerCase()} · {shortDay(e.latest.at)}</span>
            {e.history.length > 1 && <span className="muted"> · previous {e.history[e.history.length - 2].total}</span>}
          </div>
          <ScoreTrend entry={e} compact />
        </div>
      ))}
      <Link className="small strong" to={`/clinician/mind/${patientId}`}>
        Open mood & anxiety{data.open_items.length ? ` · ${data.open_items.length} to follow up` : ""}
      </Link>
      <span className="tiny muted">Patient-completed screening questionnaires.</span>
    </div>
  );
}
