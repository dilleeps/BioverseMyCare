import "./styles.css";
import HealthAI from "./HealthAI.jsx";

export default {
  id: "health-ai",
  title: "Ask about my health",
  group: "Records",
  order: 45,
  routes: [{ path: "/health-ai", element: <HealthAI />, roles: ["patient"] }],
  nav: [
    {
      to: "/health-ai",
      label: "Ask about my health",
      description: "Answers from your own record, with sources",
      roles: ["patient"],
      placement: "hub",
    },
  ],
};
