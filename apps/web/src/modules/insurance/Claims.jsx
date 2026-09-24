import { useEffect, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { ErrorBox, Loading, SubmissionChip, fmtDay, fmtMoney, fmtWhen } from "./util.jsx";

const METHOD = { ACH: "EFT", CHK: "check", NON: "no payment" };

function ClaimBuilder({ item, onDone, onCancel }) {
  const target = item.claim_id ? { claim_id: item.claim_id } : { encounter_id: item.encounter_id };
  const [draft, setDraft] = useState(null);
  const [dx, setDx] = useState("");
  const [preview, setPreview] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/insurance/claims/draft", { method: "POST", body: target })
      .then((d) => {
        setDraft(d);
        setDx(d.diagnosis_codes.join(", "));
      })
      .catch(setErr);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.claim_id, item.encounter_id]);

  const codes = () => dx.split(/[\s,]+/).filter(Boolean);

  async function run(kind) {
    setBusy(true);
    setErr(null);
    try {
      const r = await api(`/insurance/claims/${kind}`, { method: "POST", body: { ...target, diagnosis_codes: codes() } });
      if (kind === "preview") setPreview(r.x12_837);
      else onDone(r);
    } catch (e) {
      setErr(e);
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  if (!draft) return err ? <ErrorBox error={err} /> : <Loading label="Building the claim" />;
  const line = draft.service_lines[0];
  return (
    <div className="ins-builder stack">
      <dl className="ins-kv">
        <div><dt>Patient</dt><dd>{draft.patient_name}</dd></div>
        <div><dt>Payer</dt><dd>{draft.payer ? `${draft.payer.name} (${draft.payer.payer_id})` : "—"}</dd></div>
        <div><dt>Member ID</dt><dd className="ins-mono">{draft.member_id || "—"}</dd></div>
        <div><dt>Service</dt><dd>{line.procedure_code}{line.modifiers.length ? `-${line.modifiers.join("-")}` : ""} · {fmtMoney(line.charge_cents)} · {fmtDay(line.service_date)}</dd></div>
      </dl>
      {draft.prior_authorization_required && (
        <div className={`banner ${draft.prior_authorization ? "ok" : "warn"}`}>
          {draft.prior_authorization
            ? `Prior authorization ${draft.prior_authorization.payer_reference} will be sent on the claim.`
            : "This payer requires a prior authorization for this service and none is approved. The claim is likely to be denied."}
        </div>
      )}
      <div className="field">
        <label htmlFor={`dx-${draft.claim_id || draft.encounter_id}`} className="small strong">Diagnosis codes (ICD-10-CM, first is principal)</label>
        <input id={`dx-${draft.claim_id || draft.encounter_id}`} value={dx} onChange={(e) => { setDx(e.target.value); setPreview(null); }} />
      </div>
      <ErrorBox error={err} />
      <div className="row wrap" style={{ gap: 8 }}>
        <button type="button" className="btn" disabled={busy} onClick={() => run("preview")}>Preview 837P</button>
        <button type="button" className="btn primary" disabled={busy || draft.problems.length > 0} onClick={() => run("submit")}>
          {busy ? "Sending…" : "Submit claim"}
        </button>
        <button type="button" className="btn ghost" onClick={onCancel}>Cancel</button>
      </div>
      {preview && <pre className="ins-x12" aria-label="837P preview">{preview}</pre>}
    </div>
  );
}

function ReadyList({ items, onSubmitted }) {
  const [open, setOpen] = useState(null);
  const key = (w) => w.claim_id || w.encounter_id;
  if (!items.length) return <p className="small muted">Nothing waiting to be billed.</p>;
  return (
    <div className="list">
      {items.map((w) => (
        <div key={key(w)} className="ins-patient">
          <div className="row between wrap">
            <div style={{ minWidth: 0 }}>
              <div className="strong">{w.patient_name} · {w.service_name}</div>
              <div className="small muted">
                {fmtDay(w.service_date)}{w.practitioner_name ? ` · ${w.practitioner_name}` : ""}
                {w.billed_cents != null ? ` · ${fmtMoney(w.billed_cents)}` : ""}
                {w.claim_id ? " · billing claim" : " · completed visit, no claim yet"}
              </div>
            </div>
            {open !== key(w) && <button type="button" className="btn sm" onClick={() => setOpen(key(w))}>Build claim</button>}
          </div>
          {open === key(w) && (
            <ClaimBuilder item={w} onCancel={() => setOpen(null)} onDone={(r) => { setOpen(null); onSubmitted(r); }} />
          )}
        </div>
      ))}
    </div>
  );
}

function SubmissionRow({ s }) {
  const [detail, setDetail] = useState(null);
  const [err, setErr] = useState(null);
  async function toggle() {
    if (detail) {
      setDetail(null);
      return;
    }
    try {
      setDetail(await api(`/insurance/claims/submissions/${s.id}`));
    } catch (e) {
      setErr(e);
    }
  }
  return (
    <div className="ins-patient">
      <div className="row between wrap">
        <div style={{ minWidth: 0 }}>
          <div className="strong">{s.patient_name} · {s.service_name}</div>
          <div className="small muted">
            {s.patient_control_number} · {s.payer_name} · {fmtMoney(s.total_charge_cents)} · sent {fmtWhen(s.submitted_at)}
            {s.simulated ? " · simulated" : ""}
          </div>
        </div>
        <SubmissionChip status={s.status} />
      </div>
      <div className="small">{s.ack_message}{s.payer_claim_number ? ` · payer claim ${s.payer_claim_number}` : ""}</div>
      {s.denial?.map((d) => (
        <div key={d.reason_code} className="banner warn">{d.plain} (CARC {d.group}-{d.reason_code})</div>
      ))}
      <button type="button" className="btn sm ghost" style={{ alignSelf: "flex-start" }} onClick={toggle} aria-expanded={Boolean(detail)}>
        {detail ? "Hide X12" : "Show X12"}
      </button>
      <ErrorBox error={err} />
      {detail && (
        <div className="stack" style={{ gap: 6 }}>
          <span className="tiny strong">837P</span>
          <pre className="ins-x12">{detail.x12_837}</pre>
          {detail.x12_277ca && (<><span className="tiny strong">277CA</span><pre className="ins-x12">{detail.x12_277ca}</pre></>)}
        </div>
      )}
    </div>
  );
}

function Remittance({ r }) {
  return (
    <div className="ins-patient">
      <div className="row between wrap">
        <div style={{ minWidth: 0 }}>
          <div className="strong">
            {r.payer_name} · {r.payment_cents > 0 ? `${fmtMoney(r.payment_cents)} by ${METHOD[r.payment_method] || r.payment_method}` : "no payment"}
          </div>
          <div className="small muted">Trace {r.trace_number} · paid {fmtDay(r.payment_date)}</div>
        </div>
        <span className="chip">{r.source === "imported" ? "Imported 835" : "Simulated 835"}</span>
      </div>
      {r.claims.map((c) => (
        <div key={c.id} className="ins-remit-claim">
          <div className="row between wrap small">
            <span className="strong">{c.patient_name || "Unmatched"} · {c.patient_control_number}</span>
            <span>{c.status_label}: paid {fmtMoney(c.paid_cents)}, patient {fmtMoney(c.patient_resp_cents)}</span>
          </div>
          <ul className="ins-adjustments">
            {c.adjustments.map((a, i) => (
              <li key={`${a.group}${a.reason_code}${i}`}>
                <span className="ins-mono">{a.group}-{a.reason_code}</span> {fmtMoney(a.amount_cents)}: {a.plain}
              </li>
            ))}
          </ul>
          <div className="tiny muted">Posting: {c.posting_status.replace("_", " ")}. {c.posting_note}</div>
        </div>
      ))}
      {r.provider_adjustments?.length > 0 && (
        <div className="tiny muted">
          Provider adjustments (PLB): {r.provider_adjustments.map((p) => `${p.label} ${fmtMoney(p.amount_cents)}`).join("; ")}
        </div>
      )}
    </div>
  );
}

function ImportRemit({ onDone }) {
  const [text, setText] = useState("");
  const [err, setErr] = useState(null);
  const [msg, setMsg] = useState(null);
  async function submit(e) {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    try {
      const r = await api("/insurance/remittances/import", { method: "POST", body: { x12: text } });
      setMsg(r.duplicate ? "This 835 was already posted." : `Posted ${r.claims.length} claim${r.claims.length === 1 ? "" : "s"}.`);
      setText("");
      onDone();
    } catch (e2) {
      setErr(e2);
    }
  }
  return (
    <details className="ins-details">
      <summary className="strong small">Import an 835 from a clearinghouse portal</summary>
      <form className="stack" onSubmit={submit}>
        <label htmlFor="x12-835" className="small strong">835 file contents</label>
        <textarea id="x12-835" className="edit ins-mono" value={text} onChange={(e) => setText(e.target.value)} placeholder="ISA*00*…" />
        <button className="btn sm dark" style={{ alignSelf: "flex-start" }} disabled={text.length < 106}>Post remittance</button>
        {msg && <p className="small">{msg}</p>}
        <ErrorBox error={err} />
      </form>
    </details>
  );
}

export default function Claims() {
  const { data, error, loading, reload } = useApi("/insurance/claims/worklist");
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  useEffect(() => {
    document.title = "Insurance claims · Bioverse";
  }, []);
  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(null), 3500);
    return () => clearTimeout(t);
  }, [toast]);

  async function fetchRemits() {
    setBusy(true);
    setErr(null);
    try {
      const r = await api("/insurance/remittances/fetch", { method: "POST" });
      setToast(r.remittances ? `${r.remittances} remittance${r.remittances === 1 ? "" : "s"} received, ${r.claims_posted} claim${r.claims_posted === 1 ? "" : "s"} posted.` : "No new remittances.");
      reload();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <WorkspaceLayout>
      <div className="ins-page">
        <div className="page-head">
          <div>
            <h1 className="page-title">Insurance claims</h1>
            <p className="page-sub">Build and send 837P claims, follow 277CA acknowledgments, and post 835 remittances to billing.</p>
          </div>
        </div>
        {data && <div className="banner info" style={{ marginBottom: 14 }}>{data.notice}</div>}
        {error && <ErrorBox error={error} />}
        {loading && !data && <Loading />}
        {data && (
          <div className="ws-grid">
            <div className="span-6 stack">
              <section className="card stack" aria-labelledby="ready-title">
                <h2 id="ready-title" className="card-title">Ready to bill</h2>
                <ReadyList items={data.ready} onSubmitted={(r) => { setToast(`Claim ${r.patient_control_number}: ${r.ack_message}`); reload(); }} />
              </section>
              <section className="card stack" aria-labelledby="sent-title">
                <h2 id="sent-title" className="card-title">Sent claims</h2>
                {data.submissions.length === 0 && <p className="small muted">No claims sent yet.</p>}
                <div className="list">{data.submissions.map((s) => <SubmissionRow key={s.id} s={s} />)}</div>
              </section>
            </div>
            <div className="span-6 stack">
              <section className="card stack" aria-labelledby="remit-title">
                <div className="row between wrap">
                  <h2 id="remit-title" className="card-title">Remittances (835)</h2>
                  <button type="button" className="btn sm primary" onClick={fetchRemits} disabled={busy}>
                    {busy ? "Checking…" : "Check for remittances"}
                  </button>
                </div>
                <p className="tiny muted">The insurance_remits job does this every 15 minutes. In this demo the simulated payer pays or denies accepted claims when asked.</p>
                <ErrorBox error={err} />
                {data.remittances.length === 0 && <p className="small muted">No remittances yet.</p>}
                <div className="list">{data.remittances.map((r) => <Remittance key={r.id} r={r} />)}</div>
                <ImportRemit onDone={reload} />
              </section>
            </div>
          </div>
        )}
        {toast && <div className="toast" role="status">{toast}</div>}
      </div>
    </WorkspaceLayout>
  );
}
