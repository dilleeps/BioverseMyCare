import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { useSession } from "../../session.jsx";
import { WorkspaceLayout } from "../../layouts.jsx";
import { fmtShortDate } from "../../format.js";
import { Chat, Close, Inbox as InboxIcon, Sparkle, Warning } from "../../icons.jsx";
import { ASSIGNED_LABELS, Composer, MessageList, waitingFor } from "./parts.jsx";

function ThreadItem({ t, selected, onOpen }) {
  const urgent = t.priority === "urgent";
  return (
    <button type="button" className={`msg-inbox-item ${urgent ? "urgent" : ""}`} aria-current={selected} onClick={() => onOpen(t.id)}>
      <span className="row between" style={{ gap: 8 }}>
        <span className="strong msg-ellipsis">{t.patient.name}</span>
        <span className="tiny muted" style={{ flexShrink: 0 }}>
          {t.awaiting_since ? `Waiting ${waitingFor(t.awaiting_since)}` : fmtShortDate(t.last_message_at)}
        </span>
      </span>
      <span className="small msg-ellipsis">{t.subject}</span>
      <span className="row wrap" style={{ gap: 4 }}>
        {t.flagged && !t.flag_acknowledged && <span className="chip warn"><Warning size={11} /> Red flag</span>}
        {urgent && <span className="chip warn">Urgent</span>}
        {t.category_label && <span className="chip">{t.category_label}</span>}
        {t.assigned_to !== "clinician" && <span className="chip ok">{ASSIGNED_LABELS[t.assigned_to]}</span>}
        {t.unread > 0 && <span className="chip solid">{t.unread} new</span>}
      </span>
    </button>
  );
}

function Detail({ threadId, onChanged }) {
  const { me } = useSession();
  const { data, error, loading, reload } = useApi(`/messages/threads/${threadId}`);
  const [thread, setThread] = useState(null);
  const [text, setText] = useState("");
  const [draftId, setDraftId] = useState(null);
  const [busy, setBusy] = useState(null); // "send" | "draft" | "ack" | "assign"
  const [actionError, setActionError] = useState(null);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    if (data) {
      setThread(data);
      onChanged();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2600);
    return () => clearTimeout(t);
  }, [toast]);

  async function run(kind, fn, done) {
    setBusy(kind);
    setActionError(null);
    try {
      await fn();
      if (done) setToast(done);
      onChanged();
    } catch (e) {
      setActionError(e.message);
    } finally {
      setBusy(null);
    }
  }

  const send = () => run("send", async () => {
    setThread(await api(`/messages/threads/${threadId}/messages`, { method: "POST", body: { body: text, draft_id: draftId } }));
    setText("");
    setDraftId(null);
  }, "Reply sent");

  const draft = () => run("draft", async () => {
    const d = await api(`/messages/threads/${threadId}/draft`, { method: "POST" });
    setText(d.body);
    setDraftId(d.id);
    setThread((t) => ({ ...t, drafts: [...(t.drafts || []), d] }));
  });

  const loadDraft = (d) => {
    setText(d.body);
    setDraftId(d.id);
  };

  const discard = (d) => run("discard", async () => {
    await api(`/messages/drafts/${d.id}/discard`, { method: "POST" });
    setThread((t) => ({ ...t, drafts: t.drafts.filter((x) => x.id !== d.id) }));
    if (draftId === d.id) {
      setDraftId(null);
      setText("");
    }
  }, "Draft discarded");

  const acknowledge = () => run("ack", async () => {
    setThread(await api(`/messages/threads/${threadId}/acknowledge-flag`, { method: "POST" }));
  }, "Red flag acknowledged");

  const assign = (to) => run("assign", async () => {
    setThread(await api(`/messages/threads/${threadId}/assign`, { method: "POST", body: { to } }));
  }, `Handed to ${ASSIGNED_LABELS[to].toLowerCase()}`);

  if (error) return <div className="error-box">{error.message} <button className="btn sm" onClick={reload}>Try again</button></div>;
  if (loading && !thread) return <div className="card stack"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>;
  if (!thread) return null;

  const activeDraft = thread.drafts?.find((d) => d.id === draftId);
  const pending = (thread.drafts || []).filter((d) => d.source === "agent_pending_approval");
  const isClinician = me.role === "clinician";

  return (
    <section className="card stack" aria-labelledby="inbox-thread-title">
      <header className="row between wrap" style={{ gap: 10 }}>
        <div>
          <div className="eyebrow">{thread.patient.name}</div>
          <h2 id="inbox-thread-title" className="page-title" style={{ fontSize: 22 }}>{thread.subject}</h2>
          <div className="row wrap" style={{ gap: 6, marginTop: 6 }}>
            {thread.priority === "urgent" && <span className="chip warn">Urgent</span>}
            {thread.category_label && <span className="chip">{thread.category_label}</span>}
            <span className="chip ok">With {ASSIGNED_LABELS[thread.assigned_to].toLowerCase()}</span>
            {thread.kind !== "care_team" && <span className="chip">{thread.kind === "previsit" ? "Pre-visit interview" : "Follow-up check-ins"}</span>}
          </div>
          {thread.triage_reason && <p className="tiny muted" style={{ marginTop: 6 }}>Triage: {thread.triage_reason}</p>}
        </div>
        {thread.can_reply && (
          isClinician
            ? thread.assigned_to === "clinician" && !thread.flagged && (
              <button className="btn sm" disabled={busy === "assign"} onClick={() => assign("front_desk")}>Hand to front desk</button>
            )
            : <button className="btn sm" disabled={busy === "assign"} onClick={() => assign("clinician")}>Send to clinician</button>
        )}
      </header>

      {thread.flagged && !thread.flag_acknowledged && (
        <div className="banner warn row between wrap" role="alert">
          <span className="row" style={{ gap: 8 }}><Warning size={16} /> Red flag: {thread.flag_reason}. The patient was shown emergency guidance.</span>
          {isClinician && <button className="btn danger sm" disabled={busy === "ack"} onClick={acknowledge}>Acknowledge</button>}
        </div>
      )}

      {thread.previsit_answers?.length > 0 && (
        <div className="msg-answers stack" style={{ gap: 6 }}>
          <span className="small strong">Pre-visit answers</span>
          {thread.previsit_answers.map((a) => (
            <div key={a.question_text} className="small">
              <span className="muted">{a.question_text}</span> {a.answer_text}
              {a.mentions_symptoms && <span className="chip warn" style={{ marginLeft: 6 }}>Symptoms mentioned</span>}
            </div>
          ))}
        </div>
      )}

      <MessageList thread={thread} viewerId={me.id} viewerSide={(m) => m.author_kind === "clinician" || m.author_kind === "staff"} />

      {pending.map((d) => (
        <div key={d.id} className="msg-draft stack">
          <span className="small strong row" style={{ gap: 6 }}><Sparkle size={13} /> Doctor Agent answer waiting for your approval</span>
          <span className="small">{d.body}</span>
          <span className="tiny muted">Quoted from your approved education content. Not sent to the patient.</span>
          <div className="row wrap" style={{ gap: 6 }}>
            <button className="btn sm" onClick={() => loadDraft(d)}>Review in reply box</button>
            <button className="btn ghost sm" disabled={busy === "discard"} onClick={() => discard(d)}><Close size={13} /> Discard</button>
          </div>
        </div>
      ))}

      {actionError && <div className="error-box">{actionError}</div>}
      {thread.can_reply ? (
        <Composer id="inbox-reply" label={activeDraft ? "Reply (drafted by Bioverse, edit before sending)" : "Reply"}
                  value={text} onChange={setText} onSubmit={send} busy={busy === "send"}
                  placeholder="Write a reply to the patient">
          {activeDraft && (
            <span className="tiny muted row" style={{ gap: 4 }}>
              <Sparkle size={12} /> {activeDraft.produced_by.includes("claude") ? "AI draft" : "Template draft"}, not sent until you send it
            </span>
          )}
          <button type="button" className="btn" disabled={busy === "draft"} onClick={draft}>
            <Sparkle size={14} /> {busy === "draft" ? "Drafting…" : "Draft reply with AI"}
          </button>
        </Composer>
      ) : (
        <p className="small muted">This conversation is with the clinician. Only the front desk and nurse-triage threads can be answered from here.</p>
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
    </section>
  );
}

export default function Inbox() {
  const { me } = useSession();
  const [params, setParams] = useSearchParams();
  const selected = params.get("thread");
  const list = useApi("/messages/threads");
  const [filter, setFilter] = useState("waiting");

  const threads = list.data || [];
  const shown = filter === "waiting" ? threads.filter((t) => t.awaiting_since || (t.flagged && !t.flag_acknowledged)) : threads;

  return (
    <WorkspaceLayout>
      <div className="row between wrap" style={{ marginBottom: 16, gap: 10 }}>
        <div>
          <h1 className="page-title">Inbox</h1>
          <div className="page-sub">
            {me.role === "staff" ? "Front desk and nurse-triage messages" : "Patient messages, urgent first, then longest waiting"}
          </div>
        </div>
        <div className="row msg-tabs" role="group" aria-label="Filter">
          <button className={`btn sm ${filter === "waiting" ? "dark" : ""}`} aria-pressed={filter === "waiting"} onClick={() => setFilter("waiting")}>
            Needs reply {threads.length ? `(${threads.filter((t) => t.awaiting_since || (t.flagged && !t.flag_acknowledged)).length})` : ""}
          </button>
          <button className={`btn sm ${filter === "all" ? "dark" : ""}`} aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All</button>
        </div>
      </div>
      <div className="ws-grid">
        <section className="span-4 card stack msg-inbox-list" aria-label="Threads">
          <span className="card-title row" style={{ gap: 8 }}><InboxIcon size={18} /> Threads</span>
          {list.error && <div className="error-box">{list.error.message} <button className="btn sm" onClick={list.reload}>Try again</button></div>}
          {list.loading && !list.data && <div className="stack"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>}
          {list.data && shown.length === 0 && (
            <p className="small muted">{filter === "waiting" ? "Nothing waiting. All caught up." : "No messages yet."}</p>
          )}
          {shown.map((t) => (
            <ThreadItem key={t.id} t={t} selected={t.id === selected} onOpen={(id) => setParams({ thread: id })} />
          ))}
        </section>
        <div className="span-8">
          {selected
            ? <Detail key={selected} threadId={selected} onChanged={list.reload} />
            : <div className="card empty"><Chat size={20} /> Choose a thread to read and reply.</div>}
        </div>
      </div>
    </WorkspaceLayout>
  );
}
