import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api.js";
import { fmtDate, fmtDateTime } from "../../format.js";
import { Phone, Shield, Warning } from "../../icons.jsx";

export const MODE_LABEL = { message: "Message", video: "Video", phone: "Phone" };
export const MODE_LONG = { message: "Secure message", video: "Video call", phone: "Phone call" };

export function fmtMoney(cents) {
  if (cents == null) return "";
  return `$${(cents / 100).toFixed(cents % 100 === 0 ? 0 : 2)}`;
}

function Svg({ size = 18, children }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
  );
}
export const VideoIcon = (p) => <Svg {...p}><rect x="3" y="6" width="13" height="12" rx="2" /><path d="M16 10l5-3v10l-5-3" /></Svg>;
export const VideoOffIcon = (p) => <Svg {...p}><path d="M16 16v1a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h2M9 6h6a1 1 0 0 1 1 1v3l5-3v10" /><path d="M2 2l20 20" /></Svg>;
export const MicIcon = (p) => <Svg {...p}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></Svg>;
export const MicOffIcon = (p) => <Svg {...p}><path d="M15 10V6a3 3 0 0 0-5.7-1.3M9 9v2a3 3 0 0 0 4.6 2.5M5 11a7 7 0 0 0 11 5.7M19 11a7 7 0 0 1-.6 2.8M12 18v3" /><path d="M2 2l20 20" /></Svg>;
export const LeaveIcon = (p) => <Svg {...p}><path d="M3 15c3-3 15-3 18 0l-2 3-4-1v-2a13 13 0 0 0-6 0v2l-4 1z" /></Svg>;
export const ChatIcon = (p) => <Svg {...p}><path d="M4 5h16v11H9l-5 4z" /></Svg>;
export const StarIcon = ({ size = 16, filled }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" fill={filled ? "currentColor" : "none"}
       stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round">
    <path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z" />
  </svg>
);

const MODE_ICON = { message: ChatIcon, video: VideoIcon, phone: Phone };
export function ModeIcon({ mode, size = 16 }) {
  const I = MODE_ICON[mode] || ChatIcon;
  return <I size={size} />;
}

export function Rating({ rating }) {
  if (!rating || !rating.count) return <span className="small muted">No ratings yet</span>;
  return (
    <span className="consult-rating small" aria-label={`Rated ${rating.average} out of 5 from ${rating.count} consults`}>
      <StarIcon filled size={15} /> <span className="strong">{rating.average.toFixed(1)}</span>
      <span className="muted">({rating.count})</span>
    </span>
  );
}

// "Verified" chip that expands into what was checked, how, and when.
export function VerifiedBadge({ verified, id }) {
  if (!verified) return null;
  return (
    <details className="verified" id={id}>
      <summary><Shield size={14} /> Verified</summary>
      <div className="verified-body stack" style={{ gap: 6 }}>
        <div className="small"><span className="strong">{verified.license}</span></div>
        {verified.board_certification && <div className="small">{verified.board_certification}</div>}
        <div className="small">NPI {verified.npi}</div>
        <div className="small muted">
          Verified {fmtDate(verified.verified_at)} · license valid until {fmtDate(verified.expires_on)}
        </div>
        <ul className="verified-checks">
          {(verified.checks || []).map((c) => (
            <li key={c.check}>
              <span className="strong">{c.check}:</span> {c.result}{c.demo ? " (simulated)" : ""}
            </li>
          ))}
        </ul>
        <p className="tiny muted">{verified.notice}</p>
      </div>
    </details>
  );
}

export function StatusChip({ status, label }) {
  const tone = { completed: "ok", accepted: "ok", in_progress: "ok", declined: "warn", cancelled: "" }[status] ?? "";
  return <span className={`chip ${tone}`}>{label}</span>;
}

export function EmergencyCard({ payload }) {
  if (!payload) return null;
  return (
    <section className="emergency stack" role="alert" style={{ gap: 10 }}>
      <div className="row strong" style={{ color: "var(--alert-strong)" }}>
        <Warning size={20} /> {payload.crisis_line ? "Support is available now" : "Get emergency help now"}
      </div>
      <p className="small">{payload.message}</p>
      {payload.crisis_line && (
        <a className="call" href={`tel:${payload.crisis_line}`}><Phone size={20} /> Call or text {payload.crisis_line}</a>
      )}
      <a className="call" href={`tel:${payload.emergency_number}`}><Phone size={20} /> Call {payload.emergency_number}</a>
    </section>
  );
}

// Safety check for chest or headache symptoms, before any routine request goes through.
export function SafetyCheck({ check, onAnswer, busy }) {
  const [picked, setPicked] = useState([]);
  const toggle = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  return (
    <section className="card alert stack" aria-labelledby="safety-q">
      <h3 id="safety-q" className="card-title">{check.question}</h3>
      <div className="stack" style={{ gap: 8 }}>
        {check.options.map((o) => (
          <button key={o.id} type="button" className="safety-option" aria-pressed={picked.includes(o.id)} onClick={() => toggle(o.id)}>
            {o.label}
          </button>
        ))}
      </div>
      <div className="row wrap" style={{ gap: 8 }}>
        <button type="button" className="btn danger" disabled={busy || picked.length === 0} onClick={() => onAnswer(picked)}>
          Yes, I have {picked.length > 1 ? "these" : "this"}
        </button>
        <button type="button" className="btn" disabled={busy} onClick={() => onAnswer(["none"])}>None of these</button>
      </div>
    </section>
  );
}

// Conversation for a consult. Scrolls its own box, never the page.
export function Thread({ messages, viewerId }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [messages.length]);
  if (!messages.length) return <p className="small muted">No messages yet.</p>;
  return (
    <div className="consult-thread" ref={ref} aria-live="polite">
      {messages.map((m) => {
        if (m.author_kind === "system") {
          if (m.payload?.kind === "emergency") return <EmergencyCard key={m.id} payload={m.payload} />;
          return <div key={m.id} className="consult-system tiny muted">{m.body}</div>;
        }
        const mine = m.author_user_id === viewerId;
        return (
          <div key={m.id} className={`consult-msg ${mine ? "mine" : ""}`}>
            <div className="tiny muted">{mine ? "You" : m.author_label} · {fmtDateTime(m.created_at)}</div>
            <div className="consult-bubble">{m.body}</div>
          </div>
        );
      })}
    </div>
  );
}

export function Composer({ onSend, placeholder, disabled }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    const ok = await onSend(text.trim());
    setBusy(false);
    if (ok) setText("");
  }
  return (
    <form className="consult-composer" onSubmit={submit}>
      <label htmlFor="consult-msg" className="sr-only">Message</label>
      <textarea id="consult-msg" rows={2} maxLength={4000} value={text} placeholder={placeholder}
                onChange={(e) => setText(e.target.value)} disabled={disabled || busy} />
      <button className="btn primary" disabled={disabled || busy || !text.trim()}>Send</button>
    </form>
  );
}

// Load a consult and keep it fresh while the page is open.
export function useConsult(id, intervalMs = 8000) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const seq = useRef(0);
  const load = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const data = await api(`/consultations/${id}`);
      if (mine === seq.current) setState({ data, error: null, loading: false });
    } catch (error) {
      if (mine === seq.current) setState((s) => ({ ...s, error, loading: false }));
    }
  }, [id]);
  useEffect(() => {
    load();
    const t = setInterval(() => document.visibilityState !== "hidden" && load(), intervalMs);
    return () => clearInterval(t);
  }, [load, intervalMs]);
  return { ...state, reload: load, setData: (data) => setState({ data, error: null, loading: false }) };
}

export function useToast() {
  const [toast, setToast] = useState(null);
  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(t);
  }, [toast]);
  const node = toast ? <div className="toast" role="status">{toast}</div> : null;
  return [node, setToast];
}

export function whenText(c) {
  if (c.scheduled_at) return fmtDateTime(c.scheduled_at);
  return c.mode === "message" ? "By message" : "";
}
