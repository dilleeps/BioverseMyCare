import { useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { useSession } from "../../session.jsx";
import { fmtDate } from "../../format.js";
import { Check, Chevron, Close, Plus, Shield } from "../../icons.jsx";
import { downloadRecord, uploadFile } from "./transfer.js";

const MAX_BYTES = 10 * 1024 * 1024;
const ACCEPT = "application/pdf,image/png,image/jpeg,image/webp,image/gif,text/plain";
const TYPES = ACCEPT.split(",");

function Svg({ children, size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
  );
}
const UploadIcon = (p) => <Svg {...p}><path d="M12 16V4" /><path d="M7 9l5-5 5 5" /><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" /></Svg>;
const DownloadIcon = (p) => <Svg {...p}><path d="M12 4v12" /><path d="M7 11l5 5 5-5" /><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" /></Svg>;

function flagOf(row) {
  const v = Number(row.value);
  if (row.value === "" || Number.isNaN(v)) return null;
  const low = row.ref_low === "" ? null : Number(row.ref_low);
  const high = row.ref_high === "" ? null : Number(row.ref_high);
  if (high != null && !Number.isNaN(high) && v > high) return "H";
  if (low != null && !Number.isNaN(low) && v < low) return "L";
  return "N";
}

function toRows(extraction) {
  return (extraction?.results || []).map((r, i) => ({
    key: `r${i}`,
    test_name: r.test_name || "",
    value: r.value ?? "",
    value_text: r.value_text || "",
    unit: r.unit || "",
    ref_low: r.ref_low ?? "",
    ref_high: r.ref_high ?? "",
    loinc_code: r.loinc_code || null,
    loinc_display: r.loinc_display || null,
  }));
}

function rowProblem(r) {
  if (!r.test_name.trim()) return "Every row needs a test name.";
  if (r.value === "" || Number.isNaN(Number(r.value))) return `Enter a number for ${r.test_name}.`;
  for (const k of ["ref_low", "ref_high"]) {
    if (r[k] !== "" && Number.isNaN(Number(r[k]))) return `The range for ${r.test_name} must be numbers.`;
  }
  if (r.ref_low !== "" && r.ref_high !== "" && Number(r.ref_low) > Number(r.ref_high)) {
    return `The range for ${r.test_name} is back to front.`;
  }
  return null;
}

// ---------------------------------------------------------------------------------------------

function AddReport({ onExtracted }) {
  const [mode, setMode] = useState("file");
  const [file, setFile] = useState(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const fileInput = useRef(null);
  const ids = { file: useId(), text: useId(), hint: useId() };

  function pick(e) {
    const f = e.target.files?.[0] || null;
    setError(null);
    if (f && !TYPES.includes(f.type)) {
      setError("Choose a PDF, a photo (PNG, JPEG, WebP or GIF), or a text file.");
      setFile(null);
      return;
    }
    if (f && f.size > MAX_BYTES) {
      setError("That file is larger than 10 MB. Try a smaller file or paste the text instead.");
      setFile(null);
      return;
    }
    setFile(f);
  }

  async function submit(e) {
    e.preventDefault();
    setError(null);
    if (mode === "file" && !file) return setError("Choose a file first.");
    if (mode === "text" && !text.trim()) return setError("Paste the text of your report first.");
    setBusy(true);
    try {
      const doc = mode === "file" ? await uploadFile(file) : await api("/documents/text", { method: "POST", body: { text } });
      setFile(null);
      setText("");
      if (fileInput.current) fileInput.current.value = "";
      onExtracted(doc);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card stack" onSubmit={submit} aria-busy={busy}>
      <div>
        <h2 className="card-title">Add a lab report</h2>
        <p className="small muted" style={{ marginTop: 4 }}>
          From another lab or clinic. You'll check the values before anything is saved, and your clinician reviews
          them before explaining what they mean.
        </p>
      </div>
      <fieldset className="rec-choice">
        <legend className="sr-only">How would you like to add it?</legend>
        <label className={mode === "file" ? "on" : ""}>
          <input type="radio" name="mode" value="file" checked={mode === "file"} onChange={() => setMode("file")} />
          Upload a file
        </label>
        <label className={mode === "text" ? "on" : ""}>
          <input type="radio" name="mode" value="text" checked={mode === "text"} onChange={() => setMode("text")} />
          Paste the text
        </label>
      </fieldset>

      {mode === "file" ? (
        <div className="stack" style={{ gap: 6 }}>
          <label htmlFor={ids.file} className="strong small">Your report</label>
          <input ref={fileInput} id={ids.file} className="rec-file" type="file" accept={ACCEPT} onChange={pick}
                 aria-describedby={ids.hint} />
          <span id={ids.hint} className="tiny muted">PDF, photo (PNG, JPEG, WebP, GIF) or text file, up to 10 MB.</span>
        </div>
      ) : (
        <div className="stack" style={{ gap: 6 }}>
          <label htmlFor={ids.text} className="strong small">Report text</label>
          <textarea id={ids.text} className="edit rec-paste" value={text} onChange={(e) => setText(e.target.value)}
                    placeholder={"LDL Cholesterol 148 mg/dL (0-99) H\nHDL Cholesterol 58 mg/dL (>40)"} />
        </div>
      )}

      {error && <div className="error-box" role="alert">{error}</div>}
      <button className="btn primary" type="submit" disabled={busy}>
        <UploadIcon /> {busy ? "Reading your report..." : "Read my report"}
      </button>
    </form>
  );
}

// ---------------------------------------------------------------------------------------------

function Review({ doc, onSaved, onDiscarded }) {
  const ex = doc.extraction || {};
  const [rows, setRows] = useState(() => toRows(ex));
  const [meta, setMeta] = useState({
    report_name: ex.report_name || "",
    lab_name: ex.lab_name || "",
    collected_on: ex.collected_date || "",
  });
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ids = { name: useId(), lab: useId(), date: useId(), check: useId() };
  const today = new Date().toISOString().slice(0, 10);

  const update = (key, field, value) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, [field]: value, ...(field === "test_name" ? { loinc_code: null, loinc_display: null } : {}) } : r)));
  const remove = (key) => setRows((rs) => rs.filter((r) => r.key !== key));
  const add = () => setRows((rs) => [...rs, { key: `n${Date.now()}`, test_name: "", value: "", value_text: "", unit: "", ref_low: "", ref_high: "", loinc_code: null }]);

  const problem = !meta.report_name.trim() ? "Give the report a name, for example Lipid panel."
    : !meta.lab_name.trim() ? "Enter the lab's name."
    : !meta.collected_on ? "Enter the date the sample was taken."
    : meta.collected_on > today ? "The collection date can't be in the future."
    : rows.length === 0 ? "Add at least one result."
    : rows.map(rowProblem).find(Boolean) || null;

  async function save(e) {
    e.preventDefault();
    if (problem || !checked) return;
    setBusy(true);
    setError(null);
    try {
      const body = {
        confirmed: true,
        report_name: meta.report_name.trim(),
        lab_name: meta.lab_name.trim(),
        collected_on: meta.collected_on,
        results: rows.map((r) => ({
          test_name: r.test_name.trim(),
          value: Number(r.value),
          unit: r.unit.trim(),
          ref_low: r.ref_low === "" ? null : Number(r.ref_low),
          ref_high: r.ref_high === "" ? null : Number(r.ref_high),
          loinc_code: r.loinc_code,
        })),
      };
      const saved = await api(`/documents/${doc.id}/confirm`, { method: "POST", body });
      onSaved(saved);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function discard() {
    setBusy(true);
    setError(null);
    try {
      await api(`/documents/${doc.id}/discard`, { method: "POST" });
      onDiscarded();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <form className="card stack rec-review" onSubmit={save} aria-labelledby={`${ids.name}-h`}>
      <div>
        <div className="eyebrow">Step 2 of 2 · Check the values</div>
        <h2 id={`${ids.name}-h`} className="card-title" style={{ marginTop: 4 }}>Is this what your report says?</h2>
        <p className="small muted" style={{ marginTop: 4 }}>
          {doc.extracted_by?.endsWith("/claude") ? "Bioverse read these from your report. " : ""}
          Compare every row with your report and fix anything that's wrong. These will be saved as values you
          reported, and your clinician checks them before explaining them.
        </p>
      </div>
      {ex.notice && <div className="banner info" role="status">{ex.notice}</div>}
      {ex.document_is_lab_report === false && rows.length === 0 && doc.extracted_by?.endsWith("/claude") && (
        <div className="banner warn">This doesn't look like a lab report. You can still type the values in.</div>
      )}

      <div className="rec-meta">
        <div className="stack" style={{ gap: 4 }}>
          <label htmlFor={ids.name} className="small strong">Report name</label>
          <input id={ids.name} value={meta.report_name} onChange={(e) => setMeta({ ...meta, report_name: e.target.value })} maxLength={120} />
        </div>
        <div className="stack" style={{ gap: 4 }}>
          <label htmlFor={ids.lab} className="small strong">Lab</label>
          <input id={ids.lab} value={meta.lab_name} onChange={(e) => setMeta({ ...meta, lab_name: e.target.value })} maxLength={120} />
        </div>
        <div className="stack" style={{ gap: 4 }}>
          <label htmlFor={ids.date} className="small strong">Sample taken on</label>
          <input id={ids.date} type="date" max={today} value={meta.collected_on} onChange={(e) => setMeta({ ...meta, collected_on: e.target.value })} />
        </div>
      </div>

      <div className="rec-table-wrap">
        <table className="rec-table">
          <caption className="sr-only">Results to check</caption>
          <thead>
            <tr>
              <th scope="col">Test</th>
              <th scope="col">Value</th>
              <th scope="col">Unit</th>
              <th scope="col">Range low</th>
              <th scope="col">Range high</th>
              <th scope="col">Flag</th>
              <th scope="col"><span className="sr-only">Remove</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const f = flagOf(r);
              const name = r.test_name || `Row ${i + 1}`;
              return (
                <tr key={r.key}>
                  <td>
                    <input aria-label={`Test name, row ${i + 1}`} value={r.test_name} onChange={(e) => update(r.key, "test_name", e.target.value)} maxLength={120} />
                    {r.loinc_code && <span className="tiny muted rec-code">LOINC {r.loinc_code}</span>}
                  </td>
                  <td>
                    <input aria-label={`${name} value`} inputMode="decimal" value={r.value} onChange={(e) => update(r.key, "value", e.target.value)}
                           placeholder={r.value === "" && r.value_text ? r.value_text : ""} className="num" />
                  </td>
                  <td><input aria-label={`${name} unit`} value={r.unit} onChange={(e) => update(r.key, "unit", e.target.value)} maxLength={40} className="unit" /></td>
                  <td><input aria-label={`${name} range low`} inputMode="decimal" value={r.ref_low} onChange={(e) => update(r.key, "ref_low", e.target.value)} className="num" /></td>
                  <td><input aria-label={`${name} range high`} inputMode="decimal" value={r.ref_high} onChange={(e) => update(r.key, "ref_high", e.target.value)} className="num" /></td>
                  <td>
                    {f === "H" && <span className="chip warn">High</span>}
                    {f === "L" && <span className="chip warn">Low</span>}
                    {f === "N" && <span className="chip ok">In range</span>}
                  </td>
                  <td>
                    <button type="button" className="icon-btn" aria-label={`Remove ${name}`} onClick={() => remove(r.key)}><Close size={16} /></button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div>
        <button type="button" className="btn sm" onClick={add}><Plus size={14} /> Add a row</button>
      </div>

      <div className="toggle-row">
        <input id={ids.check} type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
        <label htmlFor={ids.check}>I've checked these values against my report.</label>
      </div>
      {problem && <div className="small strong" style={{ color: "var(--alert)" }} role="status">{problem}</div>}
      {error && <div className="error-box" role="alert">{error}</div>}
      <div className="row wrap">
        <button className="btn primary" type="submit" disabled={busy || !checked || Boolean(problem)}>
          <Check size={16} /> {busy ? "Saving..." : "Save to my record"}
        </button>
        <button className="btn" type="button" onClick={discard} disabled={busy}>Discard</button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------------------------

function uploadStatus(d) {
  if (d.status === "extracted") return <span className="chip">Not saved yet</span>;
  if (d.explanation_status === "approved") return <span className="chip ok"><Shield size={12} /> Reviewed by {d.reviewer || "your clinician"}</span>;
  if (d.explanation_status === "rejected") return <span className="chip">Your clinician will follow up</span>;
  return <span className="chip">Uploaded by you · awaiting clinician review</span>;
}

function Uploads({ docs, onResume }) {
  if (docs.loading && !docs.data) return <div className="card"><div className="skeleton" /></div>;
  if (docs.error) return <div className="error-box">{docs.error.message}</div>;
  if (!docs.data?.length) return <div className="card empty">You haven't uploaded any reports yet.</div>;
  return (
    <div className="card" style={{ padding: "4px 16px" }}>
      <ul className="list rec-uploads">
        {docs.data.map((d) => (
          <li key={d.id} className="row between wrap" style={{ padding: "12px 0" }}>
            <div className="stack" style={{ gap: 4 }}>
              <span className="strong">{d.report_name || d.filename || "Pasted text"}</span>
              <span className="small muted">
                {d.lab_name ? `${d.lab_name} · ` : ""}Uploaded {fmtDate(d.created_at)}
                {d.status === "confirmed" ? " · patient-reported" : ""}
              </span>
              <span>{uploadStatus(d)}</span>
            </div>
            {d.status === "extracted" ? (
              <button className="btn sm" onClick={() => onResume(d.id)}>Check values</button>
            ) : d.report_id ? (
              <Link className="btn sm" to={`/results/${d.report_id}`}>View <Chevron size={14} /></Link>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function DownloadRecord({ patientId }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const [error, setError] = useState(null);

  async function go() {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const n = await downloadRecord(patientId);
      setDone(`Downloaded ${n} items from your record.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card stack" aria-labelledby="rec-download-h">
      <div>
        <h2 id="rec-download-h" className="card-title">Download my record</h2>
        <p className="small muted" style={{ marginTop: 4 }}>
          A copy of your visits, results, care plan, appointments, allergies, consents and uploads, in the FHIR
          format other health apps and hospitals can read. Only reviewed explanations are included.
        </p>
      </div>
      {error && <div className="error-box" role="alert">{error}</div>}
      {done && <div className="banner ok" role="status"><Check size={14} /> {done}</div>}
      <button className="btn" onClick={go} disabled={busy}><DownloadIcon /> {busy ? "Preparing..." : "Download (JSON)"}</button>
    </section>
  );
}

export default function Records() {
  const { me } = useSession();
  const docs = useApi(`/documents?patient_id=${me.patient_id}`);
  const [reviewing, setReviewing] = useState(null);
  const [saved, setSaved] = useState(null);
  const [error, setError] = useState(null);

  async function resume(id) {
    setError(null);
    try {
      setReviewing(await api(`/documents/${id}`));
      setSaved(null);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <main className="column rec">
      <div className="page-head">
        <div>
          <h1 className="page-title">My records</h1>
          <div className="page-sub">Add results from other labs, or take a copy of your record with you.</div>
        </div>
      </div>
      <div className="stack">
        {saved && (
          <div className="banner ok" role="status">
            <Check size={14} /> Saved. Uploaded by you · awaiting clinician review. You'll see an explanation once it's approved.
            {" "}<Link to={`/results/${saved.report_id}`}>View result</Link>
          </div>
        )}
        {error && <div className="error-box" role="alert">{error}</div>}
        {reviewing ? (
          <Review
            key={reviewing.id}
            doc={reviewing}
            onSaved={(s) => { setSaved(s); setReviewing(null); docs.reload(); }}
            onDiscarded={() => { setReviewing(null); docs.reload(); }}
          />
        ) : (
          <AddReport onExtracted={(d) => { setSaved(null); setReviewing(d); docs.reload(); }} />
        )}

        <section className="stack" aria-labelledby="rec-uploads-h" style={{ marginTop: 8 }}>
          <h2 id="rec-uploads-h" className="eyebrow">Your uploads</h2>
          <Uploads docs={docs} onResume={resume} />
        </section>

        <DownloadRecord patientId={me.patient_id} />
      </div>
    </main>
  );
}

