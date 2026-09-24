import "./styles.css";
import Directory from "./Directory.jsx";
import SpecialistChat from "./SpecialistChat.jsx";
import PublicAgentSettings from "./PublicAgentSettings.jsx";
import AdminApprovals from "./AdminApprovals.jsx";

export default {
  id: "specialists",
  title: "Specialist AI assistants",
  group: "Learn",
  order: 74,
  routes: [
    { path: "/specialists", element: <Directory />, roles: ["patient", "student"] },
    { path: "/specialists/:agentId", element: <SpecialistChat />, roles: ["patient", "student"] },
    { path: "/clinician/public-agent", element: <PublicAgentSettings />, roles: ["clinician"] },
    { path: "/admin/public-agents", element: <AdminApprovals />, roles: ["admin"] },
  ],
  nav: [
    {
      to: "/specialists",
      label: "Specialist AI assistants",
      description: "General health questions, answered from specialists' approved guidance",
      roles: ["patient", "student"],
      placement: "hub",
    },
    {
      to: "/clinician/public-agent",
      label: "Public AI agent",
      description: "Your public education assistant: profile, scope, guidance and conversations",
      roles: ["clinician"],
      placement: "workspace",
    },
    {
      to: "/admin/public-agents",
      label: "Public AI agents",
      description: "Approve clinicians' public education assistants before they are listed",
      roles: ["admin"],
      placement: "workspace",
    },
  ],
};
