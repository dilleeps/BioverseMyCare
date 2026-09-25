import { useLocation } from "react-router-dom";
import { useSession } from "../session.jsx";
import { Logo, Shield } from "../icons.jsx";

// Provider marks for the sign-in buttons, drawn inline (no external images).
const MARKS = {
  entra: (
    <svg width="20" height="20" viewBox="0 0 21 21" aria-hidden="true">
      <rect x="1" y="1" width="9" height="9" fill="#F25022" /><rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
      <rect x="1" y="11" width="9" height="9" fill="#00A4EF" /><rect x="11" y="11" width="9" height="9" fill="#FFB900" />
    </svg>
  ),
  okta: (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="9" fill="none" stroke="#007DC1" strokeWidth="5" />
    </svg>
  ),
  google: (
    <svg width="20" height="20" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.6 5.4 2.7 13.3l7.9 6.1C12.5 13.6 17.8 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.4c-.5 2.9-2.2 5.3-4.6 6.9l7.4 5.7c4.3-4 6.9-9.9 6.9-17.1z" />
      <path fill="#FBBC05" d="M10.6 28.6c-.5-1.4-.8-3-.8-4.6s.3-3.2.8-4.6l-7.9-6.1C1 16.6 0 20.2 0 24s1 7.4 2.7 10.7l7.9-6.1z" />
      <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.4-5.7c-2.1 1.4-4.8 2.3-8.5 2.3-6.2 0-11.5-4.1-13.4-9.9l-7.9 6.1C6.6 42.6 14.6 48 24 48z" />
    </svg>
  ),
};
const BUTTON_LABEL = { entra: "Sign in with Microsoft", okta: "Sign in with Okta", google: "Sign in with Google" };

export default function SignIn() {
  const { config, status } = useSession();
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const error = params.get("error");
  const next = location.pathname === "/signin" ? params.get("next") || "/" : location.pathname + location.search;
  const providers = config?.providers || [];

  return (
    <main className="signin">
      <section className="signin-card" aria-labelledby="signin-h">
        <div className="signin-brand">
          <span className="brand-mark"><Logo size={18} /></span>
          <span>Bioverse One</span>
        </div>
        <h1 id="signin-h" className="signin-title">Sign in</h1>
        <p className="muted">Use your organization's account. Your care team or administrator sets up access.</p>
        {error && (
          <div className="error-box" role="alert">
            {config?.errors?.[error] || "Sign-in didn't work. Please try again or contact your administrator."}
          </div>
        )}
        {status === "loading" && <div className="skeleton" />}
        <div className="stack" style={{ gap: 10 }}>
          {providers.map((p) => (
            <a key={p.key} className="btn block signin-btn"
               href={`/api/auth/login/${p.key}?next=${encodeURIComponent(next)}`}>
              {MARKS[p.key]} {BUTTON_LABEL[p.key] || `Sign in with ${p.label}`}
            </a>
          ))}
        </div>
        {config && providers.length === 0 && (
          <p className="small muted">Single sign-on isn't configured yet. See deploy/gcp/README.md, "Single sign-on".</p>
        )}
        {config?.demo && (
          <p className="small muted">
            Demo mode is on: <a href="/">continue with a demo identity</a>. Use demo data only.
          </p>
        )}
        <p className="tiny muted row" style={{ gap: 6 }}>
          <Shield size={13} /> Sessions end after an hour without activity. Sign out on shared computers.
        </p>
      </section>
    </main>
  );
}
