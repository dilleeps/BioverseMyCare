import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../session.jsx";
import { Arrow, Chevron, Hospital, Person, Shield, Stethoscope } from "../icons.jsx";
import { homeFor } from "../modules/registry.js";

const SUGGESTIONS = [
  "Explain my lab report",
  "I have an itchy rash on my arm",
  "What should I do before my visit?",
  "What happened with my health this year?",
];

const JOURNEY = ["Discover", "Intake", "Navigate", "Book", "Prepare", "Visit", "Results", "Care plan", "Follow-up"];

export default function Landing() {
  const [text, setText] = useState("");
  const navigate = useNavigate();
  const { users, me, switchTo } = useSession();

  async function start(message) {
    const patient = users.find((u) => u.role === "patient");
    if (me?.role !== "patient" && patient) await switchTo(patient.id);
    navigate("/app", { state: { initial: message } });
  }

  async function openAdmin() {
    const admin = users.find((u) => u.role === "admin");
    if (admin && me?.role !== "admin") await switchTo(admin.id);
    navigate(homeFor("admin"));
  }

  async function openClinician() {
    const clinician = users.find((u) => u.role === "clinician");
    if (me?.role !== "clinician" && clinician) await switchTo(clinician.id);
    navigate("/clinician");
  }

  return (
    <main className="page">
      <section className="hero">
        <div>
          <span className="chip ok"><Shield size={14} /> Clinician reviewed. Always traceable.</span>
          <h1 style={{ marginTop: 22 }}>One place for<br />your healthcare.</h1>
          <p className="lede">
            Tell Bioverse what you need. It helps you understand, decide, connect, act and follow through, from the
            first symptom to the last follow-up.
          </p>
          <form
            style={{ marginTop: 28, maxWidth: 640 }}
            onSubmit={(e) => {
              e.preventDefault();
              if (text.trim()) start(text.trim());
            }}
          >
            <label htmlFor="ask" className="eyebrow">Start here</label>
            <div className="ask" style={{ marginTop: 10 }}>
              <input
                id="ask"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="I've had chest discomfort since yesterday…"
                autoComplete="off"
              />
              <button type="submit" className="send" aria-label="Ask Bioverse" disabled={!text.trim()}>
                <Arrow size={20} />
              </button>
            </div>
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" className="suggestion" onClick={() => start(s)}>{s}</button>
              ))}
            </div>
          </form>
        </div>

        <div className="stack">
          <button type="button" className="audience" onClick={() => start(null)} style={{ textAlign: "left" }}>
            <span className="audience-icon"><Person size={24} /></span>
            <span style={{ flexGrow: 1 }}>
              <span className="strong" style={{ display: "block", fontSize: 18 }}>Patients &amp; families</span>
              <span className="muted">A health companion that stays with you between visits.</span>
            </span>
            <Chevron size={20} />
          </button>
          <button type="button" className="audience" onClick={openClinician} style={{ textAlign: "left" }}>
            <span className="audience-icon"><Stethoscope size={24} /></span>
            <span style={{ flexGrow: 1 }}>
              <span className="strong" style={{ display: "block", fontSize: 18 }}>Clinicians</span>
              <span className="muted">A cockpit that drafts, briefs and cites. You decide.</span>
            </span>
            <Chevron size={20} />
          </button>
          <button type="button" className="audience" onClick={openAdmin} style={{ textAlign: "left" }}>
            <span className="audience-icon"><Hospital size={24} /></span>
            <span style={{ flexGrow: 1 }}>
              <span className="strong" style={{ display: "block", fontSize: 18 }}>Hospitals &amp; health systems</span>
              <span className="muted">Operations, configuration and analytics for the whole organization.</span>
            </span>
            <Chevron size={20} />
          </button>
        </div>
      </section>

      <section className="stack" style={{ gap: 14 }}>
        <div className="eyebrow">The care journey, connected</div>
        <div className="journey">
          {JOURNEY.map((j) => <span key={j}>{j}</span>)}
        </div>
        <p className="small muted">Ask → Understand → Confirm → Act → Show result</p>
      </section>
    </main>
  );
}
