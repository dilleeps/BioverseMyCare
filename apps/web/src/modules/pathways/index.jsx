import PathwaysAdmin from "./PathwaysAdmin.jsx";
import CarePlans from "./CarePlans.jsx";

const RouteIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="6" cy="5" r="2" /><circle cx="18" cy="19" r="2" /><path d="M6 7v4a4 4 0 0 0 4 4h4a4 4 0 0 1 4 4" />
  </svg>
);

const ClipboardIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 4V3h6v1" /><path d="M9 11l2 2 4-4" /><path d="M9 17h6" />
  </svg>
);

export default {
  id: "pathways",
  title: "Care pathways",
  group: "Clinical",
  order: 66,
  routes: [
    { path: "/admin/pathways", element: <PathwaysAdmin />, roles: ["admin"] },
    { path: "/clinician/care-plans", element: <CarePlans />, roles: ["clinician"] },
  ],
  nav: [
    { to: "/admin/pathways", label: "Care pathways", description: "Templates clinicians start care plans from",
      roles: ["admin"], placement: "workspace", icon: RouteIcon, group: "Administration" },
    { to: "/clinician/care-plans", label: "Care plans", description: "Start, edit and complete your patients' care plans",
      roles: ["clinician"], placement: "workspace", icon: ClipboardIcon, group: "Clinical" },
  ],
};
