// Pieces shared by the Evidence page and the patient-brief panel.

export function evidenceAge(source) {
  if (source.age_years == null) return null;
  const y = Math.floor(source.age_years);
  if (y < 1) return "Under a year old";
  return `${y} ${y === 1 ? "year" : "years"} old`;
}

const QUALITY = { high: "High quality", moderate: "Moderate quality", low: "Low quality", unrated: "Quality not graded" };

// Type, evidence date and age, and quality: always visible next to a source.
export function SourceChips({ source }) {
  const age = evidenceAge(source);
  const old = source.age_years != null && source.age_years >= 10;
  return (
    <div className="row wrap ev-chips">
      <span className="chip">{source.type_label}</span>
      {source.origin === "web" && <span className="chip">Web</span>}
      <span className={`chip ${source.date_kind === "unknown" || old ? "warn" : ""}`}>
        {source.date_display}{age ? ` · ${age}` : ""}
      </span>
      <span className={`chip ${source.quality === "high" ? "ok" : source.quality === "unrated" ? "warn" : ""}`}
            title={source.quality_note || undefined}>
        {QUALITY[source.quality] || source.quality}
      </span>
      {source.quality_note && source.quality !== "unrated" && <span className="tiny muted">{source.quality_note}</span>}
    </div>
  );
}

export function ExternalLink({ href, children, className }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
      {children}<span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}
