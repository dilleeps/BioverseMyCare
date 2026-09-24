import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { WorkspaceLayout } from "../../layouts.jsx";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { fmtDateTime } from "../../format.js";
import { Book, Lock, Sparkle, Warning } from "../../icons.jsx";
import { ExternalLink, SourceChips } from "./shared.jsx";

const FALLBACK_REASONS = {
  refusal: "the AI declined this question",
  "search did not finish": "the web search did not finish in time",
  "no cited statements": "the AI could not support an answer with citations",
  "output truncated": "the AI answer was cut short",
  "AI is disabled": "AI is switched off",
};

function Answer({ answer }) {
  const ai = answer.mode === "ai";
  return (
    <article className="card stack" aria-labelledby="answer-title" aria-live="polite">
      <div className="row between wrap">
        <h2 id="answer-title" className="card-title">Answer</h2>
        <span className={`chip ${ai ? "ok" : ""}`}>
          {ai ? <Sparkle size={12} /> : <Book size={12} />} {answer.label}
        </span>
      </div>
      <p className="small muted">Question: {answer.question}</p>

      {answer.redactions > 0 && (
        <div className="banner info"><Lock size={15} />
          Removed {answer.redactions} patient {answer.redactions === 1 ? "identifier" : "identifiers"} before searching.
        </div>
      )}
      {answer.context_used && (
        <div className="banner info"><Lock size={15} />
          {answer.context_sent_to_ai
            ? "Used this patient's de-identified context: age band, abnormal results, medicines and allergies."
            : "Used this patient's de-identified context to search the library."}
        </div>
      )}
      {answer.notes?.map((n) => <div key={n} className="banner info">{n}</div>)}
      {answer.fallback_reason && (
        <div className="banner warn"><Warning size={15} />
          AI synthesis unavailable because {FALLBACK_REASONS[answer.fallback_reason] || "of a service problem"}.
          Showing retrieved evidence instead.
        </div>
      )}
      {answer.removed_count > 0 && (
        <div className="banner warn"><Warning size={15} />
          {answer.removed_count} {answer.removed_count === 1 ? "statement was" : "statements were"} removed because
          {answer.removed_count === 1 ? " it had" : " they had"} no citation.
        </div>
      )}

      {answer.no_evidence ? (
        <div className="stack" style={{ gap: 6 }}>
          <div className="banner info"><Book size={15} /> {answer.message || "No evidence found in the library."}</div>
          <p className="small muted">Bioverse answers clinical questions only with a cited source. Try different terms,
            such as a drug name, a lab test or a condition.</p>
        </div>
      ) : (
        <ol className="ev-statements">
          {answer.statements.map((s, i) => (
            <li key={i}>
              {s.text}{" "}
              {s.citations.map((n) => (
                <a key={n} href={`#ev-src-${n}`} className="ev-cite" aria-label={`Source ${n}`}>[{n}]</a>
              ))}
            </li>
          ))}
        </ol>
      )}

      {answer.sources.length > 0 && (
        <section className="stack" style={{ gap: 8 }} aria-labelledby="sources-title">
          <h3 id="sources-title" className="eyebrow">Sources</h3>
          <ol className="list ev-sources">
            {answer.sources.map((src) => (
              <li key={src.n} id={`ev-src-${src.n}`} className="ev-source">
                <span className="ev-num" aria-hidden="true">{src.n}</span>
                <div className="stack" style={{ gap: 4, minWidth: 0 }}>
                  <ExternalLink href={src.url} className="strong small ev-title">{src.title}</ExternalLink>
                  <span className="tiny muted">{src.publisher}</span>
                  <SourceChips source={src} />
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}
      <p className="tiny muted">Evidence supports your clinical judgment. It does not replace it.</p>
    </article>
  );
}

function History({ items, error, onOpen, activeId }) {
  return (
    <article className="card stack" aria-labelledby="history-title">
      <h2 id="history-title" className="card-title">Your recent questions</h2>
      {error && <div className="error-box small">{error.message}</div>}
      {!items && !error && <div className="skeleton" />}
      {items?.length === 0 && <p className="small muted">Questions you ask appear here.</p>}
      {items?.length > 0 && (
        <ul className="list ev-history">
          {items.map((h) => (
            <li key={h.id}>
              <button className="ev-history-item" aria-current={h.id === activeId} onClick={() => onOpen(h.id)}>
                <span className="small strong">{h.question}</span>
                <span className="tiny muted">
                  {fmtDateTime(h.created_at)} · {h.mode === "ai" ? "AI synthesis" : "Retrieved"} · {h.sources_count}{" "}
                  {h.sources_count === 1 ? "source" : "sources"}{h.context_used ? " · patient context" : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

export default function EvidencePage() {
  const [params] = useSearchParams();
  const patients = useApi("/clinician/patients");
  const history = useApi("/evidence/history");
  const [question, setQuestion] = useState("");
  const [useContext, setUseContext] = useState(Boolean(params.get("patient")));
  const [patientId, setPatientId] = useState(params.get("patient") || "");
  const [answer, setAnswer] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const answerRef = useRef(null);

  useEffect(() => {
    if (!patientId && patients.data?.length) setPatientId(patients.data[0].id);
  }, [patients.data, patientId]);

  useEffect(() => {
    if (answer) answerRef.current?.focus();
  }, [answer]);

  async function submit(e) {
    e.preventDefault();
    if (question.trim().length < 3) return;
    setBusy(true);
    setError(null);
    try {
      const body = { question: question.trim(), patient_id: useContext && patientId ? patientId : null };
      setAnswer(await api("/evidence/ask", { method: "POST", body }));
      history.reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function open(id) {
    setError(null);
    try {
      setAnswer(await api(`/evidence/queries/${id}`));
    } catch (err) {
      setError(err.message);
    }
  }

  const selected = patients.data?.find((p) => p.id === patientId);

  return (
    <WorkspaceLayout>
      <div className="page-head">
        <div>
          <h1 className="page-title">Evidence</h1>
          <p className="page-sub">Cited answers from guidelines, reviews and drug labels. No source, no answer.</p>
        </div>
      </div>
      <div className="ws-grid">
        <div className="span-8 stack">
          <form className="card stack" onSubmit={submit} aria-labelledby="ask-title">
            <h2 id="ask-title" className="card-title">Ask a clinical question</h2>
            <div className="stack" style={{ gap: 6 }}>
              <label htmlFor="ev-question" className="small strong">Question</label>
              <textarea
                id="ev-question"
                className="edit"
                value={question}
                maxLength={1000}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="For example: when should LDL be rechecked after starting atorvastatin?"
                aria-describedby="ev-question-hint"
              />
              <span id="ev-question-hint" className="tiny muted">
                Leave out names and record numbers. Bioverse removes any it finds before searching.
              </span>
            </div>
            <div className="toggle-row">
              <input id="ev-context" type="checkbox" checked={useContext} onChange={(e) => setUseContext(e.target.checked)}
                     aria-describedby="ev-context-hint" />
              <label htmlFor="ev-context">Use this patient's context (de-identified)</label>
            </div>
            {useContext && (
              <div className="stack" style={{ gap: 6 }}>
                <label htmlFor="ev-patient" className="small strong">Patient</label>
                <select id="ev-patient" className="ev-select" value={patientId} onChange={(e) => setPatientId(e.target.value)}
                        disabled={!patients.data?.length}>
                  {patients.data?.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.age}</option>)}
                </select>
                {patients.data?.length === 0 && <span className="tiny muted">No patients on your list.</span>}
              </div>
            )}
            <span id="ev-context-hint" className="tiny muted">
              {useContext && selected
                ? `Only ${selected.name.split(" ")[0]}'s age band, abnormal results, active medicines and allergies are used. No name, dates or IDs.`
                : "Off: your question is answered on its own."}
            </span>
            {error && <div className="error-box small" role="alert">{error}</div>}
            <div className="row wrap">
              <button className="btn primary" type="submit" disabled={busy || question.trim().length < 3}>
                {busy ? "Searching sources..." : "Search evidence"}
              </button>
            </div>
          </form>

          {busy && <div className="card" aria-busy="true"><div className="skeleton" /></div>}
          {!busy && answer && <div ref={answerRef} tabIndex={-1} style={{ outline: "none" }}><Answer answer={answer} /></div>}
          {!busy && !answer && (
            <div className="card empty small">Ask a question to see cited evidence. Every statement links to its source.</div>
          )}
        </div>
        <div className="span-4">
          <History items={history.data} error={history.error} onOpen={open} activeId={answer?.id} />
        </div>
      </div>
    </WorkspaceLayout>
  );
}
