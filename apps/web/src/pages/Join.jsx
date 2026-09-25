import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api.js";
import { Logo, Shield } from "../icons.jsx";
import EmailCode from "../modules/invites/EmailCode.jsx";
import { MARKS, BUTTON_LABEL } from "./SignIn.jsx";
import "../modules/invites/invites.css";

const CLOSED = {
  expired: ["This invite has expired", "Ask your clinic to send you a new one."],
  revoked: ["This invite was withdrawn", "Ask your clinic if you still need access."],
  accepted: ["This invite has already been used", "If that was you, sign in with the same account."],
  locked: ["This invite is locked", "The date of birth didn't match too many times. Ask your clinic to send a new invite."],
};

function Steps({ step }) {
  return (
    <ol className="join-steps" aria-label="Steps">
      <li className={step >= 1 ? "on" : ""} aria-current={step === 1 ? "step" : undefined}><span className="dot">1</span>Confirm it's you</li>
      <li className="bar" aria-hidden="true" />
      <li className={step >= 2 ? "on" : ""} aria-current={step === 2 ? "step" : undefined}><span className="dot">2</span>Choose how to sign in</li>
    </ol>
  );
}

function ConfirmIdentity({ token, info, onDone }) {
  const [dob, setDob] = useState("");
  const [terms, setTerms] = useState(false);
  const [state, setState] = useState({ busy: false, error: null, locked: false });

  async function submit(e) {
    e.preventDefault();
    setState({ busy: true, error: null, locked: false });
    try {
      await api(`/join/${token}/confirm`, { method: "POST", body: { birth_date: dob, accept_terms: terms } });
      onDone();
    } catch (err) {
      const left = err.detail?.attempts_left;
      setState({
        busy: false, locked: err.status === 423,
        error: left != null ? `${err.message} ${left} ${left === 1 ? "try" : "tries"} left.` : err.message,
      });
    }
  }

  if (state.locked) {
    return <div className="error-box" role="alert">{CLOSED.locked[1]}</div>;
  }
  return (
    <form className="stack" onSubmit={submit}>
      <label className="inv-field">
        <span>Your date of birth</span>
        <input type="date" required value={dob} max={new Date().toISOString().slice(0, 10)}
               onChange={(e) => setDob(e.target.value)} autoComplete="bday" />
        <span className="inv-hint">We check it against what {info.clinic} has on file.</span>
      </label>
      <label className="join-check">
        <input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} required />
        <span>
          I agree to the terms of use and privacy notice, and I'm happy for {info.clinic} to share my care
          information with me through Bioverse One.
        </span>
      </label>
      {state.error && <div className="error-box" role="alert">{state.error}</div>}
      <button className="btn primary block" disabled={state.busy || !dob || !terms}>
        {state.busy ? "Checking…" : "Continue"}
      </button>
    </form>
  );
}

function ChooseSignIn({ token, info }) {
  const providers = [...(info.sign_in?.providers || [])].sort((a, b) => (a.key === "google" ? -1 : b.key === "google" ? 1 : 0));
  const email = info.sign_in?.email;
  return (
    <div className="stack">
      <p className="small muted">
        You can use any account you like; it doesn't have to be {info.email_hint}. Finish within 30 minutes.
      </p>
      {providers.map((p) => (
        <a key={p.key} className="btn block signin-btn"
           href={`/api/auth/login/${p.key}?invite=${encodeURIComponent(token)}&next=${encodeURIComponent("/")}`}>
          {MARKS[p.key]} {(BUTTON_LABEL[p.key] || `Sign in with ${p.label}`).replace("Sign in", "Continue")}
        </a>
      ))}
      {providers.length > 0 && email && <div className="join-or">or</div>}
      {email && <EmailCode invite={token} next="/" />}
      {!email && providers.length === 0 && (
        <div className="error-box">Sign-in isn't set up here yet. Please contact {info.clinic}.</div>
      )}
    </div>
  );
}

export default function Join() {
  const { token } = useParams();
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);

  async function load() {
    try {
      setInfo(await api(`/join/${token}`));
    } catch (e) {
      setError(e);
    }
  }
  useEffect(() => { load(); }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  const closed = info && CLOSED[info.status];
  const step = info?.dob_confirmed ? 2 : 1;

  return (
    <main className="signin">
      <section className="signin-card join-card" aria-labelledby="join-h">
        <div className="signin-brand">
          <span className="brand-mark"><Logo size={18} /></span>
          <span>{info?.clinic || "Bioverse One"}</span>
        </div>
        {!info && !error && <div className="skeleton" />}
        {error && (
          <>
            <h1 id="join-h" className="signin-title">Invite not found</h1>
            <div className="error-box" role="alert">{error.message}</div>
          </>
        )}
        {closed && (
          <>
            <h1 id="join-h" className="signin-title">{closed[0]}</h1>
            <p className="muted">{closed[1]}</p>
            <Link className="btn block" to="/signin">Go to sign in</Link>
          </>
        )}
        {info?.status === "pending" && (
          <>
            <h1 id="join-h" className="signin-title">Welcome, {info.first_name}</h1>
            <p className="muted">
              <strong className="strong" style={{ color: "var(--ink)" }}>{info.invited_by}</strong> invited you to
              {" "}{info.clinic} on Bioverse One: your results, care plan and messages in one place.
            </p>
            {info.message && <blockquote className="join-note">{info.message}</blockquote>}
            <Steps step={step} />
            {step === 1
              ? <ConfirmIdentity token={token} info={info} onDone={load} />
              : <ChooseSignIn token={token} info={info} />}
          </>
        )}
        <p className="tiny muted row" style={{ gap: 6 }}>
          <Shield size={13} /> Only you should use this link. Nothing clinical is shown until you've signed in.
        </p>
      </section>
    </main>
  );
}
