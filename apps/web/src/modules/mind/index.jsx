import "../nutrition/styles.css";
import "./styles.css";
import Mind from "./Mind.jsx";
import ClinicianMind from "./ClinicianMind.jsx";
import MindPanel from "./MindPanel.jsx";

export default {
  id: "mind",
  title: "Mood & mind",
  group: "Wellbeing",
  order: 62,
  routes: [
    { path: "/mind", element: <Mind />, roles: ["patient"] },
    { path: "/clinician/mind/:patientId", element: <ClinicianMind />, roles: ["clinician"] },
  ],
  nav: [
    { to: "/mind", label: "Mood & mind", description: "Mood and anxiety check-ins, journal, breathing, support",
      roles: ["patient"], placement: "hub" },
  ],
  workspacePanels: [{ id: "mood-anxiety", title: "Mood & anxiety", order: 61, component: MindPanel }],
};
