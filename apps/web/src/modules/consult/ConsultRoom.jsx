import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api.js";
import { useSession } from "../../session.jsx";
import { PatientPage } from "../../layouts.jsx";
import { fmtDate, fmtDateTime, initials } from "../../format.js";
import { Back, Check } from "../../icons.jsx";
import {
  Composer, EmergencyCard, fmtMoney, MODE_LONG, ModeIcon, StarIcon, StatusChip, Thread, useConsult, useToast,
  VerifiedBadge, VideoIcon,
} from "./shared.jsx";

const NEXT_STEP = {
  requested: (c) => c.practitioner
    ? `Waiting for ${c.practitioner.name} to accept. We'll let you know.`
    : `Waiting for the first available ${c.specialty.toLowerCase()} clinician. We'll let you know when someone takes it.`,
  accepted: (c) => c.mode === "video"
    ? "Accepted. Join the video call at your time; you can open it early to check your camera."
    : c.mode === "phone" ? "Accepted. Your clinician will call the number on your account at this time."
      : "Accepted. Your clinician will reply here.",
  in_progress: () => "Your consult is under way.",
  completed: () => "Completed. Your summary is below.",
  cancelled: (c) => `Cancelled${c.cancel_reason ? `: ${c.cancel_reason}` : "."}`,
  declined: (c) => `Declined: ${c.decline_reason}`,
};

function RateForm({ consult, onDone }) {
  const [stars, setStars] = useState(0);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [emergency, setEmergency] = useState(null);
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await api(`/consultations/${consult.id}/rating`, { method: "POST", body: { stars, comment: comment.trim() || null } });
      if (r.emergency) setEmergency(r.emergency);
      onDone();
    } catch (ex) {
      setErr(ex.message);
    }
    setBusy(false);
  }
  if (emergency) return <EmergencyCard payload={emergency} />;
  return (
    <form className="card stack" onSubmit={submit} aria-labelledby="rate-title">
      <h2 id="rate-title" className="card-title">How was your consult?</h2>
      <div className="star-pick" role="radiogroup" aria-label="Rating out of 5">
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} type="button" role="radio" aria-checked={stars === n} aria-label={`${n} star${n > 1 ? "s" : ""}`}
                  className={n <= stars ? "on" : ""} onClick={() => setStars(n)}>
            <StarIcon size={26} filled={n <= stars} />
          </button>
        ))}
      </div>
      <label htmlFor="rate-comment" className="small strong">Comment (optional, shown to other patients)</label>
      <textarea id="rate-comment" className="edit" style={{ minHeight: 64 }} maxLength={1000} value={comment}
                onChange={(e) => setComment(e.target.value)} />
      {err && <div className="error-box small">{err}</div>}
      <button className="btn primary" disabled={busy || !stars}>Send rating</button>
    </form>
  );
}

export default function ConsultRoom() {
  const { consultId } = useParams();
  const { me } = useSession();
  const { data: c, error, loading, reload, setData } = useConsult(consultId);
  const [toast, setToast] = useToast();
  const [emergency, setEmergency] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => { document.title = "Online consult · Bioverse"; }, []);

  async function send(text) {
    setErr(null);
    try {
      const r = await api(`/consultations/${consultId}/messages`, { method: "POST", body: { body: text } });
      if (r.emergency) setEmergency(r.emergency);
      setData(r);
      return true;
    } catch (e) {
      setErr(e.message);
      return false;
    }
  }

  async function cancel() {
    if (!window.confirm("Cancel this consult?")) return;
    try {
      setData(await api(`/consultations/${consultId}/cancel`, { method: "POST", body: {} }));
      setToast("Consult cancelled");
    } catch (e) {
      setErr(e.message);
    }
  }

  return (
    <PatientPage wide>
      <div className="consult-page stack" style={{ gap: 14 }}>
        <Link to="/consult" className="btn ghost sm consult-back"><Back size={16} /> Online consults</Link>
        {error && !c && <div className="error-box">{error.status === 404 ? "We couldn't find that consult." : error.message}</div>}
        {loading && !c && <div className="card"><div className="skeleton" /></div>}
        {c && (
          <>
            <header className="card stack">
              <div className="row between wrap" style={{ alignItems: "flex-start" }}>
                <div className="row" style={{ alignItems: "flex-start", minWidth: 0 }}>
                  <span className="avatar consult-avatar">{c.practitioner ? initials(c.practitioner.name) : <ModeIcon mode={c.mode} />}</span>
                  <div className="stack" style={{ gap: 2, minWidth: 0 }}>
                    <h1 className="consult-name">{c.practitioner?.name || `First available · ${c.specialty}`}</h1>
                    <span className="small muted">{c.specialty} · {MODE_LONG[c.mode]}{c.scheduled_at ? ` · ${fmtDateTime(c.scheduled_at)}` : ""}</span>
                    <VerifiedBadge verified={c.practitioner_verified} />
                  </div>
                </div>
                <StatusChip status={c.status} label={c.status_label} />
              </div>
              <p className="small">{NEXT_STEP[c.status](c)}</p>
              <div className="row wrap" style={{ gap: 8 }}>
                {c.can.join_video && (
                  <Link className="btn primary" to={`/consult/${c.id}/video`}><VideoIcon /> Join video call</Link>
                )}
                {c.can.cancel && <button className="btn" onClick={cancel}>Cancel consult</button>}
                {c.status === "declined" && (
                  <Link className="btn primary" to={`/consult?specialty=${encodeURIComponent(c.specialty)}`}>Find another {c.specialty.toLowerCase()} clinician</Link>
                )}
              </div>
              <div className="tiny muted">
                Fee {fmtMoney(c.fee_cents)}{c.estimate ? ` · about ${fmtMoney(c.estimate.patient_cents)} with ${c.estimate.plan_name}` : ""}. {c.fee_notice}
              </div>
            </header>

            {c.flagged && !emergency && (
              <div className="banner warn small" role="alert">
                You told us about a possible emergency in this consult. Online consults are not for emergencies: call 911 if you need help now.
              </div>
            )}
            {emergency && <EmergencyCard payload={emergency} />}

            {c.status === "completed" && (
              <section className="card stack consult-summary" aria-labelledby="sum-title">
                <h2 id="sum-title" className="card-title"><Check size={16} /> Visit summary</h2>
                <p>{c.summary}</p>
                {c.follow_up && <p className="small"><span className="strong">Follow-up: </span>{c.follow_up}</p>}
                {c.prescription && (
                  <p className="small">
                    <span className="strong">Prescription: </span>{c.prescription.drug_name} {c.prescription.strength} · {c.prescription.sig}.{" "}
                    <Link to="/pharmacy">Track it in Pharmacy</Link>
                  </p>
                )}
                <span className="tiny muted">Written by {c.practitioner?.name}, {fmtDate(c.completed_at)}.</span>
              </section>
            )}
            {c.can.rate && !c.rating && <RateForm consult={c} onDone={() => { setToast("Thanks for your rating"); reload(); }} />}
            {c.rating && (
              <p className="small muted">You rated this consult {c.rating.stars} out of 5{c.rating.comment_status === "withheld" ? ". Your comment wasn't published." : "."}</p>
            )}

            <section className="card stack" aria-labelledby="msgs-title">
              <h2 id="msgs-title" className="card-title">Messages</h2>
              <Thread messages={c.messages} viewerId={me.id} />
              {err && <div className="error-box small">{err}</div>}
              {c.can.message
                ? <Composer onSend={send} placeholder="Write to your clinician. For an emergency, call 911." />
                : <p className="tiny muted">Messages are closed for this consult.</p>}
            </section>
            <p className="tiny muted">{c.notice}</p>
          </>
        )}
      </div>
      {toast}
    </PatientPage>
  );
}
