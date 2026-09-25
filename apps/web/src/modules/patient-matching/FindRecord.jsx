import { useId, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { fmtDate } from "../../format.js";
import { LevelChip, Reasons, identifierText } from "./shared.jsx";

const FIELDS = [
  { key: "name", label: "Name", type: "text", autoComplete: "off", hint: "First and last, any order" },
  { key: "birth_date", label: "Date of birth", type: "date" },
  { key: "identifier", label: "MRN or other identifier", type: "text", autoComplete: "off" },
  { key: "email", label: "Email", type: "email", autoComplete: "off" },
  { key: "phone", label: "Phone", type: "tel", autoComplete: "off" },
];

export default function FindRecord() {
  const [form, setForm] = useState({ name: "", birth_date: "", identifier: "", email: "", phone: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [results, setResults] = useState(null);
  const [open, setOpen] = useState(null);
  const base = useId();

  async function submit(e) {
    e.preventDefault();
    const params = new URLSearchParams(Object.entries(form).filter(([, v]) => v.trim()));
    if (![...params.keys()].length) return setError("Enter at least one detail to search by.");
    setBusy(true);
    setError(null);
    try {
      const out = await api(`/patient-matching/search?${params}`);
      setResults(out.results);
      setOpen(null);
    } catch (err) {
      setError(err.message);
      setResults(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <WorkspaceLayout>
      <div className="pm">
        <div className="page-head">
          <div>
            <h1 className="page-title">Find a patient record</h1>
            <div className="page-sub">
              Before registering someone, check whether they are already on file (for example from a lab result or
              an earlier visit). Results are ranked by how closely they match.
            </div>
          </div>
        </div>

        <div className="ws-grid">
          <form className="card stack span-12 pm-search" onSubmit={submit} aria-busy={busy} role="search">
            <div className="pm-search-grid">
              {FIELDS.map((f) => (
                <div className="field stack" style={{ gap: 4 }} key={f.key}>
                  <label htmlFor={`${base}-${f.key}`} className="small strong">{f.label}</label>
                  <input id={`${base}-${f.key}`} type={f.type} value={form[f.key]} autoComplete={f.autoComplete}
                         aria-describedby={f.hint ? `${base}-${f.key}-hint` : undefined}
                         onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} />
                  {f.hint && <span id={`${base}-${f.key}-hint`} className="tiny muted">{f.hint}</span>}
                </div>
              ))}
            </div>
            {error && <div className="error-box" role="alert">{error}</div>}
            <div className="row wrap">
              <button className="btn primary" type="submit" disabled={busy}>{busy ? "Searching..." : "Search"}</button>
              <button className="btn" type="button" disabled={busy}
                      onClick={() => { setForm({ name: "", birth_date: "", identifier: "", email: "", phone: "" }); setResults(null); setError(null); }}>
                Clear
              </button>
            </div>
          </form>

          <section className="card stack span-12" aria-labelledby={`${base}-res`} aria-live="polite">
            <h2 id={`${base}-res`} className="card-title">
              {results == null ? "Results" : `${results.length} record${results.length === 1 ? "" : "s"} found`}
            </h2>
            {results == null && <div className="small muted">Search by any mix of details. Retired (merged) records are not shown.</div>}
            {results?.length === 0 && (
              <div className="empty">No record matches these details. Registration still checks for duplicates.</div>
            )}
            {results?.length > 0 && (
              <div className="pm-results-wrap">
                <table className="pm-results">
                  <thead>
                    <tr>
                      <th scope="col">Patient</th>
                      <th scope="col">Date of birth</th>
                      <th scope="col">Contact</th>
                      <th scope="col">Identifiers</th>
                      <th scope="col">Match</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.map((r) => (
                      <tr key={r.id}>
                        <td>
                          <div className="strong">{r.name}</div>
                          <div className="tiny muted">{r.has_login ? "Has a sign-in" : "No sign-in"} · since {fmtDate(r.created_at)}</div>
                        </td>
                        <td>{fmtDate(r.birth_date)}</td>
                        <td className="small">{[r.email, r.phone].filter(Boolean).join(" · ") || <span className="muted">—</span>}</td>
                        <td className="small">{r.identifiers.map(identifierText).join(", ") || <span className="muted">—</span>}</td>
                        <td>
                          <LevelChip level={r.level} score={r.score} percent />
                          <button type="button" className="btn ghost sm pm-why-btn" aria-expanded={open === r.id}
                                  onClick={() => setOpen(open === r.id ? null : r.id)}>
                            {open === r.id ? "Hide why" : "Why?"}
                          </button>
                          {open === r.id && <Reasons reasons={r.reasons} />}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="tiny muted">
              Two records for the same person? New registrations are checked automatically and appear under{" "}
              <Link to="/registry/duplicates">Duplicate records</Link>.
            </div>
          </section>
        </div>
      </div>
    </WorkspaceLayout>
  );
}
