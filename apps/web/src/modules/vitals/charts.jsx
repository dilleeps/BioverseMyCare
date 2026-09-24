import { useEffect, useMemo, useRef, useState } from "react";

// Hand-written SVG charts for home vitals. No chart library.
// Series colours were checked for colour-blind separation against the white card surface.
export const SERIES_COLORS = ["#008775", "#5a62b8"];

const PAD = { top: 16, right: 64, bottom: 28, left: 40 };

function niceTicks(min, max, count = 4) {
  const span = max - min || 1;
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Number(v.toFixed(6)));
  return { lo, hi, ticks };
}

const dayFmt = (t) => new Date(t).toLocaleDateString([], { day: "numeric", month: "short" });
const timeFmt = (t) => new Date(t).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

// series: [{ key, label, points: [{ t, y, flag }] }]  (t = ms). bands: [{ low, high }] shaded usual range.
function useWidth(ref, fallback) {
  const [w, setW] = useState(fallback);
  useEffect(() => {
    if (ref.current?.clientWidth) setW(Math.max(240, ref.current.clientWidth));
    if (!ref.current || typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, Math.round(e.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

export function LineChart({ series, bands = [], unit, height = 220, days, fmtY = (v) => v }) {
  const svgRef = useRef(null);
  const boxRef = useRef(null);
  const W = useWidth(boxRef, 640);
  const [hover, setHover] = useState(null);
  const H = height;
  const all = series.flatMap((s) => s.points);
  const geo = useMemo(() => {
    if (!all.length) return null;
    const now = Date.now();
    const t0 = days ? now - days * 86400000 : Math.min(...all.map((p) => p.t));
    const t1 = days ? now : Math.max(...all.map((p) => p.t));
    const ys = all.map((p) => p.y).concat(bands.flatMap((b) => [b.low, b.high]).filter((v) => v != null));
    const pad = (Math.max(...ys) - Math.min(...ys)) * 0.08 || 1;
    const { lo, hi, ticks } = niceTicks(Math.min(...ys) - pad, Math.max(...ys) + pad);
    const x = (t) => PAD.left + ((t - t0) / (t1 - t0 || 1)) * (W - PAD.left - PAD.right);
    const y = (v) => PAD.top + (1 - (v - lo) / (hi - lo || 1)) * (H - PAD.top - PAD.bottom);
    return { t0, t1, x, y, ticks, lo, hi };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(series), JSON.stringify(bands), days, H, W]);

  if (!geo) return <div ref={boxRef} />;
  const { x, y, ticks, t0, t1 } = geo;
  const times = [...new Set(all.map((p) => p.t))].sort((a, b) => a - b);

  function onMove(e) {
    const px = e.clientX - svgRef.current.getBoundingClientRect().left;
    let best = null;
    for (const t of times) if (best == null || Math.abs(x(t) - px) < Math.abs(x(best) - px)) best = t;
    setHover(best);
  }

  const xTicks = [t0, t0 + (t1 - t0) / 2, t1];
  const hoverRows = hover == null ? [] : series.map((s, i) => ({ s, i, p: s.points.find((p) => p.t === hover) })).filter((r) => r.p);
  const hx = hover == null ? 0 : x(hover);

  return (
    <div className="vt-chart" ref={boxRef}>
      {series.length > 1 && (
        <div className="vt-legend" aria-hidden="true">
          {series.map((s, i) => (
            <span key={s.key}><i style={{ background: SERIES_COLORS[i] }} /> {s.label}</span>
          ))}
          {bands.length > 0 && <span><i className="band" /> Usual range</span>}
        </div>
      )}
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="img" width={W} height={H}
           aria-label={`${series.map((s) => s.label).join(" and ")} chart. The readings are also listed below.`}
           onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
        {bands.map((b, i) => b.low != null && b.high != null && (
          <rect key={i} x={PAD.left} width={W - PAD.left - PAD.right} y={y(b.high)} height={Math.max(0, y(b.low) - y(b.high))}
                className="vt-band" />
        ))}
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="vt-gridline" />
            <text x={PAD.left - 6} y={y(t) + 4} textAnchor="end" className="vt-axis">{fmtY(t)}</text>
          </g>
        ))}
        {xTicks.map((t, i) => (
          <text key={i} x={x(t)} y={H - 8} textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"} className="vt-axis">
            {dayFmt(t)}
          </text>
        ))}
        {series.map((s, i) => {
          const pts = [...s.points].sort((a, b) => a.t - b.t);
          const last = pts[pts.length - 1];
          return (
            <g key={s.key}>
              {pts.length > 1 && (
                <polyline fill="none" stroke={SERIES_COLORS[i]} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"
                          points={pts.map((p) => `${x(p.t)},${y(p.y)}`).join(" ")} />
              )}
              {pts.map((p) => p.flag && (
                <circle key={p.t} cx={x(p.t)} cy={y(p.y)} r="3.5" className="vt-flag" />
              ))}
              {pts.length <= 1 && last && <circle cx={x(last.t)} cy={y(last.y)} r="4" fill={SERIES_COLORS[i]} />}
              {last && series.length > 1 && (
                <text x={W - PAD.right + 6} y={y(last.y) + 4} className="vt-direct" fill="currentColor">{s.label}</text>
              )}
            </g>
          );
        })}
        {hover != null && (
          <g>
            <line x1={hx} x2={hx} y1={PAD.top} y2={H - PAD.bottom} className="vt-cross" />
            {hoverRows.map(({ p, i }) => (
              <circle key={i} cx={hx} cy={y(p.y)} r="4.5" fill={SERIES_COLORS[i]} stroke="#fff" strokeWidth="2" />
            ))}
          </g>
        )}
      </svg>
      {hover != null && hoverRows.length > 0 && (
        <div className="vt-tip" style={{ left: `${Math.min(80, Math.max(8, (hx / W) * 100))}%` }} role="status">
          <div className="tiny muted">{timeFmt(hover)}</div>
          {hoverRows.map(({ s, p, i }) => (
            <div key={s.key} className="row" style={{ gap: 6 }}>
              <span className="vt-key" style={{ background: SERIES_COLORS[i] }} />
              <strong>{fmtY(p.y)}{unit ? ` ${unit}` : ""}</strong>
              <span className="tiny muted">{s.label}{p.flag ? " · outside range" : ""}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// A tiny trend line for tiles and panels. Decorative: the value beside it carries the meaning.
export function Sparkline({ values, width = 96, height = 28, alert = false }) {
  const v = (values || []).filter((n) => n != null);
  if (v.length < 2) return <svg width={width} height={height} aria-hidden="true" />;
  const lo = Math.min(...v);
  const hi = Math.max(...v);
  const pts = v.map((n, i) => `${(i / (v.length - 1)) * (width - 4) + 2},${height - 3 - ((n - lo) / (hi - lo || 1)) * (height - 6)}`);
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" className="vt-spark">
      <polyline fill="none" stroke={alert ? "var(--alert)" : SERIES_COLORS[0]} strokeWidth="2" strokeLinejoin="round"
                strokeLinecap="round" points={pts.join(" ")} />
    </svg>
  );
}

function dayLabel(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
}

// Adherence strip: one column per day, one square per plan time (clinic time).
export function SlotStrip({ days, times = [] }) {
  const LABEL = { done: "logged", missed: "missed", due: "due now", upcoming: "later today" };
  return (
    <ul className="vt-slots" aria-label="Readings asked for, by day">
      {days.map((d) => (
        <li key={d.date}>
          {d.slots.map((s, i) => {
            const label = `${dayLabel(d.date)} ${times[i] || ""}: ${LABEL[s.status]}`;
            return (
              <span key={s.due} className={`vt-slot ${s.status}`} title={label}>
                <span className="sr-only">{label}</span>
              </span>
            );
          })}
        </li>
      ))}
    </ul>
  );
}
