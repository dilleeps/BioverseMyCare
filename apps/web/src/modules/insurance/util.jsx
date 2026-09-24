// Shared bits for the insurance screens: money and dates, status chips, icons, loading and errors.

export function fmtMoney(cents) {
  if (cents == null) return "";
  const n = Number(cents);
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  const dollars = Math.floor(abs / 100).toLocaleString("en-US");
  const rest = abs % 100;
  return rest ? `${sign}$${dollars}.${String(rest).padStart(2, "0")}` : `${sign}$${dollars}`;
}

// Calendar days ("2026-10-23") parse as local dates so they don't shift west of UTC.
export function fmtDay(value, opts = { day: "numeric", month: "short", year: "numeric" }) {
  if (!value) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value));
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(value);
  return d.toLocaleDateString([], opts);
}

export function fmtWhen(value) {
  if (!value) return "";
  return new Date(value).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

export function errorList(e) {
  const errs = e?.detail?.errors;
  return Array.isArray(errs) && errs.length ? errs : [e?.message || "Something went wrong."];
}

export function ErrorBox({ error }) {
  if (!error) return null;
  const list = Array.isArray(error) ? error : errorList(error);
  return (
    <div className="error-box small" role="alert">
      {list.length === 1 ? list[0] : <ul className="ins-errors">{list.map((m) => <li key={m}>{m}</li>)}</ul>}
    </div>
  );
}

export function Loading({ label = "Loading" }) {
  return <div className="card" aria-busy="true"><div className="skeleton" /><span className="sr-only">{label}</span></div>;
}

const CHECK = {
  active: ["ok", "Active"],
  inactive: ["warn", "Not active"],
  not_found: ["warn", "Member not found"],
  error: ["warn", "Couldn't check"],
  no_coverage: ["warn", "No coverage"],
};
export function CheckChip({ status }) {
  if (!status) return <span className="chip">Not checked</span>;
  const [tone, label] = CHECK[status] || ["", status];
  return <span className={`chip ${tone}`}>{label}</span>;
}

const SUB = {
  sent: ["", "Sent"],
  accepted: ["", "Accepted (277CA)"],
  rejected: ["warn", "Rejected (277CA)"],
  paid: ["ok", "Paid (835)"],
  denied: ["warn", "Denied (835)"],
};
export function SubmissionChip({ status }) {
  const [tone, label] = SUB[status] || ["", status];
  return <span className={`chip ${tone}`}>{label}</span>;
}

const PA = {
  submitted: ["", "Submitted"],
  pended: ["", "Pending with the plan"],
  approved: ["ok", "Approved"],
  denied: ["warn", "Denied"],
};
export function PriorAuthChip({ status }) {
  const [tone, label] = PA[status] || ["", status];
  return <span className={`chip ${tone}`}>{label}</span>;
}

function Svg({ size = 18, children }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

export const CardIcon = (p) => (
  <Svg {...p}><rect x="2.5" y="5" width="19" height="14" rx="2.5" /><path d="M2.5 10h19M6.5 15h4" /></Svg>
);
export const ClaimIcon = (p) => (
  <Svg {...p}><path d="M7 3h7l4 4v14H7z" /><path d="M14 3v4h4M10 12h5M10 16h5" /></Svg>
);
export const PlugIcon = (p) => (
  <Svg {...p}><path d="M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4" /></Svg>
);
export const ScanIcon = (p) => (
  <Svg {...p}><path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M4 12h16" /></Svg>
);

export function Meter({ label, used, total }) {
  if (total == null || used == null) return null;
  const pct = total > 0 ? Math.min(100, Math.round((100 * used) / total)) : 0;
  const id = `ins-meter-${label.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="row between small wrap">
        <span id={id} className="strong">{label}</span>
        <span className="muted">{fmtMoney(used)} of {fmtMoney(total)}</span>
      </div>
      <div className="progress" role="progressbar" aria-labelledby={id} aria-valuemin={0} aria-valuemax={100}
           aria-valuenow={pct} aria-valuetext={`${fmtMoney(used)} of ${fmtMoney(total)} met`}>
        <div style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
