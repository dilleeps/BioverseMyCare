// Date-only values ("2026-10-23") are calendar days: parse them as local dates so they don't shift
// a day in time zones west of UTC. Timestamps fall through to the normal parser.
function toDate(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value));
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(value);
}

export function fmtDay(value) {
  return value ? toDate(value).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" }) : "";
}

export function fmtShortDay(value) {
  return value ? toDate(value).toLocaleDateString([], { day: "numeric", month: "short" }) : "";
}

export function fmtWeekday(value) {
  return value ? toDate(value).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" }) : "";
}

export const FILL_STEPS = [
  { key: "sent", label: "Sent" },
  { key: "received", label: "Filling" },
  { key: "ready", label: "Ready" },
  { key: "picked_up", label: "Picked up" },
];
