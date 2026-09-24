import "./styles.css";
import Visits from "./Visits.jsx";
import ClinicQueue from "./ClinicQueue.jsx";

const QueueIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M8 6h13" />
    <path d="M8 12h13" />
    <path d="M8 18h13" />
    <circle cx="4" cy="6" r="1" />
    <circle cx="4" cy="12" r="1" />
    <circle cx="4" cy="18" r="1" />
  </svg>
);

export default {
  id: "visits",
  title: "Visits",
  group: "Care",
  order: 20,
  routes: [
    { path: "/visits", element: <Visits />, roles: ["patient"] },
    { path: "/clinician/queue", element: <ClinicQueue />, roles: ["clinician", "staff", "admin"] },
  ],
  nav: [
    {
      to: "/visits",
      label: "My visits",
      description: "Checklists, directions, check-in and visit summaries",
      roles: ["patient"],
      placement: "hub",
    },
    {
      to: "/clinician/queue",
      label: "Clinic queue",
      description: "Today's patients: arrivals, rooms and after-visit summaries",
      roles: ["clinician", "staff", "admin"],
      placement: "workspace",
      icon: QueueIcon,
    },
  ],
};
