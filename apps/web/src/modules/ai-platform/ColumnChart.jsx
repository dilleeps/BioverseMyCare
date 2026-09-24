import { useEffect, useRef, useState } from "react";

// Stacked column chart over days. Validated categorical slots (light surface #ffffff, all-pairs):
//   #12876f teal, #c98500 ochre, #4a3aa7 violet. Terracotta stays reserved for warnings.
export const SERIES_COLORS = ["#12876f", "#c98500", "#4a3aa7"];

const M = { top: 10, right: 8, bottom: 26, left: 36 };
const GAP = 2;
const MAX_BAR = 24;
const RADIUS = 4;

function useWidth(ref) {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return undefined;
    const el = ref.current;
    setWidth(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return width;
}

function niceStep(max, ticks = 4) {
  if (max <= 0) return 1;
  const raw = max / ticks;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const n = raw / pow;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return Math.max(1, step * pow);
}

// A rect with rounded top corners only: data-end rounded, square at the baseline.
function topRounded(x, y, w, h, r) {
  const rr = Math.min(r, h, w / 2);
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`;
}

function dayLabel(iso, withMonth) {
  const d = new Date(`${iso}T12:00:00`);
  return withMonth ? d.toLocaleDateString([], { day: "numeric", month: "short" }) : String(d.getDate());
}

export default function ColumnChart({ data, series, height = 200, label }) {
  const wrap = useRef(null);
  const width = useWidth(wrap);
  const [active, setActive] = useState(null);

  const totals = data.map((d) => series.reduce((s, k) => s + (Number(d[k.key]) || 0), 0));
  const step = niceStep(Math.max(0, ...totals));
  const yMax = Math.max(step, Math.ceil(Math.max(0, ...totals) / step) * step);
  const ticks = [];
  for (let v = 0; v <= yMax; v += step) ticks.push(v);

  const plotW = Math.max(0, width - M.left - M.right);
  const plotH = height - M.top - M.bottom;
  const band = data.length ? plotW / data.length : 0;
  const barW = Math.max(2, Math.min(MAX_BAR, band - GAP * 2));
  const y = (v) => M.top + plotH - (v / yMax) * plotH;
  const labelEvery = Math.max(1, Math.ceil(data.length / Math.max(1, Math.floor(plotW / 44))));

  function indexAt(clientX) {
    const rect = wrap.current.getBoundingClientRect();
    const i = Math.floor((clientX - rect.left - M.left) / band);
    return i >= 0 && i < data.length ? i : null;
  }

  function onKey(e) {
    if (!data.length) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const delta = e.key === "ArrowRight" ? 1 : -1;
      setActive((a) => Math.min(data.length - 1, Math.max(0, (a ?? (delta > 0 ? -1 : data.length)) + delta)));
    } else if (e.key === "Escape") {
      setActive(null);
    }
  }

  const tip = active != null && data[active] ? data[active] : null;
  const tipLeft = tip ? Math.min(Math.max(M.left + band * (active + 0.5), 80), Math.max(80, width - 80)) : 0;

  return (
    <div className="aip-chart">
      {series.length > 1 && (
        <ul className="aip-legend" aria-label="Legend">
          {series.map((s, i) => (
            <li key={s.key}><span className="aip-swatch" style={{ background: s.color || SERIES_COLORS[i] }} />{s.label}</li>
          ))}
        </ul>
      )}
      <div ref={wrap} className="aip-plot" style={{ height }}>
        {width > 0 && (
          <svg
            width={width}
            height={height}
            role="img"
            aria-label={`${label}. Use the left and right arrow keys to read each day; the table view lists every value.`}
            tabIndex={0}
            onKeyDown={onKey}
            onPointerMove={(e) => setActive(indexAt(e.clientX))}
            onPointerLeave={() => setActive(null)}
            onBlur={() => setActive(null)}
          >
            {ticks.map((t) => (
              <g key={t}>
                <line x1={M.left} x2={width - M.right} y1={y(t)} y2={y(t)} className={t === 0 ? "aip-axis" : "aip-gridline"} />
                <text x={M.left - 6} y={y(t)} dy="0.32em" textAnchor="end" className="aip-tick">{t.toLocaleString()}</text>
              </g>
            ))}
            {data.map((d, i) => {
              const x = M.left + band * i + (band - barW) / 2;
              let base = 0;
              const segs = [];
              const nonzero = series.map((s) => Number(d[s.key]) || 0);
              const topIndex = nonzero.reduce((acc, v, k) => (v > 0 ? k : acc), -1);
              series.forEach((s, k) => {
                const v = nonzero[k];
                if (v <= 0) return;
                const y0 = y(base);
                const y1 = y(base + v);
                const gap = base > 0 ? GAP : 0;
                const h = Math.max(0, y0 - y1 - gap);
                const color = s.color || SERIES_COLORS[k];
                segs.push(
                  k === topIndex
                    ? <path key={s.key} d={topRounded(x, y1, barW, h, RADIUS)} fill={color} />
                    : <rect key={s.key} x={x} y={y1} width={barW} height={h} fill={color} />,
                );
                base += v;
              });
              return (
                <g key={d.day} opacity={active == null || active === i ? 1 : 0.55}>
                  {segs}
                </g>
              );
            })}
            {data.map((d, i) => {
              const last = data.length - 1;
              // Label every Nth day counting back from today, so the latest day is always labelled.
              if ((last - i) % labelEvery !== 0) return null;
              return (
                <text key={d.day} x={M.left + band * (i + 0.5)} y={height - 8} textAnchor="middle" className="aip-tick">
                  {dayLabel(d.day, i < labelEvery || new Date(`${d.day}T12:00:00`).getDate() <= labelEvery)}
                </text>
              );
            })}
            {tip && <line x1={M.left + band * (active + 0.5)} x2={M.left + band * (active + 0.5)} y1={M.top} y2={M.top + plotH} className="aip-cross" />}
          </svg>
        )}
        {tip && (
          <div className="aip-tooltip" style={{ left: tipLeft }} role="status">
            <div className="tiny muted">{new Date(`${tip.day}T12:00:00`).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })}</div>
            {series.map((s, k) => (
              <div key={s.key} className="aip-tip-row">
                <span className="aip-linekey" style={{ background: s.color || SERIES_COLORS[k] }} />
                <strong>{Number(tip[s.key] || 0).toLocaleString()}</strong>
                <span className="muted">{s.label}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
