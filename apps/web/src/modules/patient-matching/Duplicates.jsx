import { useId, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { fmtDate, fmtDateTime } from "../../format.js";
import { Check, Warning } from "../../icons.jsx";
import { LevelChip, Reasons, ScoreBar, SOURCES, identifierText, moduleLabel } from "./shared.jsx";

const simple = (v) => (v == null ? "" : String(v).toLowerCase().normalize("NFKD").replace(/[^a-z0-9@]/g, ""));

function DataSummary({ records }) {
  if (!records) return <span className="muted">—</span>;
  if (!records.total) return <span className="muted">Nothing yet</span>;
  const top = Object.entries(records.by_module).sort((a, b) => b[1] - a[1]).slice(0, 4);
  return (
    <div>
      <div className="strong">{records.total} item{records.total === 1 ? "" : "s"}</div>
      <div className="tiny muted">{top.map(([t, n]) => `${moduleLabel(t)} ${n}`).join(" · ")}</div>
    </div>
  );
}

function Login({ p }) {
  if (!p.has_login) return <span className="muted">No sign-in</span>;
  return <span>Has a sign-in{p.login_disabled ? " (disabled)" : ""}</span>;
}

const ROWS = [
  { label: "Name", value: (p) => p.name, key: (p) => simple(p.name) },
  { label: "Date of birth", value: (p) => fmtDate(p.birth_date), key: (p) => p.birth_date },
  { label: "Sex at birth", value: (p) => p.sex_at_birth, key: (p) => p.sex_at_birth },
  { label: "Email", value: (p) => p.email, key: (p) => simple(p.email) },
  { label: "Phone", value: (p) => p.phone, key: (p) => (p.phone || "").replace(/\D/g, "").slice(-10) },
  { label: "Identifiers", value: (p) => (p.identifiers || []).map(identifierText).join(", "), key: () => null },
  { label: "Sign-in", value: (p) => <Login p={p} />, key: () => null },
  { label: "Record created", value: (p) => fmtDate(p.created_at), key: () => null },
  { label: "Data on record", value: (p) => <DataSummary records={p.records} />, key: () => null },
];

function Compare({ review }) {
  const { existing: a, new: b } = review;
  return (
    <div className="pm-compare-wrap">
      <table className="pm-compare">
        <thead>
          <tr>
            <th scope="col"><span className="sr-only">Field</span></th>
            <th scope="col">Existing record</th>
            <th scope="col">Newer record · {SOURCES[review.source] || review.source}</th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map((r) => {
            const ka = r.key(a);
            const kb = r.key(b);
            const both = ka && kb;
            const state = both ? (ka === kb ? "same" : "diff") : "";
            const va = r.value(a);
            const vb = r.value(b);
            return (
              <tr key={r.label}>
                <th scope="row">{r.label}</th>
                <td className={state}>{va || <span className="muted">—</span>}</td>
                <td className={state}>
                  {vb || <span className="muted">—</span>}
                  {state === "diff" && <span className="sr-only"> (differs)</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function MergeReport({ report }) {
  if (!report) return null;
  const kept = Object.entries(report.kept_on_retired || {});
  const moved = Object.keys(report.moved || {}).length;
  return (
    <div className="small">
      Moved {report.total_moved} item{report.total_moved === 1 ? "" : "s"} from {moved} area{moved === 1 ? "" : "s"}
      {report.login_moved ? "; the sign-in moved to the kept record" : ""}.
      {kept.length > 0 && (
        <> {report.total_kept} stayed with the retired record because the kept record already had the same
          ({kept.map(([t, n]) => `${moduleLabel(t).toLowerCase()} ${n}`).join(", ")}).</>
      )}
    </div>
  );
}

function MergePanel({ review, onCancel, onMerged }) {
  const { existing: a, new: b } = review;
  const both = a.has_login && b.has_login;
  const suggested = b.has_login && !a.has_login ? b.id
    : (b.records?.total || 0) > (a.records?.total || 0) && !a.has_login ? b.id : a.id;
  const [survivor, setSurvivor] = useState(suggested);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const name = useId();
  const keep = survivor === a.id ? a : b;
  const retire = survivor === a.id ? b : a;

  async function merge() {
    setBusy(true);
    setError(null);
    try {
      const out = await api(`/patient-matching/reviews/${review.id}/merge`, { method: "POST", body: { survivor } });
      onMerged(out);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="pm-merge" role="group" aria-labelledby={`${name}-h`}>
      <h3 id={`${name}-h`} className="small strong">Which record do you keep?</h3>
      <div className="pm-choices">
        {[a, b].map((p) => (
          <label key={p.id} className={`pm-choice ${survivor === p.id ? "on" : ""}`}>
            <input type="radio" name={name} value={p.id} checked={survivor === p.id} onChange={() => setSurvivor(p.id)} />
            <span>
              <span className="strong">{p.name}</span>
              <span className="tiny muted" style={{ display: "block" }}>
                {p === a ? "Existing record" : "Newer record"} · {p.has_login ? "has a sign-in" : "no sign-in"}
                {" · "}{p.records?.total ?? 0} items
              </span>
            </span>
          </label>
        ))}
      </div>
      {both ? (
        <div className="banner warn" role="alert">
          <Warning size={16} /> Both records have their own sign-in, so they can't be merged here. Disable the extra
          account in People &amp; sign-in first.
        </div>
      ) : (
        <ul className="small pm-consequences">
          <li>Everything on <strong>{retire.name}</strong>'s record ({retire.records?.total ?? 0} items
            {retire.identifiers?.length ? `, plus ${retire.identifiers.length} identifier${retire.identifiers.length === 1 ? "" : "s"}` : ""})
            moves to <strong>{keep.name}</strong>'s record. Details missing on the kept record are filled in.</li>
          {retire.has_login && <li>The sign-in moves too: the patient keeps signing in as before and sees the kept record.</li>}
          <li>The other record is retired, not deleted: it stays for audit and legal purposes and disappears from lists.</li>
          <li><strong>This can't be undone in Bioverse.</strong> There is no unmerge.</li>
        </ul>
      )}
      {error && <div className="error-box" role="alert">{error}</div>}
      <div className="row wrap">
        <button className="btn primary sm" type="button" onClick={merge} disabled={busy || both}>
          {busy ? "Merging..." : `Merge into ${keep.name}'s record`}
        </button>
        <button className="btn sm" type="button" onClick={onCancel} disabled={busy}>Cancel</button>
      </div>
    </div>
  );
}

function ReviewCard({ review, onDecided }) {
  const [merging, setMerging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const open = review.status === "open";
  const h = useId();

  async function notDuplicate() {
    setBusy(true);
    setError(null);
    try {
      await api(`/patient-matching/reviews/${review.id}/not-duplicate`, { method: "POST" });
      onDecided({ kind: "not_duplicate", review });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <article className={`card pm-review ${review.level}`} aria-labelledby={h}>
      <div className="row between wrap">
        <div className="stack" style={{ gap: 4 }}>
          <h2 id={h} className="card-title">
            {review.existing.name} <span className="muted" aria-hidden="true">·</span>{" "}
            <span className="sr-only">and </span>{review.new.name}
          </h2>
          <div className="tiny muted">
            Flagged {fmtDateTime(review.created_at)} · {SOURCES[review.source] || review.source}
          </div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <LevelChip level={review.level} score={review.score} />
          <ScoreBar score={review.score} />
        </div>
      </div>

      <div className="pm-body">
        <Compare review={review} />
        <div className="pm-why">
          <div className="eyebrow">Why these were matched</div>
          <Reasons reasons={review.reasons} />
        </div>
      </div>

      {error && <div className="error-box" role="alert">{error}</div>}
      {open && !merging && (
        <div className="row wrap">
          <button className="btn primary sm" type="button" onClick={() => setMerging(true)} disabled={busy}>Merge…</button>
          <button className="btn sm" type="button" onClick={notDuplicate} disabled={busy}>
            {busy ? "Saving..." : "Not a duplicate"}
          </button>
        </div>
      )}
      {open && merging && (
        <MergePanel review={review} onCancel={() => setMerging(false)}
                    onMerged={(out) => onDecided({ kind: "merged", review, report: out.report })} />
      )}
      {!open && (
        <div className="pm-decided">
          <span className={`chip ${review.status === "merged" ? "ok" : ""}`}>
            {review.status === "merged" ? "Merged" : "Not a duplicate"}
          </span>
          <span className="small muted">
            {review.decided_by ? `${review.decided_by} · ` : ""}{fmtDateTime(review.decided_at)}
            {review.status === "merged" && review.survivor &&
              ` · kept ${review.survivor === review.existing?.id ? "the existing" : "the newer"} record`}
          </span>
          <MergeReport report={review.merge_report} />
        </div>
      )}
    </article>
  );
}

export default function Duplicates() {
  const [view, setView] = useState("open");
  const q = useApi(`/patient-matching/reviews?status=${view}`);
  const [notice, setNotice] = useState(null);

  function decided({ kind, review, report }) {
    setNotice(kind === "merged"
      ? { kind, text: `Merged ${review.existing.name} and ${review.new.name}.`, report }
      : { kind, text: `Marked ${review.existing.name} and ${review.new.name} as different people.` });
    q.reload();
  }

  const reviews = q.data?.reviews || [];
  return (
    <WorkspaceLayout>
      <div className="pm">
        <div className="page-head">
          <div>
            <h1 className="page-title">Duplicate records</h1>
            <div className="page-sub">
              Records that may belong to the same person. Merge them, or keep them apart. New sign-ups, invites,
              imports and lab messages are checked automatically.
            </div>
          </div>
        </div>

        <div className="row between wrap" style={{ marginBottom: 14 }}>
          <div className="pm-tabs" role="tablist" aria-label="Reviews">
            <button role="tab" aria-selected={view === "open"} onClick={() => { setView("open"); setNotice(null); }}>
              To review{q.data ? ` (${q.data.open})` : ""}
            </button>
            <button role="tab" aria-selected={view === "decided"} onClick={() => { setView("decided"); setNotice(null); }}>
              Decided
            </button>
          </div>
          <Link to="/registry/find" className="btn sm">Find a patient record</Link>
        </div>

        <div aria-live="polite">
          {notice && (
            <div className="banner ok pm-notice">
              <Check size={16} />
              <div>
                <div>{notice.text}</div>
                {notice.report && <MergeReport report={notice.report} />}
              </div>
            </div>
          )}
        </div>

        {q.error && <div className="error-box">{q.error.message}</div>}
        {q.loading && !q.data && <div className="card"><div className="skeleton" /></div>}
        {q.data && reviews.length === 0 && (
          <div className="card empty">
            {view === "open" ? "No possible duplicates to review." : "Nothing decided yet."}
          </div>
        )}
        <div className="stack">
          {reviews.map((r) => <ReviewCard key={r.id} review={r} onDecided={decided} />)}
        </div>
      </div>
    </WorkspaceLayout>
  );
}
