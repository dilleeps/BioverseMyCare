import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { useSession } from "../../session.jsx";
import { PatientPage } from "../../layouts.jsx";
import { fmtDateTime, fmtShortDate } from "../../format.js";
import { Back, Calendar, Chat, Chevron, Plus, Shield } from "../../icons.jsx";
import { Composer, MessageList } from "./parts.jsx";

function ThreadRow({ t, selected, onOpen }) {
  return (
    <button type="button" className="msg-thread-row" aria-current={selected} onClick={() => onOpen(t.id)}>
      <span className="stack" style={{ gap: 2, flexGrow: 1, minWidth: 0 }}>
        <span className="row between" style={{ gap: 8 }}>
          <span className="strong msg-ellipsis">{t.subject}</span>
          <span className="tiny muted" style={{ flexShrink: 0 }}>{fmtShortDate(t.last_message_at)}</span>
        </span>
        <span className="small muted">{t.kind === "previsit" ? "Pre-visit questions" : t.kind === "followup" ? "Check-ins" : "My care team"} · {t.care_team_label}</span>
        {t.last_message && (
          <span className="small msg-ellipsis" style={{ color: "var(--ink-2)" }}>
            {t.last_message.author}: {t.last_message.body}
          </span>
        )}
      </span>
      {t.unread > 0 && <span className="msg-unread" aria-label={`${t.unread} unread`}>{t.unread}</span>}
      {t.flagged && <span className="sr-only">Urgent safety message</span>}
    </button>
  );
}

function PrevisitCards({ onOpen }) {
  const { data, error, reload } = useApi("/doctor-agent/previsit");
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  if (error || !data?.length) return null;

  async function start(p) {
    setBusy(p.appointment_id);
    setErr(null);
    try {
      const r = await api(`/doctor-agent/previsit/${p.appointment_id}/start`, { method: "POST" });
      reload();
      onOpen(r.thread_id, true);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="stack" style={{ gap: 8 }}>
      {data.filter((p) => p.status !== "complete").map((p) => (
        <article key={p.appointment_id} className="card highlight row between wrap" style={{ gap: 12 }}>
          <div className="row" style={{ gap: 12 }}>
            <span className="audience-icon" style={{ width: 40, height: 40 }}><Calendar size={18} /></span>
            <div>
              <div className="strong">{p.practitioner_label} has {p.questions} questions before your visit</div>
              <div className="small muted">Visit {fmtDateTime(p.starts_at)}. Takes about two minutes.</div>
            </div>
          </div>
          <button type="button" className="btn primary" disabled={busy === p.appointment_id} onClick={() => start(p)}>
            {p.status === "in_progress" ? "Continue" : "Answer now"} <Chevron size={16} />
          </button>
        </article>
      ))}
      {err && <div className="error-box">{err}</div>}
    </div>
  );
}

function NewMessage({ onCreated, onCancel }) {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function send() {
    setBusy(true);
    setError(null);
    try {
      const thread = await api("/messages/threads", { method: "POST", body: { subject: subject || null, body } });
      onCreated(thread);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <section className="card stack" aria-labelledby="new-title">
      <div className="row between">
        <h2 id="new-title" className="card-title">New message</h2>
        <button type="button" className="btn ghost sm" onClick={onCancel}>Cancel</button>
      </div>
      <div className="stack" style={{ gap: 6 }}>
        <span className="small strong">To</span>
        <span className="chip ok" style={{ alignSelf: "flex-start" }}>My care team</span>
      </div>
      <div className="stack" style={{ gap: 6 }}>
        <label htmlFor="msg-subject" className="small strong">Subject (optional)</label>
        <input id="msg-subject" className="msg-input" value={subject} maxLength={120}
               onChange={(e) => setSubject(e.target.value)} placeholder="For example: question about my new medicine" />
      </div>
      {error && <div className="error-box">{error}</div>}
      <Composer id="msg-new-body" label="Message" value={body} onChange={setBody} onSubmit={send} busy={busy}
                placeholder="Write your message to your care team" />
    </section>
  );
}

function ThreadView({ threadId, onBack, onChanged }) {
  const { me } = useSession();
  const { data, error, loading, reload } = useApi(`/messages/threads/${threadId}`);
  const [thread, setThread] = useState(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [sendError, setSendError] = useState(null);

  useEffect(() => {
    if (data) {
      setThread(data);
      onChanged(); // opening marks it read: refresh unread counts
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);
  useEffect(() => {
    setText("");
    setSendError(null);
  }, [threadId]);

  async function send() {
    setBusy(true);
    setSendError(null);
    try {
      setThread(await api(`/messages/threads/${threadId}/messages`, { method: "POST", body: { body: text } }));
      setText("");
      onChanged();
    } catch (e) {
      setSendError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <div className="error-box">{error.message} <button className="btn sm" onClick={reload}>Try again</button></div>;
  if (loading && !thread) return <div className="card stack"><div className="skeleton" /><div className="skeleton" /></div>;
  if (!thread) return null;
  const previsit = thread.kind === "previsit";

  return (
    <section className="card stack msg-thread" aria-labelledby="thread-title">
      <header className="row between wrap" style={{ gap: 8 }}>
        <div className="row" style={{ gap: 8 }}>
          <button type="button" className="icon-btn msg-back" onClick={onBack} aria-label="Back to all messages"><Back size={18} /></button>
          <div>
            <h2 id="thread-title" className="card-title">{thread.subject}</h2>
            <div className="small muted">With {thread.care_team_label}{thread.care_team_label === "My care team" ? "" : "'s care team"}</div>
          </div>
        </div>
      </header>
      <MessageList thread={thread} viewerId={me.id} viewerSide={(m) => m.author_user_id === me.id} />
      {sendError && <div className="error-box">{sendError}</div>}
      <Composer id="msg-reply" label={previsit ? "Your answer" : "Reply"} value={text} onChange={setText} onSubmit={send}
                busy={busy} disabled={!thread.can_reply}
                placeholder={thread.flagged ? "If this is an emergency, call for help first" : "Write a reply"} />
    </section>
  );
}

export default function Messages() {
  const [params, setParams] = useSearchParams();
  const selected = params.get("thread");
  const [composing, setComposing] = useState(false);
  const list = useApi("/messages/threads");

  function open(id, refresh = false) {
    setComposing(false);
    setParams(id ? { thread: id } : {});
    if (refresh) list.reload();
  }

  return (
    <PatientPage wide>
      <div className="page-head row between wrap">
        <div>
          <h1 className="page-title">Messages</h1>
          <div className="page-sub">Secure messages with your care team</div>
        </div>
        <button type="button" className="btn primary" onClick={() => { setComposing(true); setParams({}); }}>
          <Plus size={16} /> New message
        </button>
      </div>

      <div className="banner info" style={{ marginBottom: 14 }}>
        <Shield size={15} /> For an emergency, call 911. Messages are read during clinic hours. Replies marked "Automated" come from your doctor's assistant, not your doctor.
      </div>

      <div className="msg-layout" data-open={Boolean(selected || composing)}>
        <aside className="msg-list-pane stack" aria-label="Your conversations">
          <PrevisitCards onOpen={open} />
          <div className="card msg-threads">
            {list.error && <div className="error-box">{list.error.message} <button className="btn sm" onClick={list.reload}>Try again</button></div>}
            {list.loading && !list.data && <div className="stack"><div className="skeleton" /><div className="skeleton" /></div>}
            {list.data?.length === 0 && (
              <div className="empty stack" style={{ alignItems: "center" }}>
                <Chat size={22} />
                <span>No messages yet. Start one to reach your care team.</span>
              </div>
            )}
            <div className="list">
              {list.data?.map((t) => <ThreadRow key={t.id} t={t} selected={t.id === selected} onOpen={open} />)}
            </div>
          </div>
        </aside>
        <div className="msg-detail-pane">
          {composing && (
            <NewMessage onCancel={() => setComposing(false)}
                        onCreated={(thread) => { list.reload(); open(thread.id); }} />
          )}
          {!composing && selected && (
            <ThreadView key={selected} threadId={selected} onBack={() => open(null)} onChanged={list.reload} />
          )}
          {!composing && !selected && (
            <div className="card empty msg-placeholder">Choose a conversation, or start a new message.</div>
          )}
        </div>
      </div>
    </PatientPage>
  );
}
