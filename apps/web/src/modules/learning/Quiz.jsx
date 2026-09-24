import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { Back, Check, Close } from "../../icons.jsx";

export default function Quiz() {
  const { caseId } = useParams();
  const { data, error, loading, reload } = useApi(`/learning/cases/${caseId}/quiz`);
  const [answers, setAnswers] = useState({});
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setSubmitError(null);
    try {
      const body = { answers: data.questions.map((q) => (answers[q.n] ?? null)) };
      setResult(await api(`/learning/cases/${caseId}/quiz`, { method: "POST", body }));
      window.scrollTo?.({ top: 0 });
    } catch (err) {
      setSubmitError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (loading && !data) return <main className="column"><div className="card"><div className="skeleton" /></div></main>;
  if (error) {
    return <main className="column stack"><div className="error-box row between wrap"><span>{error.message}</span>
      <button className="btn sm" onClick={reload}>Try again</button></div></main>;
  }
  const all = data.questions.every((q) => answers[q.n] != null);

  return (
    <main className="column ln-quiz">
      <div className="row" style={{ marginBottom: 8 }}>
        <Link to={`/learning/cases/${caseId}`} className="btn ghost sm"><Back size={16} /> Back to the case</Link>
      </div>
      <div className="eyebrow">Quiz</div>
      <h1 className="page-title" style={{ marginBottom: 12 }}>{data.title}</h1>

      {result && (
        <div className={`card stack ${result.score === result.total ? "highlight" : ""}`} role="status">
          <div className="card-title">You scored {result.score} of {result.total}</div>
          <div className="row wrap">
            <button className="btn sm" onClick={() => { setResult(null); setAnswers({}); }}>Try again</button>
            <Link className="btn sm" to="/learning/progress">See your progress</Link>
          </div>
        </div>
      )}

      {data.questions.length === 0 && <div className="card empty">This case has no quiz.</div>}
      <form onSubmit={submit} className="stack" style={{ marginTop: 12 }}>
        {data.questions.map((q) => {
          const r = result?.results.find((x) => x.n === q.n);
          return (
            <fieldset key={q.n} className="card stack ln-q">
              <legend className="sr-only">Question {q.n}</legend>
              <p className="strong small">{q.n}. {q.question}</p>
              <div className="stack" style={{ gap: 6 }}>
                {q.options.map((o, i) => {
                  const chosen = (r ? r.chosen : answers[q.n]) === i;
                  const cls = r ? (i === r.answer ? "right" : chosen ? "wrong" : "") : chosen ? "chosen" : "";
                  return (
                    <label key={i} className={`ln-option ${cls}`}>
                      <input type="radio" name={`q${q.n}`} checked={chosen} disabled={Boolean(result)}
                             onChange={() => setAnswers({ ...answers, [q.n]: i })} />
                      <span>{o}</span>
                      {r && i === r.answer && <Check size={16} />}
                      {r && chosen && i !== r.answer && <Close size={16} />}
                    </label>
                  );
                })}
              </div>
              {r && <p className={`small ${r.correct ? "" : "muted"}`}><span className="strong">{r.correct ? "Correct." : "Not quite."}</span> {r.explanation}</p>}
            </fieldset>
          );
        })}
        {submitError && <div className="error-box small" role="alert">{submitError}</div>}
        {!result && data.questions.length > 0 && (
          <button className="btn primary" type="submit" disabled={busy || !all}>{busy ? "Scoring..." : "Submit answers"}</button>
        )}
      </form>
    </main>
  );
}
