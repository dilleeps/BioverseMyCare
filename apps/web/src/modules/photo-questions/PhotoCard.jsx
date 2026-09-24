import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api.js";
import { Arrow, Check, Phone, Shield, Warning } from "../../icons.jsx";
import { useDisplayPrefs } from "../accessibility/prefs.js";
import { speak } from "../accessibility/speech.js";
import { kindLabel } from "./image.js";

const telHref = (phone) => `tel:${String(phone).replace(/[^\d+]/g, "")}`;

function EmergencyBlock({ r }) {
  return (
    <section className="emergency stack" role="alert">
      <div className="row strong" style={{ color: "var(--alert-strong)" }}><Warning size={20} /> {r.headline}</div>
      <p style={{ color: "var(--alert-strong)" }}>{r.message}</p>
      {r.crisis_line && <a className="call" href={`tel:${r.crisis_line}`}><Phone size={20} /> Call or text {r.crisis_line}</a>}
      <a className="call" href={`tel:${r.emergency_number}`}><Phone size={20} /> Call {r.emergency_number}</a>
      {r.flags?.length > 0 && <p className="small" style={{ color: "var(--alert-strong)" }}>Noted: {r.flags.join(", ")}.</p>}
      {r.care_team_notified && <p className="small" style={{ color: "var(--alert-strong)" }}>Your care team has been notified.</p>}
    </section>
  );
}

function AskPharmacist({ entry, r }) {
  const [state, setState] = useState({ busy: false, thread: null, error: null });
  async function send() {
    setState({ busy: true, thread: null, error: null });
    const seen = r.extracted?.drug_name
      ? `${r.extracted.drug_name}${r.extracted.strength ? ` ${r.extracted.strength}` : ""}`
      : r.seen || "a name I couldn't read";
    const body = [
      "I took a photo of a medicine and Bioverse couldn't confirm it for me. Could a pharmacist help?",
      `What the package seemed to say: ${seen}.`,
      entry.question ? `My question: ${entry.question}` : null,
    ].filter(Boolean).join("\n");
    try {
      const thread = await api("/messages/threads", {
        method: "POST",
        body: { subject: "Question for a pharmacist about a medicine", body },
      });
      setState({ busy: false, thread, error: null });
    } catch (e) {
      setState({ busy: false, thread: null, error: e.message });
    }
  }
  if (state.thread) {
    return (
      <div className="banner ok" role="status">
        <Check size={16} /> Sent to your care team for a pharmacist.{" "}
        <Link to={`/messages?thread=${state.thread.id}`}>Open the message</Link>
      </div>
    );
  }
  return (
    <>
      <button type="button" className="btn" onClick={send} disabled={state.busy}>
        {state.busy ? "Sending…" : "Ask a pharmacist"}
      </button>
      {state.error && <div className="error-box">{state.error}</div>}
    </>
  );
}

function TypedName({ onSubmit, busy }) {
  const [name, setName] = useState("");
  return (
    <form className="row wrap photo-typed" onSubmit={(e) => { e.preventDefault(); if (name.trim()) onSubmit(name.trim()); }}>
      <label htmlFor="photo-typed-name" className="sr-only">Medicine name printed on the box</label>
      <input id="photo-typed-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={120}
             placeholder="Name on the box, e.g. atorvastatin 20 mg" autoComplete="off" />
      <button type="submit" className="btn primary" disabled={!name.trim() || busy}>Check</button>
    </form>
  );
}

function Checklist({ checklist, onAnswer, busy }) {
  const [selected, setSelected] = useState([]);
  const toggle = (id) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row" style={{ color: "var(--alert)", gap: 8 }}><Warning size={16} /> <span className="strong">{checklist.question}</span></div>
      {checklist.options.map((o) => (
        <button key={o.id} type="button" className="safety-option" aria-pressed={selected.includes(o.id)} disabled={busy}
                onClick={() => toggle(o.id)}>
          {o.label} {selected.includes(o.id) && <Check size={16} />}
        </button>
      ))}
      {selected.length > 0 ? (
        <button type="button" className="btn danger" disabled={busy} onClick={() => onAnswer(selected)}>Send these answers</button>
      ) : (
        <button type="button" className="btn primary" disabled={busy} onClick={() => onAnswer(["none"])}>None of these <Arrow size={18} /></button>
      )}
    </div>
  );
}

function SendToCareTeam({ entry, checklist, onSent }) {
  const [note, setNote] = useState(entry.question || "");
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function send(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSent(await api("/photo-questions/skin/submissions", {
        method: "POST",
        body: { image: entry.image, media_type: entry.media_type, note: note.trim() || null, checklist, consent: true },
      }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="stack photo-consent" onSubmit={send} style={{ gap: 8 }}>
      <label className="stack" style={{ gap: 6 }}>
        <span className="small strong">Note for your care team</span>
        <textarea rows={2} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)}
                  placeholder="Where it is, how long you've had it, whether it has changed" />
      </label>
      <label className="photo-consent-check">
        <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
        <span className="small">Send this photo and note to my care team. It will be saved in my record so they can see it.</span>
      </label>
      {error && <div className="error-box">{error}</div>}
      <button type="submit" className="btn primary" disabled={!agree || busy}>{busy ? "Sending…" : "Send to my care team"}</button>
    </form>
  );
}

function SendReport({ r }) {
  const navigate = useNavigate();
  const [text, setText] = useState(r.text);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function send() {
    setBusy(true);
    setError(null);
    try {
      await api("/documents/text", { method: "POST", body: { text } });
      navigate(r.to || "/records");
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }
  return (
    <div className="stack" style={{ gap: 8 }}>
      <label htmlFor="photo-report-text" className="small strong">Text I read (you can correct it)</label>
      <textarea id="photo-report-text" className="photo-report-text" rows={6} value={text} onChange={(e) => setText(e.target.value)} />
      {error && <div className="error-box">{error}</div>}
      <button type="button" className="btn primary" disabled={busy || !text.trim()} onClick={send}>
        {busy ? "Sending…" : "Send to my records to check"}
      </button>
    </div>
  );
}

// One photo question and everything that follows from it. Holds the photo in memory only.
export default function PhotoCard({ entry }) {
  const [result, setResult] = useState(entry.result);
  const [checklist, setChecklist] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const { read_aloud: readAloud } = useDisplayPrefs();
  const r = result;

  useEffect(() => {
    if (!readAloud || !r) return;
    const emergency = r.status === "emergency";
    const numbers = emergency ? ` Call ${r.emergency_number}.` : "";
    speak(`${r.headline || ""}. ${r.message || ""}${numbers}`, { interrupt: emergency });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [r]);

  async function follow(extra) {
    setBusy(true);
    setError(null);
    try {
      const body = { kind: entry.kind, question: entry.question, ...extra };
      if (!extra.typed_name) Object.assign(body, { image: entry.image, media_type: entry.media_type });
      setResult(await api("/photo-questions", { method: "POST", body }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const medicine = entry.kind === "medicine";
  return (
    <section className="card stack widget photo-card" aria-label={`Photo question: ${kindLabel(entry.kind)}`}>
      <div className="row photo-card-head">
        {entry.previewUrl && <img src={entry.previewUrl} alt="" className="photo-thumb" />}
        <div style={{ minWidth: 0 }}>
          <div className="small muted">{kindLabel(entry.kind)}</div>
          {r.status !== "emergency" && <div className="card-title">{r.headline}</div>}
        </div>
      </div>

      {r.status === "emergency" ? <EmergencyBlock r={r} /> : r.message && <p>{r.message}</p>}

      {r.warnings?.map((w) => <div key={w} className="banner warn"><Warning size={16} /> {w}</div>)}
      {r.question_reply && <p className="photo-note">{r.question_reply}</p>}

      {r.info && (
        <details className="photo-info">
          <summary>About {r.prescription?.drug_name?.toLowerCase() || "this medicine"}</summary>
          <div className="stack" style={{ gap: 8, marginTop: 8 }}>
            <p>{r.info.what_for}</p>
            {r.info.good_to_know?.map((g) => <p key={g} className="small">{g}</p>)}
            <div className="small"><span className="strong">Common side effects:</span> {r.info.common_side_effects.join(", ")}.</div>
            <div className="small"><span className="strong">Call your doctor if you have:</span> {r.info.call_if.join("; ")}.</div>
            <p className="tiny muted">Demo information, curated for this demo. Not complete and not medical advice.</p>
          </div>
        </details>
      )}

      {medicine && ["needs_name", "unreadable", "unmatched"].includes(r.status) && (
        <TypedName busy={busy} onSubmit={(name) => follow({ typed_name: name })} />
      )}
      {medicine && r.offer_pharmacist && <AskPharmacist entry={entry} r={r} />}

      {r.status === "checklist" && (
        <Checklist checklist={r.checklist} busy={busy} onAnswer={(ans) => { setChecklist(ans); follow({ checklist: ans }); }} />
      )}
      {(r.status === "routine" || r.status === "urgent") && (
        <>
          {r.status === "urgent" && r.care_team_phone && (
            <a className="btn danger" href={telHref(r.care_team_phone)}><Phone size={18} /> Call my care team</a>
          )}
          <SendToCareTeam entry={entry} checklist={checklist || ["none"]} onSent={setResult} />
          <Link className="btn" to={r.book_dermatology}>Book a dermatology visit <Arrow size={18} /></Link>
        </>
      )}
      {r.status === "sent" && (
        <div className="banner ok" role="status"><Check size={16} /> Your photo is with your care team. <Link to="/ask/photo?view=sent">See photos you've sent</Link></div>
      )}

      {r.status === "report_text" && <SendReport r={r} />}
      {["report_link", "not_a_report"].includes(r.status) && (
        <Link className="btn primary" to={r.to}>Open my records <Arrow size={18} /></Link>
      )}

      {error && <div className="error-box" role="alert">{error}</div>}
      {r.caution && <p className="small strong photo-caution"><Shield size={14} /> {r.caution}</p>}
      {entry.kind === "skin" && r.status !== "emergency" && (
        <p className="tiny muted">Bioverse doesn't diagnose skin conditions from photos.</p>
      )}
    </section>
  );
}
