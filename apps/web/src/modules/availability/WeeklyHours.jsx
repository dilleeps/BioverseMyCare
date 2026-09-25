import { useEffect, useMemo, useState } from "react";
import { api } from "../../api.js";
import { Plus } from "../../icons.jsx";
import {
  ErrorBox, MODE_LABELS, SLOT_LENGTHS, TrashIcon, WEEKDAYS, WEEKDAY_SHORT, slotsIn, timeZones, toMinutes,
} from "./shared.jsx";

let seq = 0;
const key = () => `w${++seq}`;

function fromServer(data) {
  return {
    timezone: data.timezone,
    horizon_days: data.horizon_days,
    windows: data.windows.map((w) => ({ ...w, key: key(), effective_from: w.effective_from || "", effective_until: w.effective_until || "" })),
  };
}

function toServer(draft) {
  return {
    timezone: draft.timezone,
    horizon_days: Number(draft.horizon_days),
    windows: draft.windows.map((w) => ({
      weekday: w.weekday, start: w.start, end: w.end, mode: w.mode, location: w.location || null,
      slot_minutes: Number(w.slot_minutes), effective_from: w.effective_from || null, effective_until: w.effective_until || null,
    })),
  };
}

function rangesOverlap(a, b) {
  const lo = [a.effective_from, b.effective_from].filter(Boolean).sort().pop() || "0000-01-01";
  const hi = [a.effective_until, b.effective_until].filter(Boolean).sort()[0] || "9999-12-31";
  return lo <= hi;
}

// Problems the server would reject, shown next to the window before saving.
function problemsOf(windows) {
  const out = {};
  windows.forEach((w) => {
    if (!w.start || !w.end) out[w.key] = "Set a start and an end time";
    else if (toMinutes(w.end) <= toMinutes(w.start)) out[w.key] = "The end time must be after the start time";
    else if (slotsIn(w) < 1) out[w.key] = `Shorter than one ${w.slot_minutes}-minute slot`;
    else if (w.effective_from && w.effective_until && w.effective_until < w.effective_from) out[w.key] = "The end date is before the start date";
  });
  windows.forEach((a, i) => windows.slice(i + 1).forEach((b) => {
    if (a.weekday === b.weekday && !out[a.key] && !out[b.key] && toMinutes(a.start) < toMinutes(b.end)
        && toMinutes(b.start) < toMinutes(a.end) && rangesOverlap(a, b)) {
      out[b.key] = `Overlaps ${a.start}–${a.end}`;
    }
  }));
  return out;
}

function WindowRow({ w, problem, onChange, onRemove, defaultLocation }) {
  const [dates, setDates] = useState(Boolean(w.effective_from || w.effective_until));
  const set = (k) => (e) => onChange({ ...w, [k]: e.target.value });
  const id = `win-${w.key}`;
  const day = WEEKDAYS[w.weekday];
  return (
    <div className={`av-window${problem ? " invalid" : ""}`}>
      <div className="av-window-fields">
        <label className="av-f av-time"><span className="tiny muted">From</span>
          <input type="time" step="300" value={w.start} onChange={set("start")} aria-label={`${day} start time`} required /></label>
        <label className="av-f av-time"><span className="tiny muted">To</span>
          <input type="time" step="300" value={w.end} onChange={set("end")} aria-label={`${day} end time`} required /></label>
        <label className="av-f"><span className="tiny muted">Visit type</span>
          <select value={w.mode} onChange={set("mode")} aria-label={`${day} visit type`}>
            {Object.entries(MODE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select></label>
        <label className="av-f av-grow"><span className="tiny muted">Location</span>
          <input value={w.location || ""} onChange={set("location")} maxLength={120}
                 placeholder={w.mode === "video" ? "Video visit" : defaultLocation} aria-label={`${day} location`} /></label>
        <label className="av-f"><span className="tiny muted">Slot length</span>
          <select value={w.slot_minutes} onChange={(e) => onChange({ ...w, slot_minutes: Number(e.target.value) })}
                  aria-label={`${day} slot length`}>
            {SLOT_LENGTHS.map((m) => <option key={m} value={m}>{m} min</option>)}
          </select></label>
        <button type="button" className="icon-btn av-remove" onClick={onRemove} aria-label={`Remove ${day} ${w.start}–${w.end}`}>
          <TrashIcon />
        </button>
      </div>
      <div className="row wrap av-window-foot">
        <span className="tiny muted">{slotsIn(w)} slot{slotsIn(w) === 1 ? "" : "s"}</span>
        {!dates && (
          <button type="button" className="av-link tiny" onClick={() => setDates(true)} aria-controls={`${id}-dates`}>
            Only between certain dates…
          </button>
        )}
        {dates && (
          <div className="row wrap av-dates" id={`${id}-dates`}>
            <label className="av-f"><span className="tiny muted">Starting</span>
              <input type="date" value={w.effective_from} onChange={set("effective_from")} aria-label={`${day} effective from`} /></label>
            <label className="av-f"><span className="tiny muted">Until</span>
              <input type="date" value={w.effective_until} onChange={set("effective_until")} aria-label={`${day} effective until`} /></label>
            <button type="button" className="av-link tiny"
                    onClick={() => { setDates(false); onChange({ ...w, effective_from: "", effective_until: "" }); }}>
              Every week
            </button>
          </div>
        )}
        {problem && <span className="tiny av-problem" role="alert">{problem}</span>}
      </div>
    </div>
  );
}

// The weekly template: windows per weekday, the time zone they're written in, and how far ahead slots open.
export default function WeeklyHours({ data, base, onSaved }) {
  const [draft, setDraft] = useState(() => fromServer(data));
  const [saved, setSaved] = useState(() => JSON.stringify(toServer(fromServer(data))));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [note, setNote] = useState(null);

  useEffect(() => {
    const next = fromServer(data);
    setDraft(next);
    setSaved(JSON.stringify(toServer(next)));
  }, [data]);

  const problems = useMemo(() => problemsOf(draft.windows), [draft.windows]);
  const dirty = JSON.stringify(toServer(draft)) !== saved;
  const zones = useMemo(() => timeZones(draft.timezone), [draft.timezone]);
  const defaultLocation = data.practitioner.location_name;

  const update = (w) => setDraft((d) => ({ ...d, windows: d.windows.map((x) => (x.key === w.key ? w : x)) }));
  const remove = (k) => setDraft((d) => ({ ...d, windows: d.windows.filter((x) => x.key !== k) }));
  function add(weekday) {
    setDraft((d) => {
      const same = d.windows.filter((w) => w.weekday === weekday).sort((a, b) => toMinutes(a.end) - toMinutes(b.end));
      const last = same[same.length - 1];
      const start = last ? last.end : "09:00";
      const endMin = Math.min(toMinutes(start) + 180, 23 * 60 + 55);
      const end = `${String(Math.floor(endMin / 60)).padStart(2, "0")}:${String(endMin % 60).padStart(2, "0")}`;
      return { ...d, windows: [...d.windows, {
        key: key(), weekday, start, end, mode: last?.mode || "in_person", location: last?.location || "",
        slot_minutes: last?.slot_minutes || 20, effective_from: "", effective_until: "",
      }] };
    });
  }
  function copyToWeekdays(weekday) {
    setDraft((d) => {
      const source = d.windows.filter((w) => w.weekday === weekday);
      const targets = [0, 1, 2, 3, 4].filter((x) => x !== weekday);
      const kept = d.windows.filter((w) => !targets.includes(w.weekday));
      const copies = targets.flatMap((t) => source.map((w) => ({ ...w, key: key(), weekday: t })));
      return { ...d, windows: [...kept, ...copies] };
    });
  }

  async function save() {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const res = await api(`${base}/availability`, { method: "PUT", body: toServer(draft) });
      const s = res.sync;
      const parts = [];
      if (s.created) parts.push(`${s.created} slot${s.created === 1 ? "" : "s"} opened`);
      if (s.removed) parts.push(`${s.removed} free slot${s.removed === 1 ? "" : "s"} withdrawn`);
      if (s.updated) parts.push(`${s.updated} updated`);
      setNote(`Saved. ${parts.length ? parts.join(", ") + "." : "Your calendar already matched."} Booked appointments are never changed.`);
      onSaved(res);
    } catch (ex) {
      setError(ex);
    }
    setBusy(false);
  }

  const hasProblems = Object.keys(problems).length > 0;
  const weekly = draft.windows.reduce((n, w) => n + slotsIn(w), 0);

  return (
    <section className="card stack" aria-labelledby="av-week-title">
      <div className="row between wrap">
        <div>
          <h2 id="av-week-title" className="card-title">Weekly hours</h2>
          <p className="small muted">When patients can book you. Slots open {draft.horizon_days} days ahead and roll forward every day.</p>
        </div>
        <span className="chip">{weekly} slot{weekly === 1 ? "" : "s"} a week</span>
      </div>

      <div className="row wrap av-settings">
        <label className="av-f av-zone"><span className="tiny muted">Time zone</span>
          <select value={draft.timezone} onChange={(e) => setDraft({ ...draft, timezone: e.target.value })}>
            {zones.map((z) => <option key={z} value={z}>{z.replace(/_/g, " ")}</option>)}
          </select></label>
        <label className="av-f"><span className="tiny muted">Open slots ahead</span>
          <select value={draft.horizon_days} onChange={(e) => setDraft({ ...draft, horizon_days: Number(e.target.value) })}>
            {[7, 14, 21, 28, 42, 56, 90].map((d) => <option key={d} value={d}>{d} days</option>)}
          </select></label>
        {data.timezone_is_default && <span className="tiny muted">Using the clinic's time zone until you save.</span>}
      </div>

      <div className="av-week" role="list">
        {WEEKDAYS.map((day, i) => {
          const mine = draft.windows.filter((w) => w.weekday === i).sort((a, b) => toMinutes(a.start) - toMinutes(b.start));
          return (
            <div key={day} className={`av-day${mine.length ? "" : " off"}`} role="listitem" aria-label={day}>
              <div className="av-day-head">
                <span className="strong"><span className="av-day-long">{day}</span><span className="av-day-short">{WEEKDAY_SHORT[i]}</span></span>
                {!mine.length && <span className="tiny muted">Not working</span>}
              </div>
              <div className="stack av-day-body">
                {mine.map((w) => (
                  <WindowRow key={w.key} w={w} problem={problems[w.key]} defaultLocation={defaultLocation}
                             onChange={update} onRemove={() => remove(w.key)} />
                ))}
                <div className="row wrap">
                  <button type="button" className="btn sm" onClick={() => add(i)}><Plus size={14} /> Add hours</button>
                  {mine.length > 0 && i < 5 && (
                    <button type="button" className="btn sm ghost" onClick={() => copyToWeekdays(i)}>Copy to Mon–Fri</button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <ErrorBox error={error} />
      {note && !dirty && <div className="banner ok small" role="status">{note}</div>}
      <div className={`av-savebar${dirty ? " dirty" : ""}`}>
        <span className="small muted">{dirty ? "You have unsaved changes." : "All changes saved."}</span>
        <div className="row">
          {dirty && <button type="button" className="btn sm ghost" onClick={() => setDraft(fromServer(data))}>Discard</button>}
          <button type="button" className="btn primary" onClick={save} disabled={!dirty || busy || hasProblems}>
            {busy ? "Saving…" : "Save hours"}
          </button>
        </div>
      </div>
    </section>
  );
}
