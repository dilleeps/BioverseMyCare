// A bare "YYYY-MM-DD" (a due date, a birth date) is a calendar day, not an instant. new Date() would read it
// as UTC midnight, which is the previous day west of Greenwich. Parse those as local days.
function toDate(value) {
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split("-").map(Number);
    return new Date(y, m - 1, d);
  }
  return new Date(value);
}

export function fmtDateTime(iso) {
  if (!iso) return "";
  const d = toDate(iso);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (sameDay) return `Today · ${time}`;
  const date = d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
  return `${date} · ${time}`;
}

export function fmtDate(iso) {
  if (!iso) return "";
  return toDate(iso).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
}

export function fmtShortDate(iso) {
  if (!iso) return "";
  return toDate(iso).toLocaleDateString([], { day: "numeric", month: "short" });
}

export function fmtMonthYear(iso) {
  return toDate(iso).toLocaleDateString([], { month: "short", year: "numeric" });
}

export function fmtNumber(n) {
  const v = Number(n);
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

export function initials(name) {
  return name
    .replace(/^Dr\.?\s+/, "")
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}
