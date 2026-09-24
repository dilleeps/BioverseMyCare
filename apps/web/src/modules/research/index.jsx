import "./styles.css";
import ResearchHub from "./ResearchHub.jsx";
import StudyDetail from "./StudyDetail.jsx";
import Coordinator from "./Coordinator.jsx";

export default {
  id: "research",
  title: "Research studies",
  group: "Research",
  order: 80,
  routes: [
    { path: "/research", element: <ResearchHub />, roles: ["patient"] },
    { path: "/research/studies/:studyId", element: <StudyDetail />, roles: ["patient", "clinician"] },
    { path: "/clinician/research", element: <Coordinator />, roles: ["clinician"] },
  ],
  nav: [
    {
      to: "/research",
      label: "Research studies",
      description: "Clinical trials you could join, on your terms",
      roles: ["patient"],
      placement: "hub",
    },
    {
      to: "/clinician/research",
      label: "Research",
      description: "Opted-in patients, study matches and interest",
      roles: ["clinician"],
      placement: "workspace",
    },
  ],
};
