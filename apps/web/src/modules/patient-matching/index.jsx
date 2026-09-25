import "./styles.css";
import Duplicates from "./Duplicates.jsx";
import FindRecord from "./FindRecord.jsx";

const TwinIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="4" width="8" height="16" rx="2" /><rect x="13" y="4" width="8" height="16" rx="2" />
    <path d="M6 9h2M16 9h2M6 13h2M16 13h2" />
  </svg>
);

const FindIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="10" cy="10" r="6" /><path d="m20 20-5.5-5.5" /><path d="M8 9.5a2 2 0 1 0 4 0 2 2 0 1 0-4 0M7 14c.6-1 1.7-1.6 3-1.6s2.4.6 3 1.6" />
  </svg>
);

const WHO = { roles: ["admin", "staff"], teams: ["front_desk"] };

export default {
  id: "patient-matching",
  title: "Patient records",
  group: "Patient records",
  order: 86,
  routes: [
    { path: "/registry/duplicates", element: <Duplicates />, roles: WHO.roles },
    { path: "/registry/find", element: <FindRecord />, roles: WHO.roles },
  ],
  nav: [
    { to: "/registry/duplicates", label: "Duplicate records", placement: "workspace", icon: TwinIcon,
      description: "Review records that may be the same person, then merge them or keep them apart", ...WHO },
    { to: "/registry/find", label: "Find a patient record", placement: "workspace", icon: FindIcon,
      description: "Look someone up by name, date of birth, MRN, email or phone before registering them", ...WHO },
  ],
};
