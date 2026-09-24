import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PatientPage } from "../../layouts.jsx";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { fmtDate } from "../../format.js";
import { Chevron, Lock, Shield } from "../../icons.jsx";
import { CriteriaList, DECIDES, INTEREST_LABELS, MatchChip, STUDY_STATUS } from "./shared.jsx";

function ConsentCard({ consent, onChange }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  // Shown immediately; the server's answer replaces it.
  const [checked, setChecked] = useState(consent.granted);
  useEffect(() => setChecked(consent.granted), [consent.granted]);

  async function toggle(e) {
    const granted = e.target.checked;
    setChecked(granted);
    setBusy(true);
    setError(null);
    try {
      await api("/research/consent", { method: "PUT", body: { granted } });
      await onChange();
    } catch (err) {
      setChecked(!granted);
      setError(`Couldn't save your choice. ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card stack" aria-labelledby="consent-title">
      <h2 id="consent-title" className="card-title row" style={{ gap: 8 }}><Shield size={18} /> Research matching</h2>
      <div className="toggle-row">
        <input id="rs-consent" type="checkbox" checked={checked} disabled={busy} onChange={toggle}
               aria-describedby="rs-consent-what" />
        <label htmlFor="rs-consent">Let Bioverse match me to research studies</label>
      </div>
      <ul id="rs-consent-what" className="rs-points small">
        <li>Bioverse compares your health record with what each study is looking for. A computer rule does this, not a person.</li>
        <li>Your care team can see your matches only while this is on.</li>
        <li>A study team contacts you only about studies you say you're interested in.</li>
        <li>You can turn this off at any time. Turning it off stops all study contact.</li>
      </ul>
      {consent.updated_at && (
        <p className="tiny muted">
          {consent.granted ? "Turned on" : "Turned off"} {fmtDate(consent.updated_at)}.
        </p>
      )}
      {error && <div className="error-box small" role="alert">{error}</div>}
    </section>
  );
}

function Matches({ matches }) {
  if (matches.length === 0) {
    return <div className="card empty small">No recruiting studies match your record right now. We'll check again as your record changes.</div>;
  }
  return matches.map((m) => (
    <article key={m.study.id} className="card stack" aria-labelledby={`m-${m.study.id}`}>
      <div className="row between wrap" style={{ alignItems: "flex-start" }}>
        <h3 id={`m-${m.study.id}`} className="strong rs-study-title">{m.study.title}</h3>
        <MatchChip status={m.status} label={m.status_label} />
      </div>
      <p className="small muted">{m.study.summary}</p>
      <details className="rs-details">
        <summary className="small strong">Why this may fit you</summary>
        <CriteriaList criteria={m.criteria} />
        {m.status === "possibly_eligible" && (
          <p className="tiny muted">Some details aren't in your record. The study team would check them with you.</p>
        )}
        <p className="tiny muted">{DECIDES}</p>
      </details>
      <div><Link className="btn sm" to={`/research/studies/${m.study.id}`}>View study <Chevron size={14} /></Link></div>
    </article>
  ));
}

function Interests({ interests, onChange }) {
  const [error, setError] = useState(null);
  async function withdraw(id) {
    setError(null);
    try {
      await api(`/research/interests/${id}/withdraw`, { method: "POST" });
      await onChange();
    } catch (err) {
      setError(err.message);
    }
  }
  if (interests.length === 0) return null;
  return (
    <section className="stack" aria-labelledby="interest-title">
      <h2 id="interest-title" className="eyebrow">Studies you asked about</h2>
      {error && <div className="error-box small" role="alert">{error}</div>}
      <div className="card list">
        {interests.map((i) => (
          <div key={i.id} className="row between wrap rs-interest">
            <div className="stack" style={{ gap: 2 }}>
              <Link to={`/research/studies/${i.study_id}`} className="strong small">{i.short_title}</Link>
              <span className="tiny muted">
                {INTEREST_LABELS[i.status]}{!i.contact_permitted && i.status !== "withdrawn" ? " · contact paused" : ""}
              </span>
            </div>
            {i.status !== "withdrawn" && (
              <button className="btn sm" onClick={() => withdraw(i.id)}>Withdraw</button>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

export default function ResearchHub() {
  const me = useApi("/research/me");
  const studies = useApi("/research/studies");

  const reload = async () => {
    await me.reload();
  };

  return (
    <PatientPage>
      <div className="stack" style={{ marginBottom: 16 }}>
        <h1 className="page-title">Research studies</h1>
        <p className="page-sub">Studies test new ways to prevent or treat illness. Taking part is always your choice.</p>
      </div>

      {me.error && <div className="error-box">{me.error.message}</div>}
      {me.loading && !me.data && <div className="card"><div className="skeleton" /></div>}
      {me.data && (
        <div className="stack">
          <ConsentCard consent={me.data.consent} onChange={reload} />

          <section className="stack" aria-labelledby="matches-title">
            <h2 id="matches-title" className="eyebrow">Studies that may fit you</h2>
            {me.data.matches ? (
              <Matches matches={me.data.matches} />
            ) : (
              <div className="banner info"><Lock size={15} /> Turn on research matching to see studies that fit your record. You can still browse every study below.</div>
            )}
          </section>

          <Interests interests={me.data.interests} onChange={reload} />
        </div>
      )}

      <section className="stack" style={{ marginTop: 24 }} aria-labelledby="all-title">
        <h2 id="all-title" className="eyebrow">All studies</h2>
        {studies.error && <div className="error-box">{studies.error.message}</div>}
        {studies.loading && !studies.data && <div className="card"><div className="skeleton" /></div>}
        {studies.data?.length === 0 && <div className="card empty small">No studies listed yet.</div>}
        {studies.data?.length > 0 && (
          <div className="card list">
            {studies.data.map((s) => (
              <Link key={s.id} to={`/research/studies/${s.id}`} className="rs-row">
                <span className="stack" style={{ gap: 2, flexGrow: 1 }}>
                  <span className="strong small">{s.title}</span>
                  <span className="tiny muted">{s.conditions.join(", ")} · {s.phase}</span>
                </span>
                <span className={`chip ${s.status === "recruiting" ? "ok" : ""}`}>{STUDY_STATUS[s.status]}</span>
                <Chevron size={16} />
              </Link>
            ))}
          </div>
        )}
      </section>
    </PatientPage>
  );
}
