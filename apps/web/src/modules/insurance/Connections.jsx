import { useEffect, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { ErrorBox, Loading, fmtWhen } from "./util.jsx";

const TYPE = { x12_clearinghouse: "X12 through a clearinghouse", fhir_payer_api: "FHIR payer API" };

function PayerCard({ p, urlConfigured, onChanged }) {
  const [gateway, setGateway] = useState(p.gateway || "simulated");
  const [secret, setSecret] = useState(p.credentials_secret_name || "");
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const connected = p.status === "connected";

  async function act(kind) {
    setBusy(kind);
    setErr(null);
    try {
      const body = kind === "connect" ? { gateway, credentials_secret_name: secret.trim() || null } : undefined;
      await api(`/insurance/payers/${p.id}/${kind}`, { method: "POST", body });
      onChanged();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <article className="card stack" aria-labelledby={`payer-${p.id}`}>
      <div className="row between wrap">
        <div style={{ minWidth: 0 }}>
          <h2 id={`payer-${p.id}`} className="card-title">{p.name}</h2>
          <div className="small muted">Payer ID {p.payer_id} · {TYPE[p.connection_type]}</div>
        </div>
        <span className={`chip ${connected ? "ok" : ""}`}>{connected ? `Connected · ${p.gateway === "http" ? "clearinghouse" : "simulated"}` : "Not connected"}</span>
      </div>
      <div className="row wrap" style={{ gap: 6 }}>
        {p.transactions.map((t) => <span key={t} className="chip">{t}</span>)}
      </div>
      {p.fhir_base_url && (
        <p className="small">FHIR endpoint <span className="ins-mono ins-break">{p.fhir_base_url}</span>
          {p.fhir_profiles.length > 0 && <> · {p.fhir_profiles.join(", ")}</>}</p>
      )}
      {p.last_tested_at && (
        <p className={`small ${p.last_test_ok ? "" : "alert-text"}`}>
          Last test {fmtWhen(p.last_tested_at)}: {p.last_test_ok ? "passed" : "failed"}. {p.last_test_message}
        </p>
      )}
      <div className="ins-connect">
        <div className="field">
          <label htmlFor={`gw-${p.id}`} className="small strong">Route</label>
          <select id={`gw-${p.id}`} value={gateway} onChange={(e) => setGateway(e.target.value)}>
            <option value="simulated">Simulated clearinghouse (demo)</option>
            <option value="http" disabled={!urlConfigured}>Clearinghouse over HTTPS{urlConfigured ? "" : " (set BIOVERSE_CLEARINGHOUSE_URL)"}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor={`sec-${p.id}`} className="small strong">Credentials secret name</label>
          <input id={`sec-${p.id}`} value={secret} onChange={(e) => setSecret(e.target.value.toUpperCase())}
                 placeholder="e.g. CLEARINGHOUSE_API_TOKEN" aria-describedby={`sec-help-${p.id}`} autoComplete="off" />
        </div>
      </div>
      <p id={`sec-help-${p.id}`} className="tiny muted">
        The name of an environment variable or Secret Manager secret. Never paste the secret itself: Bioverse stores only the name.
      </p>
      <ErrorBox error={err} />
      <div className="row wrap" style={{ gap: 8 }}>
        <button type="button" className="btn primary" onClick={() => act("connect")} disabled={Boolean(busy)}>
          {connected ? "Save connection" : "Connect"}
        </button>
        <button type="button" className="btn" onClick={() => act("test")} disabled={!connected || Boolean(busy)}>
          {busy === "test" ? "Testing…" : "Run connection test"}
        </button>
        {connected && (
          <button type="button" className="btn ghost" onClick={() => act("disconnect")} disabled={Boolean(busy)}>Disconnect</button>
        )}
      </div>
    </article>
  );
}

export default function Connections() {
  const { data, error, loading, reload } = useApi("/insurance/payers");
  useEffect(() => {
    document.title = "Payer connections · Bioverse";
  }, []);
  return (
    <WorkspaceLayout>
      <div className="ins-page">
        <div className="page-head">
          <div>
            <h1 className="page-title">Payer connections</h1>
            <p className="page-sub">Which insurers this organization exchanges eligibility, claims and remittances with.</p>
          </div>
        </div>
        {error && <ErrorBox error={error} />}
        {loading && !data && <Loading />}
        {data && (
          <div className="stack">
            <div className="banner info">{data.notice}</div>
            {data.card_secret_is_default && (
              <div className="banner warn">
                Digital insurance cards are signed with the development secret. Set BIOVERSE_CARD_SECRET to a long random value before real use.
              </div>
            )}
            <div className="ins-payer-grid">
              {data.payers.map((p) => (
                <PayerCard key={`${p.id}-${p.updated_at}-${p.status}`} p={p} urlConfigured={data.clearinghouse_url_configured} onChanged={reload} />
              ))}
            </div>
          </div>
        )}
      </div>
    </WorkspaceLayout>
  );
}
