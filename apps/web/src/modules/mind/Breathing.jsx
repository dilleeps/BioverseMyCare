import { useEffect, useRef, useState } from "react";

const PHASES = ["Breathe in", "Hold", "Breathe out", "Hold"];
const SECONDS = 4;
const LENGTHS = [
  { id: 1, label: "1 minute", cycles: 4 },
  { id: 2, label: "2 minutes", cycles: 8 },
  { id: 4, label: "4 minutes", cycles: 16 },
];

// Box breathing: in 4, hold 4, out 4, hold 4. The phase is announced to screen readers once per phase;
// the square only moves when the person hasn't asked for reduced motion (see styles.css).
export default function Breathing() {
  const [length, setLength] = useState(LENGTHS[0]);
  const [running, setRunning] = useState(false);
  const [tick, setTick] = useState(0); // seconds elapsed
  const timer = useRef(null);

  const total = length.cycles * PHASES.length * SECONDS;
  const phase = Math.floor(tick / SECONDS) % PHASES.length;
  const count = SECONDS - (tick % SECONDS);
  const done = tick >= total;

  useEffect(() => {
    if (!running) return undefined;
    timer.current = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(timer.current);
  }, [running]);

  useEffect(() => {
    if (done && running) setRunning(false);
  }, [done, running]);

  function start() {
    setTick(0);
    setRunning(true);
  }

  const expanded = running && (phase === 0 || phase === 1);
  return (
    <div className="card stack">
      <p className="small">Breathe in through your nose for 4, hold for 4, breathe out slowly for 4, hold for 4. Stop any time if you feel light-headed.</p>
      <div className="mind-breath" aria-hidden="true">
        <div className={`mind-square ${running ? "running" : ""} ${expanded ? "big" : ""} phase-${phase}`}>
          <span className="mind-count">{running ? count : ""}</span>
        </div>
      </div>
      <p className="mind-phase" aria-live="polite" aria-atomic="true">
        {running ? PHASES[phase] : done && tick > 0 ? "Nicely done. Notice how you feel." : "Ready when you are."}
      </p>
      {running && (
        <div className="small muted" style={{ textAlign: "center" }}>
          {Math.floor((total - tick) / 60)}:{String((total - tick) % 60).padStart(2, "0")} left
        </div>
      )}
      <fieldset className="wb-field">
        <legend>Length</legend>
        <div className="wb-seg">
          {LENGTHS.map((l) => (
            <button key={l.id} type="button" aria-pressed={length.id === l.id} disabled={running} onClick={() => setLength(l)}>
              {l.label}
            </button>
          ))}
        </div>
      </fieldset>
      {running
        ? <button className="btn" onClick={() => setRunning(false)}>Stop</button>
        : <button className="btn primary" onClick={start}>Start box breathing</button>}
    </div>
  );
}
