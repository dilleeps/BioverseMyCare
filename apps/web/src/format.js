export function fmtDateTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (sameDay) return `Today · ${time}`;
  const date = d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
  return `${date} · ${time}`;
}

export function fmtDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
}

export function fmtShortDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString([], { day: "numeric", month: "short" });
}

export function fmtMonthYear(iso) {
  return new Date(iso).toLocaleDateString([], { month: "short", year: "numeric" });
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
