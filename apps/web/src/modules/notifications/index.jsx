import "./styles.css";
import Notifications from "./Notifications.jsx";
import Jobs from "./Jobs.jsx";

const ClockIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
  </svg>
);

export default {
  id: "notifications",
  title: "Notifications",
  group: "Account",
  order: 95,
  routes: [
    { path: "/notifications", element: <Notifications /> },
    { path: "/ops/jobs", element: <Jobs />, roles: ["admin"] },
  ],
  nav: [
    { to: "/notifications", label: "Notifications", description: "Your inbox, and how Bioverse One reaches you",
      roles: ["patient", "clinician", "staff", "admin"], placement: "hub" },
    { to: "/ops/jobs", label: "Scheduled jobs", description: "Reminders and deliveries that run on their own",
      roles: ["admin"], placement: "workspace", icon: ClockIcon },
  ],
};
