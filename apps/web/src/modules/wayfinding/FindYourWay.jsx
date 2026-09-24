import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useApi } from "../../hooks.js";
import { useSession } from "../../session.jsx";
import { fmtDateTime } from "../../format.js";
import { Close, Pin, Warning } from "../../icons.jsx";
import FloorMap, { KIND_NAMES } from "./FloorMap.jsx";

const QUICK = [
  ["pharmacy", "Pharmacy"],
  ["nearest:restroom", "Nearest restroom"],
  ["cafe", "Cafe"],
  ["registration", "Registration"],
  ["blood-draw", "Blood draw lab"],
  ["imaging", "Imaging"],
  ["cardiology", "Heart Centre"],
  ["parking", "Parking"],
];

const norm = (s) => (s || "").toLowerCase().normalize("NFKD").replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();

function search(destinations, q) {
  const words = norm(q).split(" ").filter(Boolean);
  if (!words.length) return [];
  const scored = destinations.map((d) => {
    const hay = norm([d.name, KIND_NAMES[d.kind], d.floor_name, ...(d.keywords || [])].join(" "));
    const name = norm(d.name);
    if (!words.every((w) => hay.includes(w))) return null;
    return { d, score: words.every((w) => name.includes(w)) ? 0 : 1 };
  }).filter(Boolean);
  return scored.sort((a, b) => a.score - b.score || a.d.name.localeCompare(b.d.name)).slice(0, 8).map((s) => s.d);
}

function Steps({ route }) {
  return (
    <ol className="wf-steps" aria-label="Directions">
      {route.steps.map((s) => (
        <li key={s.n} className={`wf-step k-${s.kind}`}>
          <span className="wf-step-n" aria-hidden="true">{s.n}</span>
          <span className="wf-step-text">
            {s.text}
            {s.kind === "floor_change" && <span className="wf-step-floor">Level change</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}

function routeFloorProps(route, level, startLabel) {
  if (!route?.found) return {};
  return {
    segments: route.segments.filter((s) => s.floor_level === level),
    markers: route.markers.filter((m) => m.floor_level === level),
    start: route.from.floor_level === level ? { ...route.from, label: startLabel } : null,
    end: route.to && route.to.floor_level === level ? { ...route.to, label: route.to_label } : null,
    highlight: route.to_area && route.to_area.floor_level === level ? [route.to_area.id] : [],
    fitKey: `${route.node_ids?.join(".")}`,
  };
}

export default function FindYourWay() {
  const { me } = useSession();
  const [params, setParams] = useSearchParams();
  const building = useApi("/wayfinding/building");
  const isPatient = me?.role === "patient";
  const appt = useApi(isPatient ? "/wayfinding/my-next-appointment" : null);

  const b = building.data;
  const fromParam = (params.get("from") || "").toUpperCase();
  const to = params.get("to") || "";
  const stepFree = params.get("sf") === "1";
  const slow = params.get("slow") === "1";

  const starts = b?.starts || [];
  const fromSign = starts.find((s) => s.code === fromParam);
  const fallback = starts.find((s) => s.group === "Entrances") || starts[0];
  const from = fromSign || fallback;
  const unknownSign = Boolean(fromParam) && b && !fromSign;

  const apptDest = appt.data?.destination;
  const target = to === "appointment" ? apptDest?.area_id : to;

  const routePath = b && from && target
    ? `/wayfinding/route?from=${encodeURIComponent(from.code)}&to=${encodeURIComponent(target)}` +
      `&step_free=${stepFree}&slow=${slow}`
    : null;
  const route = useApi(routePath);
  const r = route.data;

  const [level, setLevel] = useState(null);
  useEffect(() => {
    if (r?.found) setLevel(r.from.floor_level);
    else if (from && level === null) setLevel(from.floor_level);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [r, from?.code]);

  const [query, setQuery] = useState("");
  const [picking, setPicking] = useState(false);
  const [copied, setCopied] = useState("");
  const results = useMemo(() => search(b?.destinations || [], query), [b, query]);
  const liveRef = useRef(null);

  function update(next) {
    const p = new URLSearchParams(params);
    Object.entries(next).forEach(([k, v]) => (v ? p.set(k, v) : p.delete(k)));
    setParams(p, { replace: true });
  }

  function choose(value) {
    update({ to: value });
    setQuery("");
    setPicking(false);
  }

  async function share() {
    const url = window.location.href;
    try {
      if (navigator.share) {
        await navigator.share({ title: "Directions", url });
        return;
      }
      await navigator.clipboard.writeText(url);
      setCopied("Link copied");
    } catch {
      setCopied(url);
    }
  }

  if (building.loading && !b) {
    return <main className="page"><div className="card stack"><div className="skeleton" /><div className="skeleton" /></div></main>;
  }
  if (building.error) {
    return <main className="page"><div className="error-box" role="alert">{building.error.message}</div></main>;
  }
  if (!b) return null;

  const floors = b.floors;
  const shown = floors.find((f) => f.level === (level ?? 1)) || floors[0];
  const startLabel = fromSign ? "You are here" : "Start";
  const destName = to === "appointment"
    ? (apptDest ? `Your appointment: ${apptDest.name}` : "Your next appointment")
    : to.startsWith("nearest:") ? `Nearest ${to.split(":")[1]}`
    : (b.destinations.find((d) => d.slug === to || d.id === to)?.name || r?.to_label || to);
  const parkingNote = (to === "parking" || from?.floor_level === 0) ? b.building.parking_note : null;
  const floorsOnRoute = new Set(r?.found ? r.floors : []);

  return (
    <main className="page wf-page">
      <div className="page-head wf-head">
        <div>
          <div className="eyebrow">{b.building.campus} · {b.building.name}</div>
          <h1 className="page-title">Find your way</h1>
        </div>
      </div>

      <div className="wf-layout">
        <div className="stack wf-left">
          {unknownSign && (
            <div className="banner warn" role="alert"><Warning size={16} /> We don't recognize the sign code {fromParam}. Pick where you are below.</div>
          )}
          {fromSign && fromSign.group !== "Entrances" && (
            <div className="wf-here" aria-live="polite">
              <span className="wf-here-dot" aria-hidden="true" />
              <div>
                <div className="strong">You are here</div>
                <div className="small muted">{fromSign.name}, {fromSign.floor_name} · sign {fromSign.code}</div>
              </div>
            </div>
          )}

          <section className="card stack wf-controls wf-noprint" aria-label="Plan your route">
            <div className="field">
              <label htmlFor="wf-from" className="wf-label-text">Starting from</label>
              <select id="wf-from" className="wf-select" value={from?.code || ""} onChange={(e) => update({ from: e.target.value })}>
                {["Entrances", "Parking", "Signs"].map((g) => (
                  <optgroup key={g} label={g === "Signs" ? "“You are here” signs" : g}>
                    {starts.filter((s) => s.group === g).map((s) => (
                      <option key={s.code} value={s.code}>{s.name} · {s.floor_name}</option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>

            <div className="field">
              <span className="wf-label-text" id="wf-to-label">Going to</span>
              {to && !picking ? (
                <div className="wf-chosen">
                  <Pin size={18} />
                  <span className="strong wf-grow">{destName}</span>
                  <button type="button" className="btn sm" onClick={() => setPicking(true)}>Change</button>
                </div>
              ) : (
                <div className="stack" style={{ gap: 10 }}>
                  <div className="wf-search">
                    <label htmlFor="wf-q" className="sr-only">Search for a place</label>
                    <input id="wf-q" type="search" placeholder="Search: pharmacy, x-ray, toilets…" value={query}
                           autoComplete="off" onChange={(e) => setQuery(e.target.value)}
                           onKeyDown={(e) => { if (e.key === "Enter" && results[0]) choose(results[0].slug); }} />
                    {to && <button type="button" className="icon-btn" aria-label="Cancel" onClick={() => setPicking(false)}><Close size={16} /></button>}
                  </div>
                  {query && (
                    <ul className="wf-results" aria-label="Places">
                      {results.length === 0 && <li className="small muted" style={{ padding: 8 }}>No place matches “{query}”. Try another word, or ask at the Information Desk.</li>}
                      {results.map((d) => (
                        <li key={d.id}>
                          <button type="button" className="wf-result" onClick={() => choose(d.slug)}>
                            <span className="strong">{d.name}</span>
                            <span className="small muted">{KIND_NAMES[d.kind]} · {d.floor_name}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="wf-quick" role="group" aria-labelledby="wf-to-label">
                    {isPatient && (
                      <button type="button" className="suggestion wf-appt" onClick={() => choose("appointment")}>My next appointment</button>
                    )}
                    {QUICK.map(([v, l]) => (
                      <button key={v} type="button" className="suggestion" onClick={() => choose(v)}>{l}</button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="stack" style={{ gap: 8 }}>
              <div className="toggle-row">
                <input id="wf-sf" type="checkbox" checked={stepFree} onChange={(e) => update({ sf: e.target.checked ? "1" : "" })} />
                <label htmlFor="wf-sf"><span className="strong">Step-free route</span><br /><span className="small muted">No stairs or escalators</span></label>
              </div>
              <div className="toggle-row">
                <input id="wf-slow" type="checkbox" checked={slow} onChange={(e) => update({ slow: e.target.checked ? "1" : "" })} />
                <label htmlFor="wf-slow"><span className="strong">I walk slowly</span><br /><span className="small muted">Times allow for a gentler pace</span></label>
              </div>
            </div>
          </section>

          {to === "appointment" && appt.data && (
            <div className={`banner ${apptDest ? "info" : "warn"}`}>
              {appt.data.appointment
                ? <span>{fmtDateTime(appt.data.appointment.starts_at)} · {appt.data.message}</span>
                : <span>{appt.data.message} <Link to="/care/find">Book a visit</Link></span>}
            </div>
          )}
          {parkingNote && <div className="banner info">{parkingNote}</div>}

          <section className="stack" aria-live="polite" ref={liveRef}>
            {!to && (
              <div className="card empty">Choose where you're going. Directions appear here, step by step.</div>
            )}
            {route.loading && !r && <div className="card stack"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>}
            {route.error && <div className="error-box" role="alert">{route.error.message}</div>}
            {r && !r.found && (
              <div className="card alert stack">
                <div className="card-title">No route right now</div>
                <p>{r.explanation}</p>
                {stepFree && r.explanation.includes("stairs") && (
                  <div><button type="button" className="btn" onClick={() => update({ sf: "" })}>Show the route with stairs</button></div>
                )}
              </div>
            )}
            {r?.found && (
              <div className="card stack wf-route-card">
                <div className="wf-summary">
                  <div className="wf-time">About {r.duration_min} min</div>
                  <div className="small muted">
                    {r.distance_m} m walking · {r.floors.map((lv) => floors.find((f) => f.level === lv)?.name).join(" to ")}
                  </div>
                  <div className="row wrap" style={{ gap: 6 }}>
                    {r.step_free ? <span className="chip ok">Step-free</span> : <span className="chip">Uses stairs or escalator</span>}
                    {slow && <span className="chip">Gentle pace</span>}
                  </div>
                </div>
                {r.notices.map((n, i) => (
                  <div key={i} className="banner warn" role="status"><Warning size={16} /> {n.text}</div>
                ))}
                <h2 className="wf-h2">Directions to {r.to_label}</h2>
                <Steps route={r} />
                {to === "appointment" && appt.data?.check_in_link && (
                  <Link className="btn primary block" to={appt.data.check_in_link}>I've arrived: check in</Link>
                )}
                <div className="row wrap wf-noprint" style={{ gap: 8 }}>
                  <button type="button" className="btn" onClick={() => window.print()}>Print directions</button>
                  <button type="button" className="btn" onClick={share}>Share link</button>
                  {copied && <span className="small muted wf-copied" role="status">{copied}</span>}
                </div>
              </div>
            )}
          </section>
        </div>

        <section className="card stack wf-map-card wf-noprint" aria-label="Floor map">
          <div className="wf-floors" role="tablist" aria-label="Floors">
            {floors.map((f) => (
              <button key={f.level} type="button" role="tab" aria-selected={f.level === shown.level}
                      className={`wf-floor${f.level === shown.level ? " on" : ""}${floorsOnRoute.has(f.level) ? " route" : ""}`}
                      onClick={() => setLevel(f.level)} aria-label={`${f.name}${floorsOnRoute.has(f.level) ? ", on your route" : ""}`}>
                {f.short_name}
              </button>
            ))}
            <span className="wf-floor-name">{shown.name}{floorsOnRoute.has(shown.level) ? " · on your route" : ""}</span>
          </div>
          <FloorMap
            floor={shown}
            closed={b.closed.filter((c) => c.floor_level === shown.level)}
            label={`Plan of ${shown.name}${r?.found ? `, with your route to ${r.to_label}` : ""}`}
            {...routeFloorProps(r, shown.level, startLabel)}
            {...(!r?.found && from && from.floor_level === shown.level ? { start: { x: from.x, y: from.y, label: startLabel } } : {})}
          />
          <Legend />
        </section>
      </div>

      {r?.found && (
        <section className="wf-print-maps" aria-hidden="true">
          {r.floors.map((lv) => {
            const f = floors.find((x) => x.level === lv);
            return (
              <div key={lv} className="wf-print-map">
                <div className="strong">{f.name}</div>
                <FloorMap floor={f} interactive={false} {...routeFloorProps(r, lv, startLabel)} fitKey={`print${lv}`} />
              </div>
            );
          })}
        </section>
      )}
    </main>
  );
}

function Legend() {
  return (
    <div className="wf-legend small muted" aria-hidden="true">
      <span><i className="wf-key route" /> Your route</span>
      <span><i className="wf-key start" /> Start</span>
      <span><i className="wf-key end" /> Destination</span>
      <span><i className="wf-key closed" /> Closed</span>
      <span><i className="wf-key staff" /> Staff only</span>
    </div>
  );
}
