import { useState } from "react";
import { Link } from "react-router-dom";
import { useSession } from "../session.jsx";
import HubSearch from "../components/frontdoor/HubSearch.jsx";
import { navFor } from "../modules/registry.js";
import { Arrow, Book, Calendar, Card, Chat, Check, Chevron, Gear, Heart, Hospital, Inbox, Lock, Person, Pin, Rx, Shield, Sparkle, Stethoscope } from "../icons.jsx";
import { GreetingBand } from "../layouts.jsx";

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
// Icon and tint per hub group, like the MedKeyRX quick actions: teal for care, green for health, grey for admin.
const GROUP_ICON = {
  Care: [Stethoscope, ""], Clinical: [Stethoscope, ""], Wellbeing: [Heart, "green"], Pharmacy: [Rx, "green"],
  Family: [Person, ""], Records: [Book, "gray"], Interoperability: [Book, "gray"], Money: [Card, "gray"],
  Billing: [Card, "gray"], Insurance: [Card, "gray"], Account: [Gear, "gray"], Settings: [Gear, "gray"],
  Administration: [Hospital, "gray"], Operations: [Hospital, "gray"], "Front desk": [Inbox, ""],
  Insight: [Sparkle, ""], Research: [Sparkle, ""], Learn: [Sparkle, ""], Learning: [Sparkle, ""],
  "Trust and safety": [Shield, "gray"],
};

// A more specific icon when the label says what the screen is about.
const LABEL_ICON = [
  [/ask|chat|message|inbox|agent/i, Chat], [/medicine|pharmac|prescri|refill|\brx\b/i, Rx],
  [/vital|heart|mood|mind|wellbeing|wellness|weight|nutrition|challenge/i, Heart], [/visit|today|appointment|queue|calendar/i, Calendar],
  [/care plan|plan|task/i, Check], [/referral/i, Arrow], [/find your way|wayfinding|map/i, Pin], [/doctor|consult|clinician|credential/i, Stethoscope],
  [/result|record|story|document|evidence|case/i, Book], [/bill|insurance|coverage|payer|financial|claim/i, Card],
  [/privacy|audit|retention|break-glass|security/i, Lock], [/family|caregiver|student/i, Person], [/setting|display|notification/i, Gear],
];

function TileIcon({ item }) {
  const [Icon, tint] = GROUP_ICON[item.group] || [Sparkle, ""];
  const byLabel = LABEL_ICON.find(([re]) => re.test(item.label))?.[1];
  const Shown = item.icon || byLabel || Icon;
  return <span className={`tile-icon ${tint}`} aria-hidden="true"><Shown size={20} /></span>;
}

export default function Hub() {
  const { me } = useSession();
  const [query, setQuery] = useState("");
  if (!me) return null;
  const items = [...(CORE[me.role] || []), ...navFor(me)];
  const unique = items.filter((n, i) => items.findIndex((m) => m.to === n.to) === i);
  const groups = [...new Set(unique.map((n) => n.group || "More"))];

  return (
    <main className="page">
      <GreetingBand>
        <strong>Everything in Bioverse One</strong>
        <span>Or just ask. Bioverse One will take you to the right place.</span>
      </GreetingBand>
      <HubSearch items={unique} query={query} onQuery={setQuery} />
      {unique.length === 0 && <div className="card empty">Nothing here yet for this role.</div>}
      {!query.trim() && groups.map((g) => (
        <section key={g} className="stack" style={{ marginBottom: 24 }}>
          <div className="eyebrow">{g}</div>
          <div className="hub-grid">
            {unique.filter((n) => (n.group || "More") === g).map((n) => (
              <Link key={n.to} to={n.to} className="hub-card">
                <TileIcon item={n} />
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
