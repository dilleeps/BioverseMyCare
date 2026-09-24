import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { PatientPage } from "../../layouts.jsx";
import { Shield } from "../../icons.jsx";
import InsuranceCard from "./InsuranceCard.jsx";
import {
  CardIcon, CheckChip, ErrorBox, Loading, Meter, PriorAuthChip, ScanIcon, fmtDay, fmtWhen,
} from "./util.jsx";

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

function useCountdown(expiresAt) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  if (!expiresAt) return null;
  return Math.max(0, Math.floor((new Date(expiresAt).getTime() - now) / 1000));
}

function CardSection() {
  const { data, error, loading, reload } = useApi("/insurance/card");
  const left = useCountdown(data?.token_expires_at);
  useEffect(() => {
    if (left === 0) reload();
  }, [left, reload]);

  if (loading && !data) return <Loading label="Loading your card" />;
  if (error) return <ErrorBox error={error} />;
  if (!data.card) {
    return (
      <Section id="card-title" title="Your insurance card" icon={CardIcon}>
        <p className="small muted">No active coverage on file. Add your card below and we'll check it with your plan.</p>
      </Section>
    );
  }
  const mins = left != null ? Math.floor(left / 60) : null;
  return (
    <Section id="card-title" title="Your insurance card" icon={CardIcon}>
      <InsuranceCard card={data.card} token={data.token} />
      <div className="row between wrap small">
        <span className="muted" aria-live="polite">
          {left > 0 ? `Check-in code refreshes in ${mins}:${String(left % 60).padStart(2, "0")}` : "Refreshing code…"}
        </span>
        <button type="button" className="btn sm" onClick={reload}>Refresh code</button>
      </div>
      <details className="small">
        <summary className="strong">Can't scan? Show this code instead</summary>
        <p className="ins-token" aria-label="Check-in code">{data.token}</p>
      </details>
      <p className="tiny muted">
        The front desk scans the code on the back to confirm your coverage. It is signed by Bioverse and stops working
        after a few minutes, so a screenshot can't be reused. {data.wallet_notice}
      </p>
    </Section>
  );
}

function Benefits({ coverage, onChecked }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const check = coverage.latest_check;

  async function run() {
    setBusy(true);
    setErr(null);
    try {
      await api(`/insurance/coverage/${coverage.id}/eligibility`, { method: "POST" });
      onChecked();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  const b = check?.benefits || {};
  const ded = b.deductible_individual || {};
  const oop = b.oop_individual || {};
  return (
    <Section id="benefits-title" title="My benefits" icon={Shield}
             aside={<CheckChip status={check?.status} />}>
      <p className="small muted">{coverage.payer_display} · {coverage.plan_name}</p>
      {check ? (
        <>
          {check.status === "active" && (
            <div className="stack" style={{ gap: 14 }}>
              <Meter label="Deductible" used={ded.met_cents} total={ded.total_cents} />
              <Meter label="Out-of-pocket maximum" used={oop.met_cents} total={oop.total_cents} />
            </div>
          )}
          <ul className="ins-summary">{check.summary.map((s) => <li key={s}>{s}</li>)}</ul>
          <p className="tiny muted">
            Checked with {check.payer_name || "your plan"} {fmtWhen(check.checked_at)}
            {check.simulated ? " · simulated clearinghouse (demo data)" : ""}.
          </p>
        </>
      ) : (
        <p className="small muted">Check your benefits to see your deductible, copays and what's left this year.</p>
      )}
      <ErrorBox error={err} />
      <button type="button" className="btn primary" onClick={run} disabled={busy}>
        {busy ? "Asking your plan…" : "Check my benefits"}
      </button>
    </Section>
  );
}

// --- Add a card ---------------------------------------------------------------------------------

const EMPTY = { payer_ref: "", payer_name: "", plan_name: "", member_id: "", group_number: "", rx_bin: "",
                rx_pcn: "", rx_group: "", payer_phone: "" };

async function readPhoto(file) {
  // Downscale large phone photos so they stay under the 5 MB limit; the photo is never stored.
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = reject;
      i.src = url;
    });
    const scale = Math.min(1, 1600 / Math.max(img.width, img.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.width * scale);
    canvas.height = Math.round(img.height * scale);
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    return { image: canvas.toDataURL("image/jpeg", 0.85).split(",")[1], media_type: "image/jpeg" };
  } finally {
    URL.revokeObjectURL(url);
  }
}

function AddCard({ payers, onSaved }) {
  const [step, setStep] = useState("start");
  const [form, setForm] = useState(EMPTY);
  const [source, setSource] = useState("manual");
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function onPhoto(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setErr(null);
    try {
      const body = await readPhoto(file);
      const r = await api("/insurance/card-scan", { method: "POST", body });
      const f = r.fields || {};
      setForm({ ...EMPTY, ...Object.fromEntries(Object.entries(f).filter(([k, v]) => k in EMPTY && v)),
                payer_ref: r.payer_ref || "", payer_name: r.payer_ref ? "" : f.payer_name || "" });
      setSource(r.mode === "ai" ? "photo" : "manual");
      setNote(r.message);
      setStep("form");
    } catch (e2) {
      setErr(e2);
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() ? v.trim() : null]));
      const saved = await api("/insurance/reported-coverage", { method: "POST", body: { ...body, source } });
      await api(`/insurance/reported-coverage/${saved.id}/verify`, { method: "POST" });
      setForm(EMPTY);
      setStep("start");
      setNote(null);
      onSaved();
    } catch (e2) {
      setErr(e2);
    } finally {
      setBusy(false);
    }
  }

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const field = (k, label, props = {}) => (
    <div className="field">
      <label htmlFor={`ins-${k}`} className="small strong">{label}</label>
      <input id={`ins-${k}`} value={form[k]} onChange={set(k)} autoComplete="off" {...props} />
    </div>
  );

  return (
    <Section id="add-card-title" title="Add a new insurance card" icon={ScanIcon}>
      {step === "start" ? (
        <>
          <p className="small muted">
            Take a photo of the front of your card and we'll fill in the details for you to check, or type them in.
            We don't keep the photo.
          </p>
          <div className="row wrap" style={{ gap: 8 }}>
            <label className={`btn primary ins-file ${busy ? "busy" : ""}`}>
              {busy ? "Reading your card…" : "Take or choose a photo"}
              <input type="file" accept="image/*" capture="environment" onChange={onPhoto} disabled={busy} />
            </label>
            <button type="button" className="btn" onClick={() => { setSource("manual"); setStep("form"); }}>Type it in</button>
          </div>
        </>
      ) : (
        <form className="stack" onSubmit={save}>
          {note && <div className="banner info">{note}</div>}
          <div className="field">
            <label htmlFor="ins-payer" className="small strong">Insurance company</label>
            <select id="ins-payer" value={form.payer_ref} onChange={set("payer_ref")}>
              <option value="">Another company (type the name)</option>
              {payers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          {!form.payer_ref && field("payer_name", "Company name as printed", { required: true })}
          <div className="ins-form-grid">
            {field("member_id", "Member ID", { required: true, minLength: 3 })}
            {field("group_number", "Group number")}
            {field("plan_name", "Plan name")}
            {field("payer_phone", "Member services phone", { inputMode: "tel" })}
            {field("rx_bin", "RxBIN", { inputMode: "numeric", pattern: "\\d{6}", title: "6 digits" })}
            {field("rx_pcn", "RxPCN")}
            {field("rx_group", "RxGroup")}
          </div>
          <p className="tiny muted">Check each field against your card. We'll ask your plan to confirm it before using it.</p>
          <ErrorBox error={err} />
          <div className="row wrap" style={{ gap: 8 }}>
            <button className="btn primary" disabled={busy}>{busy ? "Checking with your plan…" : "Save and check with my plan"}</button>
            <button type="button" className="btn" onClick={() => { setStep("start"); setForm(EMPTY); setErr(null); }}>Cancel</button>
          </div>
        </form>
      )}
      {step === "start" && <ErrorBox error={err} />}
    </Section>
  );
}

function ReportedList({ items, onChanged }) {
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  if (!items.length) return null;
  async function verify(id) {
    setBusy(id);
    setErr(null);
    try {
      await api(`/insurance/reported-coverage/${id}/verify`, { method: "POST" });
      onChanged();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(null);
    }
  }
  return (
    <Section id="reported-title" title="Cards waiting for your plan" icon={CardIcon}>
      <div className="list">
        {items.map((r) => (
          <div key={r.id} className="stack" style={{ gap: 6, padding: "10px 0" }}>
            <div className="row between wrap">
              <span className="strong">{r.payer_name} · {r.member_id}</span>
              <CheckChip status={r.status === "unverified" ? null : r.status} />
            </div>
            {r.status_message && <p className="small muted">{r.status_message}</p>}
            <button type="button" className="btn sm" style={{ alignSelf: "flex-start" }} disabled={busy === r.id}
                    onClick={() => verify(r.id)}>
              {busy === r.id ? "Checking…" : "Check again"}
            </button>
          </div>
        ))}
      </div>
      <ErrorBox error={err} />
    </Section>
  );
}

function PriorAuths({ items }) {
  return (
    <Section id="pa-title" title="Approvals from your plan" icon={Shield}>
      {items.length === 0 ? (
        <p className="small muted">No prior authorizations. Some tests and procedures need your plan's approval first;
          your care team requests them and they'll show here.</p>
      ) : (
        <div className="list">
          {items.map((a) => (
            <div key={a.id} className="stack" style={{ gap: 4, padding: "10px 0" }}>
              <div className="row between wrap">
                <span className="strong">{a.description}</span>
                <PriorAuthChip status={a.status} />
              </div>
              <span className="small muted">
                {a.payer_name}{a.payer_reference ? ` · reference ${a.payer_reference}` : ""} · requested {fmtDay(a.submitted_at)}
                {a.valid_to ? ` · valid until ${fmtDay(a.valid_to)}` : ""}
              </span>
              {a.note && <span className="small">{a.note}</span>}
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

export default function Insurance() {
  const { data, error, loading, reload } = useApi("/insurance/coverage");
  const [cardKey, setCardKey] = useState(0);
  useEffect(() => {
    document.title = "Insurance card & coverage · Bioverse";
  }, []);

  const current = data?.coverages?.find((c) => c.active_today);
  const others = data?.coverages?.filter((c) => c !== current) || [];
  return (
    <PatientPage wide>
      <div className="page-head">
        <div>
          <h1 className="page-title">Insurance card &amp; coverage</h1>
          <p className="page-sub">Your card for check-in, your benefits, and approvals from your plan.</p>
        </div>
      </div>
      {data && <div className="banner info" style={{ marginBottom: 14 }}>{data.notice}</div>}
      {error && <ErrorBox error={error} />}
      <div className="ins-grid">
        <div className="stack">
          <CardSection key={cardKey} />
          {loading && !data && <Loading />}
          {current && <Benefits coverage={current} onChecked={reload} />}
        </div>
        <div className="stack">
          {data && <ReportedList items={data.reported} onChanged={() => { reload(); setCardKey((k) => k + 1); }} />}
          {data && <AddCard payers={data.payers} onSaved={() => { reload(); setCardKey((k) => k + 1); }} />}
          {data && <PriorAuths items={data.prior_authorizations} />}
          {others.length > 0 && (
            <Section id="past-title" title="Other coverage on file" icon={CardIcon}>
              <div className="list">
                {others.map((c) => (
                  <div key={c.id} className="row between wrap" style={{ padding: "8px 0" }}>
                    <span className="small"><span className="strong">{c.payer_display}</span> · {c.plan_name}</span>
                    <span className="small muted">
                      {c.effective_end ? `Ended ${fmtDay(c.effective_end)}` : `From ${fmtDay(c.effective_start)}`}
                    </span>
                  </div>
                ))}
              </div>
            </Section>
          )}
          <p className="small muted">Bills, claims and cost estimates are in <Link to="/billing">Bills &amp; coverage</Link>.</p>
        </div>
      </div>
    </PatientPage>
  );
}
