import "./styles.css";
import Vitals from "./Vitals.jsx";
import { ClinicianVitalsIndex, ClinicianVitalsPage, VitalsPanel } from "./ClinicianVitals.jsx";
import { Pulse } from "./icons.jsx";

export default {
  id: "vitals",
  title: "Vitals & devices",
  group: "Care",
  order: 56,
  routes: [
    { path: "/vitals", element: <Vitals />, roles: ["patient"] },
    { path: "/clinician/vitals", element: <ClinicianVitalsIndex />, roles: ["clinician"] },
    { path: "/clinician/vitals/:patientId", element: <ClinicianVitalsPage />, roles: ["clinician"] },
  ],
  nav: [
    { to: "/vitals", label: "Vitals & devices", description: "Log readings, snap a meter photo, see trends and devices",
      roles: ["patient"], placement: "hub" },
    { to: "/clinician/vitals", label: "Home vitals", description: "Home-reading alerts and monitoring plans",
      roles: ["clinician"], placement: "workspace", icon: Pulse, group: "Clinical" },
  ],
  workspacePanels: [{ id: "home-vitals", title: "Home vitals", order: 35, component: VitalsPanel }],
};
