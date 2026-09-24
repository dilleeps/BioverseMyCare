import { Link } from "react-router-dom";
import { useApi } from "../../hooks.js";
import { useSession } from "../../session.jsx";
import { Chevron, Lock } from "../../icons.jsx";

const DIFFICULTY = { core: "Core", intermediate: "Intermediate", advanced: "Advanced" };

function progressChip(c) {
  if (c.attempt_status === "completed") return <span className="chip ok">Completed · {c.attempt_score}%</span>;
  if (c.attempt_status === "in_progress") return <span className="chip warn">In progress</span>;
  return <span className="chip">Not started</span>;
}

export default function LearningHome() {
  const { me } = useSession();
  const cases = useApi("/learning/cases");
  const history = useApi("/learning/history");
  const stats = history.data?.stats;

  return (
    <main className="page ln-page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Medical student{me ? ` · ${me.display_name}` : ""}</div>
          <h1 className="page-title">Case library</h1>
          <p className="page-sub">Work through real-world cases one stage at a time. Commit to your thinking, then see what happened.</p>
        </div>
      </div>

      <div className="banner info ln-privacy"><Lock size={15} />
        Every case is de-identified: no names, record numbers or contact details, dates shifted, ages over 89 grouped.
        Students never see patient records.
      </div>

      {stats && (
        <div className="stats ln-stats" aria-label="Your progress">
          <div className="stat"><div className="n">{stats.cases_completed}</div><div className="tiny muted">Cases completed</div></div>
          <div className="stat"><div className="n">{stats.average_case_score ?? "–"}{stats.average_case_score != null ? "%" : ""}</div><div className="tiny muted">Average case score</div></div>
          <div className="stat"><div className="n">{stats.quizzes_taken}</div><div className="tiny muted">Quizzes taken</div></div>
          <div className="stat"><div className="n">{stats.average_quiz_percent ?? "–"}{stats.average_quiz_percent != null ? "%" : ""}</div><div className="tiny muted">Average quiz score</div></div>
        </div>
      )}

      {cases.loading && !cases.data && <div className="card"><div className="skeleton" /></div>}
      {cases.error && (
        <div className="error-box row between wrap"><span>Couldn't load cases. {cases.error.message}</span>
          <button className="btn sm" onClick={cases.reload}>Try again</button></div>
      )}
      {cases.data?.length === 0 && <div className="card empty">No cases are published yet.</div>}
      {cases.data?.length > 0 && (
        <div className="ln-grid">
          {cases.data.map((c) => (
            <article key={c.id} className="card stack ln-case" aria-labelledby={`ln-${c.id}`}>
              <div className="row between wrap" style={{ gap: 6 }}>
                <span className="eyebrow">{c.specialty} · {DIFFICULTY[c.difficulty] || c.difficulty}</span>
                {progressChip(c)}
              </div>
              <h2 id={`ln-${c.id}`} className="ln-case-title">{c.title}</h2>
              <p className="small muted">{c.summary}</p>
              <div className="row wrap" style={{ marginTop: "auto" }}>
                <Link className="btn primary sm" to={`/learning/cases/${c.id}`}>
                  {c.attempt_status === "completed" ? "Review case" : c.attempt_status === "in_progress" ? "Continue" : "Start case"}
                  <Chevron size={14} />
                </Link>
                {c.quiz_count > 0 && (
                  <Link className="btn sm" to={`/learning/cases/${c.id}/quiz`}>
                    Quiz{c.best_quiz != null ? ` · best ${c.best_quiz}%` : ""}
                  </Link>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
      <p className="tiny muted" style={{ marginTop: 16 }}>
        Also useful: <Link to="/learning/evidence">search the evidence library</Link>, <Link to="/factcheck">check a health claim</Link>,
        or <Link to="/specialists">ask a specialist's AI assistant</Link>.
      </p>
    </main>
  );
}
