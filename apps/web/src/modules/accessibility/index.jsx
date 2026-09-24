import "./styles.css";
import DisplaySettings from "./DisplaySettings.jsx";

// No `roles`: every signed-in person (patient, caregiver, clinician, staff, admin) can open it.
export default {
  id: "accessibility",
  title: "Display and reading",
  group: "Settings",
  order: 190,
  routes: [{ path: "/settings/display", element: <DisplaySettings /> }],
  nav: [
    { to: "/settings/display", label: "Display and reading",
      description: "Senior mode, text size, contrast and read-aloud", placement: "hub" },
  ],
};
