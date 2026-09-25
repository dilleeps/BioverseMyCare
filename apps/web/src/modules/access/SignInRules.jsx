import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import "./bulk.css";

const ROLE = { admin: "Administrator", staff: "Staff", clinician: "Clinician", student: "Medical student" };
const TEAM = { front_desk: "Front desk", pharmacy: "Pharmacy" };
const PROVIDER = { entra: "Microsoft Entra", okta: "Okta", google: "Google" };
const CLAIM = { groups: "Group", roles: "App role", hd: "Workspace domain", email_domain: "Email domain" };
const PLACEHOLDER = {
  groups: "Entra: group object id · Okta: group name",
  roles: "The app role's value, e.g. Bioverse.Pharmacist",
  hd: "e.g. yourhospital.org",
  email_domain: "e.g. yourhospital.org",
};

const BLANK = { provider: "", claim: "groups", custom_claim: "", match_value: "", role: "staff", team: "front_desk",
                specialty: "", priority: 100, label: "" };

function fromRule(r) {
  const known = r.claim in CLAIM;
  return { provider: r.provider || "", claim: known ? r.claim : "other", custom_claim: known ? "" : r.claim,
           match_value: r.match_value, role: r.role, team: r.team || "", specialty: r.specialty || "",
           priority: r.priority, label: r.label || "" };
}

function Settings({ settings: saved }) {
  const [settings, setSettings] = useState(saved);
  const [msg, setMsg] = useState(null);
  async function toggle(key, value) {
    setMsg(null);
    setSettings((s) => ({ ...s, [key]: value }));            // show it at once; undo if saving fails
    try { setSettings(await api("/admin/sign-in-rules/settings", { method: "PUT", body: { [key]: value } })); }
    catch (e) { setSettings((s) => ({ ...s, [key]: !value })); setMsg(e.message); }
  }
  return (
    <section className="card stack" aria-labelledby="rules-settings-h">
      <h2 id="rules-settings-h" className="card-title">What rules do</h2>
      <div className="toggle-row">
        <input id="jit" type="checkbox" checked={settings.jit_enabled} onChange={(e) => toggle("jit_enabled", e.target.checked)} />
        <label htmlFor="jit">
          <span className="strong">Create accounts on first sign-in.</span>{" "}
          <span className="muted">Someone without an account who matches a rule gets one, with the rule's role.
          Clinicians start unverified until their license is checked. Patients are never created this way.</span>
        </label>
      </div>
      <div className="toggle-row">
        <input id="sync" type="checkbox" checked={settings.sync_on_sign_in} onChange={(e) => toggle("sync_on_sign_in", e.target.checked)} />
        <label htmlFor="sync">
          <span className="strong">Keep staff roles and teams in sync.</span>{" "}
          <span className="muted">At every sign-in, administrators and staff get the role and team of their first matching
          rule. The last administrator is never demoted; clinicians, patients and students are never changed.</span>
        </label>
      </div>
      {msg && <div className="error-box" role="alert">{msg}</div>}
    </section>
  );
}

function RuleForm({ providers, editing, onSaved, onCancel }) {
  const [f, setF] = useState(editing ? fromRule(editing) : BLANK);
  const [state, setState] = useState({ busy: false, error: null });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setState({ busy: true, error: null });
    const body = {
      provider: f.provider || (editing ? "any" : null),
      claim: f.claim === "other" ? f.custom_claim.trim() : f.claim,
      match_value: f.match_value, role: f.role,
      team: f.role === "staff" ? (f.team || (editing ? "none" : null)) : null,
      specialty: f.role === "clinician" ? f.specialty : null,
      priority: Number(f.priority) || 0, label: f.label,
    };
    try {
      if (editing) await api(`/admin/sign-in-rules/${editing.id}`, { method: "PATCH", body });
      else await api("/admin/sign-in-rules", { method: "POST", body });
      setF(BLANK);
      setState({ busy: false, error: null });
      onSaved();
    } catch (err) {
      setState({ busy: false, error: err.message });
    }
  }

  const providerKeys = Array.from(new Set([...providers.map((p) => p.key), ...Object.keys(PROVIDER)]));
  return (
    <form className="card stack" onSubmit={submit} aria-labelledby="rule-form-h">
      <h2 id="rule-form-h" className="card-title">{editing ? "Edit rule" : "Add a rule"}</h2>
      <div className="people-form">
        <label className="stack" style={{ gap: 4 }}><span className="small strong">Sign-in with</span>
          <select value={f.provider} onChange={set("provider")}>
            <option value="">Any provider</option>
            {providerKeys.map((k) => <option key={k} value={k}>{PROVIDER[k] || k}</option>)}
          </select></label>
        <label className="stack" style={{ gap: 4 }}><span className="small strong">Match on</span>
          <select value={f.claim} onChange={set("claim")}>
            {Object.entries(CLAIM).map(([k, v]) => <option key={k} value={k}>{v} ({k})</option>)}
            <option value="other">Another claim…</option>
          </select></label>
        {f.claim === "other" && (
          <label className="stack" style={{ gap: 4 }}><span className="small strong">Claim name</span>
            <input required value={f.custom_claim} onChange={set("custom_claim")} placeholder="e.g. department" /></label>
        )}
        <label className="stack" style={{ gap: 4 }}><span className="small strong">Value</span>
          <input required value={f.match_value} onChange={set("match_value")} placeholder={PLACEHOLDER[f.claim] || "Exact value"} /></label>
        <label className="stack" style={{ gap: 4 }}><span className="small strong">Gives role</span>
          <select value={f.role} onChange={set("role")}>
            {Object.entries(ROLE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select></label>
        {f.role === "staff" && (
          <label className="stack" style={{ gap: 4 }}><span className="small strong">Team</span>
            <select value={f.team} onChange={set("team")}>
              <option value="">No team</option><option value="front_desk">Front desk</option><option value="pharmacy">Pharmacy</option>
            </select></label>
        )}
        {f.role === "clinician" && (
          <label className="stack" style={{ gap: 4 }}><span className="small strong">Specialty</span>
            <input required value={f.specialty} onChange={set("specialty")} placeholder="e.g. Family medicine" /></label>
        )}
        <label className="stack" style={{ gap: 4 }}><span className="small strong">Order (lower first)</span>
          <input type="number" min="0" max="10000" value={f.priority} onChange={set("priority")} /></label>
        <label className="stack" style={{ gap: 4 }}><span className="small strong">Note (optional)</span>
          <input value={f.label} onChange={set("label")} placeholder="e.g. Pharmacy team in Entra" /></label>
      </div>
      {state.error && <div className="error-box" role="alert">{state.error}</div>}
      <div className="row" style={{ gap: 8 }}>
        <button className="btn primary" disabled={state.busy}>{state.busy ? "Saving…" : editing ? "Save rule" : "Add rule"}</button>
        {editing && <button type="button" className="btn ghost" onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  );
}

function RuleList({ rules, onEdit, onChange }) {
  const [msg, setMsg] = useState(null);
  async function remove(r) {
    if (!window.confirm(`Delete the rule for ${r.match_value}? People who already have accounts keep them.`)) return;
    setMsg(null);
    try { await api(`/admin/sign-in-rules/${r.id}`, { method: "DELETE" }); onChange(); }
    catch (e) { setMsg(e.message); }
  }
  return (
    <section className="card stack" aria-labelledby="rules-h">
      <h2 id="rules-h" className="card-title">Rules ({rules.length})</h2>
      {rules.length === 0 ? (
        <p className="small muted">No rules yet. Without rules, only people added here (or by import) can sign in.</p>
      ) : (
        <div className="bulk-table-wrap">
          <table className="people-table">
            <thead><tr><th scope="col">Order</th><th scope="col">When</th><th scope="col">Then</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.id}>
                  <td className="small">{r.priority}</td>
                  <td>
                    <div><span className="small muted">{CLAIM[r.claim] || r.claim} is </span><code className="bulk-code">{r.match_value}</code></div>
                    <div className="small muted">{r.provider ? PROVIDER[r.provider] : "Any provider"}{r.label ? ` · ${r.label}` : ""}</div>
                  </td>
                  <td className="small">
                    <span className="strong">{ROLE[r.role]}</span>{r.team ? ` · ${TEAM[r.team]}` : ""}{r.specialty ? ` · ${r.specialty}` : ""}
                  </td>
                  <td>
                    <div className="row" style={{ gap: 6 }}>
                      <button type="button" className="btn sm" onClick={() => onEdit(r)}>Edit</button>
                      <button type="button" className="btn sm ghost" onClick={() => remove(r)} aria-label={`Delete rule ${r.match_value}`}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {msg && <div className="error-box" role="alert">{msg}</div>}
    </section>
  );
}

const SAMPLE = `{
  "iss": "https://login.microsoftonline.com/<tenant-id>/v2.0",
  "preferred_username": "someone@yourhospital.org",
  "groups": ["<group object id>"]
}`;

function TryRules({ providers }) {
  const [text, setText] = useState("");
  const [provider, setProvider] = useState("");
  const [state, setState] = useState({ busy: false, error: null, result: null });

  async function run(e) {
    e.preventDefault();
    const input = text.trim();
    let body;
    if (input.startsWith("{")) {
      try { body = { claims: JSON.parse(input) }; }
      catch { setState({ busy: false, error: "That isn't valid JSON. Paste the claims object, or the ID token itself.", result: null }); return; }
    } else {
      body = { token: input };
    }
    if (provider) body.provider = provider;
    setState({ busy: true, error: null, result: null });
    try { setState({ busy: false, error: null, result: await api("/admin/sign-in-rules/test", { method: "POST", body }) }); }
    catch (err) { setState({ busy: false, error: err.message, result: null }); }
  }

  const r = state.result;
  const tone = r && (r.outcome === "not_registered" || r.outcome === "disabled" ? "warn" : "ok");
  return (
    <form className="card stack" onSubmit={run} aria-labelledby="try-h">
      <h2 id="try-h" className="card-title">Test a sign-in</h2>
      <p className="small muted">
        Paste an ID token's claims as JSON, or the token itself (decode one at jwt.ms). Nothing is saved; the signature isn't
        checked. Useful for finding the group ids Entra sends.
      </p>
      <div className="people-form">
        <label className="stack" style={{ gap: 4 }}><span className="small strong">Provider</span>
          <select value={provider} onChange={(e) => setProvider(e.target.value)}>
            <option value="">Work it out from the issuer</option>
            {Array.from(new Set([...providers.map((p) => p.key), ...Object.keys(PROVIDER)])).map((k) =>
              <option key={k} value={k}>{PROVIDER[k] || k}</option>)}
          </select></label>
      </div>
      <label className="stack" style={{ gap: 4 }}><span className="small strong">Claims or ID token</span>
        <textarea className="bulk-textarea" rows={7} spellCheck={false} value={text} placeholder={SAMPLE}
                  onChange={(e) => setText(e.target.value)} /></label>
      <div><button className="btn" disabled={!text.trim() || state.busy}>{state.busy ? "Checking…" : "Test"}</button></div>
      {state.error && <div className="error-box" role="alert">{state.error}</div>}
      {r && (
        <div className="stack" style={{ gap: 8 }} role="status">
          <div className={`banner ${tone}`}>{r.summary}</div>
          <dl className="bulk-facts small">
            <div className="bulk-fact-pair"><dt>Email</dt><dd>{r.email || "none"}</dd></div>
            <div className="bulk-fact-pair"><dt>Provider</dt><dd>{r.provider ? PROVIDER[r.provider] || r.provider : "not recognized: provider-specific rules are tried too"}</dd></div>
            <div className="bulk-fact-pair"><dt>Matching rule</dt>
            <dd>{r.rule ? <>{CLAIM[r.rule.claim] || r.rule.claim} <code className="bulk-code">{r.rule.match_value}</code> → {ROLE[r.rule.role]}{r.rule.team ? ` · ${TEAM[r.rule.team]}` : ""}{r.matched_rules.length > 1 ? ` (first of ${r.matched_rules.length})` : ""}</> : "none"}</dd></div>
            {r.user && <div className="bulk-fact-pair"><dt>Existing account</dt><dd>{r.user.display_name} · {r.user.role}{r.user.team ? ` · ${TEAM[r.user.team]}` : ""}</dd></div>}
            {Object.entries(r.claims_seen).map(([k, v]) => (
              <div key={k} className="bulk-fact-pair"><dt>{k}</dt><dd>{v.length ? v.map((x) => <code key={x} className="bulk-code">{x}</code>) : <span className="muted">not in the token</span>}</dd></div>
            ))}
          </dl>
          {r.warnings.map((w) => <div key={w} className="banner warn small">{w}</div>)}
        </div>
      )}
    </form>
  );
}

export default function SignInRules() {
  const { data, error, loading, reload } = useApi("/admin/sign-in-rules");
  const [editing, setEditing] = useState(null);

  return (
    <WorkspaceLayout>
      <div className="page-head">
        <div>
          <div className="eyebrow"><Link to="/admin/people">People & sign-in</Link></div>
          <h1 className="page-title">Sign-in rules</h1>
          <p className="page-sub">Give people a role from their directory groups (Microsoft Entra, Okta) or Google Workspace domain.</p>
        </div>
      </div>
      {error && <div className="error-box">{error.message}</div>}
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {data && (
        <div className="stack">
          <Settings settings={data.settings} />
          <RuleForm key={editing?.id || "new"} providers={data.providers} editing={editing}
                    onSaved={() => { setEditing(null); reload(); }} onCancel={() => setEditing(null)} />
          <RuleList rules={data.rules} onEdit={(r) => { setEditing(r); window.scrollTo({ top: 0, behavior: "smooth" }); }}
                    onChange={reload} />
          <TryRules providers={data.providers} />
        </div>
      )}
    </WorkspaceLayout>
  );
}
