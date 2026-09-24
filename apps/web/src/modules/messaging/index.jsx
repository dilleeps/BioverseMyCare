import "./styles.css";
import { Chat } from "../../icons.jsx";
import Messages from "./Messages.jsx";
import Inbox from "./Inbox.jsx";

export default {
  id: "messaging",
  title: "Messages",
  group: "Care",
  order: 40,
  routes: [
    { path: "/messages", element: <Messages />, roles: ["patient"] },
    { path: "/clinician/inbox", element: <Inbox />, roles: ["clinician", "staff"] },
  ],
  nav: [
    { to: "/messages", label: "Messages", description: "Secure messages with your care team",
      roles: ["patient"], placement: "top" },
    { to: "/clinician/inbox", label: "Inbox", description: "Patient messages, triaged, with AI-drafted replies",
      roles: ["clinician"], placement: "workspace", icon: Chat, group: "Clinical" },
    { to: "/clinician/inbox", label: "Inbox", description: "Front desk and nurse-triage messages",
      roles: ["staff"], placement: "workspace", icon: Chat, home: true, group: "Front desk", teams: ["front_desk"] },
    { to: "/clinician/inbox", label: "Inbox", roles: ["staff"], placement: "top", group: "Front desk", teams: ["front_desk"] },
  ],
};
