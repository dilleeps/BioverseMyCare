import "./styles.css";
import People from "./People.jsx";

const PeopleIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c.8-3.6 3.3-5.5 6.5-5.5s5.7 1.9 6.5 5.5" />
    <path d="M16 4.5a3.5 3.5 0 0 1 0 7M18.5 14.8c1.7.8 2.7 2.6 3 5.2" />
  </svg>
);

export default {
  id: "access",
  title: "People & sign-in",
  group: "Administration",
  order: 90,
  routes: [{ path: "/admin/people", element: <People />, roles: ["admin"] }],
  nav: [
    { to: "/admin/people", label: "People & sign-in", description: "Who can sign in, with which account, and their role",
      roles: ["admin"], placement: "workspace", icon: PeopleIcon },
  ],
};
