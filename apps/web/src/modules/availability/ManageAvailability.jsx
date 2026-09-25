import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import AvailabilityEditor from "./AvailabilityEditor.jsx";
import { ErrorBox } from "./shared.jsx";

// Administrators and the front desk: every clinician in the organization, and how open their calendar is.
export function ClinicianList() {
  const { data, error, loading } = useApi("/admin/availability/practitioners");
  const [q, setQ] = useState("");
  useEffect(() => { document.title = "Clinician availability · Bioverse"; }, []);
  const rows = useMemo(() => (data || []).filter((p) =>
    `${p.name} ${p.specialty} ${p.location_name}`.toLowerCase().includes(q.trim().toLowerCase())), [data, q]);

  return (
    <WorkspaceLayout>
      <div className="av-page">
        <div className="page-head">
          <div>
            <h1 className="page-title">Clinician availability</h1>
            <p className="page-sub">Set weekly hours and time off for any clinician, so patients can book them.</p>
          </div>
        </div>
        <ErrorBox error={error} />
        {loading && !data && <div className="card"><div className="skeleton" /></div>}
        {data && (
          <section className="card stack" aria-label="Clinicians">
            <label className="av-f av-search"><span className="tiny muted">Find a clinician</span>
              <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, specialty or location" /></label>
            <ul className="av-people">
              {rows.map((p) => (
                <li key={p.id}>
                  <Link to={`/availability/${p.id}`} className="av-person">
                    <span className="stack" style={{ gap: 2, minWidth: 0 }}>
                      <span className="strong">{p.name}</span>
                      <span className="tiny muted">{p.specialty} · {p.location_name}</span>
                    </span>
                    <span className="row wrap av-person-chips">
                      {p.windows === 0
                        ? <span className="chip warn">No weekly hours</span>
                        : <span className="chip">{p.windows} window{p.windows === 1 ? "" : "s"}</span>}
                      <span className={`chip ${p.free_upcoming ? "ok" : "warn"}`}>{p.free_upcoming} free</span>
                      <span className="chip">{p.booked_upcoming} booked</span>
                    </span>
                  </Link>
                </li>
              ))}
              {rows.length === 0 && <li className="empty small">No clinician matches.</li>}
            </ul>
          </section>
        )}
      </div>
    </WorkspaceLayout>
  );
}

export function ClinicianAvailability() {
  const { practitionerId } = useParams();
  const navigate = useNavigate();
  const { data: people } = useApi("/admin/availability/practitioners");
  const me = (people || []).find((p) => p.id === practitionerId);
  useEffect(() => { document.title = `${me ? me.name : "Clinician"} · Availability · Bioverse`; }, [me]);

  return (
    <WorkspaceLayout>
      <div className="av-page">
        <div className="page-head av-head">
          <div style={{ minWidth: 0 }}>
            <Link to="/availability/clinicians" className="small">← All clinicians</Link>
            <h1 className="page-title">{me ? me.name : "Clinician availability"}</h1>
            {me && <p className="page-sub">{me.specialty} · {me.location_name}{me.has_login ? "" : " · no Bioverse sign-in"}</p>}
          </div>
          {people && (
            <label className="av-f av-pick"><span className="tiny muted">Switch clinician</span>
              <select value={practitionerId} onChange={(e) => navigate(`/availability/${e.target.value}`)}>
                {!me && <option value={practitionerId}>Choose…</option>}
                {people.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.specialty}</option>)}
              </select></label>
          )}
        </div>
        <AvailabilityEditor key={practitionerId} base={`/admin/practitioners/${practitionerId}`} />
      </div>
    </WorkspaceLayout>
  );
}
