import { useEffect, useRef, useState } from "react";
import { api } from "../../api.js";
import { Camera, Pill, Report, Skin } from "../../components/frontdoor/icons.jsx";
import { KINDS, checkFile, readAsBase64 } from "./image.js";

const KIND_ICON = { medicine: Pill, skin: Skin, report: Report };
const QUESTION_LABEL = {
  medicine: "What would you like to know? (optional)",
  skin: "A note for your care team (optional)",
  report: "Anything to add? (optional)",
};
const QUESTION_HINT = {
  medicine: "For example: what is this for?",
  skin: "Where it is, how long you've had it, whether it has changed",
  report: "",
};

// Choose a kind, take or pick a photo, preview it, add an optional question, send.
// `onSent({kind, image, media_type, previewUrl, question, result})` gets the first answer.
export default function PhotoFlow({ initialKind = null, onSent, onCancel }) {
  const [kind, setKind] = useState(initialKind);
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);
  const headingRef = useRef(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, [kind, file]);

  function pick(e) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    const problem = checkFile(f);
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    setFile(f);
    setPreviewUrl(URL.createObjectURL(f));
  }

  async function send(e) {
    e.preventDefault();
    e.stopPropagation(); // React events cross portals: never reach the composer form around the sheet
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    try {
      const image = await readAsBase64(file);
      const body = { kind, image, media_type: file.type, question: question.trim() || null };
      const result = await api("/photo-questions", { method: "POST", body });
      onSent({ id: `photo-${Date.now()}`, kind, image, media_type: file.type, previewUrl, question: body.question, result });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!kind) {
    return (
      <div className="stack photo-flow">
        <h2 className="card-title" tabIndex={-1} ref={headingRef}>What is the photo of?</h2>
        {KINDS.map((k) => {
          const Icon = KIND_ICON[k.id];
          return (
            <button key={k.id} type="button" className="photo-kind" onClick={() => setKind(k.id)}>
              <span className="photo-kind-icon"><Icon size={22} /></span>
              <span><span className="strong" style={{ display: "block" }}>{k.label}</span><span className="small muted">{k.help}</span></span>
            </button>
          );
        })}
        {onCancel && <button type="button" className="btn ghost" onClick={onCancel}>Cancel</button>}
      </div>
    );
  }

  const chosen = KINDS.find((k) => k.id === kind);
  return (
    <form className="stack photo-flow" onSubmit={send}>
      <div className="row between wrap">
        <h2 className="card-title" tabIndex={-1} ref={headingRef}>{chosen.label}</h2>
        {!initialKind && (
          <button type="button" className="btn ghost sm" onClick={() => { setKind(null); setFile(null); setPreviewUrl(null); }}>
            Change
          </button>
        )}
      </div>
      <input ref={inputRef} id={`photo-input-${kind}`} className="sr-only" type="file" accept="image/*"
             capture="environment" onChange={pick} tabIndex={-1} />
      {previewUrl ? (
        <figure className="photo-preview">
          <img src={previewUrl} alt="The photo you chose" />
          <button type="button" className="btn sm" onClick={() => inputRef.current?.click()}>Retake</button>
        </figure>
      ) : (
        <button type="button" className="photo-capture" onClick={() => inputRef.current?.click()}>
          <Camera size={30} />
          <span className="strong">Take or choose a photo</span>
          <span className="small muted">JPEG, PNG or WebP, up to 5 MB</span>
        </button>
      )}
      {kind === "skin" && (
        <p className="small muted">Your photo is only saved if you choose to send it to your care team.</p>
      )}
      {kind !== "report" && (
        <label className="stack photo-question" style={{ gap: 6 }}>
          <span className="small strong">{QUESTION_LABEL[kind]}</span>
          <textarea value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500} rows={2}
                    placeholder={QUESTION_HINT[kind]} />
        </label>
      )}
      {error && <div className="error-box" role="alert">{error}</div>}
      <div className="row wrap">
        <button type="submit" className="btn primary" disabled={!file || busy}>{busy ? "Checking…" : "Send photo"}</button>
        {onCancel && <button type="button" className="btn ghost" onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  );
}
