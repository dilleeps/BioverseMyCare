import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { Arrow, Check, Phone, Shield, Warning } from "../icons.jsx";

const GREETING = "Hi, I'm Bioverse One. Tell me what's going on, or what you need help with, and I'll guide you to the right next step.";

function SafetyCheck({ payload, active, onAnswer, busy }) {
  const [selected, setSelected] = useState([]);
  const toggle = (id) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  return (
    <section className="card stack widget" aria-label="Safety check">
      <div className="row" style={{ color: "var(--alert)", gap: 8 }}>
        <Warning size={16} />
        <span className="eyebrow" style={{ color: "var(--alert)" }}>Safety check</span>
      </div>
      <div className="strong" style={{ fontSize: 17 }}>{payload.question}</div>
      <div className="stack" style={{ gap: 8 }}>
        {payload.options.map((o) => (
          <button
            key={o.id}
            type="button"
            className="safety-option"
            aria-pressed={selected.includes(o.id)}
            disabled={!active || busy}
            onClick={() => toggle(o.id)}
          >
            {o.label}
            {selected.includes(o.id) && <Check size={16} />}
          </button>
        ))}
        {selected.length > 0 ? (
          <button type="button" className="btn danger" disabled={!active || busy} onClick={() => onAnswer(selected)}>
            Send these answers
          </button>
        ) : (
          <button type="button" className="btn primary" disabled={!active || busy} onClick={() => onAnswer(["none"])}>
            None of these <Arrow size={18} />
          </button>
        )}
      </div>
      <p className="small muted">If any of these start, or things get worse, call emergency services straight away.</p>
    </section>
  );
}

function Emergency({ payload }) {
  return (
    <section className="emergency stack widget" role="alert">
      <div className="row strong" style={{ color: "var(--alert-strong)" }}>
        <Warning size={20} /> {payload.crisis_line ? "Support is available now" : "Get emergency help now"}
      </div>
      {payload.crisis_line && (
        <a className="call" href={`tel:${payload.crisis_line}`}><Phone size={20} /> Call or text {payload.crisis_line}</a>
      )}
      <a className="call" href={`tel:${payload.emergency_number}`}><Phone size={20} /> Call {payload.emergency_number}</a>
      {payload.flags?.length > 0 && (
        <p className="small" style={{ color: "var(--alert-strong)" }}>Noted: {payload.flags.join(", ")}.</p>
      )}
      {payload.care_team_notified && (
        <p className="small" style={{ color: "var(--alert-strong)" }}>Your care team has been notified.</p>
      )}
    </section>
  );
}

function Message({ m, isLast, busy, onAnswer, navigate }) {
  const p = m.payload;
  return (
    <>
      <div className={`bubble ${m.role}`}>{m.content}</div>
      {p?.kind === "safety_check" && <SafetyCheck payload={p} active={isLast} onAnswer={onAnswer} busy={busy} />}
      {p?.kind === "emergency" && <Emergency payload={p} />}
      {p?.kind === "care_options" && (
        <div className="card stack widget">
          <div className="row between wrap">
            <div>
              <div className="card-title">{p.specialty}</div>
              <div className="small muted">
                {p.urgency === "urgent" ? "Needs care soon. Showing the earliest times." : "Matched to your location, language and plan."}
              </div>
            </div>
            <span className={`chip ${p.urgency === "urgent" ? "warn" : "ok"}`}>{p.urgency === "urgent" ? "Urgent" : "Routine"}</span>
          </div>
          <button
            type="button"
            className="btn primary"
            onClick={() => navigate(`/care/find?intake=${p.intake_id}&specialty=${encodeURIComponent(p.specialty)}`)}
          >
            Show my options <Arrow size={18} />
          </button>
        </div>
      )}
      {p?.kind === "link" && (
        <button type="button" className="btn primary widget" onClick={() => navigate(p.to)}>
          {p.label} <Arrow size={18} />
        </button>
      )}
    </>
  );
}

export default function FrontDoor() {
  const location = useLocation();
  const navigate = useNavigate();
  const [conversation, setConversation] = useState(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const endRef = useRef(null);
  const started = useRef(false);

  async function send(body, convo = conversation) {
    setBusy(true);
    setError(null);
    // Optimistically show the patient's words while the orchestrator works.
    if (body.text) {
      setConversation((c) => ({
        ...c,
        messages: [...c.messages, { id: `pending-${Date.now()}`, role: "user", content: body.text, payload: null }],
      }));
    }
    try {
      const next = await api(`/conversations/${convo.id}/messages`, { method: "POST", body });
      setConversation(next);
    } catch (e) {
      setError(e.message);
      const fresh = await api(`/conversations/${convo.id}`).catch(() => null);
      if (fresh) setConversation(fresh);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    (async () => {
      try {
        const convo = await api("/conversations", { method: "POST" });
        setConversation(convo);
        const initial = location.state?.initial;
        if (initial) {
          navigate(location.pathname, { replace: true, state: null });
          await send({ text: initial }, convo);
        }
      } catch (e) {
        setError(e.message);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [conversation?.messages?.length, busy]);

  const messages = conversation?.messages || [];
  const escalated = conversation?.status === "escalated";

  return (
    <main className="column">
      <div className="row between" style={{ marginBottom: 14 }}>
        <span className="page-title" style={{ fontSize: 22 }}>Ask Bioverse</span>
        <span className="chip ok"><Shield size={13} /> Private</span>
      </div>

      <div className="chat" aria-live="polite">
        <div className="bubble assistant">{GREETING}</div>
        {messages.map((m, i) => (
          <Message
            key={m.id}
            m={m}
            isLast={i === messages.length - 1}
            busy={busy}
            navigate={navigate}
            onAnswer={(answer) => send({ safety_answer: answer })}
          />
        ))}
        {busy && (
          <div className="bubble assistant" aria-label="Bioverse is thinking">
            <span className="typing"><i /><i /><i /></span>
          </div>
        )}
        {error && <div className="error-box">{error}</div>}
        <p className="tiny muted row" style={{ gap: 6 }}>
          <Shield size={13} /> Bioverse gathers and routes. It does not diagnose.
        </p>
        <div ref={endRef} />
      </div>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          const t = text.trim();
          if (!t || !conversation || busy) return;
          setText("");
          send({ text: t });
        }}
      >
        <label htmlFor="msg" className="sr-only">Message Bioverse</label>
        <input
          id="msg"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={escalated ? "Please call for help first" : "Tell me more…"}
          autoComplete="off"
          disabled={!conversation}
        />
        <button type="submit" className="btn dark" disabled={!text.trim() || busy || !conversation} aria-label="Send">
          <Arrow size={18} />
        </button>
      </form>
    </main>
  );
}
