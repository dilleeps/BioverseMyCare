import { useEffect, useMemo, useRef, useState } from "react";

// An SVG floor plan in meters. Areas are drawn largest first, so rooms sit on top of zones and desks on
// top of rooms. Zoom changes the viewBox (buttons, or drag to pan), which keeps everything sharp on phones.
// Room labels scale with the plan; the route, markers and their labels are sized in screen pixels
// (via `u`, plan units per pixel), so they stay readable and uncluttered at every zoom level.

const PAD = 2;

export const KIND_NAMES = {
  clinic: "Clinic", lab: "Lab", imaging: "Imaging", pharmacy: "Pharmacy", restroom: "Restrooms", cafe: "Cafe",
  waiting: "Waiting", desk: "Desk", elevator: "Elevator", stairs: "Stairs", escalator: "Escalator",
  entrance: "Entrance", parking: "Parking", corridor: "Corridor",
};

function polyArea(points) {
  let a = 0;
  for (let i = 0; i < points.length; i++) {
    const [x0, y0] = points[i];
    const [x1, y1] = points[(i + 1) % points.length];
    a += x0 * y1 - x1 * y0;
  }
  return Math.abs(a / 2);
}

function bounds(points) {
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
}

const pts = (polygon) => polygon.map((p) => p.join(",")).join(" ");

// Fit a label into its room: up to three lines, shrinking the text if it must.
function labelLines(text, width, height) {
  const words = text.split(/\s+/);
  for (const size of [2.0, 1.8, 1.6, 1.4, 1.25, 1.1, 1.0]) {
    const perLine = Math.max(1, Math.floor((width - 1.2) / (size * 0.56)));
    const lines = [];
    let cur = "";
    for (const w of words) {
      const next = cur ? `${cur} ${w}` : w;
      if (next.length <= perLine) cur = next;
      else {
        if (cur) lines.push(cur);
        cur = w;
      }
    }
    if (cur) lines.push(cur);
    if (lines.every((l) => l.length <= perLine) && lines.length <= 3 && lines.length * size * 1.2 <= height - 0.6) {
      return { lines, size };
    }
  }
  return null;
}

// A label pill 22 screen pixels tall, above or below a point.
function Pill({ x: px, y, text, tone, u, above, view }) {
  const size = 12 * u;
  const h = 22 * u;
  const w = text.length * size * 0.6 + 16 * u;
  const top = above ? y - h - 12 * u : y + 12 * u;
  // Keep the pill inside the visible plan.
  const x = Math.min(Math.max(px, view.x + w / 2 + 4 * u), view.x + view.w - w / 2 - 4 * u);
  return (
    <g className={`wf-pill ${tone}`} aria-hidden="true">
      <rect x={x - w / 2} y={top} width={w} height={h} rx={h / 2} style={{ strokeWidth: 1.5 * u }} />
      <text x={x} y={top + h / 2} fontSize={size} dominantBaseline="central" textAnchor="middle">{text}</text>
    </g>
  );
}

function clamp(v, full) {
  const x = Math.min(Math.max(v.x, full.x), full.x + full.w - v.w);
  const y = Math.min(Math.max(v.y, full.y), full.y + full.h - v.h);
  return { ...v, x, y };
}

export default function FloorMap({
  floor, segments = [], markers = [], start = null, end = null, closed = [], highlight = [], interactive = true,
  label, fitKey = "", whole = false,
}) {
  const W = floor.width_m;
  const H = floor.height_m;
  const full = useMemo(() => ({ x: -PAD, y: -PAD, w: W + PAD * 2, h: H + PAD * 2 }), [W, H]);
  const aspect = full.h / full.w;

  const svgRef = useRef(null);
  const [pxW, setPxW] = useState(640);
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return undefined;
    const measure = () => el.clientWidth && setPxW(el.clientWidth);
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const areas = useMemo(
    () => [...floor.areas].sort((a, b) => polyArea(b.polygon) - polyArea(a.polygon)),
    [floor.areas],
  );
  const outline = useMemo(() => bounds(floor.areas.flatMap((a) => a.polygon)), [floor.areas]);

  // What to show first: the route on this floor, never so close that fewer than ~9 px make a meter's text.
  const minW = Math.min(full.w, Math.max(36, pxW / 9));
  const focus = useMemo(() => {
    const p = [...segments.flatMap((s) => s.points), ...markers.map((m) => [m.x, m.y])];
    if (start) p.push([start.x, start.y]);
    if (end) p.push([end.x, end.y]);
    if (whole || !p.length) return full;
    const b = bounds(p);
    let w = Math.max(b.x1 - b.x0 + 24, minW);
    w = Math.max(w, (b.y1 - b.y0 + 20) / aspect);
    if (w >= full.w) return full;
    const h = w * aspect;
    return clamp({ x: (b.x0 + b.x1) / 2 - w / 2, y: (b.y0 + b.y1) / 2 - h / 2, w, h }, full);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey, floor.id, full, aspect, minW, start?.x, start?.y, whole]);

  const [view, setView] = useState(focus);
  useEffect(() => setView(focus), [focus]);
  const drag = useRef(null);
  const u = view.w / pxW;   // plan units per screen pixel

  function zoom(factor) {
    setView((v) => {
      const w = Math.min(full.w, Math.max(12, v.w * factor));
      const h = w * aspect;
      return clamp({ x: v.x + (v.w - w) / 2, y: v.y + (v.h - h) / 2, w, h }, full);
    });
  }
  function onPointerDown(e) {
    if (!interactive || view.w >= full.w - 0.01) return;
    drag.current = { x: e.clientX, y: e.clientY, view };
    e.currentTarget.setPointerCapture(e.pointerId);
  }
  function onPointerMove(e) {
    const d = drag.current;
    if (!d) return;
    const k = d.view.w / (svgRef.current?.clientWidth || pxW);
    setView(clamp({ ...d.view, x: d.view.x - (e.clientX - d.x) * k, y: d.view.y - (e.clientY - d.y) * k }, full));
  }
  function onPointerUp() {
    drag.current = null;
  }

  const zoomed = view.w < full.w - 0.01;
  const hl = new Set(highlight);
  const topRoom = view.y + 40 * u;   // too close to the top edge for a label above
  // Pills never overlap: when two points are close, the upper one's pill goes above and the lower one's below.
  const points = [start && { k: "start", ...start }, end && { k: "end", ...end },
    ...markers.map((m, i) => ({ k: `m${i}`, ...m }))].filter(Boolean);
  const above = {};
  for (const p of points) {
    const other = points.find((q) => q !== p && Math.abs(q.y - p.y) < 90 * u && Math.abs(q.x - p.x) < 220 * u);
    above[p.k] = other ? (p.y < other.y || (p.y === other.y && p.k < other.k)) : p.y > topRoom;
  }
  // A small room's own label hides under a start or end marker placed inside it.
  const covered = (a) => {
    const b = bounds(a.polygon);
    return polyArea(a.polygon) < 150
      && [start, end].some((q) => q && q.x >= b.x0 && q.x <= b.x1 && q.y >= b.y0 && q.y <= b.y1);
  };

  return (
    <div className="wf-map">
      <svg
        ref={svgRef}
        viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
        role="img"
        aria-label={label || `Plan of ${floor.name}`}
        className={zoomed ? "zoomed" : ""}
        style={{ touchAction: zoomed ? "none" : "pan-y" }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <defs>
          <pattern id="wf-hatch" width="1.2" height="1.2" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="1.2" className="wf-hatch-line" />
          </pattern>
          <pattern id="wf-bays" width="2.6" height="6" patternUnits="userSpaceOnUse">
            <line x1="0" y1="0.6" x2="0" y2="5.4" className="wf-bay-line" />
          </pattern>
        </defs>
        <rect x={outline.x0} y={outline.y0} width={outline.x1 - outline.x0} height={outline.y1 - outline.y0}
              className="wf-outline" />
        {areas.map((a) => (
          <g key={a.id}>
            <polygon points={pts(a.polygon)} className={`wf-area k-${a.kind}${hl.has(a.id) ? " hl" : ""}`} />
            {(a.kind === "stairs" || a.kind === "escalator") && <polygon points={pts(a.polygon)} fill="url(#wf-hatch)" />}
            {a.kind === "parking" && <polygon points={pts(a.polygon)} fill="url(#wf-bays)" />}
          </g>
        ))}
        {areas.map((a) => {
          const text = a.label || (a.kind === "corridor" ? null : a.name);
          if (!text || covered(a)) return null;
          const b = bounds(a.polygon);
          const fit = labelLines(text, Math.min(b.x1 - b.x0, 30), b.y1 - b.y0);
          if (!fit) return null;
          const y0 = a.label_y - ((fit.lines.length - 1) * fit.size * 1.2) / 2;
          return (
            <text key={`l${a.id}`} x={a.label_x} y={y0} fontSize={fit.size} textAnchor="middle"
                  dominantBaseline="central" className={`wf-label k-${a.kind}${hl.has(a.id) ? " hl" : ""}`}>
              {fit.lines.map((l, i) => <tspan key={i} x={a.label_x} dy={i === 0 ? 0 : fit.size * 1.2}>{l}</tspan>)}
            </text>
          );
        })}

        {closed.map((c, i) => (
          <g key={`c${i}`} className="wf-closed">
            {c.line && <line x1={c.line[0][0]} y1={c.line[0][1]} x2={c.line[1][0]} y2={c.line[1][1]}
                             style={{ strokeWidth: 4 * u, strokeDasharray: `${6 * u} ${4 * u}` }} />}
            <Cross u={u} x={c.line ? (c.line[0][0] + c.line[1][0]) / 2 : c.point[0]}
                   y={c.line ? (c.line[0][1] + c.line[1][1]) / 2 : c.point[1]} />
          </g>
        ))}

        {segments.map((s, i) => (
          <g key={`r${i}`}>
            <polyline points={pts(s.points)} className="wf-route-casing" style={{ strokeWidth: 10 * u }} />
            <polyline points={pts(s.points)} className="wf-route" style={{ strokeWidth: 5.5 * u }} />
          </g>
        ))}
        {markers.map((m, i) => (
          <g key={`m${i}`}>
            <rect x={m.x - 8 * u} y={m.y - 8 * u} width={16 * u} height={16 * u} rx={4 * u} className="wf-change"
                  style={{ strokeWidth: 2 * u }} />
            <Pill x={m.x} y={m.y} text={m.text} tone="dark" u={u} view={view} above={above[`m${i}`]} />
          </g>
        ))}
        {start && (
          <g>
            <circle cx={start.x} cy={start.y} r={8 * u} className="wf-start" style={{ strokeWidth: 2.5 * u }} />
            <Pill x={start.x} y={start.y} text={start.label} tone="dark" u={u} view={view} above={above.start} />
          </g>
        )}
        {end && (
          <g>
            <circle cx={end.x} cy={end.y} r={14 * u} className="wf-end-halo" />
            <circle cx={end.x} cy={end.y} r={7.5 * u} className="wf-end" style={{ strokeWidth: 2.5 * u }} />
            <Pill x={end.x} y={end.y} text={end.label} tone="accent" u={u} view={view} above={above.end} />
          </g>
        )}
      </svg>
      {interactive && (
        <div className="wf-zoom" role="group" aria-label="Map zoom">
          <button type="button" className="icon-btn" onClick={() => zoom(1 / 1.5)} aria-label="Zoom in">
            <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" /></svg>
          </button>
          <button type="button" className="icon-btn" onClick={() => zoom(1.5)} aria-label="Zoom out" disabled={!zoomed}>
            <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" /></svg>
          </button>
          <button type="button" className="btn sm" onClick={() => setView(zoomed ? full : focus)}
                  disabled={!zoomed && focus.w >= full.w}>
            {zoomed ? "Whole floor" : "Zoom to route"}
          </button>
          <span className="wf-scale" aria-hidden="true"><i style={{ width: `${Math.round(10 / u)}px` }} /> 10 m</span>
          {zoomed && <span className="small muted">Drag the map to move around</span>}
        </div>
      )}
    </div>
  );
}

function Cross({ x, y, u }) {
  const r = 3.5 * u;
  return (
    <g>
      <circle cx={x} cy={y} r={8 * u} className="wf-closed-dot" style={{ strokeWidth: 2 * u }} />
      <path d={`M${x - r} ${y - r} L${x + r} ${y + r} M${x + r} ${y - r} L${x - r} ${y + r}`}
            className="wf-closed-x" style={{ strokeWidth: 2 * u }} />
    </g>
  );
}
