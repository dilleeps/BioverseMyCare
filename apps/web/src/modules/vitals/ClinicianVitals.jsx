import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { fmtDateTime, fmtShortDate } from "../../format.js";
import { Back, Warning } from "../../icons.jsx";
import { SlotStrip, Sparkline } from "./charts.jsx";
import { DeviceList } from "./Devices.jsx";
import { MeasureDetail, StatusChip, readingValue, useToast } from "./shared.jsx";

const UNIT = { "mm[Hg]": "mmHg", "/min": "beats a minute", Cel: "°C", "%": "%", "mg/dL": "mg/dL", kg: "kg" };
const THRESHOLD_FIELDS = [["critical_low", "Critical low"], ["low", "Low"], ["high", "High"], ["critical_high", "Critical high"]];

function AlertCard({ alert, onDone }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const critical = alert.severity === "critical";

  async function ack() {
    setBusy(true);
    setErr(null);
    try {
      await api(`/vitals/alerts/${alert.id}/acknowledge`, { method: "POST", body: { note: note.trim() || null } });
      await onDone("Alert acknowledged");
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  }

  return (
    <article className={`queue-item ${critical ? "urgent" : ""}`} aria-label={alert.title}>
      <div className="row between wrap">
        <strong className="row" style={{ gap: 6 }}>{critical && <Warning size={16} />} {alert.title}</strong>
        <span className={`chip ${critical ? "warn" : ""}`}>{critical ? "Critical" : "Pattern"}</span>
      </div>
      <p className="small">{alert.detail}</p>
      <span className="tiny muted">
        Raised {fmtDateTime(alert.created_at)}
        {alert.reading_count > 1 ? ` · ${alert.reading_count} readings since` : ""}
        {alert.practitioner_name ? ` · assigned to ${alert.practitioner_name}` : ""}
      </span>
      {alert.status === "open" ? (
        <>
          <label htmlFor={`ack-${alert.id}`} className="sr-only">Note (optional)</label>
          <input id={`ack-${alert.id}`} className="vt-input" placeholder="Note for the record (optional)" maxLength={1000}
                 value={note} onChange={(e) => setNote(e.target.value)} />
          {err && <div className="error-box small">{err}</div>}
          <div><button className={`btn sm ${critical ? "danger" : "dark"}`} disabled={busy} onClick={ack}>Acknowledge</button></div>
        </>
      ) : (
        <span className="tiny muted">
          Acknowledged {fmtDateTime(alert.acknowledged_at)} by {alert.acknowledged_by_name}{alert.ack_note ? ` · ${alert.ack_note}` : ""}
        </span>
      )}
    </article>
  );
}

function ThresholdRow({ t, patientId, onDone }) {
  const weight = t.code === "weight_gain_3d";
  const fields = weight ? [["high", "Kg in 3 days"]] : THRESHOLD_FIELDS;
  const [vals, setVals] = useState(() => Object.fromEntries(fields.map(([k]) => [k, t[k] ?? ""])));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const dirty = fields.some(([k]) => String(vals[k]) !== String(t[k] ?? ""));

  useEffect(() => { setVals(Object.fromEntries(fields.map(([k]) => [k, t[k] ?? ""]))); }, [t]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save(reset) {
    setBusy(true);
    setErr(null);
    try {
      const url = `/vitals/patients/${patientId}/thresholds/${t.code}`;
      if (reset) await api(url, { method: "DELETE" });
      else {
        const body = Object.fromEntries(fields.map(([k]) => [k, vals[k] === "" ? null : Number(vals[k])]));
        await api(url, { method: "PUT", body });
      }
      await onDone(reset ? "Reset to default" : "Threshold saved");
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="vt-threshold">
      <div>
        <div className="small strong">{t.display}</div>
        <div className="tiny muted">{UNIT[t.unit] || t.unit} · {t.source === "clinician" ? `set by ${t.set_by}` : "default"}</div>
      </div>
      <div className="vt-threshold-fields">
        {fields.map(([k, label]) => (
          <div key={k} className="vt-field">
            <label htmlFor={`th-${t.code}-${k}`} className="tiny strong">{label}</label>
            <input id={`th-${t.code}-${k}`} type="number" step="any" inputMode="decimal" value={vals[k]}
                   onChange={(e) => setVals({ ...vals, [k]: e.target.value })} />
          </div>
        ))}
      </div>
      <div className="row wrap" style={{ gap: 6 }}>
        <button className="btn sm dark" disabled={busy || !dirty} onClick={() => save(false)}>Save</button>
        {t.source === "clinician" && <button className="btn sm" disabled={busy} onClick={() => save(true)}>Reset</button>}
      </div>
      {err && <div className="error-box small" style={{ gridColumn: "1 / -1" }}>{err}</div>}
    </div>
  );
}

function NewPlan({ patientId, measures, onDone }) {
  const [measure, setMeasure] = useState("bp");
  const [times, setTimes] = useState(["08:00", "20:00"]);
  const [days, setDays] = useState(14);
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api(`/vitals/patients/${patientId}/plans`, {
        method: "POST",
        body: { measure, times: times.filter(Boolean), days: Number(days), instructions: instructions.trim() || null },
      });
      setInstructions("");
      await onDone("Monitoring plan started. The patient is notified and reminded at each time.");
    } catch (e2) {
      setErr(e2.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="stack vt-subform" style={{ gap: 10 }} onSubmit={submit}>
      <div className="vt-fields">
        <div className="vt-field">
          <label htmlFor="plan-measure" className="small strong">Measure</label>
          <select id="plan-measure" value={measure} onChange={(e) => setMeasure(e.target.value)}>
            {measures.filter((m) => m.plan).map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
          </select>
        </div>
        <div className="vt-field">
          <label htmlFor="plan-days" className="small strong">For how many days</label>
          <input id="plan-days" type="number" min={1} max={90} value={days} onChange={(e) => setDays(e.target.value)} />
        </div>
      </div>
      <fieldset className="vt-times">
        <legend className="small strong">Times each day (clinic time)</legend>
        {times.map((t, i) => (
          <span key={i} className="row" style={{ gap: 4 }}>
            <label htmlFor={`plan-t${i}`} className="sr-only">Time {i + 1}</label>
            <input id={`plan-t${i}`} type="time" value={t} onChange={(e) => setTimes(times.map((x, j) => (j === i ? e.target.value : x)))} />
            {times.length > 1 && (
              <button type="button" className="btn sm ghost" aria-label={`Remove time ${i + 1}`}
                      onClick={() => setTimes(times.filter((_, j) => j !== i))}>Remove</button>
            )}
          </span>
        ))}
        {times.length < 4 && <button type="button" className="btn sm" onClick={() => setTimes([...times, "12:00"])}>Add a time</button>}
      </fieldset>
      <div className="vt-field">
        <label htmlFor="plan-instr" className="small strong">Instructions for the patient</label>
        <textarea id="plan-instr" className="edit" style={{ minHeight: 64 }} maxLength={500} value={instructions}
                  onChange={(e) => setInstructions(e.target.value)} placeholder="e.g. Sit for 5 minutes first, arm supported at heart level." />
      </div>
      {err && <div className="error-box small">{err}</div>}
      <div><button className="btn primary" disabled={busy}>{busy ? "Starting…" : "Start plan"}</button></div>
    </form>
  );
}

export function ClinicianVitalsPage() {
  const { patientId } = useParams();
  const { data, error, loading, reload } = useApi(`/vitals/summary?patient_id=${patientId}`);
  const [measure, setMeasure] = useState("bp");
  const [version, setVersion] = useState(0);
  const [showPlanForm, setShowPlanForm] = useState(false);
  const [toast, setToast] = useToast();

  useEffect(() => { document.title = "Home vitals · Bioverse"; }, []);

  async function refresh(message) {
    await reload();
    setVersion((v) => v + 1);
    setShowPlanForm(false);
    if (message) setToast(message);
  }

  async function stopPlan(p) {
    if (!window.confirm(`Stop "${p.label}"? Reminders stop and the patient is told.`)) return;
    try {
      await api(`/vitals/plans/${p.id}/stop`, { method: "POST" });
      await refresh("Plan stopped");
    } catch (e) {
      setToast(e.message);
    }
  }

  const open = data?.alerts.filter((a) => a.status === "open") || [];
  const past = data?.alerts.filter((a) => a.status !== "open") || [];

  return (
    <WorkspaceLayout>
      <div className="vt-clin">
        <Link to="/clinician/vitals" className="small row" style={{ gap: 4, marginBottom: 10 }}><Back size={14} /> Home vitals</Link>
        {error && <div className="error-box">{error.message}</div>}
        {loading && !data && <div className="card"><div className="skeleton" /></div>}
        {data && (
          <>
            <div className="page-head">
              <div>
                <h1 className="page-title">{data.patient.name} · home vitals</h1>
                <p className="page-sub">Home readings, alerts, thresholds and monitoring plans. Readings are patient-generated.</p>
              </div>
            </div>

            <div className="ws-grid">
              <section className="span-7 stack">
                <article className="card stack" aria-labelledby="cv-alerts">
                  <h2 id="cv-alerts" className="card-title">Alerts</h2>
                  {open.length === 0 && <p className="small muted">No open alerts.</p>}
                  {open.map((a) => <AlertCard key={a.id} alert={a} onDone={refresh} />)}
                  {past.length > 0 && (
                    <details className="vt-explain">
                      <summary className="small strong">Acknowledged in the last 30 days ({past.length})</summary>
                      <div className="stack" style={{ gap: 8, marginTop: 8 }}>
                        {past.map((a) => <AlertCard key={a.id} alert={a} onDone={refresh} />)}
                      </div>
                    </details>
                  )}
                </article>

                <article className="card stack" aria-labelledby="cv-trend">
                  <div className="row between wrap">
                    <h2 id="cv-trend" className="card-title">Trends</h2>
                    <label htmlFor="cv-measure" className="sr-only">Measure</label>
                    <select id="cv-measure" className="vt-input" style={{ width: "auto" }} value={measure} onChange={(e) => setMeasure(e.target.value)}>
                      {data.measures.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
                    </select>
                  </div>
                  <MeasureDetail measure={measure} patientId={patientId} version={version} />
                </article>
              </section>

              <section className="span-5 stack">
                <article className="card stack" aria-labelledby="cv-plans">
                  <div className="row between wrap">
                    <h2 id="cv-plans" className="card-title">Monitoring plans</h2>
                    {!showPlanForm && <button className="btn sm dark" onClick={() => setShowPlanForm(true)}>New plan</button>}
                  </div>
                  {showPlanForm && <NewPlan patientId={patientId} measures={data.measures} onDone={refresh} />}
                  {data.plans.length === 0 && !showPlanForm && <p className="small muted">No home monitoring prescribed.</p>}
                  {data.plans.map((p) => (
                    <div key={p.id} className="stack vt-plan" style={{ gap: 6 }}>
                      <div className="row between wrap">
                        <span className="strong">{p.label}</span>
                        <span className={`chip ${p.status === "active" ? "ok" : ""}`}>{p.status}</span>
                      </div>
                      <span className="small muted">
                        {p.practitioner_name} · {p.times.join(", ")} · {fmtShortDate(p.start_on)} to {fmtShortDate(p.end_on)}
                      </span>
                      <span className="small">
                        Adherence: {p.adherence.expected ? `${p.adherence.done} of ${p.adherence.expected} readings (${p.adherence.pct}%)` : "no readings due yet"}
                      </span>
                      {p.status === "active" && <SlotStrip days={p.adherence.days} times={p.times} />}
                      {p.status === "active" && <div><button className="btn sm" onClick={() => stopPlan(p)}>Stop plan</button></div>}
                    </div>
                  ))}
                </article>

                <article className="card stack" aria-labelledby="cv-th">
                  <h2 id="cv-th" className="card-title">Alert thresholds</h2>
                  <p className="small muted">
                    Readings at or beyond a critical limit alert you and the patient at once; 3 of 5 readings outside
                    low/high in 7 days raise a pattern alert.{" "}
                    {data.thresholds.some((t) => t.source === "clinician")
                      ? `Set for this patient: ${data.thresholds.filter((t) => t.source === "clinician").map((t) => t.display).join(", ")}.`
                      : "All defaults."}
                  </p>
                  <details className="vt-explain">
                    <summary className="small strong">Edit thresholds</summary>
                    <div className="stack" style={{ gap: 8, marginTop: 8 }}>
                      {data.thresholds.map((t) => <ThresholdRow key={t.code} t={t} patientId={patientId} onDone={refresh} />)}
                    </div>
                  </details>
                </article>

                <article className="card stack" aria-labelledby="cv-dev">
                  <h2 id="cv-dev" className="card-title">Devices</h2>
                  <DeviceList devices={data.devices} editable={false} />
                </article>
              </section>
            </div>
          </>
        )}
      </div>
      {toast && <div className="toast" role="status">{toast}</div>}
    </WorkspaceLayout>
  );
}

export function ClinicianVitalsIndex() {
  const { data, error, loading } = useApi("/vitals/clinician/patients");
  useEffect(() => { document.title = "Home vitals · Bioverse"; }, []);
  return (
    <WorkspaceLayout>
      <div className="vt-clin">
        <div className="page-head">
          <div>
            <h1 className="page-title">Home vitals</h1>
            <p className="page-sub">Patients with open home-reading alerts or a monitoring plan you prescribed.</p>
          </div>
        </div>
        {error && <div className="error-box">{error.message}</div>}
        {loading && !data && <div className="card"><div className="skeleton" /></div>}
        {data?.length === 0 && <div className="card empty">No patients need attention for home vitals.</div>}
        <div className="stack">
          {data?.map((p) => (
            <Link key={p.id} to={`/clinician/vitals/${p.id}`} className="card vt-patient-row">
              <span>
                <span className="strong">{p.name}</span>
                <br />
                <span className="small muted">
                  {p.bp_14d ? `BP 14-day avg ${p.bp_14d}` : "No BP in 14 days"}
                  {p.last_reading_at ? ` · last reading ${fmtDateTime(p.last_reading_at)}` : ""}
                </span>
                {p.plans.map((pl) => (
                  <span key={pl.id} className="tiny muted" style={{ display: "block" }}>
                    {pl.label}{pl.adherence.expected ? ` · ${pl.adherence.pct}% adherence` : ""}
                  </span>
                ))}
              </span>
              <span className="row wrap" style={{ gap: 6 }}>
                {p.critical_alerts > 0 && <span className="chip warn"><Warning size={12} /> {p.critical_alerts} critical</span>}
                {p.open_alerts > 0 && <span className="chip">{p.open_alerts} open alert{p.open_alerts === 1 ? "" : "s"}</span>}
              </span>
            </Link>
          ))}
        </div>
      </div>
    </WorkspaceLayout>
  );
}

// Clinician patient view panel: latest values, mini trends, open alerts, plan adherence.
export function VitalsPanel({ patientId }) {
  const { data, error, loading } = useApi(`/vitals/summary?patient_id=${patientId}`);
  if (error) return <div className="error-box small">{error.message}</div>;
  if (loading && !data) return <div className="skeleton" />;
  const tiles = data.tiles.filter((t) => t.latest && ["bp", "heart_rate", "weight", "glucose", "spo2"].includes(t.measure));
  const open = data.alerts.filter((a) => a.status === "open");
  const plans = data.plans.filter((p) => p.status === "active");
  if (!tiles.length && !open.length && !plans.length) {
    return (
      <div className="row between wrap small">
        <span className="muted">No home readings yet.</span>
        <Link className="btn sm" to={`/clinician/vitals/${patientId}`}>Start home monitoring</Link>
      </div>
    );
  }
  return (
    <div className="stack" style={{ gap: 8 }}>
      {open.map((a) => (
        <div key={a.id} className={`row between wrap small vt-panel-row ${a.severity === "critical" ? "urgent" : ""}`}>
          <span className="row" style={{ gap: 6 }}><Warning size={14} /> {a.title}</span>
          <span className="tiny muted">{fmtShortDate(a.created_at)}</span>
        </div>
      ))}
      {tiles.map((t) => (
        <div key={t.measure} className="row between wrap small vt-panel-row">
          <span>
            <span className="strong">{t.label}</span>{" "}
            <span>{readingValue(t.measure, t.latest)} {t.unit}</span>
            <span className="muted"> · {fmtShortDate(t.latest.at)}{t.week.count ? ` · 7-day avg ${t.week.average}` : ""}</span>
          </span>
          <span className="row" style={{ gap: 6 }}>
            <Sparkline values={t.spark} width={64} height={22} alert={t.latest.status && t.latest.status !== "in_range"} />
            <StatusChip status={t.latest.status} />
          </span>
        </div>
      ))}
      {plans.map((p) => (
        <div key={p.id} className="small vt-panel-row">
          <span className="strong">{p.label}</span>
          <span className="muted"> · {p.adherence.expected ? `${p.adherence.done} of ${p.adherence.expected} readings (${p.adherence.pct}%)` : "no readings due yet"}</span>
        </div>
      ))}
      <div><Link className="btn sm dark" to={`/clinician/vitals/${patientId}`}>Open home vitals</Link></div>
    </div>
  );
}
