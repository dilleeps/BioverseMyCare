import "./styles.css";
import Nutrition from "./Nutrition.jsx";
import Weight from "./Weight.jsx";
import ClinicianNutrition from "./ClinicianNutrition.jsx";
import NutritionPanel from "./NutritionPanel.jsx";

export default {
  id: "nutrition",
  title: "Food & nutrition",
  group: "Wellbeing",
  order: 61,
  routes: [
    { path: "/nutrition", element: <Nutrition />, roles: ["patient"] },
    { path: "/weight", element: <Weight />, roles: ["patient"] },
    { path: "/clinician/nutrition/:patientId", element: <ClinicianNutrition />, roles: ["clinician"] },
  ],
  nav: [
    { to: "/nutrition", label: "Food & nutrition", description: "Log meals, scan a plate, see sodium and other targets",
      roles: ["patient"], placement: "hub" },
    { to: "/weight", label: "Weight coach", description: "Weigh-ins, trend and a safe, steady goal",
      roles: ["patient"], placement: "hub" },
  ],
  workspacePanels: [{ id: "nutrition-weight", title: "Nutrition & weight", order: 60, component: NutritionPanel }],
};
