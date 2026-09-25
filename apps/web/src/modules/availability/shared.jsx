// Shared bits for the availability module.

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const CONSULT_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
export const SLOT_LENGTHS = [5, 10, 15, 20, 25, 30, 40, 45, 60, 90, 120];
export const MODE_LABELS = { in_person: "In person", video: "Video" };
export const CONSULT_MODE_LABELS = { message: "Secure message", video: "Video", phone: "Phone" };

const COMMON_ZONES = [
  "America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles",
  "America/Anchorage", "Pacific/Honolulu", "America/Puerto_Rico", "Europe/London", "Europe/Berlin", "Asia/Kolkata",
];

export function timeZones(current) {
  let all = [];
  try {
    all = Intl.supportedValuesOf ? Intl.supportedValuesOf("timeZone") : [];
  } catch {
    all = [];
  }
  const list = all.length ? all : COMMON_ZONES;
  return current && !list.includes(current) ? [current, ...list] : list;
}

export const ClockIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
  </svg>
);

export const TeamClockIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="4" width="18" height="17" rx="2" /><path d="M8 2v4M16 2v4M3 9h18" /><path d="M12 13v3l2 1" />
  </svg>
);

export const TrashIcon = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" />
  </svg>
);

// "2026-10-05" -> "Mon 5 Oct", read as a calendar day (never shifted by the browser's time zone).
export function fmtDay(iso, opts = { weekday: "short", day: "numeric", month: "short" }) {
  if (!iso) return "";
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString([], opts);
}

export function addDays(iso, n) {
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  const dt = new Date(y, m - 1, d + n);
  const pad = (v) => String(v).padStart(2, "0");
  return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}`;
}

export function toMinutes(hhmm) {
  const [h, m] = String(hhmm || "0:0").split(":").map(Number);
  return h * 60 + m;
}

export function slotsIn(w) {
  const span = toMinutes(w.end) - toMinutes(w.start);
  return w.slot_minutes > 0 && span > 0 ? Math.floor(span / w.slot_minutes) : 0;
}

export function dollars(cents) {
  return (Number(cents || 0) / 100).toLocaleString([], { style: "currency", currency: "USD", maximumFractionDigits: 2 });
}

export function ErrorBox({ error }) {
  if (!error) return null;
  return <div className="error-box small" role="alert">{typeof error === "string" ? error : error.message}</div>;
}
