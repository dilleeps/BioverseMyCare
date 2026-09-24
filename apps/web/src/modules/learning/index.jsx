import "./styles.css";
import LearningHome from "./LearningHome.jsx";
import CaseStudy from "./CaseStudy.jsx";
import Quiz from "./Quiz.jsx";
import Progress from "./Progress.jsx";
import EvidenceSearch from "./EvidenceSearch.jsx";

const STUDENT = ["student"];

export default {
  id: "learning",
  title: "Learning",
  group: "Learning",
  order: 76,
  routes: [
    { path: "/learning", element: <LearningHome />, roles: STUDENT },
    { path: "/learning/cases/:caseId", element: <CaseStudy />, roles: STUDENT },
    { path: "/learning/cases/:caseId/quiz", element: <Quiz />, roles: STUDENT },
    { path: "/learning/progress", element: <Progress />, roles: STUDENT },
    { path: "/learning/evidence", element: <EvidenceSearch />, roles: STUDENT },
  ],
  nav: [
    {
      to: "/learning", label: "Case library", description: "De-identified cases with a Socratic tutor",
      roles: STUDENT, placement: "top", home: true,
    },
    {
      to: "/learning/progress", label: "Progress", description: "Your case scores and quiz history",
      roles: STUDENT, placement: "top",
    },
    {
      to: "/learning/evidence", label: "Evidence", description: "Search guidelines, reviews and drug labels",
      roles: STUDENT, placement: "top",
    },
  ],
};
