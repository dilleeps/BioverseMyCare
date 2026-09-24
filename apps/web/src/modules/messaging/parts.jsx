import { useEffect, useRef } from "react";
import { fmtDateTime } from "../../format.js";
import { Book, Phone, Sparkle, Warning } from "../../icons.jsx";

export const ASSIGNED_LABELS = { clinician: "Clinician", front_desk: "Front desk", nurse_triage: "Nurse triage" };

export function EmergencyCard({ payload }) {
  return (
    <section className="emergency stack msg-widget" role="alert">
      <div className="row strong" style={{ color: "var(--alert-strong)" }}>
        <Warning size={20} /> {payload.crisis_line ? "Support is available now" : "Get emergency help now"}
      </div>
      {payload.crisis_line && (
        <a className="call" href={`tel:${payload.crisis_line}`}><Phone size={20} /> Call or text {payload.crisis_line}</a>
      )}
      <a className="call" href={`tel:${payload.emergency_number}`}><Phone size={20} /> Call {payload.emergency_number}</a>
      {payload.care_team_notified && (
        <p className="small" style={{ color: "var(--alert-strong)" }}>Your care team has been alerted.</p>
      )}
    </section>
  );
}

// "Seen by Dr. Okafor" under the viewer's latest message, from per-participant read positions.
function seenBy(thread, message, viewerId) {
  if (message.author_user_id !== viewerId) return [];
  return (thread.participants || [])
    .filter((p) => p.user_id !== viewerId && p.last_read_seq >= message.seq)
    .map((p) => p.name);
}

export function MessageList({ thread, viewerId, viewerSide }) {
  const boxRef = useRef(null);
  const messages = thread.messages || [];
  useEffect(() => {
    // Scroll the conversation, not the page, to the newest message.
    const box = boxRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [thread.id, messages.length]);

  const lastOwn = [...messages].reverse().find((m) => m.author_user_id === viewerId);

  return (
    <div className="msg-scroll" ref={boxRef} tabIndex={0} role="region" aria-label="Conversation">
      <ol className="msg-list">
        {messages.map((m) => {
          const mine = viewerSide(m);
          const p = m.payload || {};
          const seen = lastOwn && m.id === lastOwn.id ? seenBy(thread, m, viewerId) : [];
          return (
            <li key={m.id} className={`msg ${mine ? "mine" : "theirs"} ${m.automated ? "automated" : ""}`}>
              <div className="msg-meta">
                <span className="strong">{mine ? "You" : m.author_label}</span>
                {m.automated && <span className="chip msg-auto"><Sparkle size={11} /> Automated</span>}
                <span className="muted">{fmtDateTime(m.created_at)}</span>
              </div>
              <div className="msg-bubble">{m.body}</div>
              {p.kind === "emergency" && <EmergencyCard payload={p} />}
              {p.kind === "education" && (
                <div className="tiny muted row" style={{ gap: 6 }}>
                  <Book size={13} /> From information approved by your care team: {p.title}
                </div>
              )}
              {p.kind === "previsit_question" && (
                <div className="tiny muted">Pre-visit question {p.n} of {p.of}</div>
              )}
              {m.category && m.author_kind === "patient" && (
                <div className="row wrap" style={{ gap: 6 }}>
                  <span className={`chip ${m.priority === "urgent" ? "warn" : ""}`}>
                    {m.priority === "urgent" ? "Urgent" : "Routine"} · {m.category.replace(/_/g, " ")}
                  </span>
                  {m.triage_reason && <span className="tiny muted">{m.triage_reason}</span>}
                </div>
              )}
              {seen.length > 0 && <div className="tiny muted msg-seen">Seen by {seen.join(", ")}</div>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function Composer({ id, label, value, onChange, onSubmit, busy, disabled, placeholder, children, sendLabel = "Send" }) {
  return (
    <form
      className="msg-composer stack"
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim() && !busy && !disabled) onSubmit();
      }}
    >
      <label htmlFor={id} className="strong small">{label}</label>
      <textarea
        id={id}
        className="edit msg-textarea"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        maxLength={4000}
        disabled={disabled}
      />
      <div className="row between wrap" style={{ gap: 8 }}>
        <span className="tiny muted">Text only. Attachments aren't supported yet.</span>
        <div className="row wrap" style={{ gap: 8 }}>
          {children}
          <button type="submit" className="btn primary" disabled={!value.trim() || busy || disabled}>
            {busy ? "Sending…" : sendLabel}
          </button>
        </div>
      </div>
    </form>
  );
}

export function waitingFor(iso) {
  if (!iso) return "";
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins} min`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.round(hours / 24)} days`;
}
