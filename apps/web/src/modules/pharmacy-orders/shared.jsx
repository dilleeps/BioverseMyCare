// Shared pieces for online pharmacy ordering: money, statuses, safety findings and the order progress rail.
import { Check, Warning } from "../../icons.jsx";

export function money(cents) {
  const v = Number(cents || 0);
  return `$${Math.floor(v / 100).toLocaleString()}.${String(v % 100).padStart(2, "0")}`;
}

export function fmtTime(iso) {
  return iso ? new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
}

export function fmtWhen(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const today = new Date();
  const tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  const day = d.toDateString() === today.toDateString() ? "Today"
    : d.toDateString() === tomorrow.toDateString() ? "Tomorrow"
      : d.toDateString() === yesterday.toDateString() ? "Yesterday"
        : d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
  return `${day}, ${fmtTime(iso)}`;
}

const TONE = {
  placed: "", pharmacist_review: "warn", approved: "ok", rejected: "warn", packed: "ok",
  out_for_delivery: "ok", delivered: "ok", ready_for_pickup: "ok", picked_up: "ok", cancelled: "",
};

export function StatusChip({ status, label }) {
  return <span className={`chip ${TONE[status] ?? ""}`}>{label}</span>;
}

const SEVERITY = {
  block: { label: "Can't order", cls: "block" },
  high: { label: "Important", cls: "high" },
  moderate: { label: "Caution", cls: "moderate" },
  info: { label: "Good to know", cls: "info" },
};

// Safety findings from the checks. `only` limits to findings that mention one of these line keys.
export function Findings({ findings, only, compact = false, showReview = true }) {
  const list = (findings || []).filter((f) => !only || f.lines.some((k) => only.includes(k)));
  if (list.length === 0) return null;
  return (
    <ul className={`po-findings ${compact ? "compact" : ""}`} aria-label="Safety checks">
      {list.map((f, i) => {
        const s = SEVERITY[f.severity];
        return (
          <li key={`${f.code}-${i}`} className={`po-finding ${s.cls}`}>
            <div className="row between wrap" style={{ gap: 6 }}>
              <span className="strong small row" style={{ gap: 6 }}>
                {f.severity === "info" ? <Check size={14} /> : <Warning size={14} />} {f.title}
              </span>
              <span className="tiny strong po-sev">{s.label}</span>
            </div>
            {!compact && <p className="small">{f.message}</p>}
            {showReview && f.review && !compact && <p className="tiny muted">A pharmacist will review this before your order is packed.</p>}
          </li>
        );
      })}
    </ul>
  );
}

// The order's path, with times for the steps reached.
export function OrderProgress({ progress }) {
  return (
    <ol className="po-progress" aria-label="Order progress">
      {progress.map((p) => (
        <li key={p.status} className={`${p.state} ${p.status === "rejected" || p.status === "cancelled" ? "stopped" : ""}`}
            aria-current={p.state === "current" ? "step" : undefined}>
          <span className="po-dot" aria-hidden="true">{p.state === "done" ? <Check size={12} /> : null}</span>
          <span className="po-step">
            <span className="strong small">{p.label}</span>
            {p.at && <span className="tiny muted">{fmtWhen(p.at)}</span>}
            {!p.at && p.state === "upcoming" && <span className="tiny muted">Not yet</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}

export function Address({ a }) {
  if (!a) return null;
  return (
    <address className="po-address small">
      <span className="strong">{a.recipient_name}</span><br />
      {a.line1}{a.line2 ? `, ${a.line2}` : ""}<br />
      {a.city}, {a.state} {a.postal_code}
      {a.instructions && <><br /><span className="muted">{a.instructions}</span></>}
    </address>
  );
}

export function ProofText({ proof }) {
  if (!proof) return null;
  const at = proof.at ? fmtWhen(proof.at) : "";
  if (proof.type === "left_at_door") return <>Left at the door{at ? `, ${at}` : ""}.{proof.simulated ? " (Simulated delivery.)" : ""}</>;
  if (proof.type === "pickup") return <>Collected by {proof.recipient_name}{at ? `, ${at}` : ""}.</>;
  return <>Handed to {proof.recipient_name}{at ? `, ${at}` : ""}.{proof.simulated ? " (Simulated delivery.)" : ""}</>;
}
