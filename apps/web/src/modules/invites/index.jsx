import "./invites.css";
import Invites from "./Invites.jsx";

const InviteIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c.8-3.6 3.3-5.5 6.5-5.5 1.6 0 3 .5 4.1 1.3" />
    <path d="M19 14v6M16 17h6" />
  </svg>
);

const ROLES = ["admin", "staff", "clinician"];

export default {
  id: "invites",
  title: "Invite a patient",
  group: "Patients",
  order: 85,
  routes: [{ path: "/invites", element: <Invites />, roles: ROLES }],
  nav: [
    { to: "/invites", label: "Invite a patient", description: "Send a join link and track who has signed up",
      roles: ROLES, placement: "workspace", icon: InviteIcon, teams: ["front_desk"] },
  ],
};
