import { Link } from "react-router-dom";
import { useSession } from "../../session.jsx";
import { SCALE_MAX, SCALE_MIN, savePrefs, useDisplayPrefs } from "./prefs.js";
import { recognitionSupported, speak, synthesisSupported } from "./speech.js";

const SWITCHES = [
  { key: "senior_mode", label: "Senior mode",
    help: "Larger text, bigger buttons, simpler screens and stronger contrast. Patients get a simpler front door." },
  { key: "high_contrast", label: "High contrast", help: "Darker text and stronger outlines." },
  { key: "reduce_motion", label: "Reduce motion", help: "Turns off animations and smooth scrolling." },
  { key: "read_aloud", label: "Read replies aloud",
    help: "Bioverse reads its replies out loud. Emergency guidance is always read when this is on." },
];

const SIZES = [
  { value: 1, label: "Standard" },
  { value: 1.2, label: "Large" },
  { value: 1.4, label: "Larger" },
  { value: 1.6, label: "Largest" },
];

export default function DisplaySettings() {
  const { me } = useSession();
  const prefs = useDisplayPrefs();
  const speaks = synthesisSupported();

  return (
    <main className="column a11y-settings">
      <div className="page-head">
        <div>
          <h1 className="page-title">Display and reading</h1>
          <div className="page-sub">These settings follow you to every device you sign in on.</div>
        </div>
      </div>

      {!prefs.loaded && !prefs.error && <div className="skeleton" aria-label="Loading your settings" />}
      {prefs.error && <div className="error-box" role="alert">{prefs.error}</div>}

      <section className="card stack" aria-labelledby="a11y-switches">
        <h2 id="a11y-switches" className="card-title">How Bioverse looks</h2>
        {SWITCHES.filter((s) => s.key !== "read_aloud" || speaks).map((s) => (
          <div key={s.key} className="a11y-switch">
            <div className="a11y-switch-text">
              <label htmlFor={`pref-${s.key}`} className="strong">{s.label}</label>
              <p className="small muted" id={`pref-${s.key}-help`}>{s.help}</p>
            </div>
            <button
              id={`pref-${s.key}`}
              type="button"
              role="switch"
              aria-checked={Boolean(prefs[s.key])}
              aria-describedby={`pref-${s.key}-help`}
              className="a11y-toggle"
              onClick={() => savePrefs({ [s.key]: !prefs[s.key] })}
            >
              <span className="a11y-toggle-knob" aria-hidden="true" />
              <span className="sr-only">{prefs[s.key] ? "On" : "Off"}</span>
            </button>
          </div>
        ))}
      </section>

      <section className="card stack" aria-labelledby="a11y-size">
        <h2 id="a11y-size" className="card-title">Text size</h2>
        <div className="a11y-sizes" role="radiogroup" aria-labelledby="a11y-size">
          {SIZES.map((s) => (
            <button
              key={s.value}
              type="button"
              role="radio"
              aria-checked={Math.abs(prefs.text_scale - s.value) < 0.05}
              className="a11y-size"
              onClick={() => savePrefs({ text_scale: s.value })}
            >
              <span style={{ fontSize: `${Math.round(16 * s.value)}px` }} aria-hidden="true">Aa</span>
              {s.label}
            </button>
          ))}
        </div>
        <label className="small muted" htmlFor="a11y-scale-range">Fine-tune: {Math.round(prefs.text_scale * 100)}%</label>
        <input
          id="a11y-scale-range"
          type="range"
          min={SCALE_MIN}
          max={SCALE_MAX}
          step={0.05}
          value={prefs.text_scale}
          onChange={(e) => savePrefs({ text_scale: Number(e.target.value) })}
        />
        <p className="bubble assistant a11y-sample">This is how Bioverse's replies will look.</p>
        {speaks && (
          <button type="button" className="btn" onClick={() => speak("This is how Bioverse sounds when it reads a reply aloud.", { interrupt: true })}>
            Hear a sample
          </button>
        )}
      </section>

      <section className="card stack">
        <h2 className="card-title">Speaking instead of typing</h2>
        <p className="small muted">
          {recognitionSupported()
            ? "Tap the microphone next to any Ask box to speak. Your words appear in the box so you can check them before sending."
            : "This browser doesn't support voice input. Chrome, Edge and Safari do."}
        </p>
        {me?.role === "patient" && <Link className="btn primary" to="/app">Go to Ask Bioverse</Link>}
      </section>
      {prefs.saving && <p className="tiny muted" role="status">Saving…</p>}
    </main>
  );
}
