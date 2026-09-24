import "./styles.css";
import FactCheck from "./FactCheck.jsx";

export default {
  id: "factcheck",
  title: "Health fact check",
  group: "Learn",
  order: 72,
  // Every signed-in role: patients, caregivers, clinicians, staff, admins and students.
  routes: [{ path: "/factcheck", element: <FactCheck /> }],
  nav: [
    {
      to: "/factcheck",
      label: "Health fact check",
      description: "Check a health claim you read or were sent",
      placement: "hub",
    },
  ],
};
