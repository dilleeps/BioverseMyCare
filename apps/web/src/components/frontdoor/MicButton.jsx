import { useRef } from "react";
import { useSpeechRecognition } from "../../modules/accessibility/speech.js";
import { Mic, Stop } from "./icons.jsx";
import "./frontdoor.css";

// Voice input for any text box. Hidden where the browser has no speech recognition.
// The words appear in the box as they're heard (`onChange`) so the person reviews them before sending.
// `value` is what's already typed: speech is added after it. `onFinal(text)` fires once speech ends.
export default function MicButton({ value = "", onChange, onFinal, label = "Speak instead of typing", disabled }) {
  const base = useRef("");
  const rec = useSpeechRecognition((heard, final) => {
    const text = base.current ? `${base.current} ${heard}` : heard;
    onChange?.(text);
    if (final) onFinal?.(text);
  });
  if (!rec.supported) return null;

  function toggle() {
    if (rec.listening) {
      rec.stop();
      return;
    }
    base.current = value.trim();
    rec.start();
  }

  return (
    <span className="mic-wrap">
      <button
        type="button"
        className={`fd-icon-btn mic-btn${rec.listening ? " listening" : ""}`}
        onClick={toggle}
        aria-pressed={rec.listening}
        aria-label={rec.listening ? "Stop listening" : label}
        title={rec.listening ? "Stop listening" : label}
        disabled={disabled && !rec.listening}
      >
        {rec.listening ? <Stop size={18} /> : <Mic size={20} />}
      </button>
      {(rec.listening || rec.error) && (
        <span className={`mic-status${rec.error ? " error" : ""}`} role="status" aria-live="polite">
          {rec.error ? (
            <>
              {rec.error}
              <button type="button" className="mic-status-close" onClick={rec.clearError} aria-label="Dismiss">×</button>
            </>
          ) : (
            <>
              <span className="mic-dot" aria-hidden="true" />
              <span className="mic-text">
                <strong>Listening.</strong> {rec.transcript ? `"${rec.transcript}"` : "Speak now."}
              </span>
              <button type="button" className="mic-status-stop" onClick={rec.stop}>Stop</button>
            </>
          )}
        </span>
      )}
    </span>
  );
}
