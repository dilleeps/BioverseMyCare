import { useEffect, useId, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { fmtDateTime } from "../../format.js";
import { Check, Warning } from "../../icons.jsx";

const METHOD = { identifier: "matched by identifier", name_dob: "matched by name and date of birth" };

function Outcome({ entry }) {
  const accepted = entry.outcome === "accepted";
  const reports = entry.detail?.reports || [];
  const skipped = entry.detail?.skipped || [];
  return (
    <div className={`lab-outcome ${accepted ? "ok" : "rejected"}`}>
      <div className="row" style={{ gap: 8 }}>
        {accepted ? <Check size={16} /> : <Warning size={16} />}
        <span className="strong">{accepted ? "Imported" : "Rejected"}</span>
        <span className="small muted">
          {entry.message_type || "Unreadable message"}{entry.control_id ? ` · ${entry.control_id}` : ""}
          {entry.sending_facility ? ` · ${entry.sending_facility}` : ""}
        </span>
      </div>
      {accepted ? (
        <div className="small" style={{ marginTop: 6 }}>
          {entry.patient_name}, {METHOD[entry.match_method] || entry.match_method}.{" "}
          {reports.map((r) => `${r.name}: ${r.results} result${r.results === 1 ? "" : "s"}${r.abnormal ? `, ${r.abnormal} outside range` : ""}`).join("; ")}.
          {" "}Draft explanation sent to {entry.reviewer || "the clinician"} for review{entry.detail?.critical ? " (marked urgent: critical value)" : ""}.
          {skipped.length > 0 && <div className="tiny muted" style={{ marginTop: 4 }}>Not stored: {skipped.join("; ")}</div>}
        </div>
      ) : (
        <div className="small" style={{ marginTop: 6 }}>{entry.reason}</div>
      )}
    </div>
  );
}

export default function LabImport() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [results, setResults] = useState(null);
  const log = useApi("/lab-import/messages");
  const sample = useApi("/lab-import/sample");
  const ids = { text: useId(), hint: useId() };

  // The demo sample fills the box on load and on "Load a fresh sample" (new control id each time).
  useEffect(() => {
    if (sample.data) setText(sample.data.message);
  }, [sample.data]);

  async function loadSample() {
    setResults(null);
    await sample.reload();
  }

  async function submit(e) {
    e.preventDefault();
    if (!text.trim()) return setError("Paste a message first.");
    setBusy(true);
    setError(null);
    try {
      const out = await api("/lab-import/messages", { method: "POST", body: { text } });
      setResults(out);
      log.reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <WorkspaceLayout>
      <div className="lab">
        <div className="page-head">
          <div>
            <h1 className="page-title">Lab import</h1>
            <div className="page-sub">HL7 v2 ORU^R01 results in, reviewed explanations out.</div>
          </div>
        </div>

        <div className="ws-grid">
          <form className="card stack span-7" onSubmit={submit} aria-busy={busy}>
            <div className="stack" style={{ gap: 6 }}>
              <label htmlFor={ids.text} className="card-title">Message</label>
              <span id={ids.hint} className="small muted">
                Paste one or more ORU^R01 messages. Each segment on its own line. A sample for Maya Thornton is loaded for the demo.
              </span>
              <textarea id={ids.text} aria-describedby={ids.hint} className="edit lab-message" value={text}
                        onChange={(e) => setText(e.target.value)} spellCheck={false} />
            </div>
            {error && <div className="error-box" role="alert">{error}</div>}
            <div className="row wrap">
              <button className="btn primary" type="submit" disabled={busy}>{busy ? "Importing..." : "Import"}</button>
              <button className="btn" type="button" onClick={loadSample} disabled={busy || sample.loading}>Load a fresh sample</button>
            </div>
            <div aria-live="polite" className="stack" style={{ gap: 8 }}>
              {results && (
                <>
                  <div className="small strong">{results.accepted} imported · {results.rejected} rejected</div>
                  {results.results.map((r) => <Outcome key={r.id} entry={r} />)}
                </>
              )}
            </div>
          </form>

          <aside className="card stack span-5" aria-labelledby="lab-rules-h">
            <h2 id="lab-rules-h" className="card-title">How messages are matched</h2>
            <ul className="small lab-rules">
              <li>An MRN or Bioverse id in PID-3 matches exactly, and the name and date of birth must agree with it.</li>
              <li>Without a known identifier, family name, given name and date of birth must match exactly one patient.</li>
              <li>No match, a disagreement, or more than one candidate: the message is rejected with the reason. Nothing is guessed.</li>
              <li>Results become a report with coded observations. A draft explanation goes to the ordering clinician (OBR-16), or the patient's care-plan clinician, for review before the patient sees it.</li>
            </ul>
          </aside>

          <section className="card stack span-12" aria-labelledby="lab-log-h">
            <h2 id="lab-log-h" className="card-title">Import log</h2>
            {log.error && <div className="error-box">{log.error.message}</div>}
            {log.loading && !log.data && <div className="skeleton" />}
            {log.data?.length === 0 && <div className="empty">No messages yet.</div>}
            {log.data?.length > 0 && (
              <div className="lab-log-wrap">
                <table className="lab-log">
                  <thead>
                    <tr>
                      <th scope="col">Received</th>
                      <th scope="col">Message</th>
                      <th scope="col">Outcome</th>
                      <th scope="col">Patient</th>
                      <th scope="col">Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {log.data.map((m) => (
                      <tr key={m.id}>
                        <td>{fmtDateTime(m.received_at)}</td>
                        <td>
                          <div className="strong">{m.control_id || "Unreadable"}</div>
                          <div className="tiny muted">{[m.message_type, m.sending_facility].filter(Boolean).join(" · ")}</div>
                        </td>
                        <td>
                          {m.outcome === "accepted"
                            ? <span className="chip ok">Imported</span>
                            : <span className="chip warn">Rejected</span>}
                        </td>
                        <td>{m.patient_name || "Not matched"}</td>
                        <td className="small">
                          {m.outcome === "accepted"
                            ? `${METHOD[m.match_method] || ""}; review by ${m.reviewer || "clinician"}`
                            : m.reason}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </div>
    </WorkspaceLayout>
  );
}
