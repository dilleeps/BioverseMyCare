import { useState } from "react";
import { api } from "../../api.js";
import { Book } from "../../icons.jsx";

const QUALITY = { high: "High quality", moderate: "Moderate quality", low: "Low quality" };

export default function EvidenceSearch() {
  const [q, setQ] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function search(e) {
    e.preventDefault();
    if (q.trim().length < 3) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api(`/learning/evidence?q=${encodeURIComponent(q.trim())}`));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page ln-page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Learning</div>
          <h1 className="page-title">Evidence library</h1>
          <p className="page-sub">The same curated guidelines, reviews and drug labels clinicians use. Retrieved as written, no AI.</p>
        </div>
      </div>
      <form className="card stack" onSubmit={search} role="search">
        <label htmlFor="ln-q" className="small strong">Search</label>
        <div className="row wrap ln-search">
          <input id="ln-q" value={q} maxLength={300} onChange={(e) => setQ(e.target.value)}
                 placeholder="For example: prediabetes lifestyle, statin monitoring, amlodipine edema" />
          <button className="btn primary" type="submit" disabled={busy || q.trim().length < 3}>{busy ? "Searching..." : "Search"}</button>
        </div>
        {error && <div className="error-box small" role="alert">{error}</div>}
      </form>
      {!result && !busy && <div className="card empty small" style={{ marginTop: 12 }}>Search by condition, drug or test.</div>}
      {busy && <div className="card" style={{ marginTop: 12 }}><div className="skeleton" /></div>}
      {result && !busy && (
        <div className="stack" style={{ marginTop: 12 }} aria-live="polite">
          {result.results.length === 0 && <div className="card empty small"><Book size={15} /> {result.message}</div>}
          {result.results.map((r) => (
            <article key={r.item_id} className="card stack ln-ev">
              <a href={r.url} target="_blank" rel="noopener noreferrer" className="strong ln-ev-title">
                {r.title}<span className="sr-only"> (opens in a new tab)</span>
              </a>
              <span className="tiny muted">{r.publisher} · {r.year}</span>
              <div className="row wrap" style={{ gap: 6 }}>
                <span className="chip">{r.type_label}</span>
                <span className={`chip ${r.quality === "high" ? "ok" : ""}`}>{QUALITY[r.quality] || r.quality}</span>
                {r.quality_note && <span className="tiny muted">{r.quality_note}</span>}
              </div>
              <p className="small ln-snippet">{r.snippet}</p>
            </article>
          ))}
        </div>
      )}
    </main>
  );
}
