import { useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { fmtDate, fmtDateTime } from "../../format.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import "./invites.css";

const STATUS = { pending: "Waiting", locked: "Locked", accepted: "Joined", expired: "Expired", revoked: "Withdrawn" };
const VIA = { google: "Google", entra: "Microsoft", okta: "Okta", email: "email code" };
const FILTERS = [["", "All"], ["pending", "Waiting"], ["accepted", "Joined"], ["expired", "Expired"], ["revoked", "Withdrawn"]];

function statusOf(i) {
  return i.locked ? "locked" : i.status;
}

function deliveryNote(d) {
  if (!d || !d.status) return null;
  if (d.status === "sent") return "Emailed.";
  if (d.status === "failed") return "The email didn't go through. Copy the link and share it another way.";
  if ((d.detail || "").includes("allowlist")) return "Not emailed: that address isn't on the outbound allowlist. Copy the link instead.";
  return "Email isn't set up here, so nothing was sent. Copy the link and share it with the patient.";
}

function CopyLink({ link, note }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="inv-copy">
        <label className="sr-only" htmlFor={`link-${link}`}>Invite link</label>
        <input id={`link-${link}`} readOnly value={link} onFocus={(e) => e.target.select()} />
        <button type="button" className="btn sm primary" onClick={copy}>{copied ? "Copied" : "Copy link"}</button>
      </div>
      {note && <div className="small muted" role="status">{note}</div>}
      <div className="tiny muted">This link is shown once. Resend to get a new one; the old link then stops working.</div>
    </div>
  );
}

function NewInvite({ onDone, ways }) {
  const blank = { name: "", email: "", birth_date: "", mrn: "", message: "", days: "14" };
  const [f, setF] = useState(blank);
  const [state, setState] = useState({ busy: false, error: null, sent: null });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setState({ busy: true, error: null, sent: null });
    try {
      const r = await api("/invites", { method: "POST", body: {
        name: f.name, email: f.email, birth_date: f.birth_date, mrn: f.mrn || null, message: f.message || null,
        expires_in_days: Number(f.days) } });
      setF(blank);
      setState({ busy: false, error: null, sent: r });
      onDone();
    } catch (err) {
      setState({ busy: false, error: err.message, sent: null });
    }
  }

  return (
    <form className="card stack" onSubmit={submit} aria-labelledby="new-inv-h">
      <h2 id="new-inv-h" className="card-title">Invite a patient</h2>
      <p className="small muted">
        They'll get a link to join, confirm their date of birth, and sign in{ways.length ? ` with ${ways.join(" or ")}` : ""}.
      </p>
      <div className="inv-form">
        <label className="inv-field"><span>Patient's name</span>
          <input required minLength={2} value={f.name} onChange={set("name")} autoComplete="off" /></label>
        <label className="inv-field"><span>Email</span>
          <input required type="email" value={f.email} onChange={set("email")} autoComplete="off" /></label>
        <label className="inv-field"><span>Date of birth</span>
          <input required type="date" value={f.birth_date} onChange={set("birth_date")}
                 max={new Date().toISOString().slice(0, 10)} /></label>
        <label className="inv-field"><span>MRN or other identifier <span className="muted">(optional)</span></span>
          <input value={f.mrn} onChange={set("mrn")} maxLength={60} autoComplete="off" /></label>
        <label className="inv-field"><span>Link works for</span>
          <select value={f.days} onChange={set("days")}>
            <option value="3">3 days</option><option value="7">7 days</option>
            <option value="14">14 days</option><option value="30">30 days</option>
          </select></label>
        <label className="inv-field wide"><span>Personal message <span className="muted">(optional)</span></span>
          <textarea value={f.message} onChange={set("message")} maxLength={500}
                    placeholder="e.g. Looking forward to seeing you on Tuesday." />
          <span className="inv-hint">Anyone with the link can read this. Don't include clinical details.</span>
        </label>
      </div>
      {state.error && <div className="error-box" role="alert">{state.error}</div>}
      {state.sent && (
        <div className="banner ok stack inv-ready" style={{ gap: 8 }}>
          <div className="strong">Invite ready for {state.sent.name}.</div>
          <CopyLink link={state.sent.link} note={deliveryNote(state.sent.delivery)} />
        </div>
      )}
      <div><button className="btn primary" disabled={state.busy}>{state.busy ? "Sending…" : "Send invite"}</button></div>
    </form>
  );
}

function InviteRow({ inv, onChange }) {
  const [out, setOut] = useState(null);
  const [busy, setBusy] = useState(false);
  const st = statusOf(inv);
  const open = inv.status === "pending" || inv.status === "expired";

  async function act(path, confirmText) {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(true);
    try {
      const r = await api(`/invites/${inv.id}/${path}`, { method: "POST" });
      setOut(r.link ? { link: r.link, note: deliveryNote(r.delivery) } : { note: "Invite withdrawn." });
      onChange();
    } catch (err) {
      setOut({ error: err.message });
    }
    setBusy(false);
  }

  return (
    <>
      <tr className={open ? "" : "done"}>
        <td>
          <div className="strong">{inv.name}</div>
          <div className="small muted">{inv.email}{inv.mrn ? ` · ${inv.mrn}` : ""}</div>
        </td>
        <td>
          <span className={`chip inv-status ${st}`}>{STATUS[st] || st}</span>
          {st === "accepted" && inv.accepted_via && (
            <div className="tiny muted" style={{ marginTop: 4 }}>
              with {VIA[inv.accepted_via] || inv.accepted_via}
              {inv.accepted_email && inv.accepted_email !== inv.email ? ` as ${inv.accepted_email}` : ""}
            </div>
          )}
        </td>
        <td className="small">
          <div>{inv.sent_at ? fmtDateTime(inv.sent_at) : "—"}{inv.send_count > 1 ? ` (sent ${inv.send_count}×)` : ""}</div>
          <div className="muted">{inv.invited_by ? `by ${inv.invited_by}` : ""}</div>
        </td>
        <td className="small">
          {st === "accepted" ? `Joined ${fmtDate(inv.accepted_at)}` : open ? `Until ${fmtDate(inv.expires_at)}` : "—"}
        </td>
        <td className="inv-actions">
          {open && (
            <div className="row wrap" style={{ gap: 6 }}>
              <button type="button" className="btn sm" disabled={busy} onClick={() => act("resend")}>
                {st === "locked" ? "Unlock & resend" : "Resend"}
              </button>
              <button type="button" className="btn sm danger" disabled={busy}
                      onClick={() => act("revoke", `Withdraw the invite for ${inv.name}? The link will stop working.`)}>
                Revoke
              </button>
            </div>
          )}
        </td>
      </tr>
      {out && (
        <tr className="inv-link-row">
          <td colSpan={5}>
            {out.error && <div className="error-box" role="alert">{out.error}</div>}
            {out.link ? <CopyLink link={out.link} note={out.note} /> : out.note && <div className="small" role="status">{out.note}</div>}
          </td>
        </tr>
      )}
    </>
  );
}

export default function Invites() {
  const [filter, setFilter] = useState("");
  const { data, error, loading, reload } = useApi(`/invites${filter ? `?status=${filter}` : ""}`);
  const invites = data?.invites || [];
  const signIn = data?.sign_in;
  const ways = signIn ? [...signIn.providers, ...(signIn.email ? ["an emailed code"] : [])] : [];

  return (
    <WorkspaceLayout>
      <div className="page-head">
        <div>
          <div className="eyebrow">Patients</div>
          <h1 className="page-title">Invite a patient</h1>
          <p className="page-sub">Send a join link, see who has joined, and resend or withdraw links.</p>
        </div>
      </div>
      {error && <div className="error-box">{error.message}</div>}
      <div className="stack">
        {signIn && (
          <div className={`banner ${ways.length ? "info" : "warn"}`}>
            {ways.length
              ? `Invited patients can sign in with ${ways.join(" or ")}.`
              : "No sign-in method is available for patients yet: configure Google sign-in or turn on email codes."}
          </div>
        )}
        <NewInvite onDone={reload} ways={ways} />
        <section className="card stack" aria-labelledby="inv-list-h">
          <div className="row between wrap">
            <h2 id="inv-list-h" className="card-title">Invites</h2>
            <div className="inv-filter" role="group" aria-label="Filter invites">
              {FILTERS.map(([k, label]) => (
                <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)}>{label}</button>
              ))}
            </div>
          </div>
          {loading && !data && <div className="skeleton" />}
          {data && invites.length === 0 && <p className="small muted">No invites here yet.</p>}
          {invites.length > 0 && (
            <table className="inv-table">
              <thead>
                <tr><th scope="col">Patient</th><th scope="col">Status</th><th scope="col">Sent</th>
                  <th scope="col">Expires</th><th scope="col"><span className="sr-only">Actions</span></th></tr>
              </thead>
              <tbody>{invites.map((i) => <InviteRow key={i.id} inv={i} onChange={reload} />)}</tbody>
            </table>
          )}
        </section>
      </div>
    </WorkspaceLayout>
  );
}
