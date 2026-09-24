import "./styles.css";
import Pharmacy from "./Pharmacy.jsx";
import ClinicianRefills from "./ClinicianRefills.jsx";
import MedsPanel from "./MedsPanel.jsx";
import { Pill } from "./icons.jsx";

export default {
  id: "pharmacy",
  title: "Pharmacy",
  group: "Care",
  order: 55,
  routes: [
    { path: "/pharmacy", element: <Pharmacy />, roles: ["patient"] },
    { path: "/clinician/refills", element: <ClinicianRefills />, roles: ["clinician"] },
  ],
  nav: [
    { to: "/pharmacy", label: "Pharmacy", description: "Prescriptions, refills, doses and your pharmacy",
      roles: ["patient"], placement: "hub" },
    { to: "/clinician/refills", label: "Refill requests", description: "Approve or deny refills with none left",
      roles: ["clinician"], placement: "workspace", icon: Pill, group: "Clinical" },
  ],
  workspacePanels: [{ id: "medications", title: "Medications", order: 40, component: MedsPanel }],
};
