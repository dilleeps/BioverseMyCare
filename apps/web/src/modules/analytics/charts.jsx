// Small SVG chart kit: stacked/single column chart, line chart, horizontal bars, meters and KPI tiles.
// Every chart has a legend when it has two or more series, a hover and keyboard tooltip, and a table view.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import "./charts.css";

// Categorical slots in fixed order (validated palette). Colour follows the entity, never its rank.
export const SLOTS = ["var(--viz-1)", "var(--viz-2)", "var(--viz-3)", "var(--viz-4)", "var(--viz-5)", "var(--viz-6)", "var(--viz-7)", "var(--viz-8)"];
export const OTHER = "var(--viz-other)";
export const ACCENT = "var(--accent)";

// Known specialties keep the same colour everywhere; unknown ones follow alphabetically; the tail is "other".
const KNOWN = ["Cardiology", "Dermatology", "Primary care", "Neurology"];
export function specialtyColors(names) {
  const extra = names.filter((n) => !KNOWN.includes(n) && !n.startsWith("Not routed")).sort();
  const order = [...KNOWN, ...extra];
  const map = {};
  names.forEach((n) => {
    const i = order.indexOf(n);
    map[n] = n.startsWith("Not routed") || i < 0 || i >= SLOTS.length ? OTHER : SLOTS[i];
  });
  return map;
}

export function useWidth(initial = 600) {
  const ref = useRef(null);
  const [width, setWidth] = useState(initial);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    setWidth(el.clientWidth || initial);
    if (typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(240, Math.round(entry.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, [initial]);
  return [ref, width];
}

function niceMax(max) {
  if (!max || max <= 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(max)));
  const f = max / exp;
  const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return nice * exp;
}

function ticks(max, count = 4) {
  const top = niceMax(max);
  const step = top / count;
  return Array.from({ length: count + 1 }, (_, i) => +(i * step).toFixed(6));
}

const fmtTick = (v) => (v >= 1000 ? `${(v / 1000).toFixed(v % 1000 ? 1 : 0)}k` : Number.isInteger(v) ? String(v) : v.toFixed(1));

export function Legend({ items, shape = "rect" }) {
  if (!items || items.length < 2) return null;
  return (
    <ul className="viz-legend" aria-label="Legend">
      {items.map((it) => (
        <li key={it.label}>
          {shape === "line"
            ? <span className="viz-key-line" style={{ background: it.color }} aria-hidden="true" />
            : <span className="sw" style={{ background: it.color }} aria-hidden="true" />}
          {it.label}
        </li>
      ))}
    </ul>
  );
}

export function DataTable({ caption, columns, rows }) {
  return (
    <div className="viz-table-wrap">
      <table className="viz-table">
        {caption && <caption>{caption}</caption>}
        <thead>
          <tr>{columns.map((c) => <th key={c.key} scope="col" className={c.num ? "num" : undefined}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.key ?? i}>
              {columns.map((c, j) => {
                const v = c.render ? c.render(r) : r[c.key];
                return j === 0
                  ? <th key={c.key} scope="row" style={{ fontWeight: 600, textTransform: "none", letterSpacing: 0, fontSize: 13, color: "var(--ink)", background: "transparent", borderBottom: "1px solid var(--line-soft)" }}>{v}</th>
                  : <td key={c.key} className={c.num ? "num" : undefined}>{v ?? "—"}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// A card with a title, optional legend, and a Chart / Table toggle. The table is the accessible twin.
export function ChartCard({ title, subtitle, legend, table, children, actions }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <figure className="card viz">
      <div className="viz-head">
        <div>
          <h2>{title}</h2>
          {subtitle && <p className="small muted">{subtitle}</p>}
        </div>
        <div className="row" style={{ gap: 6 }}>
          {actions}
          {table && (
            <button type="button" className="btn sm" aria-pressed={asTable} onClick={() => setAsTable((v) => !v)}>
              {asTable ? "Show chart" : "Show table"}
            </button>
          )}
        </div>
      </div>
      {!asTable && legend}
      {asTable && table ? <DataTable {...table} /> : children}
    </figure>
  );
}

function Tooltip({ tip, width }) {
  if (!tip) return null;
  const left = Math.min(Math.max(tip.x - 80, 0), Math.max(width - 190, 0));
  return (
    <div className="viz-tip" style={{ left, top: Math.max(tip.y - 12, 0), transform: "translateY(-100%)" }} role="presentation">
      <div className="tip-title">{tip.title}</div>
      {tip.rows.map((r) => (
        <div key={r.label} className="tip-row">
          {r.color && <span className="viz-key-line" style={{ background: r.color }} />}
          <span className="v">{r.value}</span>
          <span className="l">{r.label}</span>
        </div>
      ))}
    </div>
  );
}

function roundedTop(x, y, w, h, r) {
  const rr = Math.min(r, h, w / 2);
  if (h <= 0) return "";
  return `M${x},${y + h} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h} Z`;
}

// Columns over time. `series` has one entry for a single-series chart (no legend needed).
export function ColumnChart({ data, series, height = 220, format = (v) => String(v), label, directLabelLast = true }) {
  const [ref, width] = useWidth();
  const [active, setActive] = useState(null);
  const [focused, setFocused] = useState(null);
  const m = { top: 16, right: 8, bottom: 30, left: 34 };
  const w = Math.max(width - m.left - m.right, 50);
  const h = height - m.top - m.bottom;
  const totals = data.map((d) => series.reduce((s, se) => s + (d.values[se.key] || 0), 0));
  const tk = ticks(Math.max(...totals, 1));
  const top = tk[tk.length - 1];
  const band = w / data.length;
  const barW = Math.min(24, band * 0.62);
  const y = (v) => h - (v / top) * h;
  const labelEvery = Math.max(1, Math.ceil(data.length / Math.max(1, Math.floor(w / 52))));

  function tipFor(i) {
    const d = data[i];
    const rows = series.length > 1
      ? [...series].reverse().map((s) => ({ label: s.label, value: format(d.values[s.key] || 0), color: s.color }))
      : [];
    return {
      x: m.left + band * i + band / 2,
      y: m.top + y(totals[i]),
      title: d.long || d.label,
      rows: series.length > 1 ? [{ label: "Total", value: format(totals[i]) }, ...rows] : [{ label: series[0].label, value: format(totals[i]), color: series[0].color }],
    };
  }

  return (
    <div className="viz-plot" ref={ref}>
      <svg width={width} height={height} role="img" aria-label={label}>
        <g transform={`translate(${m.left},${m.top})`}>
          {tk.map((t) => (
            <g key={t}>
              <line className={t === 0 ? "viz-axis" : "viz-grid"} x1={0} x2={w} y1={y(t)} y2={y(t)} />
              <text className="viz-tick" x={-8} y={y(t)} dy="0.32em" textAnchor="end">{fmtTick(t)}</text>
            </g>
          ))}
          {data.map((d, i) => {
            const x = band * i + (band - barW) / 2;
            let acc = 0;
            const drawn = series.filter((s) => (d.values[s.key] || 0) > 0);
            return (
              <g key={d.label + i} className={active !== null && active !== i ? "viz-dim" : undefined}>
                {drawn.map((s, k) => {
                  const v = d.values[s.key];
                  const y0 = y(acc);
                  acc += v;
                  const y1 = y(acc);
                  const isTop = k === drawn.length - 1;
                  const gap = k > 0 ? 2 : 0; // surface gap between stacked segments
                  const segH = Math.max(y0 - y1 - gap, 1);
                  return isTop
                    ? <path key={s.key} d={roundedTop(x, y1, barW, segH, 4)} fill={s.color} />
                    : <rect key={s.key} x={x} y={y1} width={barW} height={segH} fill={s.color} />;
                })}
                {i % labelEvery === (data.length - 1) % labelEvery && (
                  <text className="viz-tick" x={band * i + band / 2} y={h + 18} textAnchor="middle">{d.label}</text>
                )}
                {directLabelLast && i === data.length - 1 && (
                  <text className="viz-label" x={band * i + band / 2} y={y(totals[i]) - 6} textAnchor="middle">{format(totals[i])}</text>
                )}
                <rect
                  className="viz-hit" x={band * i} y={0} width={band} height={h} fill="transparent" tabIndex={0}
                  aria-label={`${d.long || d.label}: ${format(totals[i])}${series.length > 1 ? `. ${series.map((s) => `${s.label} ${format(d.values[s.key] || 0)}`).join(", ")}` : ""}`}
                  onPointerEnter={() => setActive(i)} onPointerMove={() => setActive(i)} onPointerLeave={() => setActive(null)}
                  onFocus={() => { setActive(i); setFocused(i); }} onBlur={() => { setActive(null); setFocused(null); }}
                />
                {focused === i && <rect className="viz-focus-ring" x={x - 4} y={y(totals[i]) - 4} width={barW + 8} height={Math.max(h - y(totals[i]) + 4, 8)} rx={6} pointerEvents="none" />}
              </g>
            );
          })}
        </g>
      </svg>
      <Tooltip tip={active !== null ? tipFor(active) : null} width={width} />
    </div>
  );
}

// One series over time, with a crosshair that snaps to the nearest point. `null` values leave a gap.
export function LineChart({ data, color = ACCENT, height = 200, format = (v) => String(v), label, seriesLabel, yMax }) {
  const [ref, width] = useWidth();
  const [active, setActive] = useState(null);
  const m = { top: 18, right: 40, bottom: 30, left: 34 };
  const w = Math.max(width - m.left - m.right, 50);
  const h = height - m.top - m.bottom;
  const values = data.map((d) => d.value).filter((v) => v !== null && v !== undefined);
  const tk = ticks(Math.max(yMax || 0, ...values, 1));
  const top = tk[tk.length - 1];
  const step = data.length > 1 ? w / (data.length - 1) : 0;
  const xOf = (i) => (data.length > 1 ? i * step : w / 2);
  const y = (v) => h - (v / top) * h;
  const labelEvery = Math.max(1, Math.ceil(data.length / Math.max(1, Math.floor(w / 52))));

  const segments = [];
  let cur = [];
  data.forEach((d, i) => {
    if (d.value === null || d.value === undefined) {
      if (cur.length) segments.push(cur);
      cur = [];
    } else cur.push([xOf(i), y(d.value)]);
  });
  if (cur.length) segments.push(cur);
  let lastIdx = -1;
  data.forEach((d, i) => { if (d.value !== null && d.value !== undefined) lastIdx = i; });
  const [focused, setFocused] = useState(false);

  function pick(evt) {
    const box = evt.currentTarget.getBoundingClientRect();
    const px = evt.clientX - box.left;
    setActive(Math.max(0, Math.min(data.length - 1, Math.round(px / (step || 1)))));
  }

  function onKey(evt) {
    if (evt.key === "ArrowRight") setActive((a) => Math.min(data.length - 1, (a ?? -1) + 1));
    else if (evt.key === "ArrowLeft") setActive((a) => Math.max(0, (a ?? data.length) - 1));
    else return;
    evt.preventDefault();
  }

  const tip = active !== null ? {
    x: m.left + xOf(active),
    y: m.top + (data[active].value == null ? h / 2 : y(data[active].value)),
    title: data[active].long || data[active].label,
    rows: [{ label: seriesLabel, value: data[active].value == null ? "No data" : format(data[active].value), color }],
  } : null;

  return (
    <div className="viz-plot" ref={ref}>
      <svg width={width} height={height} role="img" aria-label={label}>
        <g transform={`translate(${m.left},${m.top})`}>
          {tk.map((t) => (
            <g key={t}>
              <line className={t === 0 ? "viz-axis" : "viz-grid"} x1={0} x2={w} y1={y(t)} y2={y(t)} />
              <text className="viz-tick" x={-8} y={y(t)} dy="0.32em" textAnchor="end">{fmtTick(t)}</text>
            </g>
          ))}
          {data.map((d, i) => i % labelEvery === (data.length - 1) % labelEvery && (
            <text key={i} className="viz-tick" x={xOf(i)} y={h + 18} textAnchor="middle">{d.label}</text>
          ))}
          {active !== null && <line className="viz-crosshair" x1={xOf(active)} x2={xOf(active)} y1={0} y2={h} />}
          {segments.map((seg, k) => (
            <polyline key={k} points={seg.map((p) => p.join(",")).join(" ")} fill="none" stroke={color} strokeWidth={2}
                      strokeLinejoin="round" strokeLinecap="round" />
          ))}
          {segments.filter((s) => s.length === 1).map((s, k) => (
            <circle key={`solo${k}`} cx={s[0][0]} cy={s[0][1]} r={4} fill={color} stroke="var(--surface)" strokeWidth={2} />
          ))}
          {lastIdx >= 0 && (
            <>
              <circle cx={xOf(lastIdx)} cy={y(data[lastIdx].value)} r={4.5} fill={color} stroke="var(--surface)" strokeWidth={2} />
              <text className="viz-label" x={xOf(lastIdx) + 8} y={y(data[lastIdx].value)} dy="0.32em">{format(data[lastIdx].value)}</text>
            </>
          )}
          {active !== null && data[active].value != null && (
            <circle cx={xOf(active)} cy={y(data[active].value)} r={5} fill={color} stroke="var(--surface)" strokeWidth={2} />
          )}
          <rect
            className="viz-hit" x={-step / 2} y={0} width={w + step} height={h} fill="transparent" tabIndex={0}
            aria-label={`${label}. Use left and right arrow keys to read each point.`}
            onPointerMove={pick} onPointerDown={pick} onPointerLeave={() => setActive(null)}
            onFocus={() => { setFocused(true); setActive((a) => a ?? lastIdx); }}
            onBlur={() => { setFocused(false); setActive(null); }} onKeyDown={onKey}
          />
          {focused && <rect className="viz-focus-ring" x={-6} y={-6} width={w + 12} height={h + 12} rx={8} pointerEvents="none" />}
        </g>
      </svg>
      <Tooltip tip={tip} width={width} />
      {active !== null && (
        <span className="sr-only" aria-live="polite">{tip.title}: {tip.rows[0].value}</span>
      )}
    </div>
  );
}

// Horizontal bars with the value at the tip. One hue; rows are entities, not a ramp.
export function HBars({ rows, color = ACCENT, max, format = (v) => String(v), label }) {
  const top = max ?? Math.max(...rows.map((r) => r.value || 0), 1);
  return (
    <div className="hbars" role="list" aria-label={label}>
      {rows.map((r) => (
        <div key={r.key ?? r.label} className="hbar-row" role="listitem" tabIndex={0}
             aria-label={`${r.label}: ${r.display ?? format(r.value)}${r.sub ? `, ${r.sub}` : ""}`}>
          <span className="hbar-label" title={r.label}>
            {r.label}
            {r.sub && <span className="sub">{r.sub}</span>}
          </span>
          <span className="hbar-track" aria-hidden="true">
            <span className="hbar-fill" style={{ display: "block", width: `${Math.max(0, Math.min(100, (100 * (r.value || 0)) / top))}%`, background: color }} />
          </span>
          <span className="hbar-value">{r.display ?? format(r.value)}</span>
        </div>
      ))}
    </div>
  );
}

export function Meter({ value, max, label }) {
  const pct = max ? Math.min(100, (100 * value) / max) : 0;
  return (
    <div className={`meter ${pct >= 85 ? "high" : ""}`} role="meter" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} aria-label={label}>
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Kpi({ label, value, sub, tone }) {
  return (
    <div className={`kpi ${tone === "alert" ? "alert" : ""}`}>
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      {sub && <span className="kpi-sub">{sub}</span>}
    </div>
  );
}

// Re-render on an interval without losing the previous frame. Pauses while the tab is hidden.
export function useNow(intervalMs = 30000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}
