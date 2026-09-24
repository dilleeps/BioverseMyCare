import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { fmtDate, initials } from "../../format.js";
import { Check, Chevron, Lock, Phone, Plus, Shield } from "../../icons.jsx";

// RelatedPerson.relationship is the caregiver's relationship to the patient. Seen from the caregiver's
// side, the person they care for is the inverse.
const THEY_ARE = { child: "Parent", parent: "Child", spouse: "Spouse", other: "Family or friend" };
const REL_LABEL = { parent: "Parent", child: "Child", spouse: "Spouse or partner", other: "Other" };

// A chosen end date means "until the end of that day" where the patient is.
function endOfDay(isoDate) {
  return isoDate ? new Date(`${isoDate}T23:59:59`).toISOString() : null;
}
function toDateInput(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function tomorrow() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return toDateInput(d.toISOString());
}

function PermissionBoxes({ idPrefix, catalog, value, onChange, legend = "What they can see and do" }) {
  return (
    <fieldset className="fm-perms">
      <legend>{legend}</legend>
      {catalog.map((p) => (
        <label key={p.id} className="fm-perm" htmlFor={`${idPrefix}-${p.id}`}>
          <input id={`${idPrefix}-${p.id}`} type="checkbox" checked={value.includes(p.id)}
                 onChange={(e) => onChange(e.target.checked ? [...value, p.id] : value.filter((x) => x !== p.id))} />
          {p.label}
        </label>
      ))}
    </fieldset>
  );
}

function CaregiverRow({ c, patientId, catalog, relationships, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [perms, setPerms] = useState(c.permissions);
  const [rel, setRel] = useState(c.relationship);
  const [until, setUntil] = useState(toDateInput(c.expires_at));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const active = c.status === "active";

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/family/patients/${patientId}/caregivers`, {
        method: "PUT",
        body: { user_id: c.user_id, relationship: rel, permissions: perms, proxy: c.proxy && active, expires_at: endOfDay(until) },
      });
      setEditing(false);
      await onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function revoke() {
    setBusy(true);
    setError(null);
    try {
      await api(`/family/patients/${patientId}/caregivers/${c.user_id}`, { method: "DELETE" });
      await onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const labels = Object.fromEntries(catalog.map((p) => [p.id, p.label]));
  return (
    <article className="card stack" aria-labelledby={`cg-${c.user_id}`}>
      <div className="row between wrap">
        <div className="fm-person">
          <span className="avatar" aria-hidden="true">{initials(c.name)}</span>
          <div>
            <h3 id={`cg-${c.user_id}`} className="card-title">{c.name}</h3>
            <div className="small muted">{REL_LABEL[c.relationship] || "Other"} · {c.email}</div>
          </div>
        </div>
        <span className={`chip ${active ? "ok" : "warn"}`}>
          {active ? "Has access" : c.status === "expired" ? "Access ended" : "Access removed"}
        </span>
      </div>
      {!editing && (
        <>
          <div className="fm-chips">
            {c.proxy && <span className="chip solid">Full proxy</span>}
            {!c.proxy && c.permissions.map((p) => <span key={p} className="chip">{labels[p]}</span>)}
          </div>
          <div className="small muted">
            {c.expires_at ? `${active ? "Until" : "Ended"} ${fmtDate(c.expires_at)}` : "No end date"}
          </div>
          {c.results_need_own_consent && (
            <div className="small muted">Results stay private until you choose to share them yourself.</div>
          )}
          <div className="row wrap">
            <button className="btn sm" onClick={() => setEditing(true)}>{active ? "Change access" : "Give access again"}</button>
            {active && <button className="btn sm danger" onClick={revoke} disabled={busy}>Remove access</button>}
          </div>
        </>
      )}
      {editing && (
        <form className="stack" onSubmit={save}>
          {c.proxy && active
            ? <p className="small muted">{c.name} is your full proxy and can see and do everything below.</p>
            : <PermissionBoxes idPrefix={`edit-${c.user_id}`} catalog={catalog} value={perms} onChange={setPerms} />}
          <div className="fm-grid">
            <div className="fm-field">
              <label htmlFor={`rel-${c.user_id}`}>Relationship to you</label>
              <select id={`rel-${c.user_id}`} value={rel} onChange={(e) => setRel(e.target.value)}>
                {relationships.map((r) => <option key={r} value={r}>{REL_LABEL[r]}</option>)}
              </select>
            </div>
            <div className="fm-field">
              <label htmlFor={`until-${c.user_id}`}>Access ends (optional)</label>
              <input id={`until-${c.user_id}`} type="date" min={tomorrow()} value={until} onChange={(e) => setUntil(e.target.value)} />
            </div>
          </div>
          <div className="row">
            <button className="btn primary" disabled={busy || (!c.proxy && perms.length === 0)}>{busy ? "Saving…" : "Save"}</button>
            <button type="button" className="btn ghost" onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </form>
      )}
      {error && <div className="error-box">{error}</div>}
    </article>
  );
}

function AddCaregiver({ patientId, catalog, relationships, onAdded }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [rel, setRel] = useState("spouse");
  const [perms, setPerms] = useState(["view_appointments"]);
  const [until, setUntil] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function add(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/family/patients/${patientId}/caregivers`, {
        method: "PUT",
        body: { email, relationship: rel, permissions: perms, expires_at: endOfDay(until) },
      });
      setOpen(false);
      setEmail("");
      await onAdded();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) return <button className="btn" onClick={() => setOpen(true)}><Plus size={16} /> Add someone</button>;
  return (
    <form className="card stack" onSubmit={add} aria-label="Give someone access">
      <div className="card-title">Give someone access</div>
      <p className="small muted">They need their own Bioverse account. You can change or remove this at any time.</p>
      <div className="fm-grid">
        <div className="fm-field">
          <label htmlFor="cg-email">Their email</label>
          <input id="cg-email" type="email" required autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="fm-field">
          <label htmlFor="cg-rel">Relationship to you</label>
          <select id="cg-rel" value={rel} onChange={(e) => setRel(e.target.value)}>
            {relationships.map((r) => <option key={r} value={r}>{REL_LABEL[r]}</option>)}
          </select>
        </div>
      </div>
      <PermissionBoxes idPrefix="new" catalog={catalog} value={perms} onChange={setPerms} />
      <div className="fm-field">
        <label htmlFor="cg-until">Access ends (optional)</label>
        <input id="cg-until" type="date" min={tomorrow()} value={until} onChange={(e) => setUntil(e.target.value)} />
      </div>
      {error && <div className="error-box">{error}</div>}
      <div className="row">
        <button className="btn primary" disabled={busy || perms.length === 0}>{busy ? "Saving…" : "Give access"}</button>
        <button type="button" className="btn ghost" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </form>
  );
}

function EmergencyContacts({ patientId, contacts, onChanged }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", relationship: "", phone: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function add(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/family/patients/${patientId}/emergency-contacts`, { method: "POST", body: form });
      setForm({ name: "", relationship: "", phone: "" });
      setOpen(false);
      await onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(id) {
    setError(null);
    try {
      await api(`/family/patients/${patientId}/emergency-contacts/${id}`, { method: "DELETE" });
      await onChanged();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <section className="fm-section" aria-labelledby="fm-contacts">
      <div className="fm-head">
        <div>
          <h2 id="fm-contacts" className="fm-section-title">Emergency contacts</h2>
          <div className="page-sub">Who your care team should call. Contacts can't see your record.</div>
        </div>
      </div>
      <div className="card" style={{ padding: "4px 18px" }}>
        {contacts.length === 0 && <div className="empty">No emergency contacts yet.</div>}
        <div className="list">
          {contacts.map((c) => (
            <div key={c.id} className="row between wrap" style={{ padding: "12px 0" }}>
              <div>
                <div className="strong">{c.name}</div>
                <div className="small muted">{c.relationship}{c.notes ? ` · ${c.notes}` : ""}</div>
              </div>
              <div className="row">
                <a className="btn sm" href={`tel:${c.phone}`}><Phone size={14} /> {c.phone}</a>
                <button className="btn sm ghost" onClick={() => remove(c.id)} aria-label={`Remove ${c.name}`}>Remove</button>
              </div>
            </div>
          ))}
        </div>
      </div>
      {error && <div className="error-box" style={{ marginTop: 10 }}>{error}</div>}
      <div style={{ marginTop: 12 }}>
        {!open && <button className="btn" onClick={() => setOpen(true)}><Plus size={16} /> Add a contact</button>}
        {open && (
          <form className="card stack" onSubmit={add} aria-label="Add an emergency contact">
            <div className="fm-grid">
              <div className="fm-field">
                <label htmlFor="ec-name">Name</label>
                <input id="ec-name" required minLength={2} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div className="fm-field">
                <label htmlFor="ec-rel">Relationship</label>
                <input id="ec-rel" required minLength={2} placeholder="e.g. Sister" value={form.relationship}
                       onChange={(e) => setForm({ ...form, relationship: e.target.value })} />
              </div>
              <div className="fm-field">
                <label htmlFor="ec-phone">Phone</label>
                <input id="ec-phone" type="tel" required minLength={5} value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
              </div>
            </div>
            <div className="row">
              <button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Add contact"}</button>
              <button type="button" className="btn ghost" onClick={() => setOpen(false)}>Cancel</button>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}

export default function Family() {
  const { data, error, loading, reload } = useApi("/family/me");

  return (
    <main className="column">
      <div className="stack" style={{ gap: 2 }}>
        <span className="eyebrow">Family</span>
        <h1 className="page-title">Family & caregivers</h1>
        <span className="page-sub">Care is often shared. You decide who sees what, and every view is recorded.</span>
      </div>
      {error && <div className="error-box" style={{ marginTop: 16 }}>{error.message}</div>}
      {loading && !data && <div className="card" style={{ marginTop: 16 }}><div className="skeleton" /></div>}

      {data && (
        <>
          <section className="fm-section" aria-labelledby="fm-care-for">
            <div className="fm-head">
              <h2 id="fm-care-for" className="fm-section-title">People I care for</h2>
            </div>
            {data.caring_for.length === 0 && (
              <div className="card empty">No one has shared their care with you yet. They can add you from their own account.</div>
            )}
            <div className="stack">
              {data.caring_for.map((p) => (
                <Link key={p.patient_id} to={`/family/${p.patient_id}`} className="hub-card" aria-label={`Open ${p.name}'s care`}>
                  <span className="avatar" aria-hidden="true" style={{ width: 44, height: 44, background: "var(--accent-soft)", color: "var(--accent-strong)", fontSize: 14 }}>
                    {initials(p.name)}
                  </span>
                  <span style={{ flexGrow: 1 }} className="stack">
                    <span>
                      <span className="strong" style={{ display: "block" }}>{p.name}</span>
                      <span className="small muted">{THEY_ARE[p.relationship]} · {p.age}</span>
                    </span>
                    <span className="fm-chips">
                      {p.proxy ? <span className="chip solid">Full proxy</span>
                               : <span className="chip">{p.permissions.length} permission{p.permissions.length === 1 ? "" : "s"}</span>}
                      {p.expires_at && <span className="chip">Until {fmtDate(p.expires_at)}</span>}
                    </span>
                  </span>
                  <Chevron size={18} />
                </Link>
              ))}
            </div>
          </section>

          {data.me && (
            <>
              <section className="fm-section" aria-labelledby="fm-who">
                <div className="fm-head">
                  <div>
                    <h2 id="fm-who" className="fm-section-title">Who can see my care</h2>
                    <div className="page-sub row" style={{ gap: 6 }}><Shield size={14} /> Only what you tick. You can remove access at any time.</div>
                  </div>
                </div>
                {data.me.adolescent && (
                  <div className="banner info" style={{ marginBottom: 10 }}>
                    <Lock size={14} /> Your results stay private unless you choose to share them.
                  </div>
                )}
                <div className="stack">
                  {data.me.caregivers.length === 0 && <div className="card empty">Only you and your care team can see your record.</div>}
                  {data.me.caregivers.map((c) => (
                    <CaregiverRow key={c.user_id} c={c} patientId={data.me.patient_id} catalog={data.permissions}
                                  relationships={data.relationships} onChanged={reload} />
                  ))}
                  <AddCaregiver patientId={data.me.patient_id} catalog={data.permissions} relationships={data.relationships} onAdded={reload} />
                </div>
              </section>
              <EmergencyContacts patientId={data.me.patient_id} contacts={data.me.emergency_contacts} onChanged={reload} />
            </>
          )}
          <p className="tiny muted" style={{ marginTop: 24 }}>
            <Check size={12} /> Every time someone views or acts on your care, it's recorded with their name.
          </p>
        </>
      )}
    </main>
  );
}
