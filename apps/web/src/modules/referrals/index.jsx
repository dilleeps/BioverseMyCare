import "./styles.css";
import { Link } from "react-router-dom";
import { useSession } from "../../session.jsx";
import Referrals from "./Referrals.jsx";
import ReferralManager, { ReferralList } from "./ReferralManager.jsx";

const ReferralIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 12h12" />
    <path d="M12 6l6 6-6 6" />
    <path d="M20 5v14" />
  </svg>
);

// Shown in the clinician's patient view, under the pre-visit brief.
function PatientReferralsPanel({ patientId }) {
  const { me } = useSession();
  return (
    <div className="stack" style={{ gap: 8 }}>
      <ReferralList path={`/referrals?view=patient&patient_id=${patientId}`} me={me} showPatient={false}
                    empty="No referrals for this patient." />
      <Link className="small" to="/clinician/referrals">Open the referral manager</Link>
    </div>
  );
}

export default {
  id: "referrals",
  title: "Referrals",
  group: "Care",
  order: 21,
  routes: [
    { path: "/referrals", element: <Referrals />, roles: ["patient"] },
    { path: "/clinician/referrals", element: <ReferralManager />, roles: ["clinician", "staff", "admin"] },
  ],
  nav: [
    {
      to: "/referrals",
      label: "Referrals",
      description: "Where each referral is and what to do next",
      roles: ["patient"],
      placement: "hub",
    },
    {
      to: "/clinician/referrals",
      label: "Referrals",
      description: "Create, send and track referrals; see what is stuck",
      roles: ["clinician", "staff", "admin"],
      placement: "workspace",
      icon: ReferralIcon,
    },
  ],
  workspacePanels: [{ id: "referrals", title: "Referrals", order: 40, component: PatientReferralsPanel }],
};
