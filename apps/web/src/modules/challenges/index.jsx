import "../nutrition/styles.css";
import "./styles.css";
import Challenges from "./Challenges.jsx";

export default {
  id: "challenges",
  title: "Challenges & rewards",
  group: "Wellbeing",
  order: 63,
  routes: [{ path: "/challenges", element: <Challenges />, roles: ["patient"] }],
  nav: [
    { to: "/challenges", label: "Challenges & rewards", description: "Opt-in challenges, family teams, points and demo perks",
      roles: ["patient"], placement: "hub" },
  ],
};
