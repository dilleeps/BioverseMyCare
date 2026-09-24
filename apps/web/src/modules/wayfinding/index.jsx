import "./styles.css";
import FindYourWay from "./FindYourWay.jsx";
import WayfindingAdmin from "./Admin.jsx";
import SignSheet from "./SignSheet.jsx";

const SignpostIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3v18" /><path d="M5 6h11l3 2.5L16 11H5z" /><path d="M19 14H8l-3 2.5L8 19h11z" />
  </svg>
);

export default {
  id: "wayfinding",
  title: "Find your way",
  group: "Care",
  order: 22,
  routes: [
    // Any signed-in role: QR signs around the building open /find-your-way?from=<code>.
    { path: "/find-your-way", element: <FindYourWay /> },
    { path: "/wayfinding/admin", element: <WayfindingAdmin />, roles: ["staff", "admin", "clinician"] },
    { path: "/wayfinding/signs", element: <SignSheet />, roles: ["staff", "admin", "clinician"] },
  ],
  nav: [
    {
      to: "/find-your-way",
      label: "Find your way in the hospital",
      description: "Step-by-step directions and floor maps, step-free if you need",
      roles: ["patient"],
      placement: "hub",
    },
    {
      to: "/wayfinding/admin",
      label: "Wayfinding",
      description: "Floor plans, closures and “You are here” signs",
      roles: ["staff", "admin"],
      placement: "workspace",
      icon: SignpostIcon,
      group: "Operations",
    },
  ],
};
