import { Link } from "react-router-dom";
import { useApi } from "../../hooks.js";
import { Chevron } from "../../icons.jsx";
import { ExternalLink, SourceChips } from "./shared.jsx";

// Workspace panel in the patient brief: library evidence matched to this patient's abnormal
// results and medicines. Rules only, so it is instant and never sends patient data anywhere.
export default function EvidencePanel({ patientId }) {
  const { data, error, loading } = useApi(`/evidence/patients/${patientId}/suggestions`);
  const askLink = `/clinician/evidence?patient=${encodeURIComponent(patientId)}`;

  if (error) return <div className="error-box small">{error.message}</div>;
  if (loading || !data) return <div className="skeleton" />;

  return (
    <div className="stack" style={{ gap: 10 }}>
      {data.items.length === 0 ? (
        <p className="small muted">No abnormal results or active medicines to match evidence to yet.</p>
      ) : (
        <>
          <p className="tiny muted">Matched to: {data.based_on.join("; ")}</p>
          <ul className="list ev-panel">
            {data.items.map((item) => (
              <li key={item.item_id} className="stack" style={{ gap: 4 }}>
                <ExternalLink href={item.url} className="strong small ev-title">{item.title}</ExternalLink>
                <span className="small ev-snippet">{item.snippet}</span>
                <span className="tiny muted">{item.publisher} · {item.reason}</span>
                <SourceChips source={item} />
              </li>
            ))}
          </ul>
        </>
      )}
      <div>
        <Link className="btn sm" to={askLink}>Ask about this patient <Chevron size={14} /></Link>
      </div>
    </div>
  );
}
