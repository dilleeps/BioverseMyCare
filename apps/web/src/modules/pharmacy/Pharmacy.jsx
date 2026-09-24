import { useEffect, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { PatientPage } from "../../layouts.jsx";
import { Check, Phone, Pin, Warning } from "../../icons.jsx";
import { Pill, Refresh, Store } from "./icons.jsx";
import { FILL_STEPS, fmtDay, fmtShortDay, fmtWeekday } from "./format.js";

function Section({ id, title, icon: Icon, aside, children }) {
  return (
    <section className="card stack" aria-labelledby={id}>
      <div className="row between wrap">
        <h2 id={id} className="card-title row" style={{ gap: 8 }}>{Icon && <Icon size={18} />} {title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

// --- Fill progress -------------------------------------------------------------------------------

function FillProgress({ fill }) {
  const current = FILL_STEPS.findIndex((s) => s.key === fill.status);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <ol className="fill-steps" aria-label="Pharmacy progress">
        {FILL_STEPS.map((s, i) => (
          <li key={s.key} className={i < current ? "done" : i === current ? "current" : ""}
              aria-current={i === current ? "step" : undefined}>
            <span className="dot">{i < current ? <Check size={12} /> : null}</span>
            <span>{s.label}</span>
          </li>
        ))}
      </ol>
      <p className="small">
        {fill.status === "ready" && <>Ready for pickup at <strong>{fill.pharmacy_name}</strong>.</>}
        {fill.status === "sent" && <>Sent to <strong>{fill.pharmacy_name}</strong>. They'll start filling it soon.</>}
        {fill.status === "received" && <><strong>{fill.pharmacy_name}</strong> is filling it now.</>}
        {fill.status === "picked_up" && <>Picked up {fmtShortDay(fill.picked_up_at)} from {fill.pharmacy_name}.</>}
        {fill.pharmacy_phone && fill.status !== "picked_up" && (
          <> <a href={`tel:${fill.pharmacy_phone.replace(/[^\d+]/g, "")}`}>{fill.pharmacy_phone}</a></>
        )}
      </p>
    </div>
  );
}

// --- Adherence -----------------------------------------------------------------------------------

function Adherence({ rx, onChanged }) {
  const a = rx.adherence;
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  if (!a) return null;
  if (!a.tracking) {
    return <p className="small muted">Once you've picked this medicine up, you can log your doses here.</p>;
  }
  const today = a.days[a.days.length - 1].date;

  async function toggleToday() {
    setBusy(true);
    setErr(null);
    try {
      if (a.taken_today) await api(`/pharmacy/prescriptions/${rx.id}/doses/${today}`, { method: "DELETE" });
      else await api(`/pharmacy/prescriptions/${rx.id}/doses`, { method: "POST", body: {} });
      await onChanged();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  const low = a.pct_7 != null && a.pct_7 < a.target_pct && a.days_7 >= 3;
  return (
    <div className="adherence stack" style={{ gap: 10 }}>
      <div className="row between wrap">
        {a.taken_today ? (
          <div className="row wrap" style={{ gap: 8 }}>
            <span className="chip ok"><Check size={12} /> Today's dose logged</span>
            <button className="btn ghost" onClick={toggleToday} disabled={busy}>Undo</button>
          </div>
        ) : (
          <button className="btn primary" onClick={toggleToday} disabled={busy}>
            {busy ? "Saving…" : "Took today's dose"}
          </button>
        )}
      </div>
      {err && <div className="error-box small">{err}</div>}
      <dl className="adh-stats">
        <div><dt>Last 7 days</dt><dd className={low ? "alert-text" : ""}>{a.pct_7 == null ? "—" : `${a.pct_7}%`}</dd>
          <span className="tiny muted">{a.taken_7} of {a.days_7} days</span></div>
        <div><dt>Last 30 days</dt><dd>{a.pct_30 == null ? "—" : `${a.pct_30}%`}</dd>
          <span className="tiny muted">{a.taken_30} of {a.days_30} days</span></div>
        <div><dt>Streak</dt><dd>{a.streak}</dd><span className="tiny muted">{a.streak === 1 ? "day" : "days"} in a row</span></div>
      </dl>
      <ul className="dose-strip" aria-label="Doses over the last two weeks">
        {a.days.map((d) => (
          <li key={d.date} className={!d.tracked ? "untracked" : d.taken ? "taken" : d.date === today ? "pending" : "missed"}>
            <span className="sr-only">
              {fmtWeekday(d.date)}: {!d.tracked ? "before you started" : d.taken ? "taken" : d.date === today ? "not logged yet" : "not logged"}
            </span>
            <span aria-hidden="true" className="dose-day">{fmtWeekday(d.date).slice(0, 1)}</span>
          </li>
        ))}
      </ul>
      {low && (
        <p className="small muted">
          Missed doses happen. If something makes this medicine hard to take, such as side effects or cost, tell your care team.
        </p>
      )}
    </div>
  );
}

// --- Drug information ----------------------------------------------------------------------------

function DrugInfo({ code }) {
  const [info, setInfo] = useState(null);
  const [err, setErr] = useState(null);

  async function load(e) {
    if (!e.currentTarget.open || info) return;
    try {
      setInfo(await api(`/pharmacy/drugs/${code}`));
    } catch (e2) {
      setErr(e2.status === 404 ? "No demo information for this medicine." : e2.message);
    }
  }

  return (
    <details className="drug-info" onToggle={load}>
      <summary className="small strong">About this medicine</summary>
      {!info && !err && <div className="skeleton" style={{ marginTop: 8 }} />}
      {err && <p className="small muted">{err}</p>}
      {info && (
        <div className="stack" style={{ gap: 8, marginTop: 8 }}>
          <span className="chip">Demo drug information</span>
          <p className="small"><strong>What it's for.</strong> {info.uses}</p>
          <p className="small"><strong>How to take it.</strong> {info.how_to_take} Always follow your prescription label.</p>
          <div className="small"><strong>Common side effects</strong>
            <ul>{info.common_side_effects.map((s) => <li key={s}>{s}</li>)}</ul>
          </div>
          <div className="small"><strong>Call your doctor if you have</strong>
            <ul>{info.call_doctor_if.map((s) => <li key={s}>{s}</li>)}</ul>
          </div>
          <p className="tiny muted">{info.notice}</p>
        </div>
      )}
    </details>
  );
}

// --- Prescription card ---------------------------------------------------------------------------

function RefillForm({ rx, onDone }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await api(`/pharmacy/prescriptions/${rx.id}/refill-requests`, { method: "POST", body: { note: note.trim() || null } });
      onDone(r.message);
    } catch (e2) {
      setErr(e2.message);
      setBusy(false);
    }
  }
  return (
    <form className="stack" style={{ gap: 8 }} onSubmit={submit}>
      <p className="small">
        {rx.refills_remaining > 0
          ? `You have ${rx.refills_remaining} refill${rx.refills_remaining === 1 ? "" : "s"} left. We'll send this straight to your pharmacy.`
          : `No refills are left, so ${rx.prescriber_name} will need to approve this.`}
      </p>
      <label htmlFor={`note-${rx.id}`} className="small strong">Note (optional)</label>
      <textarea id={`note-${rx.id}`} className="edit" style={{ minHeight: 64 }} maxLength={500} value={note}
                onChange={(e) => setNote(e.target.value)} />
      {err && <div className="error-box small">{err}</div>}
      <button className="btn primary" disabled={busy}>{busy ? "Sending…" : "Send refill request"}</button>
    </form>
  );
}

function RxCard({ rx, onChanged }) {
  const [refilling, setRefilling] = useState(false);
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const fill = rx.latest_fill;
  const inProgress = fill && fill.status !== "picked_up";
  const lastReq = rx.last_refill_request;

  async function act(path) {
    setBusy(true);
    setErr(null);
    try {
      await api(path, { method: "POST" });
      await onChanged();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="card stack rx-card" aria-labelledby={`rx-${rx.id}`}>
      <div className="row between wrap" style={{ alignItems: "flex-start" }}>
        <div>
          <h3 id={`rx-${rx.id}`} className="rx-name">{rx.drug_name} {rx.strength}</h3>
          <p className="small">{rx.sig}</p>
          <p className="tiny muted">Prescribed by {rx.prescriber_name} · {fmtDay(rx.authored_at)} · {rx.quantity} tablets</p>
        </div>
        <span className="chip">{rx.refills_remaining} refill{rx.refills_remaining === 1 ? "" : "s"} left</span>
      </div>

      {fill && <FillProgress fill={fill} />}
      {err && <div className="error-box small">{err}</div>}
      {message && <div className="banner ok" role="status"><Check size={15} /> {message}</div>}
      {rx.pending_refill_id && (
        <div className="banner info" role="status">Refill request waiting for {rx.prescriber_name} to approve.</div>
      )}
      {!rx.pending_refill_id && lastReq?.status === "denied" && (
        <div className="banner warn"><Warning size={15} /> <span>Refill not approved {fmtShortDay(lastReq.decided_at)}. {lastReq.decision_note}</span></div>
      )}

      <div className="row wrap" style={{ gap: 8 }}>
        {fill?.status === "ready" && (
          <button className="btn primary" disabled={busy} onClick={() => act(`/pharmacy/fills/${fill.id}/pickup`)}>I picked it up</button>
        )}
        {(fill?.status === "sent" || fill?.status === "received") && (
          <button className="btn" disabled={busy} onClick={() => act(`/pharmacy/fills/${fill.id}/simulate-update`)}>
            <Refresh size={16} /> Demo: next pharmacy update
          </button>
        )}
        {!inProgress && !rx.pending_refill_id && !refilling && (
          <button className="btn dark" onClick={() => { setRefilling(true); setMessage(null); }}>Request a refill</button>
        )}
      </div>
      {refilling && (
        <RefillForm rx={rx} onDone={async (msg) => { setRefilling(false); setMessage(msg); await onChanged(); }} />
      )}

      <div className="rx-divider" />
      <Adherence rx={rx} onChanged={onChanged} />
      <DrugInfo code={rx.drug_code} />
    </article>
  );
}

// --- Interactions --------------------------------------------------------------------------------

const SEVERITY = { major: { label: "Serious", tone: "warn" }, moderate: { label: "Use caution", tone: "warn" }, advisory: { label: "Advice", tone: "" } };

function Interactions({ activeCodes }) {
  const [candidate, setCandidate] = useState("");
  const { data, error, loading } = useApi(`/pharmacy/interactions${candidate ? `?candidate=${candidate}` : ""}`);
  const drugs = useApi("/pharmacy/drugs");
  const options = (drugs.data?.drugs || []).filter((d) => !activeCodes.includes(d.code));

  return (
    <Section id="ix-title" title="Interaction check" icon={Warning}>
      <div className="field">
        <label htmlFor="ix-candidate" className="small strong">Thinking of taking something else?</label>
        <select id="ix-candidate" value={candidate} onChange={(e) => setCandidate(e.target.value)}>
          <option value="">Just check my current medicines</option>
          {options.map((d) => <option key={d.code} value={d.code}>{d.name}</option>)}
        </select>
      </div>
      {loading && !data && <div className="skeleton" />}
      {error && <div className="error-box small">{error.message}</div>}
      {data && (
        <div className="stack" aria-live="polite" style={{ gap: 8 }}>
          <span className="tiny muted">Checked: {data.checked.join(", ") || "no active medicines"}</span>
          {data.warnings.length === 0 && (
            <div className="banner ok"><Check size={15} /> No interactions found in the demo list.</div>
          )}
          {data.warnings.map((w) => {
            const s = SEVERITY[w.severity];
            return (
              <div key={w.id} className={`ix ${w.severity}`}>
                <div className="row between wrap">
                  <span className="strong small">{w.between.join(" + ")}</span>
                  <span className={`chip ${s.tone}`}>{s.label}</span>
                </div>
                <p className="small">{w.summary}</p>
                <p className="small"><strong>What to do.</strong> {w.advice}</p>
              </div>
            );
          })}
          <p className="tiny muted">{data.notice}</p>
        </div>
      )}
    </Section>
  );
}

// --- Pharmacy choice -----------------------------------------------------------------------------

function MyPharmacy({ onChanged }) {
  const preferred = useApi("/pharmacy/preferred-pharmacy");
  const [only24, setOnly24] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const list = useApi(choosing ? `/pharmacy/pharmacies${only24 ? "?open_24_hours=true" : ""}` : null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const current = preferred.data?.pharmacy;

  async function choose(id) {
    setBusy(true);
    setErr(null);
    try {
      await api("/pharmacy/preferred-pharmacy", { method: "PUT", body: { pharmacy_id: id } });
      await preferred.reload();
      setChoosing(false);
      onChanged?.();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section id="pharm-title" title="My pharmacy" icon={Store}>
      {preferred.loading && !preferred.data && <div className="skeleton" />}
      {preferred.error && <div className="error-box small">{preferred.error.message}</div>}
      {preferred.data && !current && <p className="small muted">You haven't chosen a pharmacy yet.</p>}
      {current && (
        <div className="pharmacy current">
          <div className="strong">{current.name} {current.open_24_hours && <span className="chip ok">Open 24 hours</span>}</div>
          <div className="small muted row" style={{ gap: 6 }}><Pin size={14} /> {current.address} · {Number(current.distance_km).toFixed(1)} km</div>
          <div className="small muted">{current.hours}</div>
          <a className="small row" style={{ gap: 6 }} href={`tel:${current.phone.replace(/[^\d+]/g, "")}`}><Phone size={14} /> {current.phone}</a>
        </div>
      )}
      <p className="tiny muted">New refills go to this pharmacy. Prescriptions already sent stay where they are.</p>
      {!choosing && <button className="btn" onClick={() => setChoosing(true)}>{current ? "Change pharmacy" : "Choose a pharmacy"}</button>}
      {choosing && (
        <div className="stack" style={{ gap: 8 }}>
          <label className="toggle-row">
            <input type="checkbox" checked={only24} onChange={(e) => setOnly24(e.target.checked)} />
            <span className="small">Open 24 hours only</span>
          </label>
          {list.loading && !list.data && <div className="skeleton" />}
          {list.error && <div className="error-box small">{list.error.message}</div>}
          {list.data?.pharmacies.length === 0 && <p className="small muted">No pharmacies match.</p>}
          <ul className="pharmacy-list">
            {list.data?.pharmacies.map((p) => (
              <li key={p.id} className="pharmacy">
                <div className="row between wrap" style={{ alignItems: "flex-start" }}>
                  <div>
                    <div className="strong">{p.name} {p.open_24_hours && <span className="chip ok">24 hours</span>}</div>
                    <div className="small muted">{p.address} · {Number(p.distance_km).toFixed(1)} km</div>
                    <div className="small muted">{p.hours} · {p.phone}</div>
                  </div>
                  {current?.id === p.id ? (
                    <span className="chip ok"><Check size={12} /> Current</span>
                  ) : (
                    <button className="btn" disabled={busy} onClick={() => choose(p.id)} aria-label={`Choose ${p.name}`}>Choose</button>
                  )}
                </div>
              </li>
            ))}
          </ul>
          {list.data && <p className="tiny muted">{list.data.notice}</p>}
          {err && <div className="error-box small">{err}</div>}
          <button className="btn ghost" onClick={() => setChoosing(false)}>Cancel</button>
        </div>
      )}
    </Section>
  );
}

// --- Page ----------------------------------------------------------------------------------------

export default function Pharmacy() {
  const { data, error, loading, reload } = useApi("/pharmacy/prescriptions");
  useEffect(() => {
    document.title = "Pharmacy · Bioverse";
  }, []);
  const active = data?.prescriptions.filter((p) => p.status === "active" || p.status === "on_hold") || [];
  const past = data?.prescriptions.filter((p) => p.status === "completed" || p.status === "stopped") || [];

  return (
    <PatientPage wide>
      <div className="page-head">
        <div>
          <h1 className="page-title">Pharmacy</h1>
          <p className="page-sub">Your prescriptions, refills and doses, in one place.</p>
        </div>
      </div>
      <div className="banner info" style={{ marginBottom: 16 }}>
        Demo pharmacies: fills are simulated and no real pharmacy receives these requests.
      </div>
      {error && <div className="error-box">{error.message}</div>}
      <div className="pharmacy-grid">
        <div className="stack">
          <section aria-labelledby="active-title" className="stack">
            <h2 id="active-title" className="eyebrow row" style={{ gap: 6 }}><Pill size={14} /> Active prescriptions</h2>
            {loading && !data && <div className="card" aria-busy="true"><div className="skeleton" /></div>}
            {data && active.length === 0 && <div className="card empty">No active prescriptions.</div>}
            {active.map((rx) => <RxCard key={rx.id} rx={rx} onChanged={reload} />)}
          </section>
          {past.length > 0 && (
            <section aria-labelledby="past-title" className="card stack">
              <h2 id="past-title" className="card-title">Past prescriptions</h2>
              <ul className="list plain">
                {past.map((rx) => (
                  <li key={rx.id} className="row between wrap" style={{ padding: "10px 0" }}>
                    <span>
                      <span className="strong">{rx.drug_name} {rx.strength}</span>
                      <span className="small muted" style={{ display: "block" }}>{rx.prescriber_name} · {fmtDay(rx.authored_at)}</span>
                    </span>
                    <span className="chip">{rx.status === "completed" ? "Completed" : "Stopped"}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
        <div className="stack">
          <MyPharmacy />
          <Interactions activeCodes={active.map((r) => r.drug_code)} />
        </div>
      </div>
    </PatientPage>
  );
}
