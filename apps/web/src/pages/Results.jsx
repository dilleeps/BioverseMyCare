import { Link, useNavigate, useParams } from "react-router-dom";
import { useApi } from "../hooks.js";
import { useSession } from "../session.jsx";
import { fmtDate, fmtMonthYear, fmtNumber, fmtShortDate } from "../format.js";
import { Back, Check, Chevron, Down, Shield, Up } from "../icons.jsx";

function target(o) {
  if (o.ref_high != null && o.ref_low != null) return `Target ${fmtNumber(o.ref_low)}–${fmtNumber(o.ref_high)}`;
  if (o.ref_high != null) return `Target below ${fmtNumber(o.ref_high)}`;
  if (o.ref_low != null) return `Target above ${fmtNumber(o.ref_low)}`;
  return "";
}

// Bars for each result over time, with the target as a dashed line.
function Trend({ obs }) {
  const hist = (obs.history || []).map((h) => ({ value: Number(h.value), at: h.at }));
  if (hist.length < 2) return null;
  const limit = obs.ref_high ?? obs.ref_low;
  const max = Math.max(...hist.map((h) => h.value), limit ?? 0) * 1.15;
  const W = 320, H = 130, base = 104, top = 16;
  const y = (v) => base - ((base - top) * v) / max;
  const slot = W / hist.length;
  const bw = Math.min(28, slot * 0.35);
  const label = `${obs.display}: ` + hist.map((h) => `${fmtNumber(h.value)} in ${fmtMonthYear(h.at)}`).join(", ") + (limit != null ? `. ${target(obs)}.` : ".");

  return (
    <section className="card stack" style={{ gap: 8 }}>
      <div className="row between">
        <span className="strong">{obs.display} over time</span>
        <span className="tiny muted">{obs.unit}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={label}>
        <line x1="0" y1={base} x2={W} y2={base} stroke="var(--line)" />
        {limit != null && (
          <>
            <line x1="0" y1={y(limit)} x2={W} y2={y(limit)} stroke="var(--alert)" strokeWidth="1.5" strokeDasharray="4 4" />
            <text x={W} y={y(limit) - 5} textAnchor="end" fontSize="11" fontWeight="600" fill="var(--muted)">Target {fmtNumber(limit)}</text>
          </>
        )}
        {hist.map((h, i) => {
          const cx = slot * i + slot / 2;
          const last = i === hist.length - 1;
          return (
            <g key={h.at}>
              <rect x={cx - bw / 2} y={y(h.value)} width={bw} height={base - y(h.value)} rx="4"
                    fill="var(--accent)" opacity={last ? 1 : 0.5 + (0.4 * i) / hist.length}>
                <title>{`${fmtNumber(h.value)} ${obs.unit}, ${fmtDate(h.at)}`}</title>
              </rect>
              <text x={cx} y={y(h.value) - 6} textAnchor="middle" fontSize="12" fontWeight="700" fill="var(--ink)">{fmtNumber(h.value)}</text>
              <text x={cx} y={H - 8} textAnchor="middle" fontSize="11" fill="var(--muted)">{fmtMonthYear(h.at)}</text>
            </g>
          );
        })}
      </svg>
    </section>
  );
}

export function ResultsList() {
  const { me } = useSession();
  const { data, error, loading } = useApi(`/patients/${me.patient_id}/reports`);
  return (
    <main className="column">
      <div className="page-head"><div className="page-title">Results</div></div>
      {error && <div className="error-box">{error.message}</div>}
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {data?.length === 0 && <div className="card empty">No results yet.</div>}
      <div className="stack" style={{ gap: 10 }}>
        {data?.map((r) => (
          <Link key={r.id} to={`/results/${r.id}`} className="card row between" style={{ textDecoration: "none", color: "inherit" }}>
            <div>
              <div className="strong">{r.name}</div>
              <div className="small muted">{fmtDate(r.collected_at)} · {r.lab_name}</div>
              <div className="row" style={{ gap: 6, marginTop: 6 }}>
                {r.abnormal_count > 0 ? <span className="chip warn">{r.abnormal_count} outside range</span> : <span className="chip ok">All in range</span>}
                {r.explanation_status === "approved" && <span className="chip"><Shield size={12} /> Reviewed</span>}
                {r.explanation_status === "pending_review" && <span className="chip">Awaiting review</span>}
              </div>
            </div>
            <Chevron size={20} />
          </Link>
        ))}
      </div>
    </main>
  );
}

export function ResultDetail() {
  const { reportId } = useParams();
  const navigate = useNavigate();
  const { me } = useSession();
  const { data, error, loading } = useApi(me ? `/reports/${reportId}` : null);
  const x = data?.explanation;
  const abnormal = data?.observations.filter((o) => o.interpretation !== "N") || [];

  return (
    <main className="column">
      <div className="page-head">
        <button className="icon-btn" aria-label="Back" onClick={() => navigate(-1)}><Back /></button>
        <div>
          <div className="page-title" style={{ fontSize: 22 }}>{data?.name || "Result"}</div>
          {data && <div className="page-sub">Collected {fmtDate(data.collected_at)} · {data.lab_name}</div>}
        </div>
      </div>
      {error && <div className="error-box">{error.message}</div>}
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {data && (
        <div className="stack">
          {x?.status === "approved" && (
            <div className="banner ok"><Shield size={15} /> Explanation reviewed by {x.reviewed_by} · {fmtShortDate(x.reviewed_at)}</div>
          )}
          {x?.status === "pending_review" && (
            <div className="banner info">Your clinician is reviewing these results. You'll get an explanation once they've approved it.</div>
          )}
          {x?.text && <p style={{ fontSize: 16 }}>{x.text}</p>}
          {me.role === "clinician" && x?.draft_text && x.status !== "approved" && (
            <div className="card small"><div className="eyebrow">AI draft · not visible to patient</div><p style={{ marginTop: 6 }}>{x.draft_text}</p></div>
          )}

          <section className="card" style={{ padding: "4px 16px" }}>
            <div className="list">
              {data.observations.map((o) => {
                const off = o.interpretation !== "N";
                return (
                  <div key={o.id} className="result-row">
                    <div className="row" style={{ gap: 10 }}>
                      <span className={`status-dot ${off ? "alert" : ""}`}>
                        {o.interpretation === "H" ? <Up size={13} /> : o.interpretation === "L" ? <Down size={13} /> : <Check size={13} />}
                      </span>
                      <div>
                        <div className="strong" style={{ fontSize: 15 }}>{o.display}</div>
                        <div className="tiny muted">{target(o)}</div>
                      </div>
                    </div>
                    <div>
                      <div className="value">{fmtNumber(o.value)}</div>
                      <div className="tiny strong" style={{ color: off ? "var(--alert)" : "var(--muted)", textAlign: "right" }}>
                        {o.interpretation === "H" ? "High" : o.interpretation === "L" ? "Low" : "In range"} · {o.unit}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {abnormal.map((o) => <Trend key={o.id} obs={o} />)}

          {x?.questions?.length > 0 && (
            <section className="card stack" style={{ gap: 8 }}>
              <span className="strong">Questions to ask {data.responsible_clinician || "your clinician"}</span>
              <ol style={{ margin: 0, paddingLeft: 20, color: "var(--ink-2)" }} className="small">
                {x.questions.map((q) => <li key={q} style={{ marginBottom: 4 }}>{q}</li>)}
              </ol>
            </section>
          )}

          {me.role === "patient" && (
            <button className="btn primary" onClick={() => navigate("/app", { state: { initial: `I have a question about my ${data.name} result` } })}>
              Ask about this result
            </button>
          )}
        </div>
      )}
    </main>
  );
}
