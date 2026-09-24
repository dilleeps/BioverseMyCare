import { Link } from "react-router-dom";
import { useApi } from "../../hooks.js";
import { Chevron } from "../../icons.jsx";
import { Disclosure, initialsOf } from "./shared.jsx";

export default function Directory() {
  const { data, error, loading, reload } = useApi("/specialists");

  return (
    <main className="page sp-page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Learn</div>
          <h1 className="page-title">Specialist AI assistants</h1>
          <p className="page-sub">
            Ask general health questions. Each assistant answers only from its specialist's approved guidance and
            published evidence, with sources. It can't advise on your own situation.
          </p>
        </div>
      </div>

      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {error && (
        <div className="error-box row between wrap">
          <span>Couldn't load the assistants. {error.message}</span>
          <button className="btn sm" onClick={reload}>Try again</button>
        </div>
      )}
      {data?.length === 0 && (
        <div className="card empty">No specialist assistants are available right now. Please check back later.</div>
      )}
      {data?.length > 0 && (
        <div className="sp-grid">
          {data.map((a) => (
            <article key={a.id} className="card stack sp-card" aria-labelledby={`sp-${a.id}`}>
              <div className="row" style={{ alignItems: "flex-start" }}>
                <span className="avatar sp-avatar" aria-hidden="true">{initialsOf(a.display_name)}</span>
                <div className="stack" style={{ gap: 2, minWidth: 0 }}>
                  <h2 id={`sp-${a.id}`} className="card-title">{a.display_name}</h2>
                  <span className="small muted">{a.specialty} · AI assistant</span>
                </div>
              </div>
              {a.headline && <p className="small">{a.headline}</p>}
              <div>
                <div className="eyebrow" style={{ marginBottom: 6 }}>Answers questions about</div>
                <div className="row wrap" style={{ gap: 6 }}>
                  {a.topics.map((t) => <span key={t} className="chip">{t}</span>)}
                </div>
              </div>
              <Disclosure text={a.disclosure} />
              <div style={{ marginTop: "auto" }}>
                <Link className="btn primary block" to={`/specialists/${a.id}`}>
                  Ask a general question <Chevron size={16} />
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}
      <p className="tiny muted" style={{ marginTop: 16 }}>
        For advice about you, <Link to="/care/find">book a visit</Link>. In an emergency, call 911.
      </p>
    </main>
  );
}
