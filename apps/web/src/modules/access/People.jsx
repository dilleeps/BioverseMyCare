import { useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { fmtDateTime } from "../../format.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { useSession } from "../../session.jsx";

const ROLE = { admin: "Administrator", staff: "Staff", clinician: "Clinician", patient: "Patient", student: "Medical student" };
const TEAM = { front_desk: "Front desk", pharmacy: "Pharmacy" };
const PROVIDER = { entra: "Microsoft", okta: "Okta", google: "Google" };
const MODE = {
  sso: "Single sign-on only. The demo identity switcher is off.",
  "sso+demo": "Single sign-on, plus the demo identity switcher. Use demo data only.",
  demo: "Demo identity switcher only. Configure single sign-on before real use.",
};

function AddPerson({ onDone }) {
  const blank = { display_name: "", email: "", role: "staff", team: "front_desk", specialty: "", birth_date: "" };
  const [f, setF] = useState(blank);
  const [state, setState] = useState({ busy: false, error: null });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setState({ busy: true, error: null });
    try {
      await api("/admin/users", { method: "POST", body: {
        display_name: f.display_name, email: f.email, role: f.role,
        team: f.role === "staff" ? f.team : null,
        specialty: f.role === "clinician" ? f.specialty : null,
        birth_date: f.role === "patient" ? f.birth_date || null : null,
      } });
      setF(blank);
      setState({ busy: false, error: null });
      onDone();
    } catch (err) {
      setState({ busy: false, error: err.message });
    }
  }

  return (
    <form className="card stack" onSubmit={submit} aria-labelledby="add-h">
      <h2 id="add-h" className="card-title">Add a person</h2>
      <p className="small muted">They sign in with the organization account that uses this email.</p>
      <div className="people-form">
        <label className="stack" style={{ gap: 4 }}><span className="small strong">Name</span>
          <input required value={f.display_name} onChange={set("display_name")} /></label>
        <label className="stack" style={{ gap: 4 }}><span className="small strong">Sign-in email</span>
          <input required type="email" value={f.email} onChange={set("email")} /></label>
        <label className="stack" style={{ gap: 4 }}><span className="small strong">Role</span>
          <select value={f.role} onChange={set("role")}>
            {["staff", "clinician", "admin", "patient"].map((r) => <option key={r} value={r}>{ROLE[r]}</option>)}
          </select></label>
        {f.role === "staff" && (
          <label className="stack" style={{ gap: 4 }}><span className="small strong">Team</span>
            <select value={f.team} onChange={set("team")}>
              <option value="front_desk">Front desk</option><option value="pharmacy">Pharmacy</option>
            </select></label>
        )}
        {f.role === "clinician" && (
          <label className="stack" style={{ gap: 4 }}><span className="small strong">Specialty</span>
            <input required value={f.specialty} onChange={set("specialty")} placeholder="e.g. Cardiology" /></label>
        )}
        {f.role === "patient" && (
          <label className="stack" style={{ gap: 4 }}><span className="small strong">Date of birth</span>
            <input required type="date" value={f.birth_date} onChange={set("birth_date")} /></label>
        )}
      </div>
      {state.error && <div className="error-box" role="alert">{state.error}</div>}
      <div><button className="btn primary" disabled={state.busy}>{state.busy ? "Adding…" : "Add person"}</button></div>
    </form>
  );
}

function PersonRow({ u, meId, onChange }) {
  const [email, setEmail] = useState(u.email);
  const [msg, setMsg] = useState(null);

  async function act(fn, done) {
    setMsg(null);
    try { await fn(); setMsg(done); onChange(); } catch (e) { setMsg(e.message); }
  }
  const patch = (body, done) => act(() => api(`/admin/users/${u.id}`, { method: "PATCH", body }), done);

  return (
    <tr className={u.disabled ? "off" : ""}>
      <td>
        <div className="strong">{u.display_name}</div>
        <div className="small muted">
          {ROLE[u.role] || u.role}{u.team ? ` · ${TEAM[u.team]}` : ""}{u.specialty ? ` · ${u.specialty}` : ""}
          {u.demo_label ? " · demo" : ""}{u.disabled ? " · turned off" : ""}
        </div>
      </td>
      <td>
        <form className="row" style={{ gap: 6 }} onSubmit={(e) => { e.preventDefault(); patch({ email }, "Email saved."); }}>
          <label className="sr-only" htmlFor={`em-${u.id}`}>Sign-in email for {u.display_name}</label>
          <input id={`em-${u.id}`} type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          {email !== u.email && <button className="btn sm">Save</button>}
        </form>
      </td>
      <td>
        {u.identities.length === 0 ? <span className="small muted">Not signed in yet</span> : u.identities.map((i) => (
          <div key={i.id} className="row small" style={{ gap: 6 }}>
            <span className="chip ok">{PROVIDER[i.provider] || i.provider}</span>
            <span className="muted">{i.last_login_at ? fmtDateTime(i.last_login_at) : ""}</span>
            <button type="button" className="btn sm ghost" aria-label={`Unlink ${PROVIDER[i.provider]} account`}
                    onClick={() => act(() => api(`/admin/users/${u.id}/identities/${i.id}`, { method: "DELETE" }), "Unlinked.")}>
              Unlink
            </button>
          </div>
        ))}
      </td>
      <td>
        <div className="row wrap" style={{ gap: 6 }}>
          {u.active_sessions > 0 && (
            <button type="button" className="btn sm" onClick={() => act(() => api(`/admin/users/${u.id}/sign-out`, { method: "POST" }), "Signed out.")}>
              Sign out ({u.active_sessions})
            </button>
          )}
          {u.id !== meId && (
            <button type="button" className={`btn sm ${u.disabled ? "" : "danger"}`}
                    onClick={() => patch({ disabled: !u.disabled }, u.disabled ? "Turned on." : "Turned off.")}>
              {u.disabled ? "Turn on" : "Turn off"}
            </button>
          )}
        </div>
        {msg && <div className="small" role="status">{msg}</div>}
      </td>
    </tr>
  );
}

export default function People() {
  const { me } = useSession();
  const { data, error, loading, reload } = useApi("/admin/users");
  const [q, setQ] = useState("");
  const users = (data?.users || []).filter((u) =>
    !q.trim() || `${u.display_name} ${u.email} ${u.role}`.toLowerCase().includes(q.trim().toLowerCase()));

  return (
    <WorkspaceLayout>
      <div className="page-head">
        <div>
          <div className="eyebrow">Administration</div>
          <h1 className="page-title">People & sign-in</h1>
          <p className="page-sub">Who can use Bioverse One, the email they sign in with, and their linked accounts.</p>
        </div>
      </div>
      {error && <div className="error-box">{error.message}</div>}
      {loading && !data && <div className="card"><div className="skeleton" /></div>}
      {data && (
        <div className="stack">
          <div className="banner info">
            {MODE[data.mode]} {data.providers.length > 0
              ? `Sign-in with: ${data.providers.map((p) => p.label).join(", ")}.`
              : "No identity provider is configured yet."}
          </div>
          <AddPerson onDone={reload} />
          <section className="card stack" aria-labelledby="people-h">
            <div className="row between wrap">
              <h2 id="people-h" className="card-title">Everyone ({data.users.length})</h2>
              <label className="row" style={{ gap: 6 }}>
                <span className="sr-only">Search people</span>
                <input className="people-search" placeholder="Search by name, email or role" value={q}
                       onChange={(e) => setQ(e.target.value)} />
              </label>
            </div>
            <table className="people-table">
              <thead><tr><th scope="col">Person</th><th scope="col">Sign-in email</th><th scope="col">Linked accounts</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>{users.map((u) => <PersonRow key={u.id} u={u} meId={me?.id} onChange={reload} />)}</tbody>
            </table>
          </section>
        </div>
      )}
    </WorkspaceLayout>
  );
}
