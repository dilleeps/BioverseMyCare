import Analytics from "./Analytics.jsx";

export const ChartIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 20V10" /><path d="M10 20V4" /><path d="M16 20v-7" /><path d="M3 20h18" />
  </svg>
);

export default {
  id: "analytics",
  title: "Analytics",
  group: "Insight",
  order: 62,
  routes: [{ path: "/analytics", element: <Analytics />, roles: ["admin", "clinician"] }],
  nav: [
    { to: "/analytics", label: "Analytics", description: "Demand, bookings, escalations, turnaround and leakage trends",
      roles: ["admin"], placement: "workspace", icon: ChartIcon, group: "Insight" },
    { to: "/analytics", label: "My panel", description: "Care-plan adherence, overdue tasks and follow-up gaps",
      roles: ["clinician"], placement: "workspace", icon: ChartIcon, group: "Insight" },
  ],
};
