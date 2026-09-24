import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, getUserId } from "../../api.js";
import { useApi } from "../../hooks.js";
import { PatientPage } from "../../layouts.jsx";
import { fmtDate, fmtDateTime } from "../../format.js";
import { Chevron, Lock, Shield, Warning } from "../../icons.jsx";

// Fetch a file endpoint with the demo identity header and hand it to the browser as a download.
async function download(path, fallbackName) {
  const res = await fetch(`/api${path}`, { headers: { "X-Bioverse-User": getUserId() || "" } });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const blob = await res.blob();
  const match = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "");
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = match ? match[1] : fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Choice({ choice, onChange, busy }) {
  const id = `consent-${choice.scope}`;
  return (
    <article className="card stack pv-choice">
      <div className="pv-switch-row">
        <label htmlFor={id} className="pv-switch-label">
          <span className="card-title">{choice.title}</span>
          <span className={`chip ${choice.granted ? "ok" : ""}`}>{choice.granted ? "On" : "Off"}</span>
        </label>
        <input
          id={id}
          type="checkbox"
          role="switch"
          className="pv-switch"
          checked={choice.granted}
          disabled={busy}
          aria-describedby={`${id}-now`}
          onChange={(e) => onChange(choice.scope, e.target.checked)}
        />
      </div>
      <p id={`${id}-now`} className="small">{choice.explanation}</p>
      <p className="tiny muted row" style={{ gap: 6, alignItems: "flex-start" }}>
        <Shield size={14} /> <span>{choice.always}</span>
      </p>
      {!choice.is_default && choice.updated_at && (
        <p className="tiny muted">Changed {fmtDate(choice.updated_at)}</p>
      )}
    </article>
  );
}

function AccessLog() {
  const [includeMine, setIncludeMine] = useState(false);
  const [items, setItems] = useState([]);
  const [next, setNext] = useState(null);
  const [state, setState] = useState({ loading: true, error: null });

  const load = useCallback(async (before, mine, append) => {
    setState({ loading: true, error: null });
    try {
      const qs = new URLSearchParams({ include_mine: String(mine), limit: "25" });
      if (before) qs.set("before_id", before);
      const page = await api(`/privacy/access-log?${qs}`);
      setItems((prev) => (append ? [...prev, ...page.items] : page.items));
      setNext(page.next_before_id);
      setState({ loading: false, error: null });
    } catch (e) {
      setState({ loading: false, error: e });
    }
  }, []);

  useEffect(() => {
    load(null, includeMine, false);
  }, [includeMine, load]);

  return (
    <section className="stack" aria-labelledby="access-title">
      <div className="row between wrap">
        <h2 id="access-title" className="pv-h2">Who has opened my record</h2>
      </div>
      <div className="toggle-row">
        <input id="include-mine" type="checkbox" checked={includeMine} onChange={(e) => setIncludeMine(e.target.checked)} />
        <label htmlFor="include-mine">Include things I did myself</label>
      </div>
      <div className="card">
        {state.error && <div className="error-box">{state.error.message}</div>}
        {!state.error && items.length === 0 && !state.loading && (
          <div className="empty">
            {includeMine ? "Nothing has been recorded about your record yet." : "Nobody else has opened your record yet."}
          </div>
        )}
        {items.length === 0 && state.loading && <div className="skeleton" />}
        <ul className="list pv-log">
          {items.map((i) => (
            <li key={i.id} className="pv-log-item">
              <div className="stack" style={{ gap: 2, minWidth: 0 }}>
                <span className="strong">
                  {i.who}
                  <span className="muted small"> · {i.role}</span>
                </span>
                <span className="small">{i.what}{i.via ? ` (using ${i.via})` : ""}</span>
                {i.emergency_access && (
                  <span className="chip warn" style={{ alignSelf: "flex-start" }}>
                    <Warning size={12} /> Emergency access{i.reason ? `: ${i.reason}` : ""}
                  </span>
                )}
              </div>
              <time className="tiny muted pv-when" dateTime={i.at}>{fmtDateTime(i.at)}</time>
            </li>
          ))}
        </ul>
        {next && (
          <button className="btn block" style={{ marginTop: 12 }} disabled={state.loading}
                  onClick={() => load(next, includeMine, true)}>
            {state.loading ? "Loading…" : "Show older"}
          </button>
        )}
      </div>
    </section>
  );
}

export default function PrivacyCenter() {
  const consents = useApi("/privacy/consents");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    if (consents.data) setData(consents.data);
  }, [consents.data]);

  async function change(scope, granted) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await api(`/privacy/consents/${scope}`, { method: "PUT", body: { granted } });
      setData(next);
      const choice = next.choices.find((c) => c.scope === scope);
      setNotice(`Saved. ${choice.title}: ${granted ? "on" : "off"}.`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function exportReport() {
    setDownloading(true);
    setError(null);
    try {
      await download("/privacy/export", "bioverse-privacy.json");
    } catch (e) {
      setError(e.message);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <PatientPage>
      <div className="page-head">
        <div>
          <div className="eyebrow">Account</div>
          <h1 className="page-title">Your privacy</h1>
          <div className="page-sub">What you've agreed to, and who has looked at your record.</div>
        </div>
      </div>

      <div className="stack" style={{ gap: 28 }}>
        <section className="stack" aria-labelledby="choices-title">
          <h2 id="choices-title" className="pv-h2">Your choices</h2>
          {consents.error && <div className="error-box">{consents.error.message}</div>}
          {!data && !consents.error && <div className="card"><div className="skeleton" /></div>}
          <div aria-live="polite">
            {notice && <div className="banner ok">{notice}</div>}
            {error && <div className="error-box">{error}</div>}
          </div>
          {data && data.ai_allowed === false && (
            <div className="banner info">
              AI is off for you. Bioverse is using fixed rules only: warning-sign checks and routing still work.
            </div>
          )}
          {data?.choices.map((c) => <Choice key={c.scope} choice={c} onChange={change} busy={busy} />)}
        </section>

        {data && (
          <section className="stack" aria-labelledby="helpers-title">
            <h2 id="helpers-title" className="pv-h2">People who can help with your care</h2>
            <div className="card stack">
              {data.caregivers.length === 0 && (
                <p className="small muted">You haven't given anyone access to your record.</p>
              )}
              {data.caregivers.length > 0 && (
                <ul className="list">
                  {data.caregivers.map((c) => (
                    <li key={c.grantee} className="pv-log-item">
                      <div className="stack" style={{ gap: 2 }}>
                        <span className="strong">{c.name}</span>
                        <span className="small muted">
                          {c.granted ? "Can help" : "No access"}
                          {c.permissions.length ? ` · ${c.permissions.join(", ").replaceAll("_", " ")}` : ""}
                          {c.expires_at ? ` · until ${fmtDate(c.expires_at)}` : ""}
                        </span>
                      </div>
                      <span className={`chip ${c.granted ? "ok" : ""}`}>{c.granted ? "Active" : c.status}</span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="tiny muted row" style={{ gap: 6 }}><Lock size={12} /> Managed in Family and caregivers.</p>
              <Link to="/family" className="btn" style={{ alignSelf: "flex-start" }}>
                Family and caregivers <Chevron size={16} />
              </Link>
            </div>
          </section>
        )}

        <AccessLog />

        <section className="stack" aria-labelledby="download-title">
          <h2 id="download-title" className="pv-h2">Download your privacy report</h2>
          <div className="card stack">
            <p className="small">
              A file with your choices above and the full list of every time your record was opened or changed,
              including by you. Your health record itself is exported from Records.
            </p>
            <button className="btn primary" style={{ alignSelf: "flex-start" }} onClick={exportReport} disabled={downloading}>
              {downloading ? "Preparing…" : "Download privacy report (JSON)"}
            </button>
          </div>
        </section>
      </div>
    </PatientPage>
  );
}
