import "./styles.css";
import Credentials from "./Credentials.jsx";
import MyLicense from "./MyLicense.jsx";

const BadgeIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="9" cy="11" r="2" /><path d="M6 16c.6-1.4 1.8-2 3-2s2.4.6 3 2M14 10h4M14 13h3" />
  </svg>
);

export default {
  id: "credentialing",
  title: "Credentialing",
  group: "Administration",
  order: 66,
  routes: [
    { path: "/admin/credentials", element: <Credentials />, roles: ["admin"] },
    { path: "/clinician/license", element: <MyLicense />, roles: ["clinician"] },
  ],
  nav: [
    { to: "/admin/credentials", label: "Credentialing", description: "Verify clinician licenses and watch expiry dates",
      roles: ["admin"], placement: "workspace", icon: BadgeIcon, group: "Administration" },
    { to: "/clinician/license", label: "My license", description: "Your license and verification status",
      roles: ["clinician"], placement: "hub" },
  ],
};
