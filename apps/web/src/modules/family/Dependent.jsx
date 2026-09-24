import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { fmtDate, fmtDateTime, fmtNumber, fmtShortDate } from "../../format.js";
import { Back, Calendar, Check, Lock, Shield } from "../../icons.jsx";

const SPECIALTIES = ["Primary care", "Cardiology", "Dermatology", "Neurology"];

function Section({ id, title, allowed, children }) {
  return (
    <section className="fm-section" aria-labelledby={id}>
      <div className="fm-head"><h2 id={id} className="fm-section-title">{title}</h2></div>
      {allowed ? children : (
        <div className="card fm-locked"><Lock size={16} /> Not shared with you.</div>
      )}
    </section>
  );
}

function Loadable({ state, empty, children }) {
  if (state.error) return <div className="error-box">{state.error.message}</div>;
  if (state.loading && !state.data) return <div className="card"><div className="skeleton" /></div>;
  if (state.data == null || (Array.isArray(state.data) && state.data.length === 0)) return <div className="card empty">{empty}</div>;
  return children(state.data);
}

function Appointments({ patientId, canView, canBook, name }) {
  const appts = useApi(canView ? `/family/dependents/${patientId}/appointments` : null);
  const [specialty, setSpecialty] = useState("Primary care");
  const [slots, setSlots] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [booked, setBooked] = useState(null);

  async function findTimes(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setSlots(await api(`/family/dependents/${patientId}/slots?specialty=${encodeURIComponent(specialty)}`));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function book(slot) {
    setBusy(true);
    setError(null);
    try {
      const a = await api(`/family/dependents/${patientId}/appointments`, { method: "POST", body: { slot_id: slot.id } });
      setBooked(a);
      setSlots(null);
      await appts.reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      {!canView && <div className="card fm-locked"><Lock size={16} /> You can book for {name}, but their appointments aren't shared with you.</div>}
      {canView && <Loadable state={appts} empty="Nothing booked.">
        {(list) => (
          <div className="card" style={{ padding: "4px 18px" }}>
            <div className="list">
              {list.map((a) => (
                <div key={a.id} style={{ padding: "12px 0" }}>
                  <div className="strong">{a.practitioner_name} · {a.specialty}</div>
                  <div className="small muted row" style={{ gap: 6 }}>
                    <Calendar size={14} /> {fmtDateTime(a.starts_at)} · {a.location_name}
                  </div>
                  {a.reason && <div className="small">{a.reason}</div>}
                </div>
              ))}
            </div>
          </div>
        )}
      </Loadable>}
      {booked && (
        <div className="banner ok" role="status"><Check size={16} /> Booked for {name}: {booked.practitioner_name}, {fmtDateTime(booked.starts_at)}.</div>
      )}
      {canBook && (
        <form className="card stack" onSubmit={findTimes} aria-label={`Book for ${name}`}>
          <div className="card-title">Book for {name}</div>
          <div className="row wrap" style={{ alignItems: "flex-end" }}>
            <div className="fm-field" style={{ flexGrow: 1 }}>
              <label htmlFor="dep-spec">Type of care</label>
              <select id="dep-spec" value={specialty} onChange={(e) => setSpecialty(e.target.value)}>
                {SPECIALTIES.map((s) => <option key={s}>{s}</option>)}
              </select>
            </div>
            <button className="btn" disabled={busy}>Find times</button>
          </div>
          {slots && slots.length === 0 && <p className="small muted">No free times in the next two weeks.</p>}
          {slots && slots.length > 0 && (
            <div className="list">
              {slots.map((s) => (
                <div key={s.id} className="row between wrap" style={{ padding: "10px 0" }}>
                  <div>
                    <div className="strong small">{fmtDateTime(s.starts_at)}</div>
                    <div className="small muted">{s.practitioner_name} · {s.location_name}</div>
                  </div>
                  <button type="button" className="btn primary sm" disabled={busy} onClick={() => book(s)}>Book</button>
                </div>
              ))}
            </div>
          )}
        </form>
      )}
      {error && <div className="error-box">{error}</div>}
    </div>
  );
}

function CarePlan({ patientId }) {
  const plan = useApi(`/family/dependents/${patientId}/care-plan`);
  return (
    <Loadable state={plan} empty="No active care plan.">
      {(p) => (
        <div className="card stack">
          <div>
            <div className="card-title">{p.title}</div>
            <div className="small muted">{p.practitioner_name}, {p.specialty} · started {fmtDate(p.started_at)}</div>
          </div>
          <div className="small strong">{p.done_count} of {p.total_count} done</div>
          <ul className="list" style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {p.tasks.map((t) => (
              <li key={t.id} className="row" style={{ padding: "10px 0", alignItems: "flex-start" }}>
                <span className={`chip ${t.status === "done" ? "ok" : t.overdue ? "warn" : ""}`} style={{ flexShrink: 0 }}>
                  {t.status === "done" ? "Done" : t.overdue ? "Overdue" : "To do"}
                </span>
                <span>
                  <span className="strong small" style={{ display: "block" }}>{t.title}</span>
                  <span className="small muted">{t.detail}{t.due_on && t.status !== "done" ? ` · by ${fmtShortDate(t.due_on)}` : ""}</span>
                </span>
              </li>
            ))}
          </ul>
          {p.hidden_medication_tasks > 0 && (
            <p className="small muted row" style={{ gap: 6 }}><Lock size={14} /> {p.hidden_medication_tasks} medicine task{p.hidden_medication_tasks === 1 ? " is" : "s are"} not shared with you.</p>
          )}
        </div>
      )}
    </Loadable>
  );
}

function Medicines({ patientId }) {
  const meds = useApi(`/family/dependents/${patientId}/medications`);
  return (
    <Loadable state={meds} empty="No medicines in the care plan.">
      {(list) => (
        <div className="card" style={{ padding: "4px 18px" }}>
          <div className="list">
            {list.map((m) => (
              <div key={m.id} style={{ padding: "12px 0" }}>
                <div className="row between">
                  <span className="strong">{m.title}</span>
                  <span className={`chip ${m.status === "done" ? "ok" : ""}`}>{m.status === "done" ? "Done" : "Current"}</span>
                </div>
                <div className="small muted">{m.detail}{m.detail ? " · " : ""}from {m.prescriber}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Loadable>
  );
}

function Results({ patientId }) {
  const results = useApi(`/family/dependents/${patientId}/results`);
  return (
    <Loadable state={results} empty="No results yet.">
      {(list) => (
        <div className="stack">
          {list.map((r) => (
            <article key={r.id} className="card stack" style={{ gap: 8 }}>
              <div className="row between wrap">
                <div>
                  <div className="card-title">{r.name}</div>
                  <div className="small muted">{r.lab_name} · {fmtDate(r.collected_at)}</div>
                </div>
                <span className={`chip ${r.status === "reviewed" ? "ok" : ""}`}>
                  {r.status === "reviewed" ? "Reviewed by a clinician" : "Awaiting clinician review"}
                </span>
              </div>
              {r.status === "reviewed" ? (
                <>
                  <p className="small">{r.explanation}</p>
                  <div>
                    {r.observations.map((o) => (
                      <div key={o.display} className="fm-obs">
                        <span>{o.display}</span>
                        <span className={`v ${o.interpretation !== "N" ? "abn" : ""}`}>
                          {fmtNumber(o.value)} {o.unit}{o.interpretation === "H" ? " · high" : o.interpretation === "L" ? " · low" : ""}
                        </span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <p className="small muted">Results are shared here once a clinician has reviewed them.</p>
              )}
            </article>
          ))}
        </div>
      )}
    </Loadable>
  );
}

export default function Dependent() {
  const { patientId } = useParams();
  const { data, error, loading } = useApi(`/family/dependents/${patientId}`);
  const can = (p) => data?.permissions.includes(p);

  return (
    <main className="column">
      <Link to="/family" className="btn ghost sm" style={{ paddingLeft: 0 }}><Back size={16} /> Family & caregivers</Link>
      {error && <div className="error-box" style={{ marginTop: 12 }}>{error.status === 403 ? "You don't have access to this person's care." : error.message}</div>}
      {loading && !data && <div className="card" style={{ marginTop: 12 }}><div className="skeleton" /></div>}
      {data && (
        <>
          <div className="stack" style={{ gap: 2, marginTop: 8 }}>
            <span className="eyebrow">Caring for</span>
            <h1 className="page-title">{data.name}</h1>
            <span className="page-sub">{data.age}{data.pronouns ? ` · ${data.pronouns}` : ""}{data.expires_at ? ` · access until ${fmtDate(data.expires_at)}` : ""}</span>
          </div>
          <div className="fm-readonly" style={{ marginTop: 14 }} role="note">
            <Shield size={16} /> You're viewing {data.name.split(" ")[0]}'s care{data.proxy ? " as their full proxy" : ""}. It's read-only, and every view is recorded.
          </div>
          {data.results_need_own_consent && (
            <p className="small muted" style={{ marginTop: 10 }}>
              <Lock size={12} /> Results for 13 to 17 year olds are only shared when they choose to share them.
            </p>
          )}
          <Section id="dep-appts" title="Appointments" allowed={can("view_appointments") || can("book_appointments")}>
            <Appointments patientId={patientId} canView={can("view_appointments")} canBook={can("book_appointments")}
                          name={data.name.split(" ")[0]} />
          </Section>
          <Section id="dep-plan" title="Care plan" allowed={can("view_care_plan")}>
            <CarePlan patientId={patientId} />
          </Section>
          <Section id="dep-meds" title="Medicines" allowed={can("view_medications")}>
            <Medicines patientId={patientId} />
          </Section>
          <Section id="dep-results" title="Results" allowed={can("view_results")}>
            <Results patientId={patientId} />
          </Section>
        </>
      )}
    </main>
  );
}
