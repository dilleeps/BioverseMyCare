import "./styles.css";
import Family from "./Family.jsx";
import Dependent from "./Dependent.jsx";

export default {
  id: "family",
  title: "Family & caregivers",
  group: "Family",
  order: 65,
  routes: [
    { path: "/family", element: <Family />, roles: ["patient"] },
    { path: "/family/:patientId", element: <Dependent />, roles: ["patient"] },
  ],
  nav: [
    {
      to: "/family",
      label: "Family & caregivers",
      description: "People you care for, and who can see your care",
      roles: ["patient"],
      placement: "hub",
    },
  ],
};
