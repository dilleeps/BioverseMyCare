import "./styles.css";
import Records from "./Records.jsx";

export default {
  id: "records",
  title: "My records",
  group: "Records",
  order: 40,
  routes: [{ path: "/records", element: <Records />, roles: ["patient"] }],
  nav: [
    {
      to: "/records",
      label: "My records",
      description: "Upload a lab report or download your record",
      roles: ["patient"],
      placement: "hub",
    },
  ],
};
