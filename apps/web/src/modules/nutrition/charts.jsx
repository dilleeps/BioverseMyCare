import { useState } from "react";

// Small SVG charts shared by the wellbeing modules. No chart library. Every chart has a text alternative
// (aria-label plus an optional "Show as a table"), and the layout scales to its container.

export function localDay(iso) {
  const s = String(iso);
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) {
    const [y, m, d] = s.split("-").map(Number);
    return new Date(y, m - 1, d);
  }
  return new Date(s);
}
export const shortDay = (iso) => localDay(iso).toLocaleDateString([], { day: "numeric", month: "short" });
export const weekdayShort = (iso) => localDay(iso).toLocaleDateString([], { weekday: "short" });
export const num = (v, digits = 1) =>
  v == null ? "—" : Number(v).toLocaleString([], { maximumFractionDigits: digits });

// Tooltips near an edge anchor to that edge so they never spill outside the card.
function tipStyle(fx, fy) {
  const tx = fx < 0.2 ? "0" : fx > 0.8 ? "-100%" : "-50%";
  return { left: `${fx * 100}%`, top: `${fy * 100}%`, transform: `translate(${tx}, calc(-100% - 8px))` };
}

function niceRange(values, pad = 0.1) {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || Math.max(1, Math.abs(hi) * 0.1);
  return [lo - span * pad, hi + span * pad];
}

// Line chart over time. series: [{ id, label, points: [{ at, value }], dots, dashed, strong }]
// refs: horizontal reference lines [{ value, label }]
export function LineChart({ series, refs = [], label, unit = "", yDomain, height = 180, formatValue = (v) => num(v) }) {
  const [active, setActive] = useState(null);
  const all = series.flatMap((s) => s.points);
  if (all.length === 0) return null;
  const W = 340, H = height, left = 34, right = 10, top = 16, bottom = 24;
  const times = all.map((p) => localDay(p.at).getTime());
  let t0 = Math.min(...times), t1 = Math.max(...times);
  if (t0 === t1) { t0 -= 86400000 * 3; t1 += 86400000 * 3; }
  const [y0, y1] = yDomain || niceRange([...all.map((p) => p.value), ...refs.map((r) => r.value)]);
  const x = (at) => left + ((localDay(at).getTime() - t0) / (t1 - t0)) * (W - left - right);
  const y = (v) => top + (1 - (v - y0) / (y1 - y0)) * (H - top - bottom);
  const ticks = yDomain ? [Math.ceil(y0), Math.round((y0 + y1) / 2), Math.floor(y1)]
    : [y0 + (y1 - y0) * 0.1, (y0 + y1) / 2, y1 - (y1 - y0) * 0.1];
  const primary = series.find((s) => s.dots) || series[0];

  return (
    <div className="wb-chart">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={label}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={left} x2={W - right} y1={y(t)} y2={y(t)} stroke="var(--line-soft)" />
            <text x={left - 6} y={y(t) + 4} fontSize="10" textAnchor="end" fill="var(--muted)">{formatValue(t)}</text>
          </g>
        ))}
        {refs.map((r) => (
          <g key={r.label}>
            <line x1={left} x2={W - right} y1={y(r.value)} y2={y(r.value)} stroke="var(--muted)" strokeDasharray="4 4" />
            <text x={W - right} y={y(r.value) - 5} fontSize="10" textAnchor="end" fontWeight="600" fill="var(--muted)">{r.label}</text>
          </g>
        ))}
        {series.map((s) => (
          <g key={s.id}>
            {s.points.length > 1 && (
              <polyline fill="none" stroke={s.strong ? "var(--accent)" : "var(--faint)"} strokeWidth={s.strong ? 2.5 : 1.5}
                        strokeDasharray={s.dashed ? "5 4" : undefined} strokeLinejoin="round" strokeLinecap="round"
                        points={s.points.map((p) => `${x(p.at)},${y(p.value)}`).join(" ")} />
            )}
            {s.dots && s.points.map((p, i) => (
              <circle key={i} cx={x(p.at)} cy={y(p.value)} r={active === i ? 5 : 3.5}
                      fill={p.alert ? "var(--alert)" : "var(--accent)"} stroke="var(--surface)" strokeWidth="1.5" />
            ))}
          </g>
        ))}
        <text x={left} y={H - 6} fontSize="10" fill="var(--muted)">{shortDay(new Date(t0).toISOString())}</text>
        <text x={W - right} y={H - 6} fontSize="10" textAnchor="end" fill="var(--muted)">{shortDay(new Date(t1).toISOString())}</text>
        {primary.points.map((p, i) => (
          <circle key={`hit-${i}`} className="hit" cx={x(p.at)} cy={y(p.value)} r="12" tabIndex={0}
                  aria-label={`${shortDay(p.at)}: ${formatValue(p.value)} ${unit}`}
                  onPointerEnter={() => setActive(i)} onPointerLeave={() => setActive(null)}
                  onFocus={() => setActive(i)} onBlur={() => setActive(null)} />
        ))}
      </svg>
      {active != null && primary.points[active] && (
        <div className="wb-tip" aria-hidden="true"
             style={tipStyle(x(primary.points[active].at) / W, y(primary.points[active].value) / H)}>
          <strong>{formatValue(primary.points[active].value)} {unit}</strong>
          {primary.points[active].note || shortDay(primary.points[active].at)}
        </div>
      )}
    </div>
  );
}

// Bars per day against one reference line. days: [{ date, value }], higherIsWorse colors bars over the line.
export function DayBars({ days, target, label, unit, higherIsWorse = true, formatValue = (v) => num(v, 0) }) {
  const [active, setActive] = useState(null);
  const W = 340, H = 150, base = 120, top = 18;
  const max = Math.max(target || 0, ...days.map((d) => d.value || 0), 1) * 1.1;
  const y = (v) => base - ((base - top) * v) / max;
  const slot = W / days.length;
  const bw = Math.min(26, slot * 0.55);
  const bad = (v) => v != null && target != null && (higherIsWorse ? v > target : v < target);
  const tip = active != null ? days[active] : null;
  return (
    <div className="wb-chart">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={label}>
        <line x1="0" x2={W} y1={base} y2={base} stroke="var(--line)" />
        {target != null && (
          <>
            <line x1="0" x2={W} y1={y(target)} y2={y(target)} stroke="var(--muted)" strokeDasharray="4 4" />
            <text x="0" y="11" fontSize="10" fontWeight="600" fill="var(--muted)">Line: target {formatValue(target)} {unit}</text>
          </>
        )}
        {days.map((d, i) => {
          const bx = i * slot + (slot - bw) / 2;
          const v = d.value;
          return (
            <g key={d.date}>
              {v != null && v > 0
                ? <rect x={bx} y={y(v)} width={bw} height={base - y(v)} rx="4"
                        fill={bad(v) ? "var(--alert)" : "var(--accent)"} opacity={active === i ? 0.8 : 1} />
                : <line x1={bx + 4} x2={bx + bw - 4} y1={base - 1} y2={base - 1} stroke="var(--faint)" strokeWidth="2" strokeLinecap="round" />}
              <text x={bx + bw / 2} y={base + 15} fontSize="10" textAnchor="middle" fill="var(--muted)">{weekdayShort(d.date)}</text>
              <rect className="hit" x={i * slot} y="0" width={slot} height={H} tabIndex={0}
                    aria-label={`${shortDay(d.date)}: ${v == null ? "nothing logged" : `${formatValue(v)} ${unit}`}`}
                    onPointerEnter={() => setActive(i)} onPointerLeave={() => setActive(null)}
                    onFocus={() => setActive(i)} onBlur={() => setActive(null)} />
            </g>
          );
        })}
      </svg>
      {tip && (
        <div className="wb-tip" aria-hidden="true" style={tipStyle((active + 0.5) / days.length, 0.3)}>
          <strong>{tip.value == null ? "Nothing logged" : `${formatValue(tip.value)} ${unit}`}</strong>
          {shortDay(tip.date)}
        </div>
      )}
    </div>
  );
}

export function DataTable({ caption, columns, rows }) {
  return (
    <details className="wb-table-wrap">
      <summary>Show as a table</summary>
      <table className="wb-table">
        <caption className="sr-only">{caption}</caption>
        <thead><tr>{columns.map((c) => <th key={c} scope="col">{c}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
      </table>
    </details>
  );
}

export function Meter({ value, max, label, alert = false }) {
  const pct = Math.max(0, Math.min(100, (100 * value) / (max || 1)));
  return (
    <div className={`wb-meter ${alert ? "alert" : ""}`} role="meter" aria-valuemin={0} aria-valuemax={max}
         aria-valuenow={Math.round(value)} aria-label={label}>
      <div style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Loading() {
  return <div className="card"><div className="skeleton" /><div className="skeleton" style={{ marginTop: 10, width: "60%" }} /></div>;
}
