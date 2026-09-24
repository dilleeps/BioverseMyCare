import { useEffect, useRef, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { CheckChip, ErrorBox, Loading, PriorAuthChip, ScanIcon, fmtDay, fmtWhen } from "./util.jsx";

// --- Verify a digital card ------------------------------------------------------------------------

function CameraScan({ onCode }) {
  const video = useRef(null);
  const [on, setOn] = useState(false);
  const [err, setErr] = useState(null);
  const supported = typeof window !== "undefined" && "BarcodeDetector" in window;
  const callback = useRef(onCode);
  callback.current = onCode;

  useEffect(() => {
    if (!on) return undefined;
    let stream;
    let timer;
    let stopped = false;
    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
        video.current.srcObject = stream;
        await video.current.play();
        const detector = new window.BarcodeDetector({ formats: ["qr_code"] });
        const tick = async () => {
          if (stopped) return;
          const codes = await detector.detect(video.current).catch(() => []);
          if (codes[0]?.rawValue) {
            callback.current(codes[0].rawValue);
            setOn(false);
            return;
          }
          timer = setTimeout(tick, 300);
        };
        tick();
      } catch {
        setErr("The camera isn't available. Paste the code instead.");
        setOn(false);
      }
    })();
    return () => {
      stopped = true;
      clearTimeout(timer);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [on]);

  if (!supported) return <p className="tiny muted">Camera scanning isn't supported in this browser. Paste the code instead.</p>;
  return (
    <div className="stack" style={{ gap: 8 }}>
      {on && <video ref={video} className="ins-video" muted playsInline aria-label="Camera preview" />}
      <button type="button" className="btn" onClick={() => setOn(!on)}><ScanIcon /> {on ? "Stop camera" : "Scan with camera"}</button>
      {err && <p className="small alert-text">{err}</p>}
    </div>
  );
}

function VerifyCard({ onChecked }) {
  const [token, setToken] = useState("");
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  async function verify(value) {
    const t = (value ?? token).trim();
    if (!t) return;
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      setResult(await api("/insurance/card/verify", { method: "POST", body: { token: t } }));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  async function recheck() {
    setBusy(true);
    try {
      const check = await api(`/insurance/coverage/${result.coverage.id}/eligibility`, { method: "POST" });
      setResult({ ...result, latest_check: check });
      onChecked();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  const c = result?.coverage;
  return (
    <section className="card stack" aria-labelledby="verify-title">
      <h2 id="verify-title" className="card-title">Check in a digital insurance card</h2>
      <p className="small muted">Scan the QR code on the back of the patient's card, or paste the code they read out.</p>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); verify(); }}>
        <label htmlFor="card-token" className="small strong">Card code</label>
        <textarea id="card-token" className="edit ins-mono" style={{ minHeight: 64 }} value={token}
                  onChange={(e) => setToken(e.target.value)} placeholder="BVC1…" spellCheck={false} />
        <div className="row wrap" style={{ gap: 8 }}>
          <button className="btn primary" disabled={busy || !token.trim()}>{busy ? "Checking…" : "Verify card"}</button>
        </div>
      </form>
      <CameraScan onCode={(v) => { setToken(v); verify(v); }} />
      <ErrorBox error={err} />
      {result && (
        <div className="ins-verify stack" aria-live="polite">
          <div className="row between wrap">
            <span className="strong">{result.patient.name} · born {fmtDay(result.patient.birth_date)}</span>
            <span className="chip ok">Code valid</span>
          </div>
          <dl className="ins-kv">
            <div><dt>Payer</dt><dd>{c.payer_display}</dd></div>
            <div><dt>Plan</dt><dd>{c.plan_name}</dd></div>
            <div><dt>Member ID</dt><dd className="ins-mono">{c.member_id}</dd></div>
            <div><dt>Group</dt><dd>{c.group_number || "—"}</dd></div>
            <div><dt>Rx BIN / PCN / Group</dt><dd>{[c.rx_bin, c.rx_pcn, c.rx_group].filter(Boolean).join(" / ") || "—"}</dd></div>
            <div><dt>Coverage dates</dt><dd>{fmtDay(c.effective_start)}{c.effective_end ? ` to ${fmtDay(c.effective_end)}` : " onward"}</dd></div>
          </dl>
          <div className="row between wrap">
            <span className="small">Last eligibility check: <CheckChip status={result.latest_check?.status} />
              {result.latest_check && <span className="muted"> {fmtWhen(result.latest_check.checked_at)}</span>}</span>
            <button type="button" className="btn sm" onClick={recheck} disabled={busy}>Check eligibility now</button>
          </div>
          {result.latest_check && <ul className="ins-summary small">{result.latest_check.summary.map((s) => <li key={s}>{s}</li>)}</ul>}
          {result.dev_secret && (
            <p className="tiny alert-text">This server signs cards with the development secret. Set BIOVERSE_CARD_SECRET before real use.</p>
          )}
        </div>
      )}
    </section>
  );
}

// --- Patients and upcoming visits ---------------------------------------------------------------

function PatientRow({ p, onChanged }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const check = p.coverage?.latest_check;

  async function run() {
    setBusy(true);
    setErr(null);
    try {
      await api(`/insurance/coverage/${p.coverage.id}/eligibility`, { method: "POST" });
      onChanged();
      setOpen(true);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ins-patient">
      <div className="row between wrap">
        <div style={{ minWidth: 0 }}>
          <div className="strong">{p.name}</div>
          <div className="small muted">
            {p.coverage ? `${p.coverage.payer_display} · ${p.coverage.member_id}` : "No active coverage on file"}
            {p.pending_cards > 0 ? ` · ${p.pending_cards} card waiting to verify` : ""}
          </div>
        </div>
        <div className="row wrap" style={{ gap: 6 }}>
          {p.coverage && <CheckChip status={check?.status} />}
          {p.coverage && <button type="button" className="btn sm" onClick={run} disabled={busy}>{busy ? "Checking…" : "Check eligibility"}</button>}
          {check && (
            <button type="button" className="btn sm ghost" aria-expanded={open} onClick={() => setOpen(!open)}>
              {open ? "Hide" : "Benefits"}
            </button>
          )}
        </div>
      </div>
      <ErrorBox error={err} />
      {open && check && (
        <div className="stack" style={{ gap: 6 }}>
          <ul className="ins-summary small">{check.summary.map((s) => <li key={s}>{s}</li>)}</ul>
          <span className="tiny muted">Checked {fmtWhen(check.checked_at)}{check.simulated ? " · simulated" : ""}</span>
        </div>
      )}
    </div>
  );
}

// --- Prior authorizations -------------------------------------------------------------------------

function PriorAuthRow({ a, onChanged }) {
  const [status, setStatus] = useState(a.status);
  const [ref, setRef] = useState(a.payer_reference || "");
  const [note, setNote] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const changed = status !== a.status || ref !== (a.payer_reference || "") || note.trim();

  async function save() {
    setBusy(true);
    setErr(null);
    try {
      await api(`/insurance/prior-auths/${a.id}`, { method: "PATCH",
        body: { status, payer_reference: ref.trim() || null, note: note.trim() || null } });
      setNote("");
      onChanged();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ins-patient">
      <div className="row between wrap">
        <div style={{ minWidth: 0 }}>
          <div className="strong">{a.patient_name} · {a.description}</div>
          <div className="small muted">
            CPT {a.procedure_code} · {a.payer_name} · requested {fmtDay(a.submitted_at)}
            {a.practitioner_name ? ` · ${a.practitioner_name}` : ""}
          </div>
          {a.note && <div className="small">{a.note}</div>}
        </div>
        <PriorAuthChip status={a.status} />
      </div>
      <div className="ins-pa-edit">
        <div className="field">
          <label htmlFor={`pa-s-${a.id}`} className="small strong">Status</label>
          <select id={`pa-s-${a.id}`} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="submitted">Submitted</option>
            <option value="pended">Pended by payer</option>
            <option value="approved">Approved</option>
            <option value="denied">Denied</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor={`pa-r-${a.id}`} className="small strong">Payer reference</label>
          <input id={`pa-r-${a.id}`} value={ref} onChange={(e) => setRef(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor={`pa-n-${a.id}`} className="small strong">Note</label>
          <input id={`pa-n-${a.id}`} value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <button type="button" className="btn sm dark" disabled={!changed || busy} onClick={save}>Update</button>
      </div>
      <ErrorBox error={err} />
    </div>
  );
}

function NewPriorAuth({ patients, onCreated }) {
  const [form, setForm] = useState({ patient_id: "", procedure_code: "", description: "", diagnosis_codes: "" });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api("/insurance/prior-auths", { method: "POST", body: {
        ...form, diagnosis_codes: form.diagnosis_codes.split(/[\s,]+/).filter(Boolean) } });
      setForm({ patient_id: "", procedure_code: "", description: "", diagnosis_codes: "" });
      onCreated();
    } catch (e2) {
      setErr(e2);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="ins-details">
      <summary className="strong small">Request a new prior authorization</summary>
      <form className="ins-pa-edit" onSubmit={submit}>
        <div className="field">
          <label htmlFor="pa-new-patient" className="small strong">Patient</label>
          <select id="pa-new-patient" value={form.patient_id} onChange={set("patient_id")} required>
            <option value="">Choose</option>
            {patients.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="pa-new-cpt" className="small strong">CPT code</label>
          <input id="pa-new-cpt" value={form.procedure_code} onChange={set("procedure_code")} required pattern="[0-9A-Za-z]{5}" />
        </div>
        <div className="field">
          <label htmlFor="pa-new-desc" className="small strong">Service</label>
          <input id="pa-new-desc" value={form.description} onChange={set("description")} required minLength={3} />
        </div>
        <div className="field">
          <label htmlFor="pa-new-dx" className="small strong">Diagnoses (ICD-10)</label>
          <input id="pa-new-dx" value={form.diagnosis_codes} onChange={set("diagnosis_codes")} placeholder="R07.9" />
        </div>
        <button className="btn sm primary" disabled={busy}>Submit request</button>
      </form>
      <ErrorBox error={err} />
    </details>
  );
}

export default function FrontDesk() {
  const { data, error, loading, reload } = useApi("/insurance/front-desk");
  const auths = useApi("/insurance/prior-auths");
  const [showAll, setShowAll] = useState(false);
  useEffect(() => {
    document.title = "Coverage & cards · Bioverse";
  }, []);

  return (
    <WorkspaceLayout>
      <div className="ins-page">
        <div className="page-head">
          <div>
            <h1 className="page-title">Coverage &amp; cards</h1>
            <p className="page-sub">Verify digital cards, run eligibility checks and track prior authorizations.</p>
          </div>
        </div>
        {data && <div className="banner info" style={{ marginBottom: 14 }}>{data.notice}</div>}
        {error && <ErrorBox error={error} />}
        <div className="ws-grid">
          <div className="span-6 stack">
            <VerifyCard onChecked={reload} />
            <section className="card stack" aria-labelledby="upcoming-title">
              <h2 id="upcoming-title" className="card-title">Visits in the next 3 days</h2>
              {loading && !data && <Loading />}
              {data?.upcoming.length === 0 && <p className="small muted">No visits booked in the next three days.</p>}
              <div className="list">
                {data?.upcoming.slice(0, showAll ? undefined : 6).map((u) => (
                  <div key={u.id} className="row between wrap" style={{ padding: "10px 0" }}>
                    <div style={{ minWidth: 0 }}>
                      <div className="strong">{u.patient_name}</div>
                      <div className="small muted">{fmtWhen(u.starts_at)} · {u.practitioner_name}</div>
                    </div>
                    <CheckChip status={u.check_status} />
                  </div>
                ))}
              </div>
              {data?.upcoming.length > 6 && (
                <button type="button" className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => setShowAll(!showAll)}>
                  {showAll ? "Show fewer" : `Show all ${data.upcoming.length} visits`}
                </button>
              )}
              <p className="tiny muted">The insurance_eligibility job re-checks these every morning and notifies the front desk about problems.</p>
            </section>
          </div>
          <div className="span-6 stack">
            <section className="card stack" aria-labelledby="patients-title">
              <h2 id="patients-title" className="card-title">Patients</h2>
              {loading && !data && <Loading />}
              <div className="list">{data?.patients.map((p) => <PatientRow key={p.id} p={p} onChanged={reload} />)}</div>
            </section>
            <section className="card stack" aria-labelledby="pa-title">
              <h2 id="pa-title" className="card-title">Prior authorizations</h2>
              {auths.error && <ErrorBox error={auths.error} />}
              {auths.data?.length === 0 && <p className="small muted">No prior authorizations yet.</p>}
              <div className="list">{auths.data?.map((a) => <PriorAuthRow key={`${a.id}-${a.updated_at}`} a={a} onChanged={auths.reload} />)}</div>
              {data && <NewPriorAuth patients={data.patients} onCreated={auths.reload} />}
            </section>
          </div>
        </div>
      </div>
    </WorkspaceLayout>
  );
}
