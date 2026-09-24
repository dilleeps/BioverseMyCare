import { useEffect, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { fmtDate } from "../../format.js";
import { Lock } from "../../icons.jsx";
import { PageHeader } from "./shared.jsx";

function years(days) {
  if (!days) return "";
  const y = days / 365;
  return y >= 1 ? `about ${y.toFixed(y % 1 < 0.05 || y % 1 > 0.95 ? 0 : 1)} years` : `${days} days`;
}

function PolicyRow({ policy, onSaved }) {
  const [days, setDays] = useState(policy.retention_days ?? "");
  const [notes, setNotes] = useState(policy.notes || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setDays(policy.retention_days ?? "");
    setNotes(policy.notes || "");
  }, [policy.retention_days, policy.notes]);

  const dirty = Number(days) !== policy.retention_days || notes !== (policy.notes || "");
  const tooShort = days !== "" && Number(days) < policy.min_days;

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const res = await api(`/governance/retention/${policy.category}`, {
        method: "PUT", body: { retention_days: Number(days), notes },
      });
      onSaved(res);
      setSaved(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const id = `ret-${policy.category}`;
  return (
    <form className="gv-policy" onSubmit={save} aria-labelledby={`${id}-name`}>
      <div className="stack" style={{ gap: 2 }}>
        <span id={`${id}-name`} className="strong">{policy.label}</span>
        <span className="tiny muted">Minimum {policy.min_days.toLocaleString()} days</span>
        {policy.updated_by && <span className="tiny muted">Changed by {policy.updated_by}, {fmtDate(policy.updated_at)}</span>}
      </div>
      <div className="field gv-field">
        <label htmlFor={`${id}-days`}>Keep for (days)</label>
        <input id={`${id}-days`} type="number" min={policy.min_days} max="36500" required value={days}
               aria-invalid={tooShort} aria-describedby={`${id}-hint`} onChange={(e) => setDays(e.target.value)} />
        <span id={`${id}-hint`} className="tiny muted">{tooShort ? `At least ${policy.min_days} days` : years(Number(days))}</span>
      </div>
      <div className="field gv-field">
        <label htmlFor={`${id}-notes`}>Basis or note</label>
        <input id={`${id}-notes`} maxLength={500} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>
      <div className="stack" style={{ gap: 4, alignItems: "flex-start" }}>
        <button className="btn sm primary" type="submit" disabled={!dirty || busy || tooShort || days === ""}>
          {busy ? "Saving…" : "Save"}
        </button>
        <span aria-live="polite" className="tiny">
          {error && <span style={{ color: "var(--alert-strong)" }}>{error}</span>}
          {saved && !dirty && <span className="muted">Saved</span>}
        </span>
      </div>
    </form>
  );
}

export default function RetentionPage() {
  const { data, error, loading } = useApi("/governance/retention");
  const [policies, setPolicies] = useState(null);
  const [dry, setDry] = useState(null);
  const [running, setRunning] = useState(false);
  const [dryError, setDryError] = useState(null);

  useEffect(() => {
    if (data) setPolicies(data.policies);
  }, [data]);

  async function dryRun() {
    setRunning(true);
    setDryError(null);
    try {
      setDry(await api("/governance/retention/dry-run", { method: "POST" }));
    } catch (e) {
      setDryError(e.message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <WorkspaceLayout>
      <PageHeader eyebrow="Trust and safety" title="Retention policies"
                  sub="How long each kind of data is kept before it becomes eligible for deletion.">
        <button className="btn dark" onClick={dryRun} disabled={running}>{running ? "Counting…" : "Run dry run"}</button>
      </PageHeader>

      <div className="banner info" style={{ marginBottom: 18 }}>
        <Lock size={16} /> Nothing is deleted in this version of Bioverse. Policies are recorded and the dry run
        counts what they would remove; deletion will need its own review and approval.
      </div>

      <div className="stack" style={{ gap: 18 }}>
        <article className="card stack">
          <span className="card-title">Policies</span>
          {error && <div className="error-box">{error.message}</div>}
          {loading && !policies && <div className="skeleton" />}
          {policies && (
            <div className="list">
              {policies.map((p) => (
                <PolicyRow key={p.category} policy={p} onSaved={(res) => { setPolicies(res.policies); setDry(null); }} />
              ))}
            </div>
          )}
        </article>

        <article className="card stack" aria-live="polite">
          <span className="card-title">Dry run</span>
          {dryError && <div className="error-box">{dryError}</div>}
          {!dry && !dryError && <p className="small muted">Run a dry run to count what each policy would remove today.</p>}
          {dry && (
            <>
              <p className="small">
                As of {new Date(dry.as_of).toLocaleString()}. <strong>{dry.deleted} records were deleted.</strong> {dry.note}
              </p>
              <div className="gv-table-wrap">
                <table className="gv-table">
                  <caption className="sr-only">Records each retention policy would remove</caption>
                  <thead><tr><th scope="col">Data</th><th scope="col">Keep for</th><th scope="col">Older than</th>
                    <th scope="col" className="gv-num">Would remove</th><th scope="col" className="gv-num">Total</th><th scope="col">Oldest</th></tr></thead>
                  <tbody>
                    {dry.categories.map((c) => (
                      <tr key={c.category}>
                        <td className="strong">{c.label}</td>
                        <td>{c.retention_days ? `${c.retention_days.toLocaleString()} days` : "No policy"}</td>
                        <td>{c.cutoff ? fmtDate(c.cutoff) : "—"}</td>
                        <td className="gv-num strong">{c.would_purge.toLocaleString()}</td>
                        <td className="gv-num">{c.total == null ? "—" : c.total.toLocaleString()}</td>
                        <td>{c.oldest ? fmtDate(c.oldest) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </article>
      </div>
    </WorkspaceLayout>
  );
}
