import { useEffect, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { useSession } from "../../session.jsx";
import { fmtDate, fmtDateTime, fmtShortDate } from "../../format.js";
import { Chevron, Plus, Warning } from "../../icons.jsx";
import NewReferral from "./NewReferral.jsx";

const ACTION_LABEL = {
  sent: "Send",
  accepted: "Accept",
  declined: "Decline",
  scheduled: "Mark booked",
  completed: "Mark completed",
  cancelled: "Cancel referral",
};
const HISTORY_LABEL = {
  draft: "Created", sent: "Sent", accepted: "Accepted", scheduled: "Booked", completed: "Completed",
  declined: "Declined", expired: "Expired", cancelled: "Cancelled",
};
const REQUESTER_ONLY = ["sent", "cancelled"];
const STATUS_TONE = { accepted: "ok", scheduled: "ok", completed: "", declined: "warn", expired: "warn", cancelled: "" };

function Flags({ flags }) {
  if (!flags?.length) return null;
  return (
    <div className="row wrap" style={{ gap: 6 }}>
      {flags.map((f) => <span key={f.code} className="chip warn"><Warning size={12} /> {f.label}</span>)}
    </div>
  );
}

function Detail({ id, onChanged, me }) {
  const { data, error, loading, reload } = useApi(`/referrals/${id}`);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [declining, setDeclining] = useState(false);
  const [note, setNote] = useState("");

  async function run(fn) {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      await reload();
      onChanged();
    } catch (e) {
      setActionError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const move = (status, withNote) => run(async () => {
    await api(`/referrals/${id}/status`, { method: "POST", body: { status, note: withNote ? note : null } });
    setDeclining(false);
    setNote("");
  });

  const toggleDoc = (doc) => run(() => {
    const provided = data.provided_documents.includes(doc)
      ? data.provided_documents.filter((d) => d !== doc)
      : [...data.provided_documents, doc];
    return api(`/referrals/${id}/documents`, { method: "PUT", body: { provided } });
  });

  if (error) return <div className="error-box small">{error.message}</div>;
  if (loading && !data) return <div className="skeleton" />;
  if (!data) return null;
  const isRequester = me.practitioner_id === data.requester.id;
  const actions = data.actions.filter((a) => isRequester || !REQUESTER_ONLY.includes(a));
  const docsEditable = !["completed", "declined", "expired", "cancelled"].includes(data.status);

  return (
    <div className="rf-detail stack">
      <p className="small" style={{ color: "var(--ink-2)" }}>{data.reason}</p>
      <dl className="rf-dl">
        <dt>Referred by</dt><dd>{data.requester.name}</dd>
        <dt>Sent to</dt><dd>{data.target ? `${data.target.name} · ${data.target.location}` : `Anyone in ${data.specialty}`}</dd>
        <dt>Priority</dt><dd>{data.priority === "urgent" ? "Urgent" : "Routine"}</dd>
        <dt>Valid until</dt><dd>{fmtDate(data.expires_on)}</dd>
        {data.appointment && (<><dt>Booked</dt><dd>{fmtDateTime(data.appointment.starts_at)} · {data.appointment.practitioner_name}</dd></>)}
        {data.status_note && (<><dt>Note</dt><dd>{data.status_note}</dd></>)}
      </dl>

      {data.required_documents.length > 0 && (
        <fieldset className="rf-plain">
          <legend className="small strong">Documents</legend>
          <div className="stack" style={{ gap: 4 }}>
            {data.required_documents.map((d) => {
              const cid = `doc-${id}-${d}`;
              return (
                <div key={d} className="toggle-row">
                  <input id={cid} type="checkbox" checked={data.provided_documents.includes(d)}
                         disabled={busy || !docsEditable} onChange={() => toggleDoc(d)} />
                  <label htmlFor={cid}>{d}</label>
                  {!data.provided_documents.includes(d) && <span className="chip warn">Missing</span>}
                </div>
              );
            })}
          </div>
        </fieldset>
      )}

      <div className="stack" style={{ gap: 4 }}>
        <span className="small strong">History</span>
        <ol className="rf-history">
          {data.history.map((h, i) => (
            <li key={i} className="small">
              <span className="strong">{HISTORY_LABEL[h.to_status] || h.to_status}</span>
              {" "}· {fmtDateTime(h.occurred_at)} · {h.actor}
              {h.note ? <span className="muted"> · {h.note}</span> : null}
            </li>
          ))}
        </ol>
      </div>

      {actionError && <div className="error-box small" role="alert">{actionError}</div>}
      {declining ? (
        <div className="stack" style={{ gap: 6 }}>
          <label htmlFor={`decline-${id}`} className="small strong">Why can't this referral be accepted?</label>
          <textarea id={`decline-${id}`} className="edit" value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
          <div className="row" style={{ gap: 6 }}>
            <button className="btn danger sm" disabled={busy || !note.trim()} onClick={() => move("declined", true)}>Decline referral</button>
            <button className="btn sm" disabled={busy} onClick={() => setDeclining(false)}>Back</button>
          </div>
        </div>
      ) : actions.length > 0 && (
        <div className="row wrap" style={{ gap: 6 }}>
          {actions.map((a) => (
            <button key={a} disabled={busy}
                    className={`btn sm ${a === "accepted" || a === "sent" ? "primary" : a === "cancelled" ? "ghost" : ""}`}
                    onClick={() => (a === "declined" ? setDeclining(true) : move(a, false))}>
              {ACTION_LABEL[a]}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Row({ r, open, onToggle, onChanged, me, showPatient = true }) {
  return (
    <li className={`rf-row ${open ? "open" : ""}`}>
      <button className="rf-row-head" aria-expanded={open} onClick={onToggle}>
        <span className="rf-col-main">
          <span className="strong">{showPatient ? `${r.patient.name} · ` : ""}{r.specialty}</span>
          <span className="tiny muted">
            {r.target ? r.target.name : "Any clinician"} · {r.requester.name}
            {r.sent_at ? ` · sent ${fmtShortDate(r.sent_at)}` : " · not sent"} · {r.age_days} day{r.age_days === 1 ? "" : "s"} old
          </span>
        </span>
        <span className="rf-col-status">
          <span className={`chip ${STATUS_TONE[r.status] ?? ""}`}>{r.status_label}</span>
          {r.priority === "urgent" && <span className="chip warn">Urgent</span>}
        </span>
        <Chevron size={18} />
      </button>
      <div className="rf-row-flags"><Flags flags={r.flags} /></div>
      {open && <Detail id={r.id} onChanged={onChanged} me={me} />}
    </li>
  );
}

export function ReferralList({ path, me, showPatient = true, empty }) {
  const { data, error, loading, reload } = useApi(path);
  const [openId, setOpenId] = useState(null);
  if (error) return <div className="error-box">{error.message}</div>;
  if (loading && !data) return <div className="skeleton" />;
  if (!data?.length) return <p className="small muted">{empty}</p>;
  return (
    <ul className="rf-list">
      {data.map((r) => (
        <Row key={r.id} r={r} me={me} showPatient={showPatient} open={openId === r.id}
             onToggle={() => setOpenId((o) => (o === r.id ? null : r.id))} onChanged={reload} />
      ))}
    </ul>
  );
}

export default function ReferralManager() {
  const { me } = useSession();
  const isClinician = me?.role === "clinician";
  const [view, setView] = useState(isClinician ? "sent" : "incoming");
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState("all");
  const [toast, setToast] = useState(null);
  const { data, error, loading, reload } = useApi(`/referrals?view=${view}`);
  const [openId, setOpenId] = useState(null);

  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(null), 2600);
    return () => clearTimeout(t);
  }, [toast]);

  const rows = data || [];
  const count = (code) => rows.filter((r) => r.flags.some((f) => f.code === code)).length;
  const open = rows.filter((r) => ["draft", "sent", "accepted", "scheduled"].includes(r.status)).length;
  const attention = rows.filter((r) => r.flags.length > 0).length;
  const shown = filter === "attention" ? rows.filter((r) => r.flags.length > 0) : rows;

  const tabs = [
    ...(isClinician ? [["sent", "Sent by me"]] : []),
    ["incoming", "Incoming"],
  ];

  return (
    <WorkspaceLayout>
      <header className="row between wrap" style={{ marginBottom: 18 }}>
        <div>
          <span className="eyebrow">Referral manager</span>
          <h1 className="page-title" style={{ fontSize: 26 }}>Referrals</h1>
          <div className="page-sub">Every referral from sent to seen, with anything that is stuck flagged.</div>
        </div>
        {isClinician && !creating && (
          <button className="btn primary" onClick={() => setCreating(true)}><Plus size={16} /> New referral</button>
        )}
      </header>

      {creating && (
        <div style={{ marginBottom: 18 }}>
          <NewReferral
            onClose={() => setCreating(false)}
            onCreated={(r, sent) => {
              setCreating(false);
              setToast(sent ? `Referral sent to ${r.target?.name || r.specialty}` : "Draft saved");
              setView("sent");
              setOpenId(r.id);
              reload();
            }}
          />
        </div>
      )}

      <div className="rf-tabs" role="tablist" aria-label="Referral lists">
        {tabs.map(([key, label]) => (
          <button key={key} role="tab" aria-selected={view === key} className="rf-tab"
                  onClick={() => { setView(key); setOpenId(null); }}>
            {label}
          </button>
        ))}
      </div>

      <div className="stats rf-stats">
        <div className="stat"><div className="n">{rows.length}</div><div className="tiny muted">In this list</div></div>
        <div className="stat"><div className="n">{open}</div><div className="tiny muted">Open</div></div>
        <div className={`stat ${attention ? "alert" : ""}`}><div className="n">{attention}</div><div className="tiny muted">Need attention</div></div>
        <div className={`stat ${count("leaking") ? "alert" : ""}`}><div className="n">{count("leaking")}</div><div className="tiny muted">Accepted, not booked</div></div>
      </div>

      <section className="card stack" role="tabpanel" aria-label={tabs.find(([k]) => k === view)?.[1]}>
        <div className="row between wrap">
          <div className="row rf-filter" style={{ gap: 6 }} role="group" aria-label="Filter">
            <button className="btn sm" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All</button>
            <button className="btn sm" aria-pressed={filter === "attention"} onClick={() => setFilter("attention")}>Needs attention</button>
          </div>
          <button className="btn sm ghost" onClick={reload} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>
        </div>
        {error && <div className="error-box">{error.message}</div>}
        {loading && !data && <div className="skeleton" />}
        {data && shown.length === 0 && (
          <div className="empty">
            {filter === "attention" ? "Nothing needs attention." : view === "sent" ? "You haven't made any referrals yet." : "No referrals waiting."}
          </div>
        )}
        {shown.length > 0 && (
          <ul className="rf-list">
            {shown.map((r) => (
              <Row key={r.id} r={r} me={me} open={openId === r.id}
                   onToggle={() => setOpenId((o) => (o === r.id ? null : r.id))} onChanged={reload} />
            ))}
          </ul>
        )}
      </section>
      {toast && <div className="toast" role="status">{toast}</div>}
    </WorkspaceLayout>
  );
}
