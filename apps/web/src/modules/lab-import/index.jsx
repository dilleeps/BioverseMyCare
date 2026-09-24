import "./styles.css";
import LabImport from "./LabImport.jsx";

function FlaskIcon({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9 3h6" /><path d="M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3" /><path d="M7 15h10" />
    </svg>
  );
}

export default {
  id: "lab-import",
  title: "Lab import",
  group: "Interoperability",
  order: 85,
  routes: [{ path: "/admin/lab-import", element: <LabImport />, roles: ["admin"] }],
  nav: [
    {
      to: "/admin/lab-import",
      label: "Lab import",
      description: "Import HL7 v2 lab results and review the import log",
      roles: ["admin"],
      placement: "workspace",
      icon: FlaskIcon,
    },
  ],
};
