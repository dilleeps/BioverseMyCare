// Pieces shared by the patient, clinician and admin screens for public specialist agents.
import { Lock } from "../../icons.jsx";

export const STATUS = {
  draft: { label: "Draft", cls: "" },
  pending_approval: { label: "Waiting for approval", cls: "warn" },
  approved: { label: "Approved", cls: "ok" },
  rejected: { label: "Sent back", cls: "warn" },
};

export const KIND = {
  answer: { label: "Answered", cls: "ok" },
  no_answer: { label: "No answer", cls: "" },
  out_of_scope: { label: "Out of scope", cls: "" },
  personal: { label: "Personal advice refused", cls: "" },
  emergency: { label: "Emergency guidance", cls: "warn" },
};

export const TONES = [
  { id: "warm", label: "Warm", hint: "Friendly and reassuring" },
  { id: "direct", label: "Direct", hint: "Short and to the point" },
  { id: "formal", label: "Formal", hint: "Measured, clinical wording" },
];

export function Disclosure({ text, sticky = false }) {
  return (
    <div className={`sp-disclosure ${sticky ? "sticky" : ""}`} role="note">
      <Lock size={15} />
      <span>{text}</span>
    </div>
  );
}

export function ExternalLink({ href, children, className }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
      {children}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

export function CitationList({ citations }) {
  if (!citations?.length) return null;
  return (
    <ol className="sp-cites">
      {citations.map((c) => (
        <li key={`${c.n}-${c.item_id}`}>
          <ExternalLink href={c.url} className="strong">{c.title}</ExternalLink>
          <span className="muted"> · {c.source}, {c.year}</span>
        </li>
      ))}
    </ol>
  );
}

export function initialsOf(name) {
  return name.replace(/^Dr\.?\s+/, "").split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
}
