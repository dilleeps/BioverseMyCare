import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { useApi } from "../hooks.js";
import { fmtDateTime } from "../format.js";
import { Back, Calendar, Check, Phone, Pin, Warning } from "../icons.jsx";

function OptionCard({ option, highlight, onBook, busy }) {
  const [slots, setSlots] = useState(null);
  const [loadingSlots, setLoadingSlots] = useState(false);
  const [error, setError] = useState(null);

  async function moreTimes() {
    setLoadingSlots(true);
    setError(null);
    try {
      setSlots(await api(`/practitioners/${option.practitioner_id}/slots?limit=6`));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoadingSlots(false);
    }
  }

  return (
    <article className={`card stack ${highlight ? "highlight" : ""}`} style={{ gap: 10 }}>
      <div className="row between" style={{ alignItems: "flex-start" }}>
        <div>
          <div className="strong" style={{ fontSize: 17 }}>{option.name}</div>
          <div className="small muted">{option.specialty} · {option.location}</div>
        </div>
        <div className="row" style={{ gap: 6 }}>
          {option.badges.map((b) => <span key={b} className="chip ok">{b}</span>)}
        </div>
      </div>
      {option.reasons.length > 0 && (
        <div className="row wrap" style={{ gap: 6 }}>
          {option.reasons.map((r, i) => (
            <span key={r} className="chip">{i === 0 && r.endsWith("km") && <Pin size={12} />}{r}</span>
          ))}
        </div>
      )}
      <div className="row strong" style={{ gap: 8 }}>
        <Calendar size={16} /> {fmtDateTime(option.next_slot.starts_at)}
        {option.next_slot.mode === "video" && <span className="chip">Video</span>}
      </div>
      <div className="row" style={{ gap: 8 }}>
        <button className="btn primary" style={{ flexGrow: 1 }} disabled={busy} onClick={() => onBook(option.next_slot.id, option)}>
          Book this time
        </button>
        <button className="btn" onClick={moreTimes} disabled={loadingSlots}>
          {loadingSlots ? "Loading…" : "More times"}
        </button>
      </div>
      {error && <div className="error-box">{error}</div>}
      {slots && (
        <div className="row wrap" style={{ gap: 6 }}>
          {slots.length === 0 && <span className="small muted">No other times in the next two weeks.</span>}
          {slots.map((s) => (
            <button key={s.id} className="btn sm" disabled={busy} onClick={() => onBook(s.id, option, s.starts_at)}>
              {fmtDateTime(s.starts_at)}
            </button>
          ))}
        </div>
      )}
    </article>
  );
}

function Booked({ appt }) {
  return (
    <main className="column">
      <div className="card stack">
        <span className="chip ok" style={{ alignSelf: "flex-start" }}><Check size={13} /> Booked</span>
        <div className="page-title" style={{ fontSize: 24 }}>You're booked with {appt.practitioner_name}</div>
        <div className="row strong"><Calendar size={16} /> {fmtDateTime(appt.starts_at)}</div>
        <div className="small muted">{appt.specialty} · {appt.location_name}{appt.mode === "video" ? " · Video visit" : ""}</div>
        <div className="banner info">Your clinician will see the summary you gave Bioverse before the visit.</div>
        <div className="row wrap" style={{ gap: 8 }}>
          <Link className="btn primary" to="/plan">See my care plan</Link>
          <Link className="btn" to="/app">Back to Bioverse</Link>
        </div>
      </div>
    </main>
  );
}

export default function Navigator() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const intake = params.get("intake");
  const specialty = params.get("specialty");
  const task = params.get("task");

  const query = new URLSearchParams();
  if (intake) query.set("intake_id", intake);
  if (specialty) query.set("specialty", specialty);
  const { data, error, loading, reload } = useApi(`/care/options?${query}`);

  const [busy, setBusy] = useState(false);
  const [bookError, setBookError] = useState(null);
  const [booked, setBooked] = useState(null);

  async function book(slotId) {
    setBusy(true);
    setBookError(null);
    try {
      const appt = await api("/appointments", {
        method: "POST",
        body: { slot_id: slotId, intake_id: intake || null, care_plan_task_id: task || null },
      });
      setBooked(appt);
    } catch (e) {
      setBookError(e.message);
      if (e.status === 409) reload();
    } finally {
      setBusy(false);
    }
  }

  if (booked) return <Booked appt={booked} />;

  const emergency = error?.status === 409 && error.detail?.code === "emergency";

  return (
    <main className="column">
      <div className="page-head">
        <button className="icon-btn" aria-label="Back" onClick={() => navigate(-1)}><Back /></button>
        <div>
          <div className="page-title" style={{ fontSize: 22 }}>Finding care</div>
          <div className="page-sub">
            {data ? `${data.specialty} · in network · ${data.preferred_language}` : specialty || "Matching options"}
          </div>
        </div>
      </div>

      {emergency && (
        <section className="emergency stack" role="alert">
          <div className="row strong" style={{ color: "var(--alert-strong)" }}><Warning size={20} /> This needs emergency care</div>
          <p style={{ color: "var(--alert-strong)" }}>{error.detail.message}</p>
          <a className="call" href={`tel:${error.detail.emergency_number}`}><Phone size={20} /> Call {error.detail.emergency_number}</a>
        </section>
      )}
      {error && !emergency && <div className="error-box">{error.message}</div>}
      {bookError && <div className="error-box" style={{ marginBottom: 12 }}>{bookError}</div>}

      {loading && !data && (
        <div className="stack">{[0, 1, 2].map((i) => <div key={i} className="card"><div className="skeleton" /></div>)}</div>
      )}

      {data && (
        <div className="stack">
          <div className="bubble assistant" style={{ maxWidth: "100%" }}>
            Based on what you've told me, <strong>{data.specialty}</strong> appears relevant. I found{" "}
            {data.options.length} option{data.options.length === 1 ? "" : "s"} that match your location, your{" "}
            {data.preferred_language}-language preference and your plan.
          </div>
          {data.options.length === 0 && <div className="card empty">No open times in the next two weeks. A coordinator can help.</div>}
          {data.options.map((o, i) => (
            <OptionCard key={o.practitioner_id} option={o} highlight={i === 0} onBook={book} busy={busy} />
          ))}
          <p className="small muted">Matched on {data.matched_on.join(", ")}.</p>
        </div>
      )}
    </main>
  );
}
