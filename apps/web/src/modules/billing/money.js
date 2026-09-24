// Money is integer cents everywhere. Floats never touch an amount.

export function fmtMoney(cents) {
  if (cents == null) return "";
  const n = Number(cents);
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  const dollars = Math.floor(abs / 100).toLocaleString("en-US");
  const rest = String(abs % 100).padStart(2, "0");
  return `${sign}$${dollars}.${rest}`;
}

// "25", "25.5", "25.50", "$1,025.50" -> cents. Returns null when the text isn't a valid amount.
export function parseDollars(text) {
  const clean = String(text || "").trim().replace(/^\$/, "").replace(/,/g, "");
  const m = /^(\d{1,7})(?:\.(\d{1,2}))?$/.exec(clean);
  if (!m) return null;
  return Number(m[1]) * 100 + Number((m[2] || "").padEnd(2, "0"));
}

export function centsToInput(cents) {
  return `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, "0")}`;
}

// Date-only values ("2026-10-23") are calendar days, not instants: parse them as local dates so they
// don't shift a day in time zones west of UTC.
export function fmtDay(value, opts = { day: "numeric", month: "short", year: "numeric" }) {
  if (!value) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value));
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(value);
  return d.toLocaleDateString([], opts);
}

export const fmtShortDay = (value) => fmtDay(value, { day: "numeric", month: "short" });

export const CLAIM_STATUS = {
  submitted: { label: "Submitted", tone: "" },
  in_review: { label: "In review", tone: "" },
  paid: { label: "Processed", tone: "ok" },
  denied: { label: "Denied", tone: "warn" },
  appealed: { label: "Appeal sent", tone: "" },
};
