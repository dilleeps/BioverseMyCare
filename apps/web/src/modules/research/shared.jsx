import { Check, Close } from "../../icons.jsx";

export const INTEREST_LABELS = {
  interested: "Interested",
  contacted: "Contacted by study team",
  screening: "Screening",
  enrolled: "Enrolled",
  not_eligible: "Not eligible",
  withdrawn: "Withdrawn",
};

export const STUDY_STATUS = {
  recruiting: "Recruiting",
  not_yet_recruiting: "Not yet recruiting",
  active_not_recruiting: "Not recruiting",
  completed: "Completed",
};

// Question-mark icon for criteria the record can't answer. Local to this module.
function Unknown(props) {
  return (
    <svg width={props.size || 16} height={props.size || 16} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5v.4" />
      <path d="M12 17h.01" />
    </svg>
  );
}

const OUTCOME = {
  pass: { Icon: Check, text: "Meets", cls: "pass" },
  fail: { Icon: Close, text: "Does not meet", cls: "fail" },
  unknown: { Icon: Unknown, text: "Not known yet", cls: "unknown" },
};

const EXCLUSION_TEXT = { pass: "Does not apply", fail: "Applies", unknown: "Not known yet" };

export const DECIDES = "Bioverse checks your record against the study's rules. The study team makes the final decision.";

export function MatchChip({ status, label }) {
  const cls = status === "eligible" ? "ok" : status === "not_eligible" ? "warn" : "";
  return <span className={`chip ${cls}`}>{label}</span>;
}

// One line per criterion with its outcome and the reason from the record.
export function CriteriaList({ criteria }) {
  return (
    <ul className="rs-criteria">
      {criteria.map((c) => {
        const o = OUTCOME[c.outcome];
        const exclusion = c.type === "exclusion";
        const said = exclusion ? EXCLUSION_TEXT[c.outcome] : o.text;
        return (
          <li key={c.id} className={`rs-crit ${o.cls}`}>
            <span className="rs-crit-icon"><o.Icon size={14} /></span>
            <span className="stack" style={{ gap: 1 }}>
              <span className="small strong">
                <span className="sr-only">{said}: </span>
                {exclusion ? `Can't join if: ${c.label.charAt(0).toLowerCase()}${c.label.slice(1)}` : c.label}
              </span>
              <span className="tiny muted">{c.reason}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}
