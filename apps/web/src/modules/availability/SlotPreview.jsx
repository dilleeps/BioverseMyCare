import { useMemo, useState } from "react";
import { useApi } from "../../hooks.js";
import { ErrorBox, addDays, fmtDay } from "./shared.jsx";

const SHOW = 10;

function Day({ day, slots, off, today }) {
  const [all, setAll] = useState(false);
  const free = slots.filter((s) => s.status === "free").length;
  const booked = slots.length - free;
  const shown = all ? slots : slots.slice(0, SHOW);
  return (
    <div className={`av-pday${off ? " off" : ""}${day === today ? " today" : ""}`} role="listitem"
         aria-label={`${fmtDay(day, { weekday: "long", day: "numeric", month: "long" })}: ${off ? "time off" : `${free} free, ${booked} booked`}`}>
      <div className="av-pday-head">
        <span className="strong small">{fmtDay(day)}</span>
        {day === today && <span className="chip av-chip-today">Today</span>}
      </div>
      {off && <span className="tiny av-offtag">Time off{off.reason ? ` · ${off.reason}` : ""}</span>}
      {!off && slots.length === 0 && <span className="tiny muted">No slots</span>}
      {slots.length > 0 && <span className="tiny muted">{free} free · {booked} booked</span>}
      <div className="av-slots">
        {shown.map((s) => (
          <span key={s.id || s.starts_at}
                className={`av-slot ${s.status}${s.pending ? " pending" : ""}${s.source === "manual" ? " manual" : ""}`}
                title={[
                  `${s.local_time} · ${s.duration_min} min · ${s.mode === "video" ? "Video" : "In person"}`,
                  s.location, s.status === "booked" ? `Booked${s.patient_name ? `: ${s.patient_name}` : ""}` : "Free",
                  s.pending ? "Opens when hours are applied" : null, s.source === "manual" ? "Added outside your weekly hours" : null,
                ].filter(Boolean).join("\n")}>
            {s.local_time}
            {s.mode === "video" && <span className="av-slot-mode" aria-label="video">·v</span>}
            {s.status === "booked" && s.patient_name && <span className="av-slot-who">{s.patient_name.split(" ")[0]}</span>}
          </span>
        ))}
      </div>
      {slots.length > SHOW && (
        <button type="button" className="av-link tiny" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `+${slots.length - SHOW} more`}
        </button>
      )}
    </div>
  );
}

// The next two weeks as patients will see them: free and booked slots, and days off.
export default function SlotPreview({ base, version, days = 14 }) {
  const { data, error, loading } = useApi(`${base}/availability/preview?days=${days}&v=${version}`);

  const byDay = useMemo(() => {
    if (!data) return [];
    const out = [];
    for (let i = 0; i < days; i += 1) {
      const d = addDays(data.from, i);
      if (d > data.until) break;
      out.push({
        day: d,
        slots: data.slots.filter((s) => s.local_date === d),
        off: data.days_off.find((t) => t.starts_on <= d && d <= t.ends_on) || null,
      });
    }
    return out;
  }, [data, days]);

  return (
    <section className="card stack" aria-labelledby="av-prev-title">
      <div className="row between wrap">
        <div>
          <h2 id="av-prev-title" className="card-title">Next two weeks</h2>
          <p className="small muted">
            What patients can book{data ? ` (times in ${data.timezone.replace(/_/g, " ")})` : ""}.
          </p>
        </div>
        {data && (
          <div className="row wrap" style={{ gap: 6 }}>
            <span className="chip ok">{data.summary.free} free</span>
            <span className="chip solid">{data.summary.booked} booked</span>
            {data.summary.pending > 0 && <span className="chip">{data.summary.pending} opening soon</span>}
          </div>
        )}
      </div>
      <div className="row wrap av-legend tiny muted" aria-hidden="true">
        <span><i className="av-slot free" /> Free</span>
        <span><i className="av-slot booked" /> Booked</span>
        <span><i className="av-slot free pending" /> Opening soon (next hourly update)</span>
        <span><i className="av-slot free manual" /> Added outside weekly hours</span>
      </div>
      <ErrorBox error={error} />
      {loading && !data && <div className="skeleton" />}
      {data && (
        <div className="av-preview" role="list">
          {byDay.map((d) => <Day key={d.day} today={data.from} {...d} />)}
        </div>
      )}
    </section>
  );
}
