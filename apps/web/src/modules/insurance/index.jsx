import "./styles.css";
import Insurance from "./Insurance.jsx";
import FrontDesk from "./FrontDesk.jsx";
import Claims from "./Claims.jsx";
import Connections from "./Connections.jsx";
import { CardIcon, ClaimIcon, PlugIcon } from "./util.jsx";

export default {
  id: "insurance",
  title: "Insurance card & coverage",
  group: "Money",
  order: 51,
  routes: [
    { path: "/insurance", element: <Insurance />, roles: ["patient"] },
    { path: "/insurance/front-desk", element: <FrontDesk />, roles: ["staff", "admin"] },
    { path: "/insurance/claims", element: <Claims />, roles: ["staff", "admin"] },
    { path: "/insurance/connections", element: <Connections />, roles: ["admin"] },
  ],
  nav: [
    { to: "/insurance", label: "Insurance card & coverage", description: "Your digital card, benefits and plan approvals",
      roles: ["patient"], placement: "hub" },
    { to: "/insurance/front-desk", label: "Coverage & cards", description: "Verify cards, check eligibility, prior auths",
      roles: ["staff", "admin"], placement: "workspace", icon: CardIcon, group: "Insurance" },
    { to: "/insurance/claims", label: "Insurance claims", description: "837P claims, acknowledgments and remittances",
      roles: ["staff", "admin"], placement: "workspace", icon: ClaimIcon, group: "Insurance" },
    { to: "/insurance/connections", label: "Payer connections", description: "Connect payers and test connections",
      roles: ["admin"], placement: "workspace", icon: PlugIcon, group: "Insurance" },
  ],
};
