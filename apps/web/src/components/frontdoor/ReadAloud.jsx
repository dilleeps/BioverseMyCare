import { useEffect, useRef } from "react";
import { savePrefs, useDisplayPrefs } from "../../modules/accessibility/prefs.js";
import { speak, stopSpeaking, synthesisSupported } from "../../modules/accessibility/speech.js";
import { Speaker } from "./icons.jsx";
import "./frontdoor.css";

// "Read replies aloud" switch. Hidden where the browser can't speak.
export function ReadAloudToggle() {
  const prefs = useDisplayPrefs();
  if (!synthesisSupported()) return null;
  const on = Boolean(prefs.read_aloud);
  return (
    <button
      type="button"
      className={`fd-pill${on ? " on" : ""}`}
      aria-pressed={on}
      onClick={() => {
        if (on) stopSpeaking();
        savePrefs({ read_aloud: !on });
      }}
    >
      <Speaker size={16} /> Read replies aloud
    </button>
  );
}

// What to say for a reply: its words, plus the numbers to call when it's an emergency.
export function spokenText(content, payload) {
  if (payload?.kind !== "emergency") return content;
  const calls = [payload.crisis_line && `Call or text ${payload.crisis_line}.`, `Call ${payload.emergency_number}.`];
  return [content, ...calls.filter(Boolean)].join(" ");
}

// Reads each new assistant message once, when read-aloud is on. Emergency guidance interrupts whatever is
// being read, so it is always heard.
export function useReadAloud(messages) {
  const { read_aloud: on } = useDisplayPrefs();
  const seen = useRef(new Set());
  useEffect(() => {
    for (const m of messages) {
      if (m.role !== "assistant" || seen.current.has(m.id)) continue;
      seen.current.add(m.id);
      if (!on) continue;
      const emergency = m.payload?.kind === "emergency";
      speak(spokenText(m.content, m.payload), { interrupt: emergency });
    }
  }, [messages, on]);
  useEffect(() => () => stopSpeaking(), []);
}
