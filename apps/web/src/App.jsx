import { NavLink, Link, Route, Routes, matchPath, useLocation, useNavigate } from "react-router-dom";
import { useSession } from "./session.jsx";
import { useApi } from "./hooks.js";
import { Logo } from "./icons.jsx";
import Landing from "./pages/Landing.jsx";
import FrontDoor from "./pages/FrontDoor.jsx";
import Navigator from "./pages/Navigator.jsx";
import CarePlan from "./pages/CarePlan.jsx";
import { ResultsList, ResultDetail } from "./pages/Results.jsx";
import HealthStory from "./pages/HealthStory.jsx";
import Clinician from "./pages/Clinician.jsx";
import AgentConfig from "./pages/AgentConfig.jsx";
import Hub from "./pages/Hub.jsx";
import SignIn from "./pages/SignIn.jsx";
import Join from "./pages/Join.jsx";
import Register from "./pages/Register.jsx";
import Bell from "./modules/notifications/Bell.jsx";
import { InstallBanner } from "./components/InstallApp.jsx";
import { homeFor, moduleRoutes, navFor } from "./modules/registry.js";
import { useSyncDisplayPrefs } from "./modules/accessibility/prefs.js";

const CORE_NAV = {
  patient: [
    { to: "/app", label: "Ask Bioverse" },
    { to: "/plan", label: "Care plan" },
    { to: "/results", label: "Results" },
    { to: "/story", label: "My Health Story" },
  ],
  clinician: [
    { to: "/clinician", label: "Workspace", end: true },
    { to: "/clinician/agent", label: "My agent" },
  ],
};

// Core entries, any module entries placed in the top bar, then "More" for the rest.
// Roles without core pages (admin, staff) get their module home first.
function navItems(me) {
  const core = CORE_NAV[me.role] || [{ to: homeFor(me), label: "Home", end: true }];
  const items = [...core, ...navFor(me, "top"), { to: "/hub", label: "More" }];
  return items.filter((n, i) => items.findIndex((m) => m.to === n.to) === i);
}

const AI_LABEL = { medgemma: "AI: MedGemma", claude: "AI: Claude", rules: "AI: rules mode" };

const ROLE_NOUN = { patient: "patients", clinician: "clinicians", admin: "administrators", staff: "staff", student: "medical students" };

function TopBar() {
  const { users, me, switchTo, signOut } = useSession();
  const navigate = useNavigate();
  const health = useApi("/health");
  const nav = me ? navItems(me) : [];

  async function onSwitch(e) {
    const user = users.find((u) => u.id === e.target.value);
    await switchTo(e.target.value);
    navigate(homeFor(user));
  }

  return (
    <header className="topbar">
      <Link to="/" className="brand" aria-label="Bioverse One home">
        <span className="brand-mark"><Logo size={16} /></span>
        <span className="brand-name">Bioverse One</span>
      </Link>
      <nav className="topnav" aria-label="Main">
        {nav.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end}>{n.label}</NavLink>
        ))}
      </nav>
      <div className="identity">
        {health.data && (
          <span className={`ai-pill ${health.data.ai === "rules" ? "rules" : ""}`} title="How the AI layer is running">
            {AI_LABEL[health.data.ai] || "AI: rules mode"}
          </span>
        )}
        {health.error && <span className="ai-pill rules">API offline</span>}
        {me && <Bell />}
        {me?.auth === "sso" ? (
          <>
            <span className="who" title={me.display_name}>{me.display_name}</span>
            <button type="button" className="btn sm signout" onClick={signOut}>Sign out</button>
          </>
        ) : users.length > 0 ? (
          <>
            <label htmlFor="identity" className="sr-only">Viewing as</label>
            <select id="identity" value={me?.id || ""} onChange={onSwitch}>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.display_name} · {u.subtitle}
                </option>
              ))}
            </select>
          </>
        ) : null}
      </div>
    </header>
  );
}

// Small screens hide the top nav; this bar takes its place.
function TabBar() {
  const { me } = useSession();
  if (!me) return null;
  const nav = navItems(me).slice(-5);
  return (
    <nav className="tabbar" aria-label="Sections">
      {nav.map((n) => (
        <NavLink key={n.to} to={n.to} end={n.end}>{n.label}</NavLink>
      ))}
    </nav>
  );
}

// `role` (one) or `roles` (several). No roles given means any signed-in user.
export function RequireRole({ role, roles, children }) {
  const { me, status, users, switchTo } = useSession();
  const navigate = useNavigate();
  const allowed = roles || (role ? [role] : null);
  if (status === "loading" && !me) return <div className="column"><div className="skeleton" /></div>;
  if (!me) return null;
  if (!allowed || allowed.includes(me.role)) return children;
  const target = users.find((u) => allowed.includes(u.role));
  return (
    <div className="column">
      <div className="card stack">
        <div className="card-title">This page is for {allowed.map((r) => ROLE_NOUN[r] || r).join(" and ")}.</div>
        <p className="muted small">You're signed in as {me.display_name}.</p>
        {target && (
          <button
            className="btn primary"
            onClick={async () => {
              await switchTo(target.id);
              navigate(0);
            }}
          >
            Switch to {target.display_name}
          </button>
        )}
      </div>
    </div>
  );
}

// Pages anyone can open without signing in: a patient's invite link and open registration.
const PUBLIC_ROUTES = [
  { path: "/join/:token", element: <Join /> },
  { path: "/register", element: <Register /> },
];

function SessionGate({ children }) {
  const { status, error } = useSession();
  const { pathname } = useLocation();
  if (PUBLIC_ROUTES.some((r) => matchPath(r.path, pathname))) {
    return <Routes>{PUBLIC_ROUTES.map((r) => <Route key={r.path} path={r.path} element={r.element} />)}</Routes>;
  }
  if (status === "signed_out") return <SignIn />;
  if (status === "error") {
    return (
      <div className="column">
        <div className="error-box">
          {error?.message || "Could not start a session."} Make sure the API is running on port 8000 and the
          database is seeded.
        </div>
      </div>
    );
  }
  return children;
}

export default function App() {
  // Senior mode, text size, contrast and motion: applied to the root <html> element as data attributes.
  useSyncDisplayPrefs(useSession().me?.id);
  return (
    <>
      <TopBar />
      <InstallBanner />
      <SessionGate>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/signin" element={<SignIn />} />
          <Route path="/app" element={<RequireRole role="patient"><FrontDoor /></RequireRole>} />
          <Route path="/care/find" element={<RequireRole role="patient"><Navigator /></RequireRole>} />
          <Route path="/plan" element={<RequireRole role="patient"><CarePlan /></RequireRole>} />
          <Route path="/results" element={<RequireRole role="patient"><ResultsList /></RequireRole>} />
          <Route path="/results/:reportId" element={<ResultDetail />} />
          <Route path="/story" element={<RequireRole role="patient"><HealthStory /></RequireRole>} />
          <Route path="/clinician" element={<RequireRole role="clinician"><Clinician /></RequireRole>} />
          <Route path="/clinician/agent" element={<RequireRole role="clinician"><AgentConfig /></RequireRole>} />
          <Route path="/hub" element={<RequireRole><Hub /></RequireRole>} />
          {moduleRoutes().map((r) => (
            <Route key={r.path} path={r.path} element={<RequireRole roles={r.roles}>{r.element}</RequireRole>} />
          ))}
          <Route path="*" element={<div className="column empty">Page not found. <Link to="/">Go home</Link></div>} />
        </Routes>
        <TabBar />
      </SessionGate>
    </>
  );
}
