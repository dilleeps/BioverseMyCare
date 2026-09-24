import "./styles.css";
import AuditPage from "./AuditPage.jsx";
import RetentionPage from "./RetentionPage.jsx";
import IncidentsPage from "./IncidentsPage.jsx";
import BreakGlassPage from "./BreakGlassPage.jsx";
import { Shield, Warning } from "../../icons.jsx";

const GROUP = "Trust and safety";

export default {
  id: "governance",
  title: "Trust and safety",
  group: GROUP,
  order: 92,
  routes: [
    { path: "/admin/audit", element: <AuditPage />, roles: ["admin"] },
    { path: "/admin/retention", element: <RetentionPage />, roles: ["admin"] },
    { path: "/safety/incidents", element: <IncidentsPage />, roles: ["clinician", "admin"] },
    { path: "/break-glass", element: <BreakGlassPage />, roles: ["clinician"] },
  ],
  nav: [
    { to: "/admin/audit", label: "Compliance audit", description: "Search, export and verify the audit trail",
      roles: ["admin"], placement: "workspace", icon: Shield },
    { to: "/admin/retention", label: "Retention", description: "How long each kind of data is kept",
      roles: ["admin"], placement: "workspace" },
    { to: "/safety/incidents", label: "Safety incidents", description: "Report and triage AI safety and privacy incidents",
      roles: ["clinician", "admin"], placement: "workspace", icon: Warning },
    { to: "/break-glass", label: "Break-glass access", description: "Emergency access to a record, with a reason",
      roles: ["clinician"], placement: "workspace" },
  ],
};
