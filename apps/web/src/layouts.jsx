import { NavLink } from "react-router-dom";
import { useSession } from "./session.jsx";
import { navFor } from "./modules/registry.js";
import { fmtDateTime, initials } from "./format.js";
import { Calendar, Chevron, Gear } from "./icons.jsx";

const CORE_WORKSPACE_NAV = {
  clinician: [
    { to: "/clinician", label: "Today", icon: Calendar, end: true },
    { to: "/clinician/agent", label: "My agent", icon: Gear },
  ],
  admin: [],
  staff: [],
};

// Dark side navigation for clinicians, staff and admins. Module pages wrap themselves in
// <WorkspaceLayout> to get it; entries come from modules with placement "workspace".
export function WorkspaceNav({ patients, selected, onSelect }) {
  const { me } = useSession();
  if (!me) return null;
  const core = CORE_WORKSPACE_NAV[me.role] || [];
  const extra = navFor(me, "workspace");
  return (
    <nav className="sidenav" aria-label="Workspace">
      {core.map((n) => {
        const Icon = n.icon;
        return <NavLink key={n.to} to={n.to} end={n.end}><Icon size={18} /> {n.label}</NavLink>;
      })}
      {extra.map((n) => (
        <NavLink key={n.to} to={n.to} end={n.end}>
          {n.icon ? <n.icon size={18} /> : <Chevron size={18} />} {n.label}
        </NavLink>
      ))}
      {patients && (
        <>
          <div className="section">My patients</div>
          {patients.map((p) => (
            <button key={p.id} className="patient-pick" aria-current={p.id === selected} onClick={() => onSelect(p.id)}>
              <div className="who">{p.name}{p.open_items > 0 ? ` · ${p.open_items}` : ""}</div>
              <div className="meta">
                {p.age} · {p.pronouns || "—"}
                {p.next_appointment ? ` · ${fmtDateTime(p.next_appointment)}` : ""}
              </div>
            </button>
          ))}
        </>
      )}
      <div style={{ flexGrow: 1 }} />
      <div className="row nav-foot" style={{ padding: "12px 8px" }}>
        <span className="avatar" style={{ width: 34, height: 34, background: "var(--brand-700)", color: "#fff", fontSize: 13 }}>
          {initials(me.display_name)}
        </span>
        <span className="small strong">{me.display_name}</span>
      </div>
    </nav>
  );
}

export function WorkspaceLayout({ children, patients, selected, onSelect }) {
  return (
    <div className="workspace">
      <WorkspaceNav patients={patients} selected={selected} onSelect={onSelect} />
      <main className="ws-main">{children}</main>
    </div>
  );
}

// Patient pages: a single readable column, or a wider page.
export function PatientPage({ wide = false, children }) {
  return <main className={wide ? "page" : "column"}>{children}</main>;
}

const ROLE_LABEL = { patient: "Patient", clinician: "Clinician", staff: "Staff", admin: "Administrator", student: "Medical student" };

function greeting(now = new Date()) {
  const h = now.getHours();
  return h < 12 ? "Good morning," : h < 18 ? "Good afternoon," : "Good evening,";
}

// The teal greeting band from the MedKeyRX home screen. `children` go in the translucent overview strip.
export function GreetingBand({ children }) {
  const { me } = useSession();
  if (!me) return null;
  return (
    <section className="hero-band" aria-label="Welcome">
      <div className="greet">{greeting()}</div>
      <div className="name">{me.display_name}</div>
      <span className="role">{ROLE_LABEL[me.role] || me.role}</span>
      {children && <div className="overview">{children}</div>}
    </section>
  );
}
