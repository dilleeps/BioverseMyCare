import "./styles.css";
import EvidencePage from "./EvidencePage.jsx";
import EvidencePanel from "./EvidencePanel.jsx";

export default {
  id: "evidence",
  title: "Evidence",
  group: "Clinical",
  order: 40,
  routes: [{ path: "/clinician/evidence", element: <EvidencePage />, roles: ["clinician"] }],
  nav: [
    {
      to: "/clinician/evidence",
      label: "Evidence",
      description: "Cited answers from guidelines, reviews and drug labels",
      roles: ["clinician"],
      placement: "workspace",
    },
  ],
  workspacePanels: [{ id: "evidence", title: "Evidence for this patient", order: 40, component: EvidencePanel }],
};
