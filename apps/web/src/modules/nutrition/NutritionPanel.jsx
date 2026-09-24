import { Link } from "react-router-dom";
import { useApi } from "../../hooks.js";
import { num } from "./charts.jsx";
import { WeightChart } from "./Weight.jsx";

// Clinician workspace panel: this week's food-log patterns and the weight trend.
export default function NutritionPanel({ patientId }) {
  const week = useApi(`/nutrition/patients/${patientId}/week`);
  const weight = useApi(`/weight/patients/${patientId}`);
  if (week.error) return <div className="error-box small">{week.error.message}</div>;
  if (!week.data || !weight.data) return <div className="skeleton" />;
  const w = weight.data;
  const hasAny = week.data.logged_days > 0 || w.weigh_ins.length > 0;
  return (
    <div className="stack" style={{ gap: 8 }}>
      {!hasAny && <p className="small muted">No food log or weigh-ins yet.</p>}
      {week.data.patterns.map((p) => (
        <div key={p.nutrient} className="small" style={{ padding: "8px 12px", borderRadius: 12, background: "var(--ground)" }}>{p.text}</div>
      ))}
      {week.data.logged_days > 0 && week.data.patterns.length === 0 && (
        <p className="small muted">{week.data.enough_data ? "No food-log patterns flagged this week." : "Fewer than 3 days logged this week."}</p>
      )}
      {w.latest && (
        <>
          <div className="small">
            <span className="strong">{num(w.latest.value)} kg</span>
            {w.bmi != null && <span className="muted"> · BMI {w.bmi}</span>}
            {w.goal?.status === "active" && <span className="muted"> · goal {num(w.goal.target_weight_kg)} kg, {w.goal.percent}% there</span>}
            {w.screening.state === "paused_for_review" && <span className="chip warn" style={{ marginLeft: 6 }}>Eating screen needs review</span>}
          </div>
          <WeightChart data={w} compact />
        </>
      )}
      <Link className="small strong" to={`/clinician/nutrition/${patientId}`}>Open nutrition & weight</Link>
      <span className="tiny muted">Patient-reported.</span>
    </div>
  );
}
