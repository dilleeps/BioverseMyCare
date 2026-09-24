import { Link } from "react-router-dom";
import { useSession } from "../session.jsx";
import { navFor } from "../modules/registry.js";
import { Chevron } from "../icons.jsx";

const CORE = {
  patient: [
    { to: "/app", label: "Ask Bioverse", description: "Tell Bioverse what you need", group: "Care" },
    { to: "/plan", label: "Care plan", description: "Your tasks, medicines and next steps", group: "Care" },
    { to: "/results", label: "Results", description: "Lab reports, explained and reviewed", group: "Records" },
    { to: "/story", label: "My Health Story", description: "Your year in health, in plain language", group: "Records" },
  ],
  clinician: [
    { to: "/clinician", label: "Workspace", description: "Patients, pre-visit briefs, review queue", group: "Clinical" },
    { to: "/clinician/agent", label: "My Doctor Agent", description: "Questions, follow-ups, escalation rules", group: "Clinical" },
  ],
};

// Everything the signed-in role can open, grouped. Every module appears here automatically.
export default function Hub() {
  const { me } = useSession();
  if (!me) return null;
  const items = [...(CORE[me.role] || []), ...navFor(me.role)];
  const unique = items.filter((n, i) => items.findIndex((m) => m.to === n.to) === i);
  const groups = [...new Set(unique.map((n) => n.group || "More"))];

  return (
    <main className="page">
      <div className="page-head">
        <div>
          <div className="page-title">Everything in Bioverse</div>
          <div className="page-sub">Or just ask. Bioverse will take you to the right place.</div>
        </div>
      </div>
      {unique.length === 0 && <div className="card empty">Nothing here yet for this role.</div>}
      {groups.map((g) => (
        <section key={g} className="stack" style={{ marginBottom: 24 }}>
          <div className="eyebrow">{g}</div>
          <div className="hub-grid">
            {unique.filter((n) => (n.group || "More") === g).map((n) => (
              <Link key={n.to} to={n.to} className="hub-card">
                <span style={{ flexGrow: 1 }}>
                  <span className="strong" style={{ display: "block" }}>{n.label}</span>
                  {n.description && <span className="small muted">{n.description}</span>}
                </span>
                <Chevron size={18} />
              </Link>
            ))}
          </div>
        </section>
      ))}
    </main>
  );
}
