import { NavLink, Link, Route, Routes, useNavigate } from "react-router-dom";
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

const PATIENT_NAV = [
  { to: "/app", label: "Ask Bioverse" },
  { to: "/plan", label: "Care plan" },
  { to: "/results", label: "Results" },
  { to: "/story", label: "My Health Story" },
];
const CLINICIAN_NAV = [
  { to: "/clinician", label: "Workspace", end: true },
  { to: "/clinician/agent", label: "My agent" },
];

function TopBar() {
  const { users, me, switchTo } = useSession();
  const navigate = useNavigate();
  const health = useApi("/health");
  const nav = me?.role === "clinician" ? CLINICIAN_NAV : PATIENT_NAV;

  async function onSwitch(e) {
    const user = users.find((u) => u.id === e.target.value);
    await switchTo(e.target.value);
    navigate(user?.role === "clinician" ? "/clinician" : "/app");
  }

  return (
    <header className="topbar">
      <Link to="/" className="brand" aria-label="Bioverse home">
        <span className="brand-mark"><Logo size={16} /></span>
        <span className="brand-name">Bioverse</span>
      </Link>
      <nav className="topnav" aria-label="Main">
        {nav.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end}>{n.label}</NavLink>
        ))}
      </nav>
      <div className="identity">
        {health.data && (
          <span className={`ai-pill ${health.data.ai === "claude" ? "" : "rules"}`} title="How the AI layer is running">
            {health.data.ai === "claude" ? "AI: Claude" : "AI: rules mode"}
          </span>
        )}
        {health.error && <span className="ai-pill rules">API offline</span>}
        <label htmlFor="identity" className="sr-only">Viewing as</label>
        <select id="identity" value={me?.id || ""} onChange={onSwitch} disabled={!users.length}>
          {users.map((u) => (
            <option key={u.id} value={u.id}>
              {u.display_name} · {u.subtitle}
            </option>
          ))}
        </select>
      </div>
    </header>
  );
}

// Small screens hide the top nav; this bar takes its place.
function TabBar() {
  const { me } = useSession();
  if (!me) return null;
  const nav = me.role === "clinician" ? CLINICIAN_NAV : PATIENT_NAV;
  return (
    <nav className="tabbar" aria-label="Sections">
      {nav.map((n) => (
        <NavLink key={n.to} to={n.to} end={n.end}>{n.label}</NavLink>
      ))}
    </nav>
  );
}

function RequireRole({ role, children }) {
  const { me, status, users, switchTo } = useSession();
  const navigate = useNavigate();
  if (status === "loading" && !me) return <div className="column"><div className="skeleton" /></div>;
  if (!me) return null;
  if (me.role === role) return children;
  const target = users.find((u) => u.role === role);
  return (
    <div className="column">
      <div className="card stack">
        <div className="card-title">This page is for {role === "patient" ? "patients" : "clinicians"}.</div>
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

function SessionGate({ children }) {
  const { status, error } = useSession();
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
  return (
    <>
      <TopBar />
      <SessionGate>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/app" element={<RequireRole role="patient"><FrontDoor /></RequireRole>} />
          <Route path="/care/find" element={<RequireRole role="patient"><Navigator /></RequireRole>} />
          <Route path="/plan" element={<RequireRole role="patient"><CarePlan /></RequireRole>} />
          <Route path="/results" element={<RequireRole role="patient"><ResultsList /></RequireRole>} />
          <Route path="/results/:reportId" element={<ResultDetail />} />
          <Route path="/story" element={<RequireRole role="patient"><HealthStory /></RequireRole>} />
          <Route path="/clinician" element={<RequireRole role="clinician"><Clinician /></RequireRole>} />
          <Route path="/clinician/agent" element={<RequireRole role="clinician"><AgentConfig /></RequireRole>} />
          <Route path="*" element={<div className="column empty">Page not found. <Link to="/">Go home</Link></div>} />
        </Routes>
        <TabBar />
      </SessionGate>
    </>
  );
}
