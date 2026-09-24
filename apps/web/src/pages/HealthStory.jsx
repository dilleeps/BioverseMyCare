import { Link, useNavigate } from "react-router-dom";
import { useApi } from "../hooks.js";
import { useSession } from "../session.jsx";
import { fmtShortDate } from "../format.js";
import { Warning } from "../icons.jsx";

const LINK_FOR = {
  report: (id) => `/results/${id}`,
  care_plan: () => "/plan",
  appointment: () => "/visits",
  visit: () => "/visits",
  referral: () => "/referrals",
  prescription: () => "/pharmacy",
  document: () => "/records",
  goal: () => "/wellness",
  goal_milestone: () => "/wellness",
  assessment: () => "/wellness",
};

export default function HealthStory() {
  const { me } = useSession();
  const navigate = useNavigate();
  const { data, error, loading } = useApi(`/patients/${me.patient_id}/story`);

  return (
    <main className="column">
      <div className="stack" style={{ gap: 2, marginBottom: 16 }}>
        <span className="eyebrow">My Health Story</span>
        <span className="page-title">{data ? `${data.year} so far` : "Your year"}</span>
      </div>
      {error && <div className="error-box">{error.message}</div>}
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {data && (
        <div className="stack">
          <div className="stats">
            <div className="stat"><div className="n">{data.counts.visits}</div><div className="tiny muted">Visits</div></div>
            <div className="stat"><div className="n">{data.counts.lab_panels}</div><div className="tiny muted">Lab panels</div></div>
            <div className="stat"><div className="n">{data.counts.new_medicines}</div><div className="tiny muted">New medicine</div></div>
            <div className={`stat ${data.counts.care_gaps ? "alert" : ""}`}>
              <div className="n">{data.counts.care_gaps}</div>
              <div className="tiny strong" style={{ color: data.counts.care_gaps ? "var(--alert-strong)" : "var(--muted)" }}>Care gap{data.counts.care_gaps === 1 ? "" : "s"}</div>
            </div>
          </div>

          <div className="bubble assistant" style={{ maxWidth: "100%" }}>{data.summary}</div>

          <section className="card" style={{ padding: "6px 16px" }}>
            {data.events.length === 0 && <div className="empty">Nothing recorded this year yet.</div>}
            {data.events.map((e) => {
              const to = LINK_FOR[e.type]?.(e.ref_id);
              const body = (
                <div className="stack" style={{ gap: 2 }}>
                  <span className="tiny muted">{fmtShortDate(e.at)}</span>
                  <span className="strong" style={{ fontSize: 15 }}>{e.title}</span>
                  {e.detail && <span className="small muted">{e.detail}</span>}
                </div>
              );
              return (
                <div key={`${e.type}-${e.ref_id}`} className="tl-item">
                  <div className="tl-rail"><span className={`tl-dot ${e.tone}`} /><span className="tl-line" /></div>
                  {to ? <Link to={to} style={{ textDecoration: "none", color: "inherit" }}>{body}</Link> : body}
                </div>
              );
            })}
          </section>

          {data.gaps.map((g) => (
            <section key={g.id} className="card alert row" style={{ gap: 12 }}>
              <span style={{ color: "var(--alert)", display: "flex" }}><Warning size={20} /></span>
              <div style={{ flexGrow: 1 }}>
                <div className="strong small" style={{ color: "var(--alert-strong)" }}>{g.title}</div>
                <div className="small" style={{ color: "var(--alert-strong)" }}>{g.detail}</div>
              </div>
              {g.specialty && (
                <Link className="btn danger sm" to={`/care/find?specialty=${encodeURIComponent(g.specialty)}`}>Book</Link>
              )}
            </section>
          ))}

          <button className="btn primary" onClick={() => navigate("/app", { state: { initial: "Help me prepare questions for my next visit" } })}>
            Prepare questions for my next visit
          </button>
        </div>
      )}
    </main>
  );
}
