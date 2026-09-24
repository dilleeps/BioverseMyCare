import "./styles.css";
import PrivacyCenter from "./PrivacyCenter.jsx";

export default {
  id: "privacy",
  title: "Privacy",
  group: "Account",
  order: 90,
  routes: [{ path: "/privacy", element: <PrivacyCenter />, roles: ["patient"] }],
  nav: [
    {
      to: "/privacy",
      label: "Privacy",
      description: "Your choices, and who has opened your record",
      roles: ["patient"],
      placement: "hub",
    },
  ],
};
