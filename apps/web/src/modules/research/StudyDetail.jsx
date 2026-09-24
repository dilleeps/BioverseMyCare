import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { PatientPage, WorkspaceLayout } from "../../layouts.jsx";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { useSession } from "../../session.jsx";
import { Back, Lock, Phone, Pin, Sparkle } from "../../icons.jsx";
import { CriteriaList, DECIDES, INTEREST_LABELS, MatchChip, STUDY_STATUS } from "./shared.jsx";

function Explanation({ studyId }) {
  const [state, setState] = useState({ data: null, busy: false, error: null });
  async function load() {
    setState({ data: null, busy: true, error: null });
    try {
      setState({ data: await api(`/research/studies/${studyId}/explanation`), busy: false, error: null });
    } catch (err) {
      setState({ data: null, busy: false, error: err.message });
    }
  }
  if (state.data) {
    const ai = state.data.produced_by.endsWith("/claude");
    return (
      <div className="rs-explain stack" style={{ gap: 6 }} aria-live="polite">
        <p className="small">{state.data.text}</p>
        <span className="tiny muted">
          {ai ? "Rewritten in plainer words by Bioverse AI from the study's own summary. Not medical advice."
              : "This is the study's own summary."}
        </span>
      </div>
    );
  }
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div>
        <button className="btn sm" onClick={load} disabled={state.busy}>
          <Sparkle size={14} /> {state.busy ? "Explaining..." : "Explain in plainer words"}
        </button>
      </div>
      {state.error && <div className="error-box small" role="alert">{state.error}</div>}
    </div>
  );
}

function PatientActions({ data, reload }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const { study, consent, interest, match } = data;
  const active = interest && interest.status !== "withdrawn" && interest.contact_permitted;

  async function act(path) {
    setBusy(true);
    setError(null);
    try {
      await api(path, { method: "POST" });
      await reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card stack" aria-labelledby="fit-title">
      <div className="row between wrap">
        <h2 id="fit-title" className="card-title">Could this study fit you?</h2>
        {match && <MatchChip status={match.status} label={match.status_label} />}
      </div>
      {!consent.granted && (
        <div className="banner info"><Lock size={15} /> Research matching is off, so Bioverse hasn't compared this study with your record.</div>
      )}
      {match && <CriteriaList criteria={match.criteria} />}
      {match && <p className="tiny muted">{DECIDES}</p>}
      {match?.status === "possibly_eligible" && (
        <p className="tiny muted">Some details aren't in your record. The study team would check them with you.</p>
      )}
      {interest && (
        <p className="small">
          <span className="strong">Your status: </span>{INTEREST_LABELS[interest.status]}
          {!interest.contact_permitted && interest.status !== "withdrawn" ? " · contact paused" : ""}
        </p>
      )}
      {error && <div className="error-box small" role="alert">{error}</div>}
      {study.status !== "recruiting" ? (
        <p className="small muted">This study is not recruiting.</p>
      ) : !consent.granted ? (
        <div className="stack" style={{ gap: 6 }}>
          <p className="small">To tell the study team you're interested, first turn on research matching.</p>
          <div><Link className="btn primary" to="/research">Go to research matching</Link></div>
        </div>
      ) : (
        <div className="row wrap">
          {!active && !["enrolled", "not_eligible"].includes(interest?.status) && (
            <button className="btn primary" disabled={busy} onClick={() => act(`/research/studies/${study.id}/interest`)}>
              I'm interested
            </button>
          )}
          {interest && interest.status !== "withdrawn" && (
            <button className="btn" disabled={busy} onClick={() => act(`/research/interests/${interest.id}/withdraw`)}>
              Withdraw
            </button>
          )}
        </div>
      )}
      {consent.granted && study.status === "recruiting" && !active && (
        <p className="tiny muted">Saying you're interested lets the study team contact you. It doesn't sign you up. You can withdraw at any time.</p>
      )}
    </section>
  );
}

function StudyBody({ data, reload, isPatient }) {
  const s = data.study;
  return (
    <div className="stack">
      <div className="stack" style={{ gap: 6 }}>
        <div className="row wrap" style={{ gap: 6 }}>
          {s.is_demo && <span className="chip warn">Fictional demo study</span>}
          <span className={`chip ${s.status === "recruiting" ? "ok" : ""}`}>{STUDY_STATUS[s.status]}</span>
          <span className="chip">{s.phase}</span>
        </div>
        <h1 className="page-title">{s.title}</h1>
        <p className="page-sub">{s.sponsor}</p>
      </div>

      <section className="card stack" aria-labelledby="about-title">
        <h2 id="about-title" className="card-title">About this study</h2>
        <p className="small">{s.summary}</p>
        {s.what_happens && <p className="small"><span className="strong">What happens: </span>{s.what_happens}</p>}
        <Explanation studyId={s.id} />
      </section>

      {isPatient && <PatientActions data={data} reload={reload} />}

      <section className="card stack" aria-labelledby="who-title">
        <h2 id="who-title" className="card-title">Who can take part</h2>
        <ul className="rs-points small">{s.who_can_join.map((w) => <li key={w}>{w}</li>)}</ul>
        {s.who_cannot_join.length > 0 && (
          <>
            <h3 className="small strong">Who can't take part</h3>
            <ul className="rs-points small">{s.who_cannot_join.map((w) => <li key={w}>{w}</li>)}</ul>
          </>
        )}
      </section>

      <section className="card stack" aria-labelledby="where-title">
        <h2 id="where-title" className="card-title">Where and who to contact</h2>
        {s.sites.map((site) => (
          <p key={site.name} className="small row" style={{ gap: 6 }}>
            <Pin size={14} /> {site.name}, {site.city}{site.distance_km ? ` · ${site.distance_km} km` : ""}
          </p>
        ))}
        {s.contact?.name && (
          <p className="small row wrap" style={{ gap: 6 }}>
            <Phone size={14} /> {s.contact.name} · {s.contact.phone} · {s.contact.email}
          </p>
        )}
      </section>
    </div>
  );
}

export default function StudyDetail() {
  const { studyId } = useParams();
  const { me } = useSession();
  const { data, error, loading, reload } = useApi(`/research/studies/${studyId}`);
  const isPatient = me?.role === "patient";
  const back = isPatient ? "/research" : "/clinician/research";

  const content = (
    <>
      <Link to={back} className="btn ghost sm" style={{ marginBottom: 8, paddingLeft: 0 }}>
        <Back size={16} /> {isPatient ? "Research studies" : "Research pipeline"}
      </Link>
      {error && <div className="error-box">{error.status === 404 ? "This study doesn't exist." : error.message}</div>}
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {data && <StudyBody data={data} reload={reload} isPatient={isPatient} />}
    </>
  );
  return isPatient ? <PatientPage>{content}</PatientPage> : <WorkspaceLayout>{content}</WorkspaceLayout>;
}
