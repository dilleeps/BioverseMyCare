import { Link } from "react-router-dom";
import { useApi } from "../../hooks.js";

const FILL = { sent: "Sent to pharmacy", received: "Being filled", ready: "Ready for pickup", picked_up: "Picked up" };

// Clinician patient view: active medicines with fill status and patient-logged adherence.
export default function MedsPanel({ patientId }) {
  const { data, error, loading } = useApi(`/pharmacy/prescriptions?patient_id=${patientId}`);
  if (error) return <div className="error-box small">{error.message}</div>;
  if (loading && !data) return <div className="skeleton" />;
  const active = data.prescriptions.filter((p) => p.status === "active" || p.status === "on_hold");
  if (active.length === 0) return <p className="small muted">No active prescriptions.</p>;
  return (
    <div className="stack" style={{ gap: 8 }}>
      {active.map((p) => {
        const a = p.adherence;
        const low = a?.tracking && a.pct_7 != null && a.days_7 >= 3 && a.pct_7 < a.target_pct;
        return (
          <div key={p.id} className="row between wrap small" style={{ padding: "8px 12px", borderRadius: 12, background: "var(--ground)" }}>
            <span>
              <span className="strong">{p.drug_name} {p.strength}</span>
              <span className="muted"> · {p.dispense_status ? FILL[p.dispense_status] : "Not sent"} · {p.refills_remaining} refills left</span>
            </span>
            <span className="row" style={{ gap: 6 }}>
              {a?.tracking && a.pct_7 != null && (
                <span className={`chip ${low ? "warn" : "ok"}`}>{a.pct_7}% last {a.days_7} days</span>
              )}
              {p.pending_refill_id && <Link className="chip" to="/clinician/refills">Refill waiting</Link>}
            </span>
          </div>
        );
      })}
      <span className="tiny muted">Adherence is what the patient logged in Bioverse.</span>
    </div>
  );
}
