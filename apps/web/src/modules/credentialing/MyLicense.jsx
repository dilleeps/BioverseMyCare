import { useEffect, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { fmtDate } from "../../format.js";
import { Shield } from "../../icons.jsx";

const EMPTY = { license_number: "", jurisdiction: "", license_type: "MD", board_certification: "", npi: "", issued_on: "", expires_on: "" };

// Clinicians: see their own licenses and submit a new or renewed one for verification.
export default function MyLicense() {
  const { data, error, loading, reload } = useApi("/credentialing/mine");
  const [form, setForm] = useState(EMPTY);
  const [npiCheck, setNpiCheck] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [done, setDone] = useState(false);

  useEffect(() => { document.title = "My license · Bioverse"; }, []);
  useEffect(() => {
    setNpiCheck(null);
    if (form.npi.length !== 10) return;
    api(`/credentialing/npi/${form.npi}`).then(setNpiCheck).catch(() => {});
  }, [form.npi]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api("/credentialing/mine", {
        method: "POST",
        body: { ...form, board_certification: form.board_certification || null, issued_on: form.issued_on || null },
      });
      setForm(EMPTY);
      setDone(true);
      reload();
    } catch (ex) {
      setErr(ex.message);
    }
    setBusy(false);
  }

  return (
    <WorkspaceLayout>
      <div className="cred-page">
        <div className="page-head">
          <div>
            <h1 className="page-title">My license</h1>
            <p className="page-sub">What patients see behind your "Verified" badge, and what keeps you in the online directory.</p>
          </div>
        </div>
        {error && <div className="error-box">{error.message}</div>}
        {loading && !data && <div className="card"><div className="skeleton" /></div>}
        {data && (
          <div className="stack">
            <div className={`banner ${data.credentialed ? "ok" : "warn"} small`}><Shield size={15} /> <span>{data.message}</span></div>
            {data.credentials.map((c) => (
              <div key={c.id} className="card row between wrap">
                <div className="stack" style={{ gap: 2 }}>
                  <span className="strong">{c.license_type} license {c.license_number} ({c.jurisdiction})</span>
                  <span className="small muted">NPI {c.npi} · expires {fmtDate(c.expires_on)}</span>
                  {c.decision_reason && <span className="small">Reason: {c.decision_reason}</span>}
                </div>
                <span className={`chip ${c.status === "verified" && !c.lapsed ? "ok" : c.status === "pending" ? "" : "warn"}`}>
                  {c.lapsed ? "Lapsed" : c.status_label}
                </span>
              </div>
            ))}
            <form className="card stack" onSubmit={submit} aria-labelledby="new-lic">
              <h2 id="new-lic" className="card-title">Submit a license</h2>
              <div className="cred-form-grid">
                <div className="field"><label htmlFor="l-num" className="small strong">License number</label>
                  <input id="l-num" value={form.license_number} onChange={set("license_number")} maxLength={30} required /></div>
                <div className="field"><label htmlFor="l-jur" className="small strong">State</label>
                  <input id="l-jur" value={form.jurisdiction} onChange={set("jurisdiction")} maxLength={2} placeholder="NY" required /></div>
                <div className="field"><label htmlFor="l-type" className="small strong">Type</label>
                  <select id="l-type" value={form.license_type} onChange={set("license_type")}>
                    {["MD", "DO", "NP", "PA", "RN", "PsyD", "PhD"].map((t) => <option key={t}>{t}</option>)}
                  </select></div>
                <div className="field"><label htmlFor="l-npi" className="small strong">NPI</label>
                  <input id="l-npi" inputMode="numeric" value={form.npi} onChange={set("npi")} maxLength={10} required
                         aria-describedby="npi-help" />
                  <span id="npi-help" className={`tiny ${npiCheck && !npiCheck.valid ? "alert-text" : "muted"}`}>
                    {npiCheck ? (npiCheck.valid ? "Check digit ok" : npiCheck.problem) : "10 digits"}
                  </span></div>
                <div className="field"><label htmlFor="l-iss" className="small strong">Issued</label>
                  <input id="l-iss" type="date" value={form.issued_on} onChange={set("issued_on")} /></div>
                <div className="field"><label htmlFor="l-exp" className="small strong">Expires</label>
                  <input id="l-exp" type="date" value={form.expires_on} onChange={set("expires_on")} required /></div>
              </div>
              <div className="field"><label htmlFor="l-board" className="small strong">Board certification (optional)</label>
                <input id="l-board" value={form.board_certification} onChange={set("board_certification")} maxLength={160} /></div>
              {err && <div className="error-box small">{err}</div>}
              {done && <div className="banner ok small">Submitted. An administrator will verify it.</div>}
              <button className="btn primary" disabled={busy || (npiCheck && !npiCheck.valid)}>Submit for verification</button>
            </form>
          </div>
        )}
      </div>
    </WorkspaceLayout>
  );
}
