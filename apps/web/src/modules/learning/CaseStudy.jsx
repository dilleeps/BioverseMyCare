import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { Back, Book, Check, Lock, Sparkle } from "../../icons.jsx";

function StageTable({ rows }) {
  return (
    <div className="ln-table-wrap">
      <table className="ln-table">
        <thead>
          <tr><th scope="col">Test</th><th scope="col">Result</th><th scope="col">Reference</th><th scope="col">Date</th></tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={r.flag ? "flag" : ""}>
              <td>{r.test}</td>
              <td className="strong">{r.value} {r.unit}{r.flag ? ` · ${r.flag}` : ""}</td>
              <td>{r.reference || "–"}</td>
              <td>{r.date}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Feedback({ response, completed }) {
  return (
    <div className="ln-feedback stack" aria-label="Tutor feedback">
      <div className="ln-answer">
        <div className="eyebrow">Your answer</div>
        <p className="small">{response.answer}</p>
      </div>
      <div className="stack" style={{ gap: 6 }}>
        <div className="eyebrow row" style={{ gap: 6 }}>
          {response.mode === "ai" ? <Sparkle size={12} /> : <Book size={12} />} Tutor
        </div>
        <p className="small">{response.feedback}</p>
        {response.covered.length > 0 && (
          <div className="row wrap" style={{ gap: 6 }}>
            {response.covered.map((c) => <span key={c} className="chip ok"><Check size={12} /> {c}</span>)}
          </div>
        )}
        {completed && response.missed.length > 0 && (
          <div className="row wrap" style={{ gap: 6 }}>
            {response.missed.map((c) => <span key={c} className="chip">Missed: {c}</span>)}
          </div>
        )}
        {response.question && !completed && <p className="small ln-socratic">{response.question}</p>}
      </div>
    </div>
  );
}

export default function CaseStudy() {
  const { caseId } = useParams();
  const { data, error, loading, reload } = useApi(`/learning/cases/${caseId}`);
  const [view, setView] = useState(null);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);
  const promptRef = useRef(null);

  useEffect(() => {
    if (data) setView(data);
  }, [data]);

  async function start() {
    setBusy(true);
    setActionError(null);
    try {
      setView(await api(`/learning/cases/${caseId}/attempts`, { method: "POST" }));
    } catch (err) {
      setActionError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setActionError(null);
    try {
      const out = await api(`/learning/attempts/${view.attempt.id}/respond`, { method: "POST", body: { answer } });
      setView(out);
      setAnswer("");
      setTimeout(() => promptRef.current?.scrollIntoView?.({ block: "start", behavior: "smooth" }), 50);
    } catch (err) {
      setActionError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (loading && !view) return <main className="page ln-page"><div className="card"><div className="skeleton" /></div></main>;
  if (error) {
    return (
      <main className="page ln-page stack">
        <div className="error-box row between wrap"><span>{error.message}</span><button className="btn sm" onClick={reload}>Try again</button></div>
        <Link to="/learning" className="btn">Back to the case library</Link>
      </main>
    );
  }
  if (!view) return null;

  const attempt = view.attempt;
  const completed = attempt?.status === "completed";
  const responses = attempt?.responses || [];
  const stageIndex = (n) => n - 1;

  return (
    <main className="page ln-page">
      <div className="row" style={{ marginBottom: 8 }}>
        <Link to="/learning" className="btn ghost sm"><Back size={16} /> Case library</Link>
      </div>
      <div className="page-head">
        <div>
          <div className="eyebrow">{view.specialty} · {view.demographics?.sex}, {view.demographics?.age}</div>
          <h1 className="page-title">{view.title}</h1>
          <p className="page-sub">
            {completed
              ? `Finished · score ${attempt.score}%`
              : attempt
                ? `Question ${view.current?.number} of ${view.current?.of}. Commit to an answer to see the next stage.`
                : "Read the presentation, then start the case."}
          </p>
        </div>
      </div>

      <div className="ln-progress" aria-hidden="true">
        {Array.from({ length: view.total_stages }).map((_, i) => (
          <span key={i} className={i < view.stages.length ? "on" : ""} />
        ))}
      </div>

      <ol className="ln-stages">
        {view.stages.map((s) => {
          const response = responses.find((r) => r.stage === stageIndex(s.n));
          const isCurrent = view.current && view.current.stage === stageIndex(s.n);
          return (
            <li key={s.n} className="card stack ln-stage" ref={isCurrent ? promptRef : null}>
              <div className="row between wrap">
                <h2 className="card-title">Stage {s.n} · {s.title}</h2>
              </div>
              {s.lines?.length > 0 && (
                <ul className="ln-lines">
                  {s.lines.map((l, i) => <li key={i} className="small">{l}</li>)}
                </ul>
              )}
              {s.table && <StageTable rows={s.table} />}
              {s.prompt && (response || isCurrent || completed) && (
                <div className="ln-prompt"><span className="eyebrow">Your turn</span><p className="strong small">{s.prompt}</p></div>
              )}
              {response && <Feedback response={response} completed={completed} />}
              {isCurrent && (
                <form className="stack" onSubmit={submit}>
                  <label htmlFor="ln-answer" className="sr-only">Your answer</label>
                  <textarea id="ln-answer" className="edit" value={answer} maxLength={4000}
                            placeholder="Commit to your differential or plan before you see more."
                            onChange={(e) => setAnswer(e.target.value)} aria-describedby="ln-answer-hint" />
                  <span id="ln-answer-hint" className="tiny muted">At least a sentence. The tutor won't give the answer away.</span>
                  {actionError && <div className="error-box small" role="alert">{actionError}</div>}
                  <div className="row wrap">
                    <button className="btn primary" type="submit" disabled={busy || answer.trim().length < 15}>
                      {busy ? "Thinking..." : "Commit and reveal next stage"}
                    </button>
                  </div>
                </form>
              )}
              {completed && s.model_answer && (
                <div className="ln-model stack">
                  <div className="eyebrow">Model answer</div>
                  <p className="small">{s.model_answer}</p>
                </div>
              )}
            </li>
          );
        })}
      </ol>

      {!attempt && (
        <div className="card stack">
          <p className="small">You'll see the case in stages. At each stage, write your thinking; the tutor responds with feedback and a question, then reveals what came next.</p>
          {actionError && <div className="error-box small" role="alert">{actionError}</div>}
          <div><button className="btn primary" onClick={start} disabled={busy}>Start case</button></div>
        </div>
      )}

      {completed && (
        <section className="card stack" aria-labelledby="ln-wrap">
          <h2 id="ln-wrap" className="card-title">Teaching points</h2>
          <ul className="ln-lines">{view.teaching_points?.map((t) => <li key={t} className="small">{t}</li>)}</ul>
          {view.evidence?.length > 0 && (
            <>
              <div className="eyebrow">Evidence</div>
              <ul className="list ln-evidence">
                {view.evidence.map((e) => (
                  <li key={e.item_id}>
                    <a href={e.url} target="_blank" rel="noopener noreferrer" className="small strong">{e.title}<span className="sr-only"> (opens in a new tab)</span></a>
                    <div className="tiny muted">{e.source} · {e.year}</div>
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="row wrap">
            {view.quiz_count > 0 && <Link className="btn primary" to={`/learning/cases/${caseId}/quiz`}>Take the quiz</Link>}
            <button className="btn" onClick={start} disabled={busy}>Try the case again</button>
          </div>
        </section>
      )}
      <p className="tiny muted ln-deid"><Lock size={12} /> {view.deidentification?.method}</p>
    </main>
  );
}
