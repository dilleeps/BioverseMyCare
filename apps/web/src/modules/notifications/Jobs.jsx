import { useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { fmtDateTime } from "../../format.js";
import { WorkspaceLayout } from "../../layouts.jsx";

function summary(detail) {
  if (!detail) return "";
  if (detail.error) return `${detail.error}: ${detail.message || ""}`;
  return Object.entries(detail).filter(([, v]) => v).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ") || "nothing to do";
}

export default function Jobs() {
  const { data, error, loading, reload } = useApi("/admin/jobs");
  const [busy, setBusy] = useState(null);
  const [msg, setMsg] = useState(null);

  async function run(path, label) {
    setBusy(label); setMsg(null);
    try {
      const r = await api(path, { method: "POST" });
      const results = r.results || [r];
      setMsg(results.length ? `Ran ${results.map((x) => `${x.name} (${x.status})`).join(", ")}.` : "No jobs were due.");
      await reload();
    } catch (err) {
      setMsg(err.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <WorkspaceLayout>
      <div className="page-head">
        <div>
          <div className="eyebrow">Operations</div>
          <h1 className="page-title">Scheduled jobs</h1>
          <p className="page-sub">Reminders, alerts and deliveries that run on their own. In the cloud they run every five minutes.</p>
        </div>
      </div>
      {error && <div className="error-box">{error.message}</div>}
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {data && (
        <div className="stack">
          <div className="row wrap">
            <button className="btn primary" disabled={!!busy} onClick={() => run("/admin/jobs/run", "due")}>
              {busy === "due" ? "Running…" : "Run due jobs now"}
            </button>
            {msg && <span className="small" role="status">{msg}</span>}
          </div>
          <section className="card stack" aria-labelledby="jobs-h">
            <h2 id="jobs-h" className="card-title">Jobs</h2>
            <table className="jobs-table">
              <thead><tr><th scope="col">Job</th><th scope="col">Every</th><th scope="col">Last run</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>
                {data.jobs.map((j) => (
                  <tr key={j.name}>
                    <td><div className="strong">{j.description}</div><div className="small muted">{j.name}</div></td>
                    <td>{j.every_minutes} min</td>
                    <td>
                      {j.last_run ? (
                        <>
                          <span className={`chip ${j.last_run.status === "succeeded" ? "ok" : j.last_run.status === "failed" ? "warn" : ""}`}>{j.last_run.status}</span>
                          <div className="small muted">{fmtDateTime(j.last_run.started_at)}</div>
                        </>
                      ) : <span className="small muted">Never</span>}
                    </td>
                    <td>
                      <button className="btn sm" disabled={!!busy} onClick={() => run(`/admin/jobs/${j.name}/run`, j.name)}>
                        {busy === j.name ? "Running…" : "Run now"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          <section className="card stack" aria-labelledby="hist-h">
            <h2 id="hist-h" className="card-title">Recent runs</h2>
            {data.history.length === 0 ? <p className="small muted">No runs yet.</p> : (
              <ul className="list">
                {data.history.map((h) => (
                  <li key={h.id} className="row between wrap" style={{ gap: 8 }}>
                    <span><span className="strong">{h.name}</span> <span className="small muted">{fmtDateTime(h.started_at)}</span></span>
                    <span className="small">{h.status} · {summary(h.detail)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </WorkspaceLayout>
  );
}
