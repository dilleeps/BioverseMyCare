import { useEffect, useRef, useState } from "react";
import { api } from "../../api.js";
import { Camera } from "./icons.jsx";
import { SafetyMessage, StatusChip, readingValue } from "./shared.jsx";

const HINT = { bp: "bp_cuff", glucose: "glucometer", temperature: "thermometer", weight: "scale", spo2: "pulse_oximeter" };
const PHOTO_MEASURES = Object.keys(HINT);
const EMPTY = { systolic: "", diastolic: "", pulse: "", value: "", unit: "", context: "" };

function localNow() {
  const d = new Date();
  d.setSeconds(0, 0);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

// Phone photos can be large: shrink to 1600px JPEG before sending. The photo is never stored.
async function shrink(file) {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = () => reject(new Error("That file isn't an image we can open."));
      i.src = url;
    });
    const scale = Math.min(1, 1600 / Math.max(img.naturalWidth, img.naturalHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.naturalWidth * scale);
    canvas.height = Math.round(img.naturalHeight * scale);
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.85);
  } finally {
    URL.revokeObjectURL(url);
  }
}

function Field({ id, label, children, hint }) {
  return (
    <div className="vt-field">
      <label htmlFor={id} className="small strong">{label}</label>
      {children}
      {hint && <span className="tiny muted">{hint}</span>}
    </div>
  );
}

export default function LogReading({ meta, onSaved, initialMeasure = "bp" }) {
  const [measure, setMeasure] = useState(initialMeasure);
  const [form, setForm] = useState(EMPTY);
  const [takenAt, setTakenAt] = useState(localNow());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [fieldErr, setFieldErr] = useState(null);
  const [result, setResult] = useState(null);
  const [photo, setPhoto] = useState(null);         // { url, status, message, confidence, problem }
  const fileRef = useRef(null);
  const m = meta.measures.find((x) => x.key === measure);

  useEffect(() => { setMeasure(initialMeasure); }, [initialMeasure]);

  function set(k, v) { setForm((f) => ({ ...f, [k]: v })); }

  function pick(key) {
    setMeasure(key);
    setForm(EMPTY);
    setFieldErr(null);
    setErr(null);
    setResult(null);
  }

  async function onPhoto(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setErr(null);
    setResult(null);
    try {
      const dataUrl = await shrink(file);
      setPhoto({ url: dataUrl, status: "reading" });
      const r = await api("/vitals/photo", {
        method: "POST",
        body: { image: dataUrl.split(",")[1], media_type: "image/jpeg", hint: HINT[measure] || null },
      });
      if (r.needs_manual) {
        setPhoto({ url: dataUrl, status: "manual", message: r.message });
        return;
      }
      const p = r.proposal;
      setMeasure(p.measure);
      setForm({
        systolic: p.systolic ?? "", diastolic: p.diastolic ?? "", pulse: p.pulse ?? "", value: p.value ?? "",
        unit: p.unit || "", context: "",
      });
      setPhoto({ url: dataUrl, status: "proposed", message: r.notice, confidence: r.confidence, problem: r.problem });
    } catch (e2) {
      setPhoto(null);
      setErr(e2.message);
    }
  }

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setFieldErr(null);
    const n = (v) => (v === "" || v == null ? null : Number(v));
    const body = {
      measure,
      taken_at: new Date(takenAt).toISOString(),
      note: note.trim() || null,
      source: photo?.status === "proposed" ? "photo" : "manual",
    };
    if (measure === "bp") Object.assign(body, { systolic: n(form.systolic), diastolic: n(form.diastolic), pulse: n(form.pulse) });
    else body.value = n(form.value);
    if (measure === "spo2" && form.pulse !== "") body.pulse = n(form.pulse);
    if (m.units && form.unit) body.unit = form.unit.replace("°", "");
    if (measure === "glucose" && form.context) body.context = form.context;
    try {
      const r = await api("/vitals/readings", { method: "POST", body });
      setResult(r);
      setForm(EMPTY);
      setNote("");
      setPhoto(null);
      setTakenAt(localNow());
      onSaved?.(r);
    } catch (e2) {
      if (e2.detail?.field) setFieldErr(e2.detail);
      else setErr(e2.message);
    } finally {
      setBusy(false);
    }
  }

  const invalid = (f) => fieldErr?.field === f;
  const numInput = (k, props = {}) => (
    <input id={`vt-${k}`} inputMode="decimal" type="number" step="any" value={form[k]} onChange={(e) => set(k, e.target.value)}
           aria-invalid={invalid(k) || undefined} aria-describedby={invalid(k) ? "vt-field-err" : undefined} {...props} />
  );

  return (
    <div className="stack" style={{ gap: 14 }}>
      {result?.safety && <SafetyMessage safety={result.safety} onClose={() => setResult({ ...result, safety: null })} />}
      {result && !result.safety && (
        <div className="banner ok" role="status">
          Saved {readingValue(result.reading.measure || measure, result.reading)}. <StatusChip status={result.reading.status} />
        </div>
      )}
      {result?.note && !result.safety && <p className="small muted">{result.note}</p>}

      <div role="group" aria-label="What did you measure?" className="vt-measure-pick">
        {meta.measures.map((x) => (
          <button key={x.key} type="button" aria-pressed={measure === x.key} onClick={() => pick(x.key)}>{x.label}</button>
        ))}
      </div>

      {PHOTO_MEASURES.includes(measure) && (
        <div className="vt-photo-row">
          <label className="btn" htmlFor="vt-photo">
            <Camera size={18} /> Snap the meter's display
          </label>
          <input ref={fileRef} id="vt-photo" type="file" accept="image/*" capture="environment" className="sr-only" onChange={onPhoto} />
          <span className="tiny muted">We read the numbers for you to check. The photo isn't kept.</span>
        </div>
      )}

      <div className={photo ? "vt-with-photo" : ""}>
        {photo && (
          <figure className="vt-photo">
            <img src={photo.url} alt="Your meter photo" />
            <figcaption className="tiny">
              {photo.status === "reading" && "Reading the display…"}
              {photo.status === "manual" && photo.message}
              {photo.status === "proposed" && (
                <>
                  {photo.message}
                  {photo.confidence === "low" && " The display was hard to read, so check each number."}
                </>
              )}
            </figcaption>
            <button type="button" className="btn sm ghost" onClick={() => setPhoto(null)}>Remove photo</button>
          </figure>
        )}

        <form className="stack" style={{ gap: 12 }} onSubmit={save} noValidate>
          {photo?.problem && <div className="banner warn">{photo.problem}</div>}
          {measure === "bp" ? (
            <div className="vt-fields">
              <Field id="vt-systolic" label="Top number (systolic)">{numInput("systolic", { min: 50, max: 260, required: true })}</Field>
              <Field id="vt-diastolic" label="Bottom number (diastolic)">{numInput("diastolic", { min: 30, max: 160, required: true })}</Field>
              <Field id="vt-pulse" label="Pulse (optional)">{numInput("pulse", { min: 25, max: 250 })}</Field>
            </div>
          ) : (
            <div className="vt-fields">
              <Field id="vt-value" label={`${m.label}${m.units ? "" : ` (${m.unit})`}`}>{numInput("value", { min: 0 })}</Field>
              {m.units && (
                <Field id="vt-unit" label="Unit">
                  <select id="vt-unit" value={form.unit || m.units[0]} onChange={(e) => set("unit", e.target.value)}>
                    {m.units.map((u) => <option key={u} value={u}>{u}</option>)}
                  </select>
                </Field>
              )}
              {measure === "spo2" && <Field id="vt-pulse" label="Pulse (optional)">{numInput("pulse", { min: 25, max: 250 })}</Field>}
              {measure === "glucose" && (
                <Field id="vt-context" label="When">
                  <select id="vt-context" value={form.context} onChange={(e) => set("context", e.target.value)}>
                    <option value="">Not sure</option>
                    {meta.glucose_contexts.map((c) => <option key={c.key} value={c.key}>{c.label[0].toUpperCase() + c.label.slice(1)}</option>)}
                  </select>
                </Field>
              )}
            </div>
          )}
          <div className="vt-fields">
            <Field id="vt-at" label="Taken at">
              <input id="vt-at" type="datetime-local" value={takenAt} max={localNow()} onChange={(e) => setTakenAt(e.target.value)} />
            </Field>
            <Field id="vt-note" label="Note (optional)">
              <input id="vt-note" type="text" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. after a walk" />
            </Field>
          </div>
          {fieldErr && <div id="vt-field-err" className="error-box small" role="alert">{fieldErr.message}</div>}
          {err && <div className="error-box small" role="alert">{err}</div>}
          <button className="btn primary" type="submit" disabled={busy || photo?.status === "reading"}>
            {busy ? "Saving…" : photo?.status === "proposed" ? "Confirm and save" : "Save reading"}
          </button>
        </form>
      </div>
    </div>
  );
}
