// Web Speech API helpers: speech recognition (voice input) and speech synthesis (read aloud).
// Both are optional browser features. Callers hide their controls when these return false.
import { useCallback, useEffect, useRef, useState } from "react";

function Recognition() {
  if (typeof window === "undefined") return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

export function recognitionSupported() {
  return Boolean(Recognition());
}

export function synthesisSupported() {
  return typeof window !== "undefined" && "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
}

const lang = () => (typeof navigator !== "undefined" && navigator.language) || "en-US";

const ERRORS = {
  "not-allowed": "Microphone access is blocked. Allow it in your browser settings, or type instead.",
  "service-not-allowed": "Voice input isn't allowed here. Please type instead.",
  "no-speech": "I didn't hear anything. Tap the microphone and try again.",
  "audio-capture": "No microphone was found. Please type instead.",
  network: "Voice input needs a connection. Please type instead.",
};

// One recognition session at a time. `onText(text, final)` gets the transcript so far.
export function useSpeechRecognition(onText) {
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState(null);
  const recRef = useRef(null);
  const cb = useRef(onText);
  cb.current = onText;

  const stop = useCallback(() => {
    recRef.current?.stop();
  }, []);

  const start = useCallback(() => {
    const R = Recognition();
    if (!R) return;
    recRef.current?.abort();
    const rec = new R();
    rec.lang = lang();
    rec.interimResults = true;
    rec.continuous = false;
    rec.maxAlternatives = 1;
    rec.onresult = (e) => {
      let text = "";
      let final = true;
      for (let i = 0; i < e.results.length; i += 1) {
        text += e.results[i][0].transcript;
        if (!e.results[i].isFinal) final = false;
      }
      setTranscript(text);
      cb.current?.(text.trim(), final);
    };
    rec.onerror = (e) => {
      if (e.error !== "aborted") setError(ERRORS[e.error] || "Voice input stopped. Please try again or type.");
    };
    rec.onend = () => {
      setListening(false);
      recRef.current = null;
    };
    recRef.current = rec;
    setError(null);
    setTranscript("");
    try {
      rec.start();
      setListening(true);
    } catch {
      setError("Voice input couldn't start. Please type instead.");
    }
  }, []);

  useEffect(() => () => recRef.current?.abort(), []);

  return { supported: recognitionSupported(), listening, transcript, error, start, stop, clearError: () => setError(null) };
}

// Read text aloud. `interrupt` cancels anything still being read (used for emergency guidance).
export function speak(text, { interrupt = false } = {}) {
  if (!synthesisSupported() || !text) return;
  const synth = window.speechSynthesis;
  if (interrupt) synth.cancel();
  const u = new window.SpeechSynthesisUtterance(text);
  u.lang = lang();
  u.rate = 0.95;
  synth.speak(u);
}

export function stopSpeaking() {
  if (synthesisSupported()) window.speechSynthesis.cancel();
}
