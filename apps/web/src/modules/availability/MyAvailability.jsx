import { useEffect } from "react";
import { WorkspaceLayout } from "../../layouts.jsx";
import AvailabilityEditor from "./AvailabilityEditor.jsx";

// Clinicians: their own weekly hours, time off, upcoming slots and online consult profile.
export default function MyAvailability() {
  useEffect(() => { document.title = "My availability · Bioverse"; }, []);
  return (
    <WorkspaceLayout>
      <div className="av-page">
        <div className="page-head">
          <div>
            <h1 className="page-title">My availability</h1>
            <p className="page-sub">Set the hours patients can book you, plan time off, and choose how you consult online.</p>
          </div>
        </div>
        <AvailabilityEditor base="/clinician" isSelf />
      </div>
    </WorkspaceLayout>
  );
}
