// Calendar days ("2026-09-24") are local days, and dose times ("2026-09-24T20:00") are wall-clock times on the
// patient's clock. Neither is an instant, so parse them by hand rather than with new Date(string).

export function localDay(iso) {
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}

export const longDay = (iso) => localDay(iso).toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
export const shortDay = (iso) => localDay(iso).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
export const weekdayLetter = (iso) => localDay(iso).toLocaleDateString([], { weekday: "narrow" });

// "20:00" -> "8:00 PM"
export function clock(hhmm) {
  const [h, m] = String(hhmm).split(":").map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

export function greeting(date = new Date()) {
  const h = date.getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export const pct = (v) => (v == null ? "—" : `${v}%`);
