import { useMemo, useState } from "react";
import { api } from "../../api.js";
import { downloadFile } from "./download.js";
import "./bulk.css";

const MAX_BYTES = 2_000_000;
const STATUS = {
  would_create: { label: "New", tone: "ok" },
  created: { label: "Created", tone: "ok" },
  would_update: { label: "Update team", tone: "info" },
  updated: { label: "Updated", tone: "info" },
  skip: { label: "Skipped", tone: "muted" },
  duplicate: { label: "Duplicate", tone: "warn" },
  error: { label: "Needs fixing", tone: "warn" },
};
const ROLE = { admin: "Administrator", staff: "Staff", clinician: "Clinician", patient: "Patient", student: "Medical student" };
const TEAM = { front_desk: "Front desk", pharmacy: "Pharmacy" };

function Totals({ t, done }) {
  const parts = [
    [t.create, done ? "created" : "new"],
    [t.update, done ? "updated" : "to update"],
    [t.skip, "skipped"],
    [t.duplicate, "duplicate"],
    [t.error, "need fixing"],
  ].filter(([n]) => n > 0);
  return (
    <p className="small" aria-live="polite">
      <span className="strong">{t.rows} {t.rows === 1 ? "row" : "rows"}:</span>{" "}
      {parts.map(([n, label]) => `${n} ${label}`).join(" · ")}
    </p>
  );
}

function ReportTable({ report }) {
  const [problemsOnly, setProblemsOnly] = useState(report.blocking > 0);
  const rows = problemsOnly ? report.rows.filter((r) => r.status === "error" || r.status === "duplicate") : report.rows;
  return (
    <div className="stack" style={{ gap: 8 }}>
      {report.blocking > 0 && (
        <label className="row small" style={{ gap: 8 }}>
          <input type="checkbox" checked={problemsOnly} onChange={(e) => setProblemsOnly(e.target.checked)} />
          Show only rows that need fixing
        </label>
      )}
      <div className="bulk-table-wrap" tabIndex={0} aria-label="Import rows">
        <table className="people-table bulk-table">
          <thead>
            <tr><th scope="col">Row</th><th scope="col">Person</th><th scope="col">Role</th><th scope="col">Result</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const s = STATUS[r.status] || { label: r.status, tone: "muted" };
              return (
                <tr key={r.row} className={`bulk-${s.tone}`}>
                  <td className="small muted">{r.row}</td>
                  <td>
                    <div className="strong">{r.name || <span className="muted">(no name)</span>}</div>
                    <div className="small muted">{r.email}</div>
                  </td>
                  <td className="small">
                    {r.role ? ROLE[r.role] : "?"}{r.team ? ` · ${TEAM[r.team]}` : ""}{r.specialty ? ` · ${r.specialty}` : ""}
                  </td>
                  <td>
                    <span className={`bulk-status ${s.tone}`}>{s.label}</span>
                    {r.message && <div className="small bulk-message">{r.message}</div>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function ImportPeople({ onDone, onClose }) {
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState(null);
  const [opts, setOpts] = useState({ update_existing: false, skip_errors: false });
  const [report, setReport] = useState(null);
  const [state, setState] = useState({ busy: null, error: null, done: null });

  const reset = () => { setReport(null); setState({ busy: null, error: null, done: null }); };
  const setOpt = (k) => (e) => { setOpts({ ...opts, [k]: e.target.checked }); if (k === "update_existing") reset(); };

  function chooseFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    reset();
    if (file.size > MAX_BYTES) {
      setState({ busy: null, error: "That file is too large. Import at most 1,000 people at a time.", done: null });
      return;
    }
    const reader = new FileReader();
    reader.onload = () => { setText(String(reader.result || "")); setFileName(file.name); };
    reader.onerror = () => setState({ busy: null, error: "Couldn't read that file.", done: null });
    reader.readAsText(file);
  }

  async function send(dryRun) {
    setState({ busy: dryRun ? "check" : "import", error: null, done: null });
    try {
      const r = await api("/admin/users/import", { method: "POST", body: { csv: text, dry_run: dryRun, ...opts } });
      setReport(r);
      setState({ busy: null, error: null, done: dryRun ? null : r.totals });
      if (!dryRun) onDone?.();
    } catch (err) {
      if (err.detail?.report) setReport(err.detail.report);
      setState({ busy: null, error: err.message, done: null });
    }
  }

  const importable = report ? report.totals.create + report.totals.update : 0;
  const canImport = report && report.dry_run && importable > 0 && (report.blocking === 0 || opts.skip_errors);
  const lines = useMemo(() => text.split(/\r?\n/).filter((l) => l.trim()).length, [text]);

  return (
    <section className="card stack bulk-panel" aria-labelledby="import-h">
      <div className="row between wrap">
        <h2 id="import-h" className="card-title">Import people from a spreadsheet</h2>
        {onClose && <button type="button" className="btn sm ghost" onClick={onClose}>Close</button>}
      </div>
      <p className="small muted">
        Save your spreadsheet as CSV with the columns <code>name, email, role, team, specialty, location, birth_date,
        consult_fee</code>. Clinicians need a specialty and patients a date of birth (year-month-day). You'll see what
        each row will do before anything is saved.
      </p>
      <div className="row wrap" style={{ gap: 8 }}>
        <label className="btn sm bulk-file">
          Choose CSV file
          <input type="file" accept=".csv,text/csv,text/plain" onChange={chooseFile} />
        </label>
        <button type="button" className="btn sm ghost" onClick={() => downloadFile("/admin/users/import/template", "bioverse-people-template.csv")
          .catch((e) => setState({ busy: null, error: e.message, done: null }))}>
          Download template
        </button>
        {fileName && <span className="small muted">{fileName}</span>}
      </div>
      <label className="stack" style={{ gap: 4 }}>
        <span className="small strong">Or paste the CSV</span>
        <textarea className="bulk-textarea" rows={7} spellCheck={false} value={text}
                  placeholder={"name,email,role,team,specialty,location,birth_date,consult_fee\nAlex Rivera,alex@yourhospital.org,staff,front_desk,,,,"}
                  onChange={(e) => { setText(e.target.value); setFileName(null); reset(); }} />
      </label>
      <div className="stack" style={{ gap: 6 }}>
        <label className="row small" style={{ gap: 8 }}>
          <input type="checkbox" checked={opts.update_existing} onChange={setOpt("update_existing")} />
          For people who already have an account, update their staff team (roles are never changed)
        </label>
        <label className="row small" style={{ gap: 8 }}>
          <input type="checkbox" checked={opts.skip_errors} onChange={setOpt("skip_errors")} />
          Import the good rows even if some need fixing (otherwise nothing is imported until every row is fixed)
        </label>
      </div>
      <div className="row wrap" style={{ gap: 8 }}>
        <button type="button" className="btn" disabled={!text.trim() || state.busy} onClick={() => send(true)}>
          {state.busy === "check" ? "Checking…" : `Check ${lines > 1 ? `${lines - 1} rows` : "file"}`}
        </button>
        <button type="button" className="btn primary" disabled={!canImport || state.busy} onClick={() => send(false)}>
          {state.busy === "import" ? "Importing…"
            : importable > 0 && report?.dry_run ? `Import ${importable} ${importable === 1 ? "person" : "people"}` : "Import"}
        </button>
      </div>
      {report?.ignored_columns?.length > 0 && (
        <div className="banner info small">Ignored columns: {report.ignored_columns.join(", ")}</div>
      )}
      {state.error && <div className="error-box" role="alert">{state.error}</div>}
      {state.done && (
        <div className="banner ok" role="status">
          Import finished: {state.done.create} created{state.done.update ? `, ${state.done.update} updated` : ""}
          {state.done.skip ? `, ${state.done.skip} skipped` : ""}{state.done.error + state.done.duplicate ? `, ${state.done.error + state.done.duplicate} not imported` : ""}.
        </div>
      )}
      {report && !state.done && report.dry_run && report.blocking > 0 && !opts.skip_errors && (
        <div className="banner warn small" role="status">
          {report.blocking} {report.blocking === 1 ? "row needs" : "rows need"} fixing. Fix the file and check again, or
          choose to import the good rows.
        </div>
      )}
      {report && (
        <>
          <Totals t={report.totals} done={report.committed} />
          <ReportTable key={`${report.committed}-${report.rows.length}`} report={report} />
        </>
      )}
    </section>
  );
}
