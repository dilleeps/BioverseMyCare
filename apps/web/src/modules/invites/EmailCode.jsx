import { useEffect, useState } from "react";
import { api } from "../../api.js";
import "./invites.css";

// Demo deployments have no mail server: the API keeps a copy of what it would have sent.
function DevOutbox({ email, onUse }) {
  const [code, setCode] = useState(null);
  useEffect(() => {
    let live = true;
    api(`/auth/dev-outbox?email=${encodeURIComponent(email)}`)
      .then((r) => {
        const m = (r.messages || [])[0];
        const found = m && /\b(\d{6})\b/.exec(m.subject);
        if (live) setCode(found ? found[1] : "");
      })
      .catch(() => live && setCode(""));
    return () => { live = false; };
  }, [email]);
  if (code === null) return null;
  return (
    <div className="dev-outbox" role="note">
      Demo outbox:{" "}
      {code ? (
        <>code <strong>{code}</strong> <button type="button" className="btn sm ghost" onClick={() => onUse(code)}>Use it</button></>
      ) : (
        "nothing was sent to this address (only patients and invited people get codes)."
      )}
    </div>
  );
}

// "Email me a code": ask for an address, then the 6-digit code. On success the API sets the session cookie
// and the page reloads into the app. `started` skips the first step (self-registration already sent a code).
export default function EmailCode({ invite, next = "/", started = null, initialEmail = "" }) {
  const [email, setEmail] = useState(initialEmail);
  const [sent, setSent] = useState(started);
  const [code, setCode] = useState("");
  const [state, setState] = useState({ busy: false, error: null });

  async function send(e) {
    e?.preventDefault();
    setState({ busy: true, error: null });
    try {
      const r = await api("/auth/email/start", { method: "POST", body: { email, invite: invite || null } });
      setSent({ ...r, at: Date.now() });
      setCode("");
      setState({ busy: false, error: null });
    } catch (err) {
      setState({ busy: false, error: err.message });
    }
  }

  async function check(e) {
    e.preventDefault();
    setState({ busy: true, error: null });
    try {
      const r = await api("/auth/email/verify", { method: "POST", body: { email, code, invite: invite || null, next } });
      window.location.assign(r.next || "/");
    } catch (err) {
      setState({ busy: false, error: err.message });
    }
  }

  if (!sent) {
    return (
      <form className="stack" style={{ gap: 10 }} onSubmit={send}>
        <label className="inv-field">
          <span>Email address</span>
          <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)}
                 placeholder="you@example.com" />
        </label>
        {state.error && <div className="error-box" role="alert">{state.error}</div>}
        <button className="btn block signin-btn" disabled={state.busy || !email}>
          <MailIcon /> {state.busy ? "Sending…" : "Email me a code"}
        </button>
      </form>
    );
  }

  return (
    <form className="stack" style={{ gap: 10 }} onSubmit={check}>
      <p className="small" role="status">
        {sent.message || "We've emailed you a code."} It expires in {sent.expires_in_minutes || 10} minutes.
      </p>
      {sent.dev_outbox && <DevOutbox key={sent.at || email} email={email} onUse={setCode} />}
      <label className="inv-field">
        <span>6-digit code sent to {email}</span>
        <input className="code-input" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]*" maxLength={7}
               required value={code} onChange={(e) => setCode(e.target.value.replace(/[^0-9]/g, ""))} autoFocus />
      </label>
      {state.error && <div className="error-box" role="alert">{state.error}</div>}
      <button className="btn primary block" disabled={state.busy || code.length !== 6}>
        {state.busy ? "Checking…" : "Sign in"}
      </button>
      <div className="row between small">
        <button type="button" className="btn sm ghost" onClick={() => { setSent(null); setState({ busy: false, error: null }); }}>
          Use a different email
        </button>
        <button type="button" className="btn sm ghost" disabled={state.busy} onClick={() => send()}>Send a new code</button>
      </div>
    </form>
  );
}

export function MailIcon({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="5" width="18" height="14" rx="2.5" /><path d="m4 7 8 6 8-6" />
    </svg>
  );
}
