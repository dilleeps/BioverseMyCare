import { useEffect, useRef, useState } from "react";
import { useApi } from "../../hooks.js";
import { fmtDateTime } from "../../format.js";
import { Warning } from "../../icons.jsx";
import { LineChart } from "./charts.jsx";

export const SOURCE_LABEL = { manual: "Typed", photo: "From photo", device: "Device", import: "Imported", clinic: "Clinic" };
export const CONTEXT_LABEL = { fasting: "fasting", before_meal: "before a meal", after_meal: "after a meal", bedtime: "bedtime", random: "any time" };
export const STATUS_LABEL = {
  in_range: "In range", high: "Above range", low: "Below range",
  critical_high: "Very high", critical_low: "Very low",
};

export function num(v, decimals = 0) {
  if (v == null) return "—";
  const n = Number(v);
  return decimals && !Number.isInteger(n) ? n.toFixed(decimals) : String(Math.round(n * 10) / 10);
}

export function readingValue(measure, r) {
  if (!r) return "—";
  if (measure === "bp") return `${num(r.systolic)}/${num(r.diastolic)}`;
  if (measure === "steps") return Number(r.value).toLocaleString();
  return num(r.value, measure === "temperature" || measure === "weight" || measure === "sleep" ? 1 : 0);
}

export function StatusChip({ status }) {
  if (!status) return null;
  const off = status !== "in_range";
  return (
    <span className={`chip ${off ? "warn" : "ok"}`}>
      {off && <Warning size={12} />} {STATUS_LABEL[status]}
    </span>
  );
}

export function useToast() {
  const [toast, setToast] = useState(null);
  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(null), 2800);
    return () => clearTimeout(t);
  }, [toast]);
  return [toast, setToast];
}

// Fixed safety guidance after a critical reading. The copy comes from the API and is the same every time.
export function SafetyMessage({ safety, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    if (safety && ref.current) {
      ref.current.scrollIntoView({ block: "start", behavior: "smooth" });
      ref.current.focus({ preventScroll: true });
    }
  }, [safety]);
  if (!safety) return null;
  return (
    <div ref={ref} tabIndex={-1} className="emergency stack" role="alert" style={{ gap: 12, scrollMarginTop: 80 }}>
      <div className="row" style={{ gap: 8 }}>
        <Warning size={20} />
        <strong style={{ fontSize: 18 }}>{safety.title}</strong>
      </div>
      <p>{safety.message}</p>
      <a className="call" href={`tel:${safety.call}`}>Call {safety.call}</a>
      <p className="small">Your care team has been told about this reading.</p>
      {onClose && <button className="btn" onClick={onClose}>I've read this</button>}
    </div>
  );
}

const RANGE_DAYS = [7, 30, 90];

// Chart, statistics, explanation and reading list for one measure. Used by the patient and the clinician.
export function MeasureDetail({ measure, patientId, version = 0, canDelete = false, onDelete }) {
  const [days, setDays] = useState(30);
  const q = patientId ? `&patient_id=${patientId}` : "";
  const { data, error, loading, reload } = useApi(`/vitals/measures/${measure}?days=${days}${q}`);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => { setShowAll(false); }, [measure, days]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (version) reload(); }, [version]);

  if (error) return <div className="error-box">{error.message}</div>;
  if (!data) return <div className="skeleton" style={{ height: 180 }} />;

  const s = data.stats;
  const rows = [...data.readings].reverse();
  const t = (r) => new Date(r.at).getTime();
  const flag = (r) => r.status && r.status !== "in_range";
  const outside = (v, rg) => rg && ((rg.high != null && v > rg.high) || (rg.low != null && v < rg.low));
  const series = measure === "bp"
    ? [{ key: "sys", label: "Systolic", points: rows.map((r) => ({ t: t(r), y: r.systolic, flag: outside(r.systolic, data.ranges.bp_systolic) })) },
       { key: "dia", label: "Diastolic", points: rows.map((r) => ({ t: t(r), y: r.diastolic, flag: outside(r.diastolic, data.ranges.bp_diastolic) })) }]
    : [{ key: measure, label: data.label, points: rows.map((r) => ({ t: t(r), y: Number(r.value), flag: flag(r) })) }];
  const bands = Object.entries(data.ranges)
    .filter(([code]) => code !== "glucose_fasting")
    .map(([, r]) => ({ low: r.low, high: r.high }));
  const list = showAll ? data.readings : data.readings.slice(0, 8);
  const dec = measure === "temperature" || measure === "weight" || measure === "sleep" ? 1 : 0;

  return (
    <div className="stack" style={{ gap: 14, opacity: loading ? 0.6 : 1 }}>
      <div className="row between wrap">
        <div role="group" aria-label="Time range" className="vt-seg">
          {RANGE_DAYS.map((d) => (
            <button key={d} aria-pressed={days === d} onClick={() => setDays(d)}>{d} days</button>
          ))}
        </div>
        <span className="small muted">{s.count} reading{s.count === 1 ? "" : "s"}</span>
      </div>

      {s.count === 0 ? (
        <div className="empty small">No {data.label.toLowerCase()} readings in the last {days} days.</div>
      ) : (
        <>
          <LineChart series={series} bands={bands} unit={data.unit} days={days}
                     fmtY={(v) => (measure === "steps" ? Math.round(v).toLocaleString() : num(v, dec))} />
          <dl className="vt-stats">
            <div><dt>Average</dt><dd>{s.average ?? "—"}</dd><span className="tiny muted">{data.unit}</span></div>
            {s.in_range_pct != null && (
              <div><dt>In range</dt><dd className={s.in_range_pct < 50 ? "vt-alert-text" : ""}>{s.in_range_pct}%</dd>
                <span className="tiny muted">{s.high} above · {s.low} below</span></div>
            )}
            {s.min != null && <div><dt>Lowest · highest</dt><dd>{s.min} · {s.max}</dd><span className="tiny muted">{measure === "bp" ? "systolic" : data.unit}</span></div>}
            {s.change != null && <div><dt>Change</dt><dd>{s.change > 0 ? "+" : ""}{s.change}</dd><span className="tiny muted">kg over {days} days</span></div>}
            {s.morning && (
              <div><dt>Morning · evening</dt><dd>{s.morning.average ?? "—"} · {s.evening.average ?? "—"}</dd>
                <span className="tiny muted">{s.morning.count} morning, {s.evening.count} evening</span></div>
            )}
          </dl>
        </>
      )}

      <details className="vt-explain">
        <summary className="small strong">What the ranges mean</summary>
        <p className="small" style={{ marginTop: 6 }}>{data.explanation.text}</p>
      </details>

      {data.readings.length > 0 && (
        <div>
          <h3 className="small strong" style={{ marginBottom: 4 }}>Readings</h3>
          <ul className="list vt-list vt-readings">
            {list.map((r) => (
              <li key={r.id} className="row between wrap">
                <span>
                  <span className="strong">{readingValue(measure, r)}</span>
                  <span className="small muted"> {data.unit}{r.pulse ? ` · pulse ${num(r.pulse)}` : ""}</span>
                  <br />
                  <span className="tiny muted">
                    {fmtDateTime(r.at)} · {SOURCE_LABEL[r.source] || r.source}{r.context ? ` · ${CONTEXT_LABEL[r.context]}` : ""}
                    {r.device ? ` · ${r.device}` : ""}
                  </span>
                </span>
                <span className="row" style={{ gap: 6 }}>
                  <StatusChip status={r.status} />
                  {canDelete && r.deletable && (
                    <button className="btn sm ghost" onClick={() => onDelete(r)} aria-label={`Delete reading ${readingValue(measure, r)} from ${fmtDateTime(r.at)}`}>
                      Delete
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
          {data.readings.length > 8 && (
            <button className="btn sm" style={{ marginTop: 8 }} onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Show fewer" : `Show all ${data.readings.length}`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
