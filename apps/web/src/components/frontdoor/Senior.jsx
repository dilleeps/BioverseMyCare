import { Link } from "react-router-dom";
import { useApi } from "../../hooks.js";
import { Calendar, Chat, Phone } from "../../icons.jsx";
import { savePrefs, useDisplayPrefs } from "../../modules/accessibility/prefs.js";
import { Pill, TextSize } from "./icons.jsx";
import "./frontdoor.css";

// Quick switch at the top of the front door.
export function SeniorToggle() {
  const { senior_mode: on } = useDisplayPrefs();
  return (
    <button type="button" className={`fd-pill${on ? " on" : ""}`} aria-pressed={Boolean(on)}
            onClick={() => savePrefs({ senior_mode: !on })}>
      <TextSize size={16} /> {on ? "Senior mode on" : "Larger & simpler"}
    </button>
  );
}

const telHref = (phone) => `tel:${String(phone).replace(/[^\d+]/g, "")}`;

// The simplified front door: four large buttons above the ask box.
export function SeniorHome({ onAsk }) {
  const branding = useApi("/org/branding");
  const phone = branding.data?.support_phone;
  const clinic = branding.data?.display_name || "your clinic";
  return (
    <nav className="senior-home" aria-label="Main tasks">
      <button type="button" className="senior-tile primary" onClick={onAsk}>
        <Chat size={28} /> <span>Ask a question</span>
      </button>
      <Link to="/pharmacy" className="senior-tile"><Pill size={28} /> <span>My medicines</span></Link>
      {phone ? (
        <a href={telHref(phone)} className="senior-tile">
          <Phone size={28} />
          <span>Call my care team<small>{clinic} · {phone}</small></span>
        </a>
      ) : (
        <Link to="/messages" className="senior-tile">
          <Phone size={28} />
          <span>Contact my care team{branding.loading ? null : <small>Send a message</small>}</span>
        </Link>
      )}
      <Link to="/visits" className="senior-tile"><Calendar size={28} /> <span>My appointments</span></Link>
    </nav>
  );
}
