import { useState } from "react";
import { useApi } from "../../hooks.js";
import ConsultProfileCard from "./ConsultProfileCard.jsx";
import SlotPreview from "./SlotPreview.jsx";
import TimeOff from "./TimeOff.jsx";
import WeeklyHours from "./WeeklyHours.jsx";
import { ErrorBox } from "./shared.jsx";

// Everything about one clinician's availability. `base` is "/clinician" for the signed-in clinician, or
// "/admin/practitioners/<id>" for an administrator or the front desk; the API shapes are the same.
export default function AvailabilityEditor({ base, isSelf = false }) {
  const { data, error, loading, reload } = useApi(`${base}/availability`);
  const [version, setVersion] = useState(0);
  const changed = () => { reload(); setVersion((v) => v + 1); };

  if (error) return <ErrorBox error={error} />;
  if (loading && !data) return <div className="card"><div className="skeleton" /></div>;
  if (!data) return null;

  const u = data.upcoming;
  return (
    <div className="stack av-editor">
      <div className="av-stats" aria-label="Upcoming">
        <div className="av-stat"><span className="n">{u.free}</span><span className="tiny muted">free slots ahead</span></div>
        <div className="av-stat"><span className="n">{u.booked}</span><span className="tiny muted">booked visits ahead</span></div>
        <div className="av-stat"><span className="n">{data.windows.length}</span><span className="tiny muted">weekly windows</span></div>
        <div className="av-stat"><span className="n">{data.time_off.length}</span><span className="tiny muted">time off planned</span></div>
      </div>
      <div className="av-layout">
        <div className="stack av-main">
          <WeeklyHours data={data} base={base} onSaved={changed} />
          <SlotPreview base={base} version={version} />
        </div>
        <div className="stack av-side">
          <TimeOff data={data} base={base} onChanged={changed} />
          <ConsultProfileCard base={base} windows={data.windows} isSelf={isSelf} />
        </div>
      </div>
    </div>
  );
}
