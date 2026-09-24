import { Link, useNavigate } from "react-router-dom";
import { Chevron } from "../../icons.jsx";
import MicButton from "./MicButton.jsx";
import { search } from "./fuzzy.js";
import { Search } from "./icons.jsx";
import "./frontdoor.css";

// Search every screen the role can open, by typing or speaking. Enter opens the top hit.
export default function HubSearch({ items, query, onQuery }) {
  const navigate = useNavigate();
  const q = query.trim();
  const hits = q ? search(q, items) : [];

  return (
    <div className="hub-search" role="search">
      <form
        className="hub-search-box"
        onSubmit={(e) => {
          e.preventDefault();
          if (hits[0]) navigate(hits[0].to);
        }}
      >
        <Search size={20} />
        <label htmlFor="hub-search-input" className="sr-only">Search Bioverse One</label>
        <input
          id="hub-search-input"
          type="search"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder="Search, or say what you're looking for"
          autoComplete="off"
          aria-controls="hub-search-results"
          aria-describedby="hub-search-hint"
        />
        <MicButton value="" onChange={onQuery} label="Search by voice" />
      </form>
      <p id="hub-search-hint" className="sr-only">Press Enter to open the first result.</p>
      {q && (
        <div id="hub-search-results" className="stack" aria-live="polite" style={{ marginTop: 12 }}>
          <div className="small muted">
            {hits.length ? `${hits.length} match${hits.length === 1 ? "" : "es"}. Press Enter to open the first.` : `Nothing matches "${q}".`}
          </div>
          {hits.length > 0 && (
            <div className="hub-grid">
              {hits.map((n, i) => (
                <Link key={n.to} to={n.to} className={`hub-card${i === 0 ? " hub-top-hit" : ""}`}>
                  <span style={{ flexGrow: 1, minWidth: 0 }}>
                    <span className="strong" style={{ display: "block" }}>{n.label}</span>
                    {n.description && <span className="small muted">{n.description}</span>}
                  </span>
                  <Chevron size={18} />
                </Link>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
