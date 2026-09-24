import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { PatientPage } from "../../layouts.jsx";
import { Check, Chevron, Lock, Shield, Warning } from "../../icons.jsx";
import { CLAIM_STATUS, centsToInput, fmtDay, fmtMoney, fmtShortDay, parseDollars } from "./money.js";
import { Calculator, Heart, ReceiptIcon, Wallet } from "./icons.jsx";

function Loading() {
  return <div className="card" aria-busy="true"><div className="skeleton" /><span className="sr-only">Loading</span></div>;
}

function Section({ id, title, icon: Icon, children, aside }) {
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

function Meter({ label, used, total }) {
  const pct = total > 0 ? Math.min(100, Math.round((100 * used) / total)) : 0;
  const id = `meter-${label.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="row between small">
        <span id={id} className="strong">{label}</span>
        <span className="muted">{fmtMoney(used)} of {fmtMoney(total)} met</span>
      </div>
      <div className="progress" role="progressbar" aria-labelledby={id} aria-valuemin={0} aria-valuemax={100}
           aria-valuenow={pct} aria-valuetext={`${fmtMoney(used)} of ${fmtMoney(total)} met`}>
        <div style={{ width: `${pct}%` }} />
      </div>
      <span className="tiny muted">{fmtMoney(Math.max(0, total - used))} left this plan year</span>
    </div>
  );
}

// --- Coverage ------------------------------------------------------------------------------------

function CoverageCard() {
  const { data, error, loading, reload } = useApi("/billing/coverage");
  const [memberId, setMemberId] = useState(null);
  const [check, setCheck] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const cov = data?.coverages?.[0];

  async function reveal() {
    setErr(null);
    try {
      setMemberId((await api(`/billing/coverage/${cov.id}/member-id`)).member_id);
    } catch (e) {
      setErr(e.message);
    }
  }

  async function runCheck() {
    setBusy(true);
    setErr(null);
    try {
      setCheck(await api(`/billing/coverage/${cov.id}/eligibility`, { method: "POST" }));
      reload();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (loading && !data) return <Loading />;
  if (error) return <div className="error-box">{error.message}</div>;
  if (!cov) {
    return (
      <Section id="coverage-title" title="Coverage" icon={Shield}>
        <p className="small muted">No insurance on file. Estimates will use self-pay prices.</p>
      </Section>
    );
  }
  const active = check ? check.status === "active" : cov.eligible_today;
  const copays = Object.entries(cov.copays || {});

  return (
    <Section id="coverage-title" title="Coverage" icon={Shield}
             aside={<span className={`chip ${active ? "ok" : "warn"}`}>{active ? "Active" : "Not active"}</span>}>
      <div className="coverage-card">
        <div className="tiny muted strong">{cov.payer_label}</div>
        <div className="coverage-plan">{cov.plan_name}</div>
        <dl className="kv">
          <div><dt>Member ID</dt><dd>
            <span aria-live="polite">{memberId || cov.member_id_masked}</span>{" "}
            {!memberId && <button className="linkish" onClick={reveal}>Show</button>}
          </dd></div>
          <div><dt>Group</dt><dd>{cov.group_number || "—"}</dd></div>
          <div><dt>Effective</dt><dd>{fmtDay(cov.effective_start)}{cov.effective_end ? ` to ${fmtDay(cov.effective_end)}` : " onward"}</dd></div>
          <div><dt>Coinsurance</dt><dd>{cov.coinsurance_pct}% in network · {cov.oon_coinsurance_pct}% out of network</dd></div>
        </dl>
      </div>
      {cov.eligible_today && (
        <div className="stack" style={{ gap: 14 }}>
          <Meter label="Deductible" used={Math.min(cov.deductible_met_cents, cov.deductible_cents)} total={cov.deductible_cents} />
          <Meter label="Out-of-pocket maximum" used={Math.min(cov.oop_met_cents, cov.oop_max_cents)} total={cov.oop_max_cents} />
        </div>
      )}
      {copays.length > 0 && (
        <div className="stack" style={{ gap: 6 }}>
          <span className="small strong">Copays</span>
          <div className="row wrap" style={{ gap: 6 }}>
            {copays.map(([k, v]) => {
              const label = k.replace("_", " ");
              return <span key={k} className="chip">{label[0].toUpperCase() + label.slice(1)} {fmtMoney(v)}</span>;
            })}
          </div>
          <span className="tiny muted">Lab tests and imaging go toward your deductible, then coinsurance.</span>
        </div>
      )}
      {err && <div className="error-box small">{err}</div>}
      <div className="row wrap between">
        <button className="btn" onClick={runCheck} disabled={busy}>{busy ? "Checking…" : "Check eligibility"}</button>
        {(check || cov.last_check) && (
          <span className="small muted" aria-live="polite">
            Last checked {fmtShortDay(check?.checked_at || cov.last_check.checked_at)}: {check?.status || cov.last_check.outcome}
          </span>
        )}
      </div>
    </Section>
  );
}

// --- Estimates -----------------------------------------------------------------------------------

function EstimateTool() {
  const services = useApi("/billing/services");
  const clinicians = useApi("/billing/clinicians");
  const [code, setCode] = useState("");
  const [practitioner, setPractitioner] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function submit(e) {
    e.preventDefault();
    if (!code) return;
    setBusy(true);
    setErr(null);
    try {
      const q = new URLSearchParams({ service_code: code });
      if (practitioner) q.set("practitioner_id", practitioner);
      setResult(await api(`/billing/estimate?${q}`));
    } catch (e2) {
      setErr(e2.message);
      setResult(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section id="estimate-title" title="Estimate a cost" icon={Calculator}>
      {services.error && <div className="error-box small">{services.error.message}</div>}
      <form className="stack" onSubmit={submit}>
        <div className="field">
          <label htmlFor="est-service" className="small strong">Service</label>
          <select id="est-service" value={code} onChange={(e) => { setCode(e.target.value); setResult(null); }} required>
            <option value="">Choose a service</option>
            {services.data?.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="est-clinician" className="small strong">Clinician (optional, checks network)</label>
          <select id="est-clinician" value={practitioner} onChange={(e) => { setPractitioner(e.target.value); setResult(null); }}>
            <option value="">Any in-network clinician</option>
            {clinicians.data?.map((c) => (
              <option key={c.id} value={c.id}>{c.name} · {c.specialty}{c.in_network ? "" : " · out of network"}</option>
            ))}
          </select>
        </div>
        <button className="btn primary" disabled={!code || busy}>{busy ? "Working it out…" : "Get estimate"}</button>
      </form>
      {err && <div className="error-box small">{err}</div>}
      {result && (
        <div className="estimate stack" aria-live="polite">
          <div className="row between wrap">
            <div>
              <div className="tiny muted strong">Estimated you pay</div>
              <div className="big-money">{fmtMoney(result.patient_cents)}</div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div className="tiny muted strong">Plan pays</div>
              <div className="strong">{fmtMoney(result.plan_cents)}</div>
            </div>
          </div>
          {result.network_checked && (
            <span className={`chip ${result.in_network ? "ok" : "warn"}`}>
              {result.practitioner.name}: {result.in_network ? "in network" : "out of network"}
            </span>
          )}
          <table className="money-table">
            <caption className="sr-only">How the estimate adds up</caption>
            <tbody>
              <tr><th scope="row">Allowed amount</th><td>{fmtMoney(result.allowed_cents)}</td></tr>
              {result.copay_cents > 0 && <tr><th scope="row">Copay</th><td>{fmtMoney(result.copay_cents)}</td></tr>}
              {result.deductible_cents > 0 && <tr><th scope="row">Toward deductible</th><td>{fmtMoney(result.deductible_cents)}</td></tr>}
              {result.coinsurance_cents > 0 && <tr><th scope="row">Coinsurance</th><td>{fmtMoney(result.coinsurance_cents)}</td></tr>}
              {result.oop_cap_reduction_cents > 0 && (
                <tr><th scope="row">Out-of-pocket cap</th><td>-{fmtMoney(result.oop_cap_reduction_cents)}</td></tr>
              )}
              <tr className="total"><th scope="row">You pay</th><td>{fmtMoney(result.patient_cents)}</td></tr>
            </tbody>
          </table>
          <details>
            <summary className="small strong">Show the math</summary>
            <ol className="small steps">{result.steps.map((s) => <li key={s}>{s}</li>)}</ol>
          </details>
          <p className="tiny muted">{result.notice} Your actual bill depends on what is billed and how the claim is processed.</p>
        </div>
      )}
    </Section>
  );
}

// --- Claims --------------------------------------------------------------------------------------

function AppealForm({ claim, onDone }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api(`/billing/claims/${claim.id}/appeal`, { method: "POST", body: { reason } });
      onDone();
    } catch (e2) {
      setErr(e2.message);
      setBusy(false);
    }
  }
  return (
    <form className="stack" style={{ gap: 8 }} onSubmit={submit}>
      <label htmlFor={`appeal-${claim.id}`} className="small strong">Why should this be reconsidered?</label>
      <textarea id={`appeal-${claim.id}`} className="edit" value={reason} onChange={(e) => setReason(e.target.value)}
                minLength={10} maxLength={2000} required />
      {err && <div className="error-box small">{err}</div>}
      <button className="btn dark" disabled={busy || reason.trim().length < 10}>Send appeal</button>
    </form>
  );
}

function ClaimRow({ claim, onChanged }) {
  const [open, setOpen] = useState(false);
  const [appealing, setAppealing] = useState(false);
  const s = CLAIM_STATUS[claim.status] || { label: claim.status, tone: "" };
  const eob = claim.eob;
  return (
    <div className="claim">
      <button className="claim-head" aria-expanded={open} aria-controls={`claim-${claim.id}`} onClick={() => setOpen(!open)}>
        <span style={{ flexGrow: 1, textAlign: "left" }}>
          <span className="strong" style={{ display: "block" }}>{claim.service_name}</span>
          <span className="small muted">{fmtDay(claim.service_date)}{claim.practitioner_name ? ` · ${claim.practitioner_name}` : ""}</span>
        </span>
        <span className="stack" style={{ gap: 4, alignItems: "flex-end" }}>
          <span className={`chip ${s.tone}`}>{s.label}</span>
          {eob && <span className="small strong">You owe {fmtMoney(eob.patient_resp_cents)}</span>}
        </span>
        <Chevron size={18} style={{ transform: open ? "rotate(90deg)" : "none" }} />
      </button>
      {open && (
        <div id={`claim-${claim.id}`} className="claim-body stack">
          {eob ? (
            <>
              <div className="tiny muted strong">Explanation of benefits · {claim.payer} · processed {fmtShortDay(eob.adjudicated_at)}</div>
              <table className="money-table">
                <caption className="sr-only">Explanation of benefits for {claim.service_name}</caption>
                <tbody>
                  <tr><th scope="row">Billed by the clinic</th><td>{fmtMoney(claim.billed_cents)}</td></tr>
                  <tr><th scope="row">Allowed by the plan</th><td>{fmtMoney(eob.allowed_cents)}</td></tr>
                  <tr><th scope="row">Plan paid</th><td>{fmtMoney(eob.plan_paid_cents)}</td></tr>
                  {eob.copay_cents > 0 && <tr><th scope="row">Your copay</th><td>{fmtMoney(eob.copay_cents)}</td></tr>}
                  {eob.deductible_cents > 0 && <tr><th scope="row">Toward your deductible</th><td>{fmtMoney(eob.deductible_cents)}</td></tr>}
                  {eob.coinsurance_cents > 0 && <tr><th scope="row">Your coinsurance</th><td>{fmtMoney(eob.coinsurance_cents)}</td></tr>}
                  <tr className="total"><th scope="row">Your responsibility</th><td>{fmtMoney(eob.patient_resp_cents)}</td></tr>
                </tbody>
              </table>
              <p className="tiny muted">The difference between billed and allowed is a plan discount. You don't owe it.</p>
            </>
          ) : (
            <p className="small muted">
              {claim.status === "denied" || claim.status === "appealed"
                ? "No payment was made on this claim."
                : `Billed ${fmtMoney(claim.billed_cents)}. ${claim.payer} is still processing this claim; you won't be billed until it's done.`}
            </p>
          )}
          {claim.denial_reason && (
            <div className="banner warn"><Warning size={15} /> <span>Denied: {claim.denial_reason}</span></div>
          )}
          {claim.status === "appealed" && (
            <div className="banner info">Appeal sent {fmtShortDay(claim.appealed_at)}. We'll update this claim when there's a decision.</div>
          )}
          {claim.status === "denied" && !appealing && (
            <button className="btn" onClick={() => setAppealing(true)}>Appeal this decision</button>
          )}
          {claim.status === "denied" && appealing && <AppealForm claim={claim} onDone={onChanged} />}
        </div>
      )}
    </div>
  );
}

function Claims() {
  const { data, error, loading, reload } = useApi("/billing/claims");
  return (
    <Section id="claims-title" title="Claims" icon={ReceiptIcon}>
      {loading && !data && <div className="skeleton" />}
      {error && <div className="error-box small">{error.message}</div>}
      {data?.length === 0 && <p className="small muted">No claims yet.</p>}
      <div className="list">{data?.map((c) => <ClaimRow key={c.id} claim={c} onChanged={reload} />)}</div>
    </Section>
  );
}

// --- Bills, payments, plans ----------------------------------------------------------------------

function PayForm({ statement, suggested, onDone }) {
  const [text, setText] = useState(centsToInput(suggested ?? statement.balance_cents));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const cents = parseDollars(text);
  const invalid = cents == null || cents <= 0 || cents > statement.balance_cents;

  async function submit(e) {
    e.preventDefault();
    if (invalid) return;
    setBusy(true);
    setErr(null);
    try {
      const p = await api(`/billing/statements/${statement.id}/payments`, { method: "POST", body: { amount_cents: cents } });
      onDone(p);
    } catch (e2) {
      setErr(e2.message);
      setBusy(false);
    }
  }

  return (
    <form className="stack pay-form" style={{ gap: 8 }} onSubmit={submit} noValidate>
      <label htmlFor={`amt-${statement.id}`} className="small strong">Amount (USD)</label>
      <div className="row" style={{ gap: 8 }}>
        <input id={`amt-${statement.id}`} className="money-input" inputMode="decimal" autoComplete="off"
               value={text} onChange={(e) => setText(e.target.value)} aria-invalid={text !== "" && invalid}
               aria-describedby={`amt-help-${statement.id}`} />
        <button className="btn primary" disabled={busy || invalid}>{busy ? "Recording…" : "Pay"}</button>
      </div>
      <span id={`amt-help-${statement.id}`} className="tiny muted">
        Up to {fmtMoney(statement.balance_cents)}. Demo only: no card details are collected and no money moves.
        Real payments go through the hospital's own payment processor.
      </span>
      {err && <div className="error-box small">{err}</div>}
    </form>
  );
}

function PlanForm({ statement, onDone }) {
  const max = Math.min(12, Math.floor(statement.balance_cents / 500));
  const [n, setN] = useState(Math.min(3, max));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  if (max < 2) return <p className="small muted">This balance is too small to split into monthly payments.</p>;
  const base = Math.floor(statement.balance_cents / n);
  const extra = statement.balance_cents % n;

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api(`/billing/statements/${statement.id}/payment-plan`, { method: "POST", body: { installments: Number(n) } });
      onDone();
    } catch (e2) {
      setErr(e2.message);
      setBusy(false);
    }
  }

  return (
    <form className="stack" style={{ gap: 8 }} onSubmit={submit}>
      <label htmlFor={`plan-${statement.id}`} className="small strong">Number of monthly payments</label>
      <div className="row wrap" style={{ gap: 8 }}>
        <select id={`plan-${statement.id}`} className="plan-select" value={n} onChange={(e) => setN(Number(e.target.value))}>
          {Array.from({ length: max - 1 }, (_, i) => i + 2).map((k) => <option key={k} value={k}>{k} months</option>)}
        </select>
        <button className="btn dark" disabled={busy}>{busy ? "Setting up…" : "Set up plan"}</button>
      </div>
      <span className="tiny muted">
        {extra ? `${extra} payment${extra > 1 ? "s" : ""} of ${fmtMoney(base + 1)} then ` : ""}
        {n - extra} of {fmtMoney(base)}. No interest in this demo.
      </span>
      {err && <div className="error-box small">{err}</div>}
    </form>
  );
}

function PlanSchedule({ plan }) {
  return (
    <div className="stack" style={{ gap: 6 }}>
      <span className="small strong">Payment plan · {plan.installments} monthly payments {plan.status === "completed" ? "(complete)" : ""}</span>
      <table className="money-table schedule">
        <caption className="sr-only">Payment plan schedule</caption>
        <thead><tr><th scope="col">Due</th><th scope="col">Amount</th><th scope="col">Status</th></tr></thead>
        <tbody>
          {plan.schedule.map((s) => (
            <tr key={s.id}>
              <td>{fmtDay(s.due_on)}</td>
              <td>{fmtMoney(s.amount_cents)}</td>
              <td>{s.paid ? <span className="chip ok"><Check size={12} /> Paid</span>
                : s.remaining_cents < s.amount_cents ? `${fmtMoney(s.remaining_cents)} left` : "Upcoming"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatementCard({ statement, onChanged, onPaid }) {
  const [mode, setMode] = useState(null); // "pay" | "plan"
  const plan = statement.plan?.status === "active" ? statement.plan : null;
  const next = plan?.next_installment;
  const overdue = statement.status === "overdue";
  return (
    <article className={`bill ${overdue ? "overdue" : ""}`} aria-label={`Bill for ${statement.service_name}`}>
      <div className="row between wrap" style={{ alignItems: "flex-start" }}>
        <div>
          <div className="strong">{statement.service_name}</div>
          <div className="small muted">{fmtDay(statement.service_date)}{statement.practitioner_name ? ` · ${statement.practitioner_name}` : ""}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="big-money">{fmtMoney(statement.balance_cents)}</div>
          <div className={`tiny strong ${overdue ? "alert-text" : "muted"}`}>
            {overdue ? `Overdue since ${fmtShortDay(statement.due_on)}` : `Due ${fmtDay(statement.due_on)}`}
          </div>
        </div>
      </div>
      {statement.adjustments.length > 0 && (
        <div className="banner ok"><Heart size={15} /> Financial assistance applied: -{fmtMoney(statement.adjustments_cents)}</div>
      )}
      {plan && <PlanSchedule plan={plan} />}
      <div className="row wrap" style={{ gap: 8 }}>
        {plan && next ? (
          <button className="btn primary" aria-expanded={mode === "pay"} onClick={() => setMode(mode === "pay" ? null : "pay")}>
            Pay next installment ({fmtMoney(next.remaining_cents)})
          </button>
        ) : (
          <button className="btn primary" aria-expanded={mode === "pay"} onClick={() => setMode(mode === "pay" ? null : "pay")}>Pay</button>
        )}
        {!plan && (
          <button className="btn" aria-expanded={mode === "plan"} onClick={() => setMode(mode === "plan" ? null : "plan")}>Payment plan</button>
        )}
      </div>
      {mode === "pay" && (
        <PayForm statement={statement} suggested={plan && next ? next.remaining_cents : undefined}
                 onDone={(p) => { setMode(null); onPaid(p); }} />
      )}
      {mode === "plan" && <PlanForm statement={statement} onDone={() => { setMode(null); onChanged(); }} />}
    </article>
  );
}

function Bills({ data, error, loading, reload }) {
  const [paid, setPaid] = useState(null);
  const open = data?.statements.filter((s) => s.balance_cents > 0) || [];
  const settled = data?.statements.filter((s) => s.balance_cents <= 0) || [];
  const payments = data?.statements.flatMap((s) => s.payments.map((p) => ({ ...p, service_name: s.service_name }))) || [];
  payments.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));

  return (
    <Section id="bills-title" title="Bills" icon={Wallet}
             aside={data && <span className="small strong">Balance due {fmtMoney(data.balance_due_cents)}</span>}>
      {loading && !data && <div className="skeleton" />}
      {error && <div className="error-box small">{error.message}</div>}
      <div className="banner info"><Lock size={15} /> {data?.payment_notice || "Demo payments only. No card details are collected."}</div>
      {paid && (
        <div className="banner ok" role="status">
          <Check size={15} /> Payment of {fmtMoney(paid.amount_cents)} recorded.{" "}
          <Link to={`/billing/receipts/${paid.id}`}>View receipt {paid.receipt_number}</Link>
        </div>
      )}
      {data && open.length === 0 && <p className="small muted">You're all paid up. Nothing is due.</p>}
      <div className="stack">
        {open.map((s) => (
          <StatementCard key={s.id} statement={s} onChanged={reload} onPaid={(p) => { setPaid(p); reload(); }} />
        ))}
      </div>
      {settled.length > 0 && (
        <details>
          <summary className="small strong">Paid bills ({settled.length})</summary>
          <div className="list" style={{ marginTop: 8 }}>
            {settled.map((s) => (
              <div key={s.id} className="row between small" style={{ padding: "10px 0" }}>
                <span>{s.service_name} · {fmtShortDay(s.service_date)}</span>
                <span className="chip ok"><Check size={12} /> Paid {fmtMoney(s.amount_cents)}</span>
              </div>
            ))}
          </div>
        </details>
      )}
      {payments.length > 0 && (
        <div className="stack" style={{ gap: 6 }}>
          <span className="small strong">Receipts</span>
          <div className="list">
            {payments.map((p) => (
              <Link key={p.id} to={`/billing/receipts/${p.id}`} className="receipt-link">
                <span>{fmtShortDay(p.created_at)} · {p.service_name}</span>
                <span className="row" style={{ gap: 6 }}>{fmtMoney(p.amount_cents)} <Chevron size={16} /></span>
              </Link>
            ))}
          </div>
        </div>
      )}
    </Section>
  );
}

// --- Financial assistance ------------------------------------------------------------------------

const ATTESTATIONS = [
  ["information_accurate", "The information I've given is true and complete."],
  ["will_report_changes", "I'll tell the hospital if my income or household changes."],
  ["consent_to_verify", "The hospital may verify my income if needed."],
];

function Assistance({ onChanged }) {
  const { data, error, loading, reload } = useApi("/billing/assistance-applications");
  const [form, setForm] = useState({ household_size: "1", income_band: "", attestations: {} });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const latest = data?.applications?.[0];
  const pending = latest?.status === "submitted";
  const allChecked = ATTESTATIONS.every(([k]) => form.attestations[k]);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api("/billing/assistance-applications", {
        method: "POST",
        body: {
          household_size: Number(form.household_size),
          income_band: form.income_band,
          attestations: Object.fromEntries(ATTESTATIONS.map(([k]) => [k, Boolean(form.attestations[k])])),
        },
      });
      setShowForm(false);
      reload();
      onChanged();
    } catch (e2) {
      setErr(e2.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section id="assist-title" title="Financial assistance" icon={Heart}>
      {loading && !data && <div className="skeleton" />}
      {error && <div className="error-box small">{error.message}</div>}
      {latest && (
        <div className={`banner ${latest.status === "approved" ? "ok" : latest.status === "denied" ? "warn" : "info"}`} role="status">
          {latest.status === "submitted" && `Application sent ${fmtShortDay(latest.created_at)}. The hospital's billing team is reviewing it.`}
          {latest.status === "approved" && `Approved ${fmtShortDay(latest.decided_at)}: ${latest.discount_pct}% off your open bills.`}
          {latest.status === "denied" && `Not approved ${fmtShortDay(latest.decided_at)}. ${latest.decision_note || ""}`}
        </div>
      )}
      {!pending && !showForm && (
        <>
          <p className="small muted">If paying is hard, you may qualify for a discount based on household size and income.</p>
          <button className="btn" onClick={() => setShowForm(true)}>Apply for assistance</button>
        </>
      )}
      {showForm && data && (
        <form className="stack" onSubmit={submit}>
          <div className="field">
            <label htmlFor="fa-size" className="small strong">People in your household</label>
            <input id="fa-size" type="number" min="1" max="20" value={form.household_size}
                   onChange={(e) => setForm({ ...form, household_size: e.target.value })} required />
          </div>
          <fieldset className="stack" style={{ gap: 6, border: 0, padding: 0, margin: 0 }}>
            <legend className="small strong" style={{ marginBottom: 6 }}>Yearly household income</legend>
            {Object.entries(data.income_bands).map(([k, label]) => (
              <label key={k} className="toggle-row">
                <input type="radio" name="income_band" value={k} checked={form.income_band === k}
                       onChange={() => setForm({ ...form, income_band: k })} required />
                <span className="small">{label}</span>
              </label>
            ))}
          </fieldset>
          <fieldset className="stack" style={{ gap: 6, border: 0, padding: 0, margin: 0 }}>
            <legend className="small strong" style={{ marginBottom: 6 }}>Please confirm</legend>
            {ATTESTATIONS.map(([k, label]) => (
              <label key={k} className="toggle-row">
                <input type="checkbox" checked={Boolean(form.attestations[k])}
                       onChange={(e) => setForm({ ...form, attestations: { ...form.attestations, [k]: e.target.checked } })} />
                <span className="small">{label}</span>
              </label>
            ))}
          </fieldset>
          <p className="tiny muted">Don't upload pay stubs or tax documents here. The billing team will contact you if they need proof.</p>
          {err && <div className="error-box small">{err}</div>}
          <div className="row wrap" style={{ gap: 8 }}>
            <button className="btn primary" disabled={busy || !form.income_band || !allChecked}>{busy ? "Sending…" : "Send application"}</button>
            <button type="button" className="btn ghost" onClick={() => setShowForm(false)}>Cancel</button>
          </div>
        </form>
      )}
    </Section>
  );
}

// --- Page ----------------------------------------------------------------------------------------

export default function Billing() {
  const statements = useApi("/billing/statements");
  useEffect(() => {
    document.title = "Bills & coverage · Bioverse";
  }, []);

  return (
    <PatientPage wide>
      <div className="page-head">
        <div>
          <h1 className="page-title">Bills & coverage</h1>
          <p className="page-sub">What you owe, what your plan covers, and what things will cost.</p>
        </div>
      </div>
      <div className="banner info" style={{ marginBottom: 16 }}>
        <Shield size={15} /> Demo payer: coverage, prices and claims are simulated for this demo. No real insurer is contacted.
      </div>
      <div className="billing-grid">
        <div className="stack">
          <Bills {...statements} />
          <Claims />
        </div>
        <div className="stack">
          <CoverageCard />
          <EstimateTool />
          <Assistance onChanged={statements.reload} />
        </div>
      </div>
    </PatientPage>
  );
}
