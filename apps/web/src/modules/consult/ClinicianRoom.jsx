import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { useSession } from "../../session.jsx";
import { WorkspaceLayout } from "../../layouts.jsx";
import { fmtDateTime } from "../../format.js";
import { Back, Warning } from "../../icons.jsx";
import { Composer, MODE_LONG, StatusChip, Thread, useConsult, useToast, VideoIcon } from "./shared.jsx";

function List({ title, items, empty }) {
  return (
    <div className="stack" style={{ gap: 4 }}>
      <span className="eyebrow">{title}</span>
      {items?.length ? (
        <ul className="consult-list small">{items.map((x) => <li key={x}>{x}</li>)}</ul>
      ) : <span className="small muted">{empty}</span>}
    </div>
  );
}

function PatientContext({ c }) {
  const ctx = c.patient_context;
  const intake = c.intake;
  return (
    <aside className="stack" aria-label="Patient context">
      <section className="card stack">
        <div className="row between wrap">
          <h2 className="card-title">Pre-consult summary</h2>
          <span className="tiny muted">{c.intake_produced_by?.endsWith("/claude") ? "AI draft" : "Rules summary"} · for clinicians</span>
        </div>
        {intake ? (
          <>
            <p className="small">{intake.summary}</p>
            {intake.key_points?.length > 0 && <List title="Notice first" items={intake.key_points} />}
            <List title="Questions to ask" items={intake.suggested_questions} />
          </>
        ) : <p className="small muted">No summary yet.</p>}
      </section>
      <section className="card stack">
        <h2 className="card-title">{ctx.name}, {ctx.age}{ctx.pronouns ? ` · ${ctx.pronouns}` : ""}</h2>
        <span className="small muted">Prefers {ctx.preferred_language} · Phone {ctx.phone || "not on file"}</span>
        <div className={ctx.allergies.length ? "banner warn small" : "small muted"}>
          {ctx.allergies.length ? <><Warning size={14} /> Allergies: {ctx.allergies.join(", ")}</> : "No allergies recorded"}
        </div>
        <List title="Active medicines" items={ctx.medications} empty="None on record" />
        <List title="Recent results" items={ctx.recent_results} empty="None in the last year" />
        <List title="History" items={ctx.history} empty="Nothing recorded" />
      </section>
    </aside>
  );
}

function CompleteForm({ c, onDone }) {
  const drugs = useApi("/pharmacy/drugs");
  const [summary, setSummary] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [rxOn, setRxOn] = useState(false);
  const [rx, setRx] = useState({ drug_code: "", strength: "", sig: "", quantity: "30", refills: "0" });
  const [check, setCheck] = useState(null);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setCheck(null);
    setAck(false);
    if (!rxOn || !rx.drug_code) return;
    api(`/consultations/${c.id}/prescribe-check?drug_code=${rx.drug_code}`).then(setCheck).catch((e) => setErr(e.message));
  }, [rxOn, rx.drug_code, c.id]);

  const warnings = (check?.warnings || []).filter((w) => w.involves_candidate);
  const major = warnings.some((w) => w.severity === "major");

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    const body = { summary: summary.trim(), follow_up: followUp.trim() || null };
    if (rxOn) {
      body.prescription = { drug_code: rx.drug_code, strength: rx.strength.trim(), sig: rx.sig.trim(),
                            quantity: Number(rx.quantity), refills: Number(rx.refills), acknowledge_interactions: ack };
    }
    try {
      onDone(await api(`/consultations/${c.id}/complete`, { method: "POST", body }));
    } catch (ex) {
      setErr(ex.message);
      setBusy(false);
    }
  }

  const rxReady = !rxOn || (rx.drug_code && rx.strength.trim() && rx.sig.trim().length >= 5 && Number(rx.quantity) > 0 && (!major || ack));
  return (
    <form className="card stack" onSubmit={submit} aria-labelledby="complete-title">
      <h2 id="complete-title" className="card-title">Complete the consult</h2>
      <div className="field">
        <label htmlFor="sum" className="small strong">Visit summary for the patient</label>
        <textarea id="sum" className="edit" maxLength={4000} value={summary} onChange={(e) => setSummary(e.target.value)}
                  placeholder="What you found, what to do, in plain language" />
      </div>
      <div className="field">
        <label htmlFor="fu" className="small strong">Follow-up (optional)</label>
        <textarea id="fu" className="edit" style={{ minHeight: 56 }} maxLength={1000} value={followUp} onChange={(e) => setFollowUp(e.target.value)} />
      </div>
      <label className="toggle-row">
        <input type="checkbox" checked={rxOn} onChange={(e) => setRxOn(e.target.checked)} disabled={!c.can.prescribe} />
        <span className="small">Issue a prescription{!c.can.prescribe ? " (needs a verified license)" : ""}</span>
      </label>
      {rxOn && (
        <div className="stack rx-form" style={{ gap: 10 }}>
          <div className="consult-filters">
            <div className="field">
              <label htmlFor="rx-drug" className="small strong">Medicine</label>
              <select id="rx-drug" value={rx.drug_code} onChange={(e) => setRx({ ...rx, drug_code: e.target.value })}>
                <option value="">Choose</option>
                {drugs.data?.drugs.map((d) => <option key={d.code} value={d.code}>{d.name}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="rx-str" className="small strong">Strength</label>
              <input id="rx-str" value={rx.strength} maxLength={40} onChange={(e) => setRx({ ...rx, strength: e.target.value })} placeholder="e.g. 250 mg" />
            </div>
            <div className="field">
              <label htmlFor="rx-qty" className="small strong">Quantity</label>
              <input id="rx-qty" type="number" min="1" max="365" value={rx.quantity} onChange={(e) => setRx({ ...rx, quantity: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="rx-ref" className="small strong">Refills</label>
              <select id="rx-ref" value={rx.refills} onChange={(e) => setRx({ ...rx, refills: e.target.value })}>
                {[0, 1, 2, 3, 5, 11].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
          </div>
          <div className="field">
            <label htmlFor="rx-sig" className="small strong">Directions</label>
            <input id="rx-sig" value={rx.sig} maxLength={300} onChange={(e) => setRx({ ...rx, sig: e.target.value })} placeholder="Take 1 tablet by mouth once daily" />
          </div>
          {check && (
            <div className="stack" style={{ gap: 6 }}>
              {check.allergies.length > 0 && <div className="banner warn small">Allergies on record: {check.allergies.join(", ")}</div>}
              {warnings.map((w) => (
                <div key={w.id} className={`banner ${w.severity === "advisory" ? "info" : "warn"} small`}>
                  <Warning size={14} /> <span>{w.between.join(" + ")}: {w.summary}</span>
                </div>
              ))}
              {warnings.length === 0 && <span className="small muted">No interactions on the curated list.</span>}
              {major && (
                <label className="toggle-row">
                  <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                  <span className="small">I've reviewed this serious interaction and still want to prescribe</span>
                </label>
              )}
              <span className="tiny muted">{check.notice}</span>
            </div>
          )}
        </div>
      )}
      {err && <div className="error-box small">{err}</div>}
      <button className="btn primary" disabled={busy || summary.trim().length < 10 || !rxReady}>Complete and send summary</button>
    </form>
  );
}

export default function ClinicianRoom() {
  const { consultId } = useParams();
  const { me } = useSession();
  const { data: c, error, loading, setData } = useConsult(consultId);
  const [toast, setToast] = useToast();
  const [reason, setReason] = useState("");
  const [err, setErr] = useState(null);

  useEffect(() => { document.title = "Online consult · Bioverse"; }, []);

  async function act(path, body, msg) {
    setErr(null);
    try {
      setData(await api(`/consultations/${consultId}/${path}`, { method: "POST", body }));
      if (msg) setToast(msg);
      return true;
    } catch (e) {
      setErr(e.message);
      return false;
    }
  }

  return (
    <WorkspaceLayout>
      <div className="consult-ws stack">
        <Link to="/clinician/consults" className="btn ghost sm consult-back"><Back size={16} /> Online consults</Link>
        {error && !c && <div className="error-box">{error.status === 404 ? "This consult isn't assigned to you or open in your specialty." : error.message}</div>}
        {loading && !c && <div className="card"><div className="skeleton" /></div>}
        {c && (
          <>
            <header className="card stack">
              <div className="row between wrap" style={{ alignItems: "flex-start" }}>
                <div className="stack" style={{ gap: 2 }}>
                  <h1 className="page-title">{c.patient.name}</h1>
                  <span className="small muted">
                    {c.specialty} · {MODE_LONG[c.mode]}{c.scheduled_at ? ` · ${fmtDateTime(c.scheduled_at)}` : ""} · requested {fmtDateTime(c.created_at)}
                    {c.first_available ? " · first available" : ""}
                  </span>
                </div>
                <StatusChip status={c.status} label={c.status_label} />
              </div>
              {c.flagged && (
                <div className="banner warn small" role="alert"><Warning size={14} /> Red flag: {c.flag_reason}. The patient was shown emergency guidance.</div>
              )}
              <p className="small"><span className="strong">Reason: </span>{c.reason}</p>
              {!c.credentialed && <div className="banner warn small">Your license isn't verified and in date, so you can't accept or prescribe.</div>}
              <div className="row wrap" style={{ gap: 8 }}>
                {c.can.claim && <button className="btn primary" onClick={() => act("claim", undefined, "Claimed. It's yours.")}>Claim</button>}
                {c.can.accept && <button className="btn primary" onClick={() => act("accept", undefined, "Accepted")}>Accept</button>}
                {c.can.start && <button className="btn primary" onClick={() => act("start", undefined, "Consult started")}>Start consult</button>}
                {c.can.join_video && <Link className="btn dark" to={`/clinician/consults/${c.id}/video`}><VideoIcon /> Join video call</Link>}
              </div>
              {(c.can.decline || c.can.cancel) && (
                <div className="row wrap" style={{ gap: 8, alignItems: "flex-end" }}>
                  <div className="field" style={{ flex: "1 1 240px" }}>
                    <label htmlFor="why" className="small strong">{c.can.decline ? "Reason to decline" : "Reason to cancel"} (sent to the patient)</label>
                    <input id="why" value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)} />
                  </div>
                  <button className="btn" disabled={reason.trim().length < 3}
                          onClick={() => act(c.can.decline ? "decline" : "cancel", { reason }, c.can.decline ? "Declined" : "Cancelled")}>
                    {c.can.decline ? "Decline" : "Cancel consult"}
                  </button>
                </div>
              )}
              {err && <div className="error-box small">{err}</div>}
            </header>

            <div className="consult-room-grid">
              <PatientContext c={c} />
              <div className="stack">
                <section className="card stack" aria-labelledby="msgs">
                  <h2 id="msgs" className="card-title">Messages</h2>
                  <Thread messages={c.messages} viewerId={me.id} />
                  {c.can.message
                    ? <Composer onSend={(t) => act("messages", { body: t })} placeholder={c.status === "accepted" ? "Your first message starts the consult" : "Reply to the patient"} />
                    : <p className="tiny muted">{c.status === "requested" ? "Accept or claim the consult to reply." : "Messages are closed."}</p>}
                </section>
                {c.can.complete && <CompleteForm c={c} onDone={(d) => { setData(d); setToast("Completed. The patient can read your summary."); }} />}
                {c.status === "completed" && (
                  <section className="card stack">
                    <h2 className="card-title">Summary sent</h2>
                    <p className="small">{c.summary}</p>
                    {c.follow_up && <p className="small"><span className="strong">Follow-up: </span>{c.follow_up}</p>}
                    {c.prescription && <p className="small"><span className="strong">Prescribed: </span>{c.prescription.drug_name} {c.prescription.strength} · {c.prescription.sig}</p>}
                    {c.rating && <p className="small muted">Patient rating: {c.rating.stars} of 5</p>}
                  </section>
                )}
              </div>
            </div>
          </>
        )}
      </div>
      {toast}
    </WorkspaceLayout>
  );
}
