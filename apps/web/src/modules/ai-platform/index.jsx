import "./styles.css";
import AiConsole from "./AiConsole.jsx";
import { Sparkle } from "../../icons.jsx";

export default {
  id: "ai-platform",
  title: "AI governance",
  group: "Trust and safety",
  order: 94,
  routes: [{ path: "/admin/ai", element: <AiConsole />, roles: ["admin"] }],
  nav: [
    {
      to: "/admin/ai",
      label: "AI governance",
      description: "Agent registry, AI activity, evaluations and monitoring",
      roles: ["admin"],
      placement: "workspace",
      icon: Sparkle,
    },
  ],
};
