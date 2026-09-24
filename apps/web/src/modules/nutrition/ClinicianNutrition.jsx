import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { Back, Check, Warning } from "../../icons.jsx";
import { DayBars, Loading, num, shortDay } from "./charts.jsx";
import { WeightChart } from "./Weight.jsx";

const KINDS = ["weight_screen", "vital_alert"];

function ReviewItem({ item, onDone }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function act(action) {
    setBusy(true);
    setError(null);
    try {
      await api(`/weight/review-items/${item.id}/resolve`, { method: "POST", body: { action, note } });
      onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className={`queue-item ${item.priority === "urgent" ? "urgent" : ""}`}>
      <span className="strong small">{item.title}</span>
      <span className="small">{item.body}</span>
      <label className="sr-only" htmlFor={`note-${item.id}`}>Note</label>
      <textarea id={`note-${item.id}`} className="edit" placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
      {error && <div className="error-box small">{error}</div>}
      <div className="row wrap" style={{ gap: 8 }}>
        {item.kind === "weight_screen" ? (
          <>
            <button className="btn dark sm" disabled={busy} onClick={() => act("clear")}>Clear for coaching</button>
            <button className="btn sm" disabled={busy} onClick={() => act("keep_paused")}>Keep coaching paused</button>
          </>
        ) : (
          <button className="btn dark sm" disabled={busy} onClick={() => act("acknowledge")}>Acknowledge</button>
        )}
      </div>
    </div>
  );
}

function TargetRow({ patientId, t, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(t.value);
  const [reason, setReason] = useState(t.reason || "");
  const [error, setError] = useState(null);
  async function save(e) {
    e.preventDefault();
    setError(null);
    try {
      onChanged(await api(`/nutrition/patients/${patientId}/targets/${t.nutrient}`, {
        method: "PUT", body: { value: Number(value), reason: reason || null },
      }));
      setEditing(false);
    } catch (err) {
      setError(err.message);
    }
  }
  async function reset() {
    setError(null);
    try {
      onChanged(await api(`/nutrition/patients/${patientId}/targets/${t.nutrient}`, { method: "DELETE" }));
    } catch (err) {
      setError(err.message);
    }
  }
  return (
    <div className="wb-row" style={{ flexWrap: "wrap" }}>
      <div className="grow">
        <div className="strong small">{t.label}: {t.kind === "max" ? "under" : "at least"} {num(t.value, 0)} {t.unit}</div>
        <div className="tiny muted">{t.set_by === "clinician" ? `Override · ${t.reason || "no reason given"}` : t.reason || t.source}</div>
      </div>
      {!editing && (
        <div className="row" style={{ gap: 6 }}>
          <button className="btn sm" onClick={() => setEditing(true)}>Override</button>
          {t.set_by === "clinician" && <button className="btn ghost sm" onClick={reset}>Use default ({num(t.default, 0)})</button>}
        </div>
      )}
      {editing && (
        <form onSubmit={save} className="wb-inline" style={{ width: "100%" }}>
          <div className="wb-field">
            <label htmlFor={`tv-${t.nutrient}`}>Target ({t.unit})</label>
            <input id={`tv-${t.nutrient}`} type="number" min="0" step="any" required value={value} onChange={(e) => setValue(e.target.value)} />
          </div>
          <div className="wb-field" style={{ flexBasis: 220 }}>
            <label htmlFor={`tr-${t.nutrient}`}>Reason shown to the patient</label>
            <input id={`tr-${t.nutrient}`} type="text" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <button className="btn dark sm">Save</button>
          <button type="button" className="btn ghost sm" onClick={() => setEditing(false)}>Cancel</button>
        </form>
      )}
      {error && <div className="error-box small" style={{ width: "100%" }}>{error}</div>}
    </div>
  );
}

export default function ClinicianNutrition() {
  const { patientId } = useParams();
  const patients = useApi("/clinician/patients");
  const week = useApi(`/nutrition/patients/${patientId}/week`);
  const weight = useApi(`/weight/patients/${patientId}`);
  const queue = useApi("/clinician/review-queue");
  const [targets, setTargets] = useState(null);
  useEffect(() => {
    if (week.data) setTargets(week.data.targets);
  }, [week.data]);
  const name = patients.data?.find((p) => p.id === patientId)?.name;
  const items = (queue.data || []).filter((i) => i.patient_id === patientId && KINDS.includes(i.kind));

  return (
    <WorkspaceLayout>
      <div className="stack" style={{ gap: 4, marginBottom: 16 }}>
        <Link to="/clinician" className="small strong"><Back size={14} /> Workspace</Link>
        <span className="eyebrow">Nutrition & weight</span>
        <h1 className="page-title">{name || "Patient"}</h1>
        <span className="page-sub">Patient-reported food log and weigh-ins. Targets you set here replace the defaults.</span>
      </div>
      <div className="ws-grid">
        <section className="span-7 stack">
          {queue.error && <div className="error-box">{queue.error.message}</div>}
          {items.length > 0 && (
            <article className="card stack">
              <span className="card-title"><Warning size={16} /> Needs your decision</span>
              {items.map((i) => <ReviewItem key={i.id} item={i} onDone={() => { queue.reload(); weight.reload(); }} />)}
            </article>
          )}
          <article className="card stack">
            <span className="card-title">Weight</span>
            {weight.error && <div className="error-box">{weight.error.message}</div>}
            {weight.loading && !weight.data && <Loading />}
            {weight.data && (
              <>
                <div className="wb-stats">
                  <div className="wb-stat"><div className="v">{weight.data.latest ? `${num(weight.data.latest.value)} kg` : "—"}</div><div className="l">Latest</div></div>
                  <div className="wb-stat"><div className="v">{weight.data.bmi ?? "—"}</div><div className="l">BMI</div></div>
                  <div className="wb-stat"><div className="v">{weight.data.goal?.status === "active" ? `${num(weight.data.goal.target_weight_kg)} kg` : "—"}</div>
                    <div className="l">{weight.data.goal?.status === "active" ? `Goal · ${weight.data.goal.pace_kg_week} kg/wk` : "No active goal"}</div></div>
                </div>
                <WeightChart data={weight.data} />
                <p className="small muted">Eating screen: {{
                  none: "not taken", negative: "negative", cleared: "positive, cleared by the care team",
                  paused_for_review: "positive, coaching paused for your review", declined_by_care_team: "positive, coaching kept paused",
                  expired: "older than 90 days",
                }[weight.data.screening.state]}{weight.data.screening.taken_at ? ` (${shortDay(weight.data.screening.taken_at)})` : ""}.</p>
              </>
            )}
          </article>
        </section>
        <section className="span-5 stack">
          <article className="card stack">
            <span className="card-title">Daily targets</span>
            {week.error && <div className="error-box">{week.error.message}</div>}
            {!targets && week.loading && <Loading />}
            {targets && targets.map((t) => <TargetRow key={t.nutrient} patientId={patientId} t={t} onChanged={(next) => { setTargets(next); week.reload(); }} />)}
          </article>
          {week.data && (
            <article className="card stack">
              <span className="card-title">Last 7 days</span>
              <DayBars unit="mg" target={week.data.targets.find((t) => t.nutrient === "sodium_mg").value}
                       label="Sodium per day, last 7 days"
                       days={week.data.days.map((d) => ({ date: d.date, value: d.totals ? d.totals.sodium_mg : null }))} />
              {week.data.patterns.map((p) => <p key={p.nutrient} className="small">{p.text}</p>)}
              {!week.data.enough_data && <p className="small muted">Fewer than 3 days logged this week.</p>}
              {week.data.enough_data && week.data.patterns.length === 0 && <p className="small"><Check size={14} /> No patterns flagged.</p>}
            </article>
          )}
        </section>
      </div>
    </WorkspaceLayout>
  );
}
