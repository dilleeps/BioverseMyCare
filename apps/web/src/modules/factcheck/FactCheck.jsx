import { useEffect, useRef, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { Book, Check, Phone, Shield, Warning } from "../../icons.jsx";

const MAX = 5000;

const VERDICT_CLASS = {
  supported: "ok",
  contradicted: "warn",
  misleading: "warn",
  not_enough_evidence: "",
};

function ExternalLink({ href, children, className }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
      {children}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

function Citations({ items, label }) {
  if (!items?.length) return null;
  return (
    <div className="stack fc-cites">
      <div className="eyebrow">{label}</div>
      <ul className="list fc-cite-list">
        {items.map((c) => (
          <li key={c.item_id}>
            <ExternalLink href={c.url} className="small strong fc-cite-title">{c.title}</ExternalLink>
            <span className="tiny muted">
              {c.source} · {c.year} · {c.type_label}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SafetyBlock({ safety }) {
  return (
    <section className="emergency stack" role="alert" aria-labelledby="fc-safety-title">
      <h2 id="fc-safety-title" className="card-title row" style={{ gap: 8 }}>
        <Warning size={18} /> {safety.level === "crisis" ? "Help is available now" : "This may be an emergency"}
      </h2>
      <p className="small">{safety.message}</p>
      <a className="call" href={`tel:${safety.call}`}><Phone size={20} /> Call {safety.call}</a>
    </section>
  );
}

function ClaimCard({ claim }) {
  return (
    <article className="card stack fc-claim" aria-labelledby={`fc-claim-${claim.n}`}>
      <div className="row between wrap fc-claim-head">
        <span className={`chip fc-verdict ${VERDICT_CLASS[claim.verdict]}`}>
          {claim.verdict === "supported" && <Check size={12} />}
          {(claim.verdict === "contradicted" || claim.verdict === "misleading") && <Warning size={12} />}
          {claim.verdict_label}
        </span>
        <span className="tiny muted">
          {claim.method === "curated" ? "Reviewed claim" : claim.method === "ai" ? "AI check against sources" : "Library search"}
        </span>
      </div>
      <h3 id={`fc-claim-${claim.n}`} className="fc-claim-text">“{claim.claim}”</h3>
      <p className="fc-explain">{claim.explanation}</p>
      <Citations items={claim.citations} label="Sources" />
      {claim.related?.length > 0 && (
        <details className="fc-related">
          <summary className="small strong">Related reading (not a verdict)</summary>
          <Citations items={claim.related} label="Related sources" />
        </details>
      )}
    </article>
  );
}

function ShareCard({ share, disclaimer }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);

  async function copy() {
    setFailed(false);
    try {
      await navigator.clipboard.writeText(share.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      setFailed(true);
    }
  }

  return (
    <section className="card stack fc-share" aria-labelledby="fc-share-title">
      <div className="row between wrap">
        <h2 id="fc-share-title" className="card-title row" style={{ gap: 8 }}><Shield size={18} /> Share-safe summary</h2>
        <button type="button" className="btn sm" onClick={copy}>{copied ? "Copied" : "Copy summary"}</button>
      </div>
      <p className="tiny muted">Names, phone numbers and e-mail addresses are removed. Only the claims and verdicts are included.</p>
      <div className="fc-share-preview">
        <div className="strong small">Health fact check (Bioverse One)</div>
        <ul>
          {share.lines.map((l, i) => (
            <li key={i} className="small">
              <span className="strong">“{l.claim}”</span>: {l.verdict_label}. {l.explanation}
              {l.sources && <span className="muted"> Sources: {l.sources}.</span>}
            </li>
          ))}
        </ul>
        <div className="tiny muted">{disclaimer}</div>
      </div>
      {failed && <div className="error-box small" role="alert">Couldn't copy. Select the text above and copy it instead.</div>}
      <span className="sr-only" aria-live="polite">{copied ? "Summary copied" : ""}</span>
    </section>
  );
}

export default function FactCheck() {
  const examples = useApi("/factcheck/examples");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const resultRef = useRef(null);

  useEffect(() => {
    if (result) resultRef.current?.focus();
  }, [result]);

  async function submit(e) {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api("/factcheck/check", { method: "POST", body: { text } }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const counts = result?.claims?.reduce((acc, c) => ({ ...acc, [c.verdict]: (acc[c.verdict] || 0) + 1 }), {}) || {};

  return (
    <main className="page fc-page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Health fact check</div>
          <h1 className="page-title">Is this true?</h1>
          <p className="page-sub">
            Paste a forwarded message, a social post or part of an article. Bioverse checks each health claim against
            published evidence and shows its sources.
          </p>
        </div>
      </div>

      <form className="card stack" onSubmit={submit} aria-labelledby="fc-form-title">
        <h2 id="fc-form-title" className="sr-only">Text to check</h2>
        <div className="stack" style={{ gap: 6 }}>
          <label htmlFor="fc-text" className="small strong">Paste the text</label>
          <textarea
            id="fc-text"
            className="edit fc-textarea"
            value={text}
            maxLength={MAX}
            onChange={(e) => setText(e.target.value)}
            placeholder="For example: garlic cures high blood pressure, so you can stop your pills."
            aria-describedby="fc-hint fc-count"
          />
          <div className="row between wrap">
            <span id="fc-hint" className="tiny muted">Paste words, not links. Bioverse doesn't open links.</span>
            <span id="fc-count" className={`tiny ${text.length > MAX - 200 ? "strong" : "muted"}`}>
              {text.length.toLocaleString()} / {MAX.toLocaleString()}
            </span>
          </div>
        </div>
        {examples.data?.length > 0 && (
          <div className="stack" style={{ gap: 6 }}>
            <span className="tiny muted">Or try an example:</span>
            <div className="row wrap fc-examples">
              {examples.data.map((ex) => (
                <button key={ex.id} type="button" className="btn sm" onClick={() => { setText(ex.text); setResult(null); }}>
                  {ex.claim}
                </button>
              ))}
            </div>
          </div>
        )}
        {examples.error && <span className="tiny muted">Examples are unavailable right now.</span>}
        {error && <div className="error-box small" role="alert">{error}</div>}
        <div className="row wrap">
          <button className="btn primary" type="submit" disabled={busy || !text.trim()}>
            {busy ? "Checking sources..." : "Check this text"}
          </button>
          {text && !busy && (
            <button type="button" className="btn ghost" onClick={() => { setText(""); setResult(null); setError(null); }}>
              Clear
            </button>
          )}
        </div>
      </form>

      {busy && <div className="card" aria-busy="true" style={{ marginTop: 16 }}><div className="skeleton" /></div>}

      {!busy && !result && (
        <div className="card empty small" style={{ marginTop: 16 }}>
          Results appear here. Every verdict links to its sources, and when there's no good evidence, Bioverse says so.
        </div>
      )}

      {!busy && result && (
        <div ref={resultRef} tabIndex={-1} className="stack fc-results" aria-live="polite">
          {result.safety && <SafetyBlock safety={result.safety} />}
          {result.status === "needs_text" && (
            <div className="card stack">
              <div className="card-title">Paste the words instead of the link</div>
              <p className="small">{result.message}</p>
            </div>
          )}
          {result.status === "no_claims" && <div className="card empty small">{result.message}</div>}
          {result.url_notice && <div className="banner info">{result.url_notice}</div>}
          {result.status === "checked" && (
            <>
              <div className="row wrap fc-summary" aria-label="Summary">
                <span className="small strong">
                  {result.claims.length} {result.claims.length === 1 ? "claim" : "claims"} checked
                </span>
                {Object.entries(counts).map(([v, n]) => (
                  <span key={v} className={`chip ${VERDICT_CLASS[v]}`}>{n} · {result.verdict_labels[v]}</span>
                ))}
                <span className="chip"><Book size={12} /> {result.mode === "ai" ? "AI with library sources" : "Library rules, no AI"}</span>
              </div>
              {result.claims.map((c) => <ClaimCard key={c.n} claim={c} />)}
              {result.share && <ShareCard share={result.share} disclaimer={result.disclaimer} />}
            </>
          )}
          <p className="tiny muted">{result.disclaimer}</p>
        </div>
      )}
    </main>
  );
}
