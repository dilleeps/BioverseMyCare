import { Link } from "react-router-dom";
import { useApi } from "../../hooks.js";
import { fmtDateTime } from "../../format.js";

export default function Progress() {
  const { data, error, loading, reload } = useApi("/learning/history");
  return (
    <main className="page ln-page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Learning</div>
          <h1 className="page-title">Your progress</h1>
          <p className="page-sub">Case scores count the key points you covered at each stage.</p>
        </div>
      </div>
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {error && <div className="error-box row between wrap"><span>{error.message}</span><button className="btn sm" onClick={reload}>Try again</button></div>}
      {data && (
        <div className="stack">
          <div className="stats">
            <div className="stat"><div className="n">{data.stats.cases_completed}</div><div className="tiny muted">Cases completed</div></div>
            <div className="stat"><div className="n">{data.stats.average_case_score ?? "–"}</div><div className="tiny muted">Average case score (%)</div></div>
            <div className="stat"><div className="n">{data.stats.quizzes_taken}</div><div className="tiny muted">Quizzes taken</div></div>
            <div className="stat"><div className="n">{data.stats.average_quiz_percent ?? "–"}</div><div className="tiny muted">Average quiz score (%)</div></div>
          </div>
          <div className="ln-two">
            <section className="card stack" aria-labelledby="pr-cases">
              <h2 id="pr-cases" className="card-title">Cases</h2>
              {data.attempts.length === 0 && <p className="small muted">No cases yet. <Link to="/learning">Start one</Link>.</p>}
              <ul className="list ln-hist">
                {data.attempts.map((a) => (
                  <li key={a.id}>
                    <Link to={`/learning/cases/${a.case_id}`} className="small strong">{a.title}</Link>
                    <span className="tiny muted">
                      {a.status === "completed" ? `Completed · ${a.score}%` : `In progress · ${a.answered} answered`} · {fmtDateTime(a.started_at)}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
            <section className="card stack" aria-labelledby="pr-quiz">
              <h2 id="pr-quiz" className="card-title">Quizzes</h2>
              {data.quizzes.length === 0 && <p className="small muted">No quizzes yet.</p>}
              <ul className="list ln-hist">
                {data.quizzes.map((q) => (
                  <li key={q.id}>
                    <Link to={`/learning/cases/${q.case_id}/quiz`} className="small strong">{q.title}</Link>
                    <span className="tiny muted">{q.score} of {q.total} · {fmtDateTime(q.created_at)}</span>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </div>
      )}
    </main>
  );
}
