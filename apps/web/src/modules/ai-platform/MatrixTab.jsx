import { useApi } from "../../hooks.js";

const LEVEL = {
  none: ["No review", ""],
  staff: ["Clinician or delegated staff", "ok"],
  clinician: ["Clinician review", "ok"],
  clinician_edit: ["Clinician review and edit", "ok"],
  escalate: ["Immediate escalation", "warn"],
  configurable: ["Per clinician configuration", ""],
  tiered: ["Tiered by urgency", "warn"],
};

export default function MatrixTab() {
  const { data, error, loading } = useApi("/ai/review-matrix");
  if (error) return <div className="error-box">{error.message}</div>;
  if (loading && !data) return <div className="card"><div className="skeleton" /></div>;
  if (!data?.length) return <div className="card empty">The review matrix has not been loaded.</div>;
  return (
    <div className="stack" style={{ gap: 12 }}>
      <p className="small muted">
        Which AI outputs need a human before they reach a patient. These are the organization defaults from the
        governance policy; organizations may only loosen them deliberately. Read-only in this version.
      </p>
      <article className="card">
        <div className="aip-table-wrap">
          <table className="aip-table">
            <caption className="sr-only">Clinical review matrix</caption>
            <thead><tr><th scope="col">Output type</th><th scope="col">Review</th><th scope="col">Default policy</th><th scope="col">Rationale</th></tr></thead>
            <tbody>
              {data.map((r) => {
                const [label, tone] = LEVEL[r.review_level] || [r.review_level, ""];
                return (
                  <tr key={r.id}>
                    <th scope="row" className="strong">{r.output_type}</th>
                    <td><span className={`chip ${tone}`}>{label}</span></td>
                    <td>{r.default_policy}</td>
                    <td className="muted">{r.rationale}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </article>
    </div>
  );
}
