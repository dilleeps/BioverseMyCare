import "./styles.css";
import Companion from "./Companion.jsx";
import ClinicianCompanion from "./ClinicianCompanion.jsx";
import BetweenVisitsPanel from "./BetweenVisitsPanel.jsx";
import { Pulse } from "./icons.jsx";

export default {
  id: "companion",
  title: "Today",
  group: "Care",
  order: 12,
  routes: [
    { path: "/companion", element: <Companion />, roles: ["patient"] },
    { path: "/clinician/companion", element: <ClinicianCompanion />, roles: ["clinician"] },
  ],
  nav: [
    { to: "/companion", label: "Today", description: "Your doses, check-ins and reminders",
      roles: ["patient"], placement: "top" },
    { to: "/clinician/companion", label: "Between visits", description: "Check-in escalations from patients",
      roles: ["clinician"], placement: "workspace", icon: Pulse, group: "Clinical" },
  ],
  workspacePanels: [{ id: "between-visits", title: "Between visits", order: 45, component: BetweenVisitsPanel }],
};
