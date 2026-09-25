import "./availability.css";
import MyAvailability from "./MyAvailability.jsx";
import { ClinicianAvailability, ClinicianList } from "./ManageAvailability.jsx";
import { ClockIcon, TeamClockIcon } from "./shared.jsx";

export default {
  id: "availability",
  title: "Availability",
  group: "Scheduling",
  order: 23,
  routes: [
    { path: "/availability", element: <MyAvailability />, roles: ["clinician"] },
    { path: "/availability/clinicians", element: <ClinicianList />, roles: ["admin", "staff"] },
    { path: "/availability/:practitionerId", element: <ClinicianAvailability />, roles: ["admin", "staff"] },
  ],
  nav: [
    { to: "/availability", label: "My availability", description: "Weekly hours, time off and your online consult profile",
      roles: ["clinician"], placement: "workspace", icon: ClockIcon, group: "Clinical" },
    { to: "/availability/clinicians", label: "Clinician availability", description: "Clinicians' weekly hours and time off",
      roles: ["admin", "staff"], placement: "workspace", icon: TeamClockIcon, group: "Scheduling", teams: ["front_desk"] },
  ],
};
