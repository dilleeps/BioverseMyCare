import Organization from "./Organization.jsx";

const BuildingIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="4" y="3" width="16" height="18" rx="2" /><path d="M9 7h2M13 7h2M9 11h2M13 11h2M10 21v-4h4v4" />
  </svg>
);

export default {
  id: "organization",
  title: "Organization",
  group: "Administration",
  order: 64,
  routes: [{ path: "/admin/org", element: <Organization />, roles: ["admin"] }],
  nav: [
    { to: "/admin/org", label: "Organization", description: "Profile, locations, departments, services and providers",
      roles: ["admin"], placement: "workspace", icon: BuildingIcon, group: "Administration" },
  ],
};
