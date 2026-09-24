import "./styles.css";
import Wellness from "./Wellness.jsx";

export default {
  id: "wellness",
  title: "Wellness & prevention",
  group: "Wellbeing",
  order: 60,
  routes: [{ path: "/wellness", element: <Wellness />, roles: ["patient"] }],
  nav: [
    {
      to: "/wellness",
      label: "Wellness & prevention",
      description: "Screenings, vaccines, goals and a lifestyle check-in",
      roles: ["patient"],
      placement: "hub",
    },
  ],
};
