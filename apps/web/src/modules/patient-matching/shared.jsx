// Small pieces shared by the review queue and the record search.

export const LEVELS = {
  certain: { label: "Certain match", tone: "certain" },
  probable: { label: "Probable duplicate", tone: "probable" },
  possible: { label: "Possible duplicate", tone: "possible" },
  none: { label: "Weak match", tone: "none" },
  // Search results: how well a record fits what was searched for.
  identifier: { label: "Identifier match", tone: "certain" },
  strong: { label: "Strong match", tone: "probable" },
  partial: { label: "Partial match", tone: "possible" },
  weak: { label: "Weak match", tone: "none" },
};

export const SOURCES = {
  hl7: "Lab import (HL7)",
  import: "Import",
  csv: "CSV import",
  front_desk: "Front desk",
  admin: "Added by an admin",
  invite: "Patient invite",
  self: "Self sign-up",
  registration: "Registration",
};

export function LevelChip({ level, score, percent = false }) {
  const l = LEVELS[level] || LEVELS.none;
  return (
    <span className={`pm-level ${l.tone}`}>
      {l.label}
      {score != null && <span className="pm-score">{percent ? `${score}%` : `${score}/100`}</span>}
    </span>
  );
}

export function ScoreBar({ score }) {
  const pct = Math.max(0, Math.min(100, score || 0));
  return (
    <span className="pm-bar" role="img" aria-label={`Match score ${pct} out of 100`}>
      <span style={{ width: `${pct}%` }} />
    </span>
  );
}

export function Reasons({ reasons }) {
  if (!reasons?.length) return null;
  return (
    <ul className="pm-reasons">
      {reasons.map((r, i) => (
        <li key={`${r.code}-${i}`} className={r.kind}>
          <span className="pm-points" aria-hidden="true">
            {r.code === "identifier" ? "ID" : r.points > 0 ? `+${r.points}` : r.points}
          </span>
          <span>{r.label}</span>
        </li>
      ))}
    </ul>
  );
}

export function moduleLabel(table) {
  const s = table.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function identifierText(i) {
  return `${i.value} (${i.authority || i.type})`;
}
