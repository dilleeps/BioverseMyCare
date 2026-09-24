import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { Back, Calendar, Phone, Warning } from "../../icons.jsx";
import { useSession } from "../../session.jsx";
import { CitationList, Disclosure, initialsOf } from "./shared.jsx";

const STARTERS = {
  Cardiology: ["What do statins do?", "What's the right way to measure blood pressure at home?", "How much exercise is good for the heart?"],
  Neurology: ["Why keep a headache diary for migraine?", "Which headache warning signs need emergency care?"],
};

function AssistantMessage({ m, isPatient }) {
  if (m.kind === "emergency") {
    return (
      <div className="emergency stack sp-bubble-emergency" role="alert">
        <div className="card-title row" style={{ gap: 8 }}><Warning size={18} /> This may be an emergency</div>
        <p className="small">{m.answer}</p>
        <a className="call" href={`tel:${m.safety?.call || "911"}`}><Phone size={20} /> Call {m.safety?.call || "911"}</a>
      </div>
    );
  }
  return (
    <div className="bubble assistant sp-bubble">
      <div>{m.answer}</div>
      {m.guidance?.length > 0 && (
        <div className="tiny muted sp-meta">From the clinician's guidance: {m.guidance.map((g) => g.title).join("; ")}</div>
      )}
      <CitationList citations={m.citations} />
      {(m.suggestion || (m.booking && m.kind !== "answer")) && (
        <div className="row wrap sp-actions">
          {m.suggestion && <Link className="btn sm" to={m.suggestion.to}>{m.suggestion.label}</Link>}
          {m.booking && m.kind !== "answer" && isPatient && (
            <Link className="btn sm primary" to={m.booking.to}><Calendar size={14} /> {m.booking.label}</Link>
          )}
        </div>
      )}
    </div>
  );
}

export default function SpecialistChat() {
  const { agentId } = useParams();
  const { me } = useSession();
  const detail = useApi(`/specialists/${agentId}`);
  const [messages, setMessages] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [remaining, setRemaining] = useState(null);
  const endRef = useRef(null);

  useEffect(() => {
    if (!detail.data) return;
    setMessages(detail.data.history.map((h) => ({ ...h, guidance: [], suggestion: null, booking: null })));
    setConversationId(detail.data.history.at(-1)?.conversation_id || null);
    setRemaining(detail.data.remaining_today);
  }, [detail.data]);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length, busy]);

  async function send(question) {
    const q = (question ?? text).trim();
    if (!q || busy) return;
    setBusy(true);
    setError(null);
    setText("");
    setMessages((ms) => [...ms, { id: `pending-${Date.now()}`, question: q, pending: true }]);
    try {
      const out = await api(`/specialists/${agentId}/chat`, { method: "POST", body: { message: q, conversation_id: conversationId } });
      setConversationId(out.conversation_id);
      setRemaining(out.remaining_today);
      setMessages((ms) => [...ms.filter((m) => !m.pending), { ...out, question: q }]);
    } catch (err) {
      setMessages((ms) => ms.filter((m) => !m.pending));
      setText(q);
      setError(err.status === 429 || err.status === 409 ? err.message : `Couldn't send your question. ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  if (detail.loading && !detail.data) return <main className="column"><div className="card"><div className="skeleton" /></div></main>;
  if (detail.error) {
    return (
      <main className="column stack">
        <div className="error-box">{detail.error.status === 404 ? "This assistant isn't available." : detail.error.message}</div>
        <Link to="/specialists" className="btn">Back to specialist assistants</Link>
      </main>
    );
  }
  const a = detail.data;
  const starters = STARTERS[a.specialty] || [];
  const isPatient = me?.role === "patient";

  return (
    <main className="column sp-chat-page">
      <div className="row" style={{ marginBottom: 8 }}>
        <Link to="/specialists" className="btn ghost sm"><Back size={16} /> All assistants</Link>
      </div>
      <header className="row sp-chat-head">
        <span className="avatar sp-avatar" aria-hidden="true">{initialsOf(a.display_name)}</span>
        <div className="stack" style={{ gap: 2, minWidth: 0 }}>
          <h1 className="sp-chat-title">{a.display_name}'s AI assistant</h1>
          <span className="small muted">{a.specialty} · {a.topics.join(" · ")}</span>
        </div>
      </header>
      <Disclosure text={a.disclosure} sticky />
      {a.paused && <div className="banner warn" style={{ marginTop: 8 }}>This assistant is paused right now.</div>}

      <section className="chat sp-chat" aria-label="Conversation" aria-live="polite">
        {messages.length === 0 && (
          <div className="stack sp-empty">
            <p className="small muted">
              Ask a general question about {a.topics.map((t) => t.toLowerCase()).join(", ")}. For questions about your own
              health, results or medicines, book a visit instead.
            </p>
            <div className="row wrap" style={{ gap: 8 }}>
              {starters.map((s) => (
                <button key={s} type="button" className="btn sm sp-starter" onClick={() => send(s)} disabled={busy || a.paused}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className="stack" style={{ gap: 8 }}>
            <div className="bubble user">{m.question}</div>
            {m.pending ? (
              <div className="bubble assistant"><span className="typing" aria-label="Answering"><i /><i /><i /></span></div>
            ) : (
              <AssistantMessage m={m} isPatient={isPatient} />
            )}
          </div>
        ))}
        <div ref={endRef} />
      </section>

      {error && <div className="error-box small" role="alert">{error}</div>}
      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <label htmlFor="sp-input" className="sr-only">Your question</label>
        <input
          id="sp-input"
          value={text}
          maxLength={1000}
          onChange={(e) => setText(e.target.value)}
          placeholder="Ask a general question"
          disabled={a.paused}
          autoComplete="off"
        />
        <button className="btn primary" type="submit" disabled={busy || !text.trim() || a.paused}>Ask</button>
      </form>
      {remaining != null && (
        <p className="tiny muted sp-remaining">
          {remaining} of {a.daily_limit} questions left today. Conversations are reviewed by the clinician to improve their guidance.
        </p>
      )}
    </main>
  );
}
