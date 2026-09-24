import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { Back, Warning } from "../../icons.jsx";
import { LineChart, Loading, shortDay } from "../nutrition/charts.jsx";
import { ScoreTrend } from "./Mind.jsx";

const ANSWER = ["Not at all", "Several days", "More than half", "Nearly every day"];
const MOOD = ["", "Very low", "Low", "Okay", "Good", "Very good"];

function FollowUp({ item, onDone }) {
  const [note, setNote] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function resolve(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/mind/review-items/${item.id}/resolve`, { method: "POST", body: { note } });
      onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className={`queue-item ${item.priority === "urgent" ? "urgent" : ""}`} onSubmit={resolve}>
      <span className="strong small">{item.priority === "urgent" && <Warning size={14} />} {item.title}</span>
      <span className="small">{item.body}</span>
      <label className="small strong" htmlFor={`fu-${item.id}`}>Follow-up note</label>
      <textarea id={`fu-${item.id}`} className="edit" required minLength={2} placeholder="e.g. Called patient, safety plan reviewed"
                value={note} onChange={(e) => setNote(e.target.value)} />
      {error && <div className="error-box small">{error}</div>}
      <button className="btn dark sm" style={{ alignSelf: "flex-start" }} disabled={busy || note.trim().length < 2}>Mark followed up</button>
    </form>
  );
}

export default function ClinicianMind() {
  const { patientId } = useParams();
  const patients = useApi("/clinician/patients");
  const res = useApi(`/mind/patients/${patientId}/results`);
  const journal = useApi(`/mind/patients/${patientId}/journal`);
  const name = patients.data?.find((p) => p.id === patientId)?.name;
  const data = res.data;
  return (
    <WorkspaceLayout>
      <div className="stack" style={{ gap: 4, marginBottom: 16 }}>
        <Link to="/clinician" className="small strong"><Back size={14} /> Workspace</Link>
        <span className="eyebrow">Mood & anxiety</span>
        <h1 className="page-title">{name || "Patient"}</h1>
        <span className="page-sub">Patient-completed PHQ-9 and GAD-7, and mood ratings. Screening results, not diagnoses.</span>
      </div>
      {res.error && <div className="error-box">{res.error.message}</div>}
      {res.loading && !data && <Loading />}
      {data && (
        <div className="ws-grid">
          <section className="span-7 stack">
            {data.open_items.length > 0 && (
              <article className="card stack">
                <span className="card-title">Needs follow-up</span>
                {data.open_items.map((i) => <FollowUp key={i.id} item={i} onDone={res.reload} />)}
              </article>
            )}
            {Object.entries(data.instruments).map(([key, entry]) => (
              <article key={key} className="card stack">
                <span className="card-title">{entry.name}</span>
                {entry.history.length === 0 && <p className="small muted">Not completed yet.</p>}
                <ScoreTrend entry={entry} />
                {entry.responses.length > 0 && (
                  <details className="wb-table-wrap">
                    <summary>Item answers</summary>
                    {entry.responses.slice(0, 3).map((r) => (
                      <div key={r.id} className="stack" style={{ gap: 2, marginTop: 8 }}>
                        <span className="small strong">{shortDay(r.at)} · total {r.total}{r.difficulty ? ` · ${r.difficulty}` : ""}</span>
                        <table className="wb-table">
                          <tbody>
                            {r.items.map((v, i) => (
                              <tr key={i} style={key === "phq9" && i === 8 && v > 0 ? { color: "var(--alert-strong)", fontWeight: 700 } : undefined}>
                                <td>{i + 1}. {data.item_texts[key][i]}</td><td>{ANSWER[v]}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ))}
                  </details>
                )}
              </article>
            ))}
          </section>
          <section className="span-5 stack">
            <article className="card stack">
              <span className="card-title">Mood journal</span>
              {journal.error && <div className="error-box">{journal.error.message}</div>}
              {journal.data && journal.data.entries.length === 0 && <p className="small muted">No mood entries in the last 60 days.</p>}
              {journal.data && journal.data.entries.length > 1 && (
                <LineChart label="Mood ratings, 1 very low to 5 very good" yDomain={[0.5, 5.5]} height={120} unit="of 5"
                           formatValue={(v) => Math.round(v)}
                           series={[{ id: "mood", label: "Mood", dots: true, strong: true,
                                      points: journal.data.entries.slice().reverse().map((e) => ({ at: e.created_at, value: e.mood, note: MOOD[e.mood] })) }]} />
              )}
              {journal.data && journal.data.entries.slice(0, 6).map((e) => (
                <div key={e.id} className="wb-row small">
                  <div className="grow">
                    <span className="strong">{MOOD[e.mood]}</span><span className="muted"> · {shortDay(e.created_at)}{e.tags.length ? ` · ${e.tags.join(", ")}` : ""}</span>
                    {e.note && <p style={{ overflowWrap: "anywhere" }}>{e.note}</p>}
                  </div>
                </div>
              ))}
              <span className="tiny muted">Notes appear only when the patient chose to share them.</span>
            </article>
          </section>
        </div>
      )}
    </WorkspaceLayout>
  );
}
