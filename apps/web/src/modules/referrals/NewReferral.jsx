import { useMemo, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { Close, Plus } from "../../icons.jsx";

const COMMON_DOCUMENTS = ["Referral letter", "Recent results", "Visit notes", "Medication list", "Imaging report"];

export default function NewReferral({ onCreated, onClose }) {
  const patients = useApi("/clinician/patients");
  const directory = useApi("/referrals/directory");
  const [form, setForm] = useState({
    patient_id: "",
    specialty: "",
    target_practitioner_id: "",
    reason: "",
    priority: "routine",
    expires_on: "",
  });
  const [docs, setDocs] = useState(
    COMMON_DOCUMENTS.map((name) => ({ name, needed: name === "Referral letter", attached: name === "Referral letter" })),
  );
  const [customDoc, setCustomDoc] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value, ...(k === "specialty" ? { target_practitioner_id: "" } : {}) }));
  const practitioners = useMemo(
    () => (directory.data?.practitioners || []).filter((p) => p.specialty === form.specialty),
    [directory.data, form.specialty],
  );

  function toggleDoc(i, key) {
    setDocs((d) => d.map((doc, j) => {
      if (j !== i) return doc;
      const next = { ...doc, [key]: !doc[key] };
      if (key === "needed" && !next.needed) next.attached = false;
      if (key === "attached" && next.attached) next.needed = true;
      return next;
    }));
  }

  function addDoc(e) {
    e.preventDefault();
    const name = customDoc.trim();
    if (!name || docs.some((d) => d.name.toLowerCase() === name.toLowerCase())) return;
    setDocs((d) => [...d, { name, needed: true, attached: false }]);
    setCustomDoc("");
  }

  async function submit(send) {
    setBusy(true);
    setError(null);
    try {
      const needed = docs.filter((d) => d.needed);
      const created = await api("/referrals", {
        method: "POST",
        body: {
          patient_id: form.patient_id,
          specialty: form.specialty,
          target_practitioner_id: form.target_practitioner_id || null,
          reason: form.reason,
          priority: form.priority,
          expires_on: form.expires_on || null,
          required_documents: needed.map((d) => d.name),
          provided_documents: needed.filter((d) => d.attached).map((d) => d.name),
          send,
        },
      });
      onCreated(created, send);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  const ready = form.patient_id && form.specialty && form.reason.trim().length >= 3;
  const missing = docs.filter((d) => d.needed && !d.attached).length;

  return (
    <section className="card stack" aria-labelledby="new-ref-title">
      <div className="row between">
        <h2 id="new-ref-title" className="card-title">New referral</h2>
        <button className="icon-btn" aria-label="Close new referral" onClick={onClose}><Close size={16} /></button>
      </div>
      {(patients.error || directory.error) && <div className="error-box">{(patients.error || directory.error).message}</div>}
      <form className="rf-form" onSubmit={(e) => { e.preventDefault(); submit(true); }}>
        <div className="field">
          <label htmlFor="rf-patient" className="small strong">Patient</label>
          <select id="rf-patient" value={form.patient_id} onChange={set("patient_id")} required>
            <option value="">{patients.loading ? "Loading…" : "Choose a patient"}</option>
            {(patients.data || []).map((p) => <option key={p.id} value={p.id}>{p.name} · {p.age}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="rf-specialty" className="small strong">Specialty or service</label>
          <select id="rf-specialty" value={form.specialty} onChange={set("specialty")} required>
            <option value="">{directory.loading ? "Loading…" : "Choose"}</option>
            {(directory.data?.specialties || []).map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="rf-target" className="small strong">Send to <span className="muted">(optional)</span></label>
          <select id="rf-target" value={form.target_practitioner_id} onChange={set("target_practitioner_id")} disabled={!form.specialty}>
            <option value="">Anyone in {form.specialty || "the specialty"}</option>
            {practitioners.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.location_name}</option>)}
          </select>
        </div>
        <div className="field rf-wide">
          <label htmlFor="rf-reason" className="small strong">Reason for referral</label>
          <textarea id="rf-reason" className="edit" value={form.reason} onChange={set("reason")} required minLength={3}
                    maxLength={2000} placeholder="Question for the specialist and relevant history. The patient sees this." />
        </div>
        <fieldset className="field rf-plain">
          <legend className="small strong">Priority</legend>
          <div className="row" style={{ gap: 16 }}>
            {["routine", "urgent"].map((p) => (
              <label key={p} className="row small" style={{ gap: 6, minHeight: 44 }}>
                <input type="radio" name="rf-priority" value={p} checked={form.priority === p} onChange={set("priority")} />
                {p === "routine" ? "Routine" : "Urgent"}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="field">
          <label htmlFor="rf-expires" className="small strong">Valid until</label>
          <input id="rf-expires" type="date" value={form.expires_on} onChange={set("expires_on")} />
          <span className="tiny muted">Leave empty for {form.priority === "urgent" ? "30" : "90"} days.</span>
        </div>
        <fieldset className="field rf-wide rf-plain">
          <legend className="small strong">Documents the receiving team needs</legend>
          <div className="rf-docs" role="table" aria-label="Documents">
            <div role="row" className="rf-doc th">
              <span role="columnheader">Document</span><span role="columnheader">Needed</span><span role="columnheader">Attached</span>
            </div>
            {docs.map((d, i) => (
              <div role="row" key={d.name} className="rf-doc">
                <span role="cell" className="small">{d.name}</span>
                <span role="cell">
                  <input type="checkbox" aria-label={`${d.name} needed`} checked={d.needed} onChange={() => toggleDoc(i, "needed")} />
                </span>
                <span role="cell">
                  <input type="checkbox" aria-label={`${d.name} attached`} checked={d.attached} onChange={() => toggleDoc(i, "attached")} />
                </span>
              </div>
            ))}
          </div>
          <div className="row" style={{ gap: 6, marginTop: 8 }}>
            <label htmlFor="rf-custom-doc" className="sr-only">Another document</label>
            <input id="rf-custom-doc" value={customDoc} maxLength={120} onChange={(e) => setCustomDoc(e.target.value)}
                   placeholder="Another document" onKeyDown={(e) => { if (e.key === "Enter") addDoc(e); }} />
            <button type="button" className="btn sm" onClick={addDoc} disabled={!customDoc.trim()}><Plus size={14} /> Add</button>
          </div>
          {missing > 0 && <span className="tiny" style={{ color: "var(--alert-strong)" }}>{missing} needed document{missing === 1 ? " is" : "s are"} not attached yet. The referral will be flagged.</span>}
        </fieldset>
        {error && <div className="error-box small rf-wide" role="alert">{error}</div>}
        <div className="row wrap rf-wide" style={{ gap: 8 }}>
          <button type="submit" className="btn primary" disabled={busy || !ready}>{busy ? "Sending…" : "Send referral"}</button>
          <button type="button" className="btn" disabled={busy || !ready} onClick={() => submit(false)}>Save as draft</button>
        </div>
      </form>
    </section>
  );
}
