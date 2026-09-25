import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { Logo, Shield } from "../icons.jsx";
import EmailCode from "../modules/invites/EmailCode.jsx";
import "../modules/invites/invites.css";

// Open self-registration. The API answers 404 unless BIOVERSE_SELF_REGISTRATION=on.
export default function Register() {
  const [open, setOpen] = useState(null);
  const [f, setF] = useState({ name: "", birth_date: "", email: "", terms: false });
  const [sent, setSent] = useState(null);
  const [state, setState] = useState({ busy: false, error: null });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  useEffect(() => {
    api("/auth/register").then(() => setOpen(true)).catch(() => setOpen(false));
  }, []);

  async function submit(e) {
    e.preventDefault();
    setState({ busy: true, error: null });
    try {
      const r = await api("/auth/register", { method: "POST", body: {
        name: f.name, birth_date: f.birth_date, email: f.email, accept_terms: f.terms } });
      setSent({ ...r, at: Date.now() });
    } catch (err) {
      setState({ busy: false, error: err.message });
    }
  }

  return (
    <main className="signin">
      <section className="signin-card join-card" aria-labelledby="reg-h">
        <div className="signin-brand">
          <span className="brand-mark"><Logo size={18} /></span>
          <span>Bioverse One</span>
        </div>
        <h1 id="reg-h" className="signin-title">Create your account</h1>
        {open === null && <div className="skeleton" />}
        {open === false && (
          <>
            <p className="muted">Registration isn't open here. Ask your clinic to send you an invite link.</p>
            <Link className="btn block" to="/signin">Go to sign in</Link>
          </>
        )}
        {open && !sent && (
          <form className="stack" onSubmit={submit}>
            <label className="inv-field"><span>Full name</span>
              <input required minLength={2} autoComplete="name" value={f.name} onChange={set("name")} /></label>
            <label className="inv-field"><span>Date of birth</span>
              <input required type="date" autoComplete="bday" max={new Date().toISOString().slice(0, 10)}
                     value={f.birth_date} onChange={set("birth_date")} /></label>
            <label className="inv-field"><span>Email address</span>
              <input required type="email" autoComplete="email" value={f.email} onChange={set("email")} /></label>
            <label className="join-check">
              <input type="checkbox" required checked={f.terms} onChange={set("terms")} />
              <span>I agree to the terms of use and privacy notice.</span>
            </label>
            {state.error && <div className="error-box" role="alert">{state.error}</div>}
            <button className="btn primary block" disabled={state.busy}>{state.busy ? "Sending…" : "Email me a code"}</button>
            <p className="small muted">Already have an account? <Link to="/signin">Sign in</Link></p>
          </form>
        )}
        {open && sent && <EmailCode started={sent} initialEmail={f.email} next="/" />}
        <p className="tiny muted row" style={{ gap: 6 }}>
          <Shield size={13} /> No password: each time you sign in, we email you a one-time code.
        </p>
      </section>
    </main>
  );
}
