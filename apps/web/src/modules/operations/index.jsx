import Dashboard from "./Dashboard.jsx";
import Assistant from "./Assistant.jsx";

const PulseIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 12h4l3-7 4 14 3-7h4" />
  </svg>
);

const AgentIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 5h16v11H9l-5 4z" /><path d="M9 10h6" />
  </svg>
);

export default {
  id: "operations",
  title: "Hospital operations",
  group: "Operations",
  order: 60,
  routes: [
    { path: "/ops", element: <Dashboard />, roles: ["admin"] },
    { path: "/ops/assistant", element: <Assistant />, roles: ["admin"] },
  ],
  nav: [
    { to: "/ops", label: "Operations", description: "Capacity, demand, intakes, escalations and workload today",
      roles: ["admin"], placement: "workspace", home: true, end: true, icon: PulseIcon },
    { to: "/ops/assistant", label: "Hospital Agent", description: "Ask operations questions in plain language",
      roles: ["admin"], placement: "workspace", icon: AgentIcon },
  ],
};
