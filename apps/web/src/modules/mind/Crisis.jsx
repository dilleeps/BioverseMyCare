import { Phone, Warning } from "../../icons.jsx";

// Crisis support lives in the page itself, so it shows even when the API is unreachable.
export const CRISIS = {
  title: "You don't have to go through this alone",
  message: "If you're having thoughts of hurting yourself or that you'd be better off dead, please reach out now. "
    + "Call or text 988 to reach the Suicide & Crisis Lifeline, any time, day or night. "
    + "If you are in immediate danger, call 911.",
  crisis_line: "988",
  emergency_number: "911",
  chat_url: "https://988lifeline.org/chat/",
};

export function CrisisCard({ crisis, notified, headingLevel = 2 }) {
  const c = { ...CRISIS, ...(crisis || {}) };
  const H = `h${headingLevel}`;
  return (
    <section className="wb-crisis" role="alert" aria-label="Crisis support">
      <H className="title" style={{ fontSize: 17, margin: 0 }}><Warning size={20} /> {c.title}</H>
      <p>{c.message}</p>
      <div className="actions">
        <a className="btn danger" href={`tel:${c.crisis_line}`}><Phone size={18} /> Call {c.crisis_line}</a>
        <a className="btn danger" href={`sms:${c.crisis_line}`}>Text {c.crisis_line}</a>
        <a className="btn" href={c.chat_url} target="_blank" rel="noreferrer">Chat online</a>
        <a className="btn" href={`tel:${c.emergency_number}`}><Phone size={18} /> Call {c.emergency_number}</a>
      </div>
      {notified === true && <p className="small">Your care team has been told and will follow up with you.</p>}
      {notified === false && <p className="small">We couldn't reach your care team automatically. Please use the numbers above.</p>}
    </section>
  );
}

export function SupportStrip() {
  return (
    <div className="wb-support-strip" role="note">
      <span>Need to talk to someone now? Call or text <strong>988</strong>, any time.</span>
      <span className="row" style={{ gap: 6 }}>
        <a className="btn sm" href="tel:988"><Phone size={14} /> Call</a>
        <a className="btn sm" href="sms:988">Text</a>
      </span>
    </div>
  );
}
