import { useCallback, useEffect, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { WorkspaceLayout } from "../../layouts.jsx";
import { Lock, Plus } from "../../icons.jsx";
import { DataTable } from "../analytics/charts.jsx";
import { Check, Field, LoadingCard, Select, Toast, useSave } from "../analytics/kit.jsx";
import "../analytics/charts.css";

const DAYS = [["mon", "Mon"], ["tue", "Tue"], ["wed", "Wed"], ["thu", "Thu"], ["fri", "Fri"], ["sat", "Sat"], ["sun", "Sun"]];
const MODES = [{ value: "in_person", label: "In person" }, { value: "video", label: "Video" }, { value: "either", label: "In person or video" }];
const MODE_LABEL = Object.fromEntries(MODES.map((m) => [m.value, m.label]));
const TABS = [["profile", "Profile"], ["locations", "Locations"], ["departments", "Departments"], ["services", "Services"],
  ["providers", "Providers"], ["roles", "Roles"]];

const listText = (v) => (v || []).join(", ");
const toList = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);

function hoursSummary(hours) {
  const open = DAYS.filter(([d]) => hours?.[d]);
  if (!open.length) return "No hours set";
  return open.map(([d, label]) => `${label} ${hours[d].open}–${hours[d].close}`).join(", ");
}

function Status({ active }) {
  return active ? <span className="chip ok">Active</span> : <span className="chip">Inactive</span>;
}

// A list with an "Add" button and an edit panel. `Form` receives { initial, onSaved, onCancel }.
function Registry({ title, path, columns, blank, Form, empty, toast }) {
  const list = useApi(path);
  const [editing, setEditing] = useState(null); // null | "new" | row

  function saved(message) {
    setEditing(null);
    list.reload();
    toast(message);
  }

  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className="row between wrap">
        <h2 className="card-title">{title}</h2>
        {!editing && <button type="button" className="btn primary" onClick={() => setEditing("new")}><Plus size={16} /> Add</button>}
      </div>
      {editing && (
        <Form key={editing === "new" ? "new" : editing.id} initial={editing === "new" ? blank : editing}
              isNew={editing === "new"} onSaved={saved} onCancel={() => setEditing(null)} />
      )}
      {list.error && <div className="error-box" role="alert">{list.error.message}</div>}
      {list.loading && !list.data && <LoadingCard />}
      {list.data?.length === 0 && <div className="card empty">{empty}</div>}
      {list.data?.length > 0 && (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <DataTable
            columns={[...columns, { key: "edit", label: "", render: (r) => (
              <button type="button" className="btn sm" onClick={() => setEditing(r)} aria-label={`Edit ${r.name}`}>Edit</button>
            ) }]}
            rows={list.data.map((r) => ({ ...r, key: r.id }))}
          />
        </div>
      )}
    </div>
  );
}

function FormShell({ title, save, onSubmit, onCancel, children }) {
  return (
    <form className="card stack" onSubmit={(e) => { e.preventDefault(); onSubmit(); }} aria-label={title}>
      <span className="card-title">{title}</span>
      {children}
      {save.error && <div className="error-box" role="alert">{save.error}</div>}
      <div className="row wrap" style={{ gap: 8 }}>
        <button type="submit" className="btn primary" disabled={save.busy}>{save.busy ? "Saving…" : "Save"}</button>
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function useForm(initial) {
  const [form, setForm] = useState(initial);
  const set = (key) => (value) => setForm((f) => ({ ...f, [key]: value }));
  return [form, set, setForm];
}

// --- Profile ---------------------------------------------------------------------------------------------

function Profile({ toast }) {
  const { data, error, loading, reload } = useApi("/org/profile");
  const [form, set, setForm] = useForm(null);
  const save = useSave();
  useEffect(() => { if (data) setForm({ display_name: data.display_name, accent_color: data.accent_color, support_phone: data.support_phone || "" }); }, [data, setForm]);

  if (error) return <div className="error-box" role="alert">{error.message}</div>;
  if (loading || !form) return <LoadingCard />;

  async function submit() {
    const out = await save.run(() => api("/org/profile", { method: "PUT", body: form }));
    if (out) { toast("Profile saved"); reload(); }
  }

  return (
    <form className="card stack" onSubmit={(e) => { e.preventDefault(); submit(); }} aria-label="Organization profile">
      <span className="card-title">Profile and branding</span>
      <div className="form-grid">
        <Field id="org-name" label="Display name" value={form.display_name} onChange={set("display_name")} required minLength={2} maxLength={120} />
        <Field id="org-phone" label="Support phone" type="tel" value={form.support_phone} onChange={set("support_phone")}
               hint="Shown to patients who need help signing in" />
      </div>
      <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0, gap: 6 }}>
        <legend className="small strong" style={{ color: "var(--ink-2)", marginBottom: 6 }}>Accent colour</legend>
        <div className="swatches">
          {data.palette.map((p) => (
            <label key={p.value} className="swatch">
              <input type="radio" name="accent" value={p.value} checked={form.accent_color === p.value}
                     onChange={() => set("accent_color")(p.value)} />
              <span className="chipcolor" style={{ background: p.value }} aria-hidden="true" />
              {p.label}
            </label>
          ))}
        </div>
        <span className="tiny muted">Approved colours all keep white text readable (WCAG AA). The public branding endpoint serves this for future theming.</span>
      </fieldset>
      <div className="row wrap" style={{ gap: 10 }}>
        <span className="small muted">Preview</span>
        <span className="btn sm" style={{ background: form.accent_color, borderColor: form.accent_color, color: "#fff" }} aria-hidden="true">
          {form.display_name || "Organization"}
        </span>
      </div>
      {save.error && <div className="error-box" role="alert">{save.error}</div>}
      <div><button type="submit" className="btn primary" disabled={save.busy}>{save.busy ? "Saving…" : "Save profile"}</button></div>
    </form>
  );
}

// --- Locations ---------------------------------------------------------------------------------------------

function LocationForm({ initial, isNew, onSaved, onCancel }) {
  const [f, set] = useForm({ ...initial, address: initial.address || "", phone: initial.phone || "" });
  const save = useSave();
  async function submit() {
    const body = { name: f.name, kind: f.kind, address: f.kind === "virtual" ? null : f.address, phone: f.phone || null,
      step_free: f.step_free, active: f.active };
    const out = await save.run(() => api(isNew ? "/org/locations" : `/org/locations/${initial.id}`, { method: isNew ? "POST" : "PUT", body }));
    if (out) onSaved(isNew ? "Location added" : "Location saved");
  }
  return (
    <FormShell title={isNew ? "New location" : `Edit ${initial.name}`} save={save} onSubmit={submit} onCancel={onCancel}>
      <div className="form-grid">
        <Field id="loc-name" label="Name" value={f.name} onChange={set("name")} required />
        <Select id="loc-kind" label="Type" value={f.kind} onChange={set("kind")}
                options={[{ value: "physical", label: "Building" }, { value: "virtual", label: "Virtual (video visits)" }]} />
        {f.kind === "physical" && <Field id="loc-addr" label="Address" value={f.address} onChange={set("address")} required />}
        <Field id="loc-phone" label="Phone" type="tel" value={f.phone} onChange={set("phone")} />
      </div>
      <div className="row wrap" style={{ gap: 16 }}>
        <Check id="loc-step" label="Step-free access" checked={f.step_free} onChange={set("step_free")} />
        <Check id="loc-active" label="Active" checked={f.active} onChange={set("active")} />
      </div>
    </FormShell>
  );
}

// --- Departments --------------------------------------------------------------------------------------------

function DepartmentForm({ initial, isNew, onSaved, onCancel }) {
  const locations = useApi("/org/locations");
  const [f, set] = useForm({ ...initial, location_id: initial.location_id || "", hours: { ...initial.hours } });
  const save = useSave();

  function setDay(day, value) {
    set("hours")({ ...f.hours, [day]: value });
  }

  async function submit() {
    const body = { name: f.name, specialty: f.specialty, location_id: f.location_id || null, active: f.active,
      hours: Object.fromEntries(DAYS.map(([d]) => [d, f.hours[d] || null])) };
    const out = await save.run(() => api(isNew ? "/org/departments" : `/org/departments/${initial.id}`, { method: isNew ? "POST" : "PUT", body }));
    if (out) onSaved(isNew ? "Department added" : "Department saved");
  }

  return (
    <FormShell title={isNew ? "New department" : `Edit ${initial.name}`} save={save} onSubmit={submit} onCancel={onCancel}>
      <div className="form-grid">
        <Field id="dep-name" label="Name" value={f.name} onChange={set("name")} required />
        <Field id="dep-spec" label="Specialty" value={f.specialty} onChange={set("specialty")} required
               hint="Matches clinicians' specialty for capacity reporting" />
        <Select id="dep-loc" label="Location" value={f.location_id} onChange={set("location_id")}
                options={[{ value: "", label: "Not set" }, ...(locations.data || []).filter((l) => l.active || l.id === f.location_id).map((l) => ({ value: l.id, label: l.name }))]} />
      </div>
      <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0, gap: 6 }}>
        <legend className="small strong" style={{ color: "var(--ink-2)", marginBottom: 6 }}>Opening hours</legend>
        {DAYS.map(([d, label]) => {
          const h = f.hours[d];
          return (
            <div key={d} className="hours-row">
              <span className="small strong">{label}</span>
              <Check id={`dep-${d}-open`} label="Open" checked={Boolean(h)}
                     onChange={(on) => setDay(d, on ? { open: "08:00", close: "17:00" } : null)} />
              {h ? (
                <>
                  <div className="fld">
                    <label htmlFor={`dep-${d}-from`} className="sr-only">{label} opens</label>
                    <input id={`dep-${d}-from`} type="time" value={h.open} onChange={(e) => setDay(d, { ...h, open: e.target.value })} required />
                  </div>
                  <div className="fld">
                    <label htmlFor={`dep-${d}-to`} className="sr-only">{label} closes</label>
                    <input id={`dep-${d}-to`} type="time" value={h.close} onChange={(e) => setDay(d, { ...h, close: e.target.value })} required />
                  </div>
                </>
              ) : <span className="small muted" style={{ gridColumn: "span 2" }}>Closed</span>}
            </div>
          );
        })}
      </fieldset>
      <Check id="dep-active" label="Active" checked={f.active} onChange={set("active")} />
    </FormShell>
  );
}

// --- Services -----------------------------------------------------------------------------------------------

function ServiceForm({ initial, isNew, onSaved, onCancel }) {
  const departments = useApi("/org/departments");
  const [f, set] = useForm({ ...initial });
  const save = useSave();
  useEffect(() => {
    if (!f.department_id && departments.data?.length) set("department_id")(departments.data[0].id);
  }, [departments.data]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit() {
    const body = { name: f.name, department_id: f.department_id, duration_min: Number(f.duration_min), mode: f.mode, active: f.active };
    const out = await save.run(() => api(isNew ? "/org/services" : `/org/services/${initial.id}`, { method: isNew ? "POST" : "PUT", body }));
    if (out) onSaved(isNew ? "Service added" : "Service saved");
  }
  return (
    <FormShell title={isNew ? "New service" : `Edit ${initial.name}`} save={save} onSubmit={submit} onCancel={onCancel}>
      {departments.data?.length === 0 && <div className="banner info">Add a department first.</div>}
      <div className="form-grid">
        <Field id="svc-name" label="Name" value={f.name} onChange={set("name")} required />
        <Select id="svc-dep" label="Department" value={f.department_id} onChange={set("department_id")}
                options={(departments.data || []).map((d) => ({ value: d.id, label: d.name }))} />
        <Field id="svc-dur" label="Duration (minutes)" type="number" min={5} max={240} step={5} value={f.duration_min}
               onChange={set("duration_min")} required hint="5 to 240, in 5-minute steps" />
        <Select id="svc-mode" label="Mode" value={f.mode} onChange={set("mode")} options={MODES} />
      </div>
      <Check id="svc-active" label="Active" checked={f.active} onChange={set("active")} />
    </FormShell>
  );
}

// --- Providers ---------------------------------------------------------------------------------------------

function ProviderForm({ initial, isNew, onSaved, onCancel }) {
  const locations = useApi("/org/locations");
  const [f, set] = useForm({ ...initial, location_id: initial.location_id || "", languages: listText(initial.languages),
    accessibility: listText(initial.accessibility), accepted_plans: listText(initial.accepted_plans) });
  const save = useSave();
  useEffect(() => {
    if (!f.location_id && locations.data?.length) set("location_id")(locations.data.find((l) => l.active)?.id || "");
  }, [locations.data]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit() {
    const body = { name: f.name, specialty: f.specialty, location_id: f.location_id, languages: toList(f.languages),
      accessibility: toList(f.accessibility), accepted_plans: toList(f.accepted_plans), offers_telehealth: f.offers_telehealth };
    const out = await save.run(() => api(isNew ? "/org/providers" : `/org/providers/${initial.id}`, { method: isNew ? "POST" : "PUT", body }));
    if (out) onSaved(isNew ? "Provider added" : "Provider saved");
  }
  return (
    <FormShell title={isNew ? "New provider" : `Edit ${initial.name}`} save={save} onSubmit={submit} onCancel={onCancel}>
      <div className="form-grid">
        <Field id="pr-name" label="Name" value={f.name} onChange={set("name")} required />
        <Field id="pr-spec" label="Specialty" value={f.specialty} onChange={set("specialty")} required />
        <Select id="pr-loc" label="Location" value={f.location_id} onChange={set("location_id")}
                options={(locations.data || []).filter((l) => l.active || l.id === f.location_id).map((l) => ({ value: l.id, label: l.name }))} />
        <Field id="pr-lang" label="Languages" value={f.languages} onChange={set("languages")} required hint="Separate with commas" />
        <Field id="pr-acc" label="Accessibility" value={f.accessibility} onChange={set("accessibility")} hint="For example: Step-free access" />
        <Field id="pr-plans" label="Accepted plans" value={f.accepted_plans} onChange={set("accepted_plans")} hint="Separate with commas" />
      </div>
      <Check id="pr-tele" label="Offers telehealth" checked={f.offers_telehealth} onChange={set("offers_telehealth")} />
    </FormShell>
  );
}

// --- Roles -------------------------------------------------------------------------------------------------

function Roles() {
  const { data, error, loading } = useApi("/org/users");
  if (error) return <div className="error-box" role="alert">{error.message}</div>;
  if (loading || !data) return <LoadingCard />;
  const counts = data.role_counts;
  return (
    <div className="stack" style={{ gap: 14 }}>
      <h2 className="card-title">Roles</h2>
      <div className="banner info"><Lock size={15} /> {data.note}</div>
      <p className="small muted">
        {Object.entries(counts).map(([r, n]) => `${n} ${r}${n === 1 ? "" : "s"}`).join(" · ")}. Patient accounts are counted, not listed.
      </p>
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <DataTable
          columns={[
            { key: "display_name", label: "Name" },
            { key: "email", label: "Email" },
            { key: "role", label: "Role", render: (r) => <span className="chip">{r.role}</span> },
            { key: "practitioner", label: "Directory entry", render: (r) => (r.practitioner_name ? `${r.practitioner_name} · ${r.specialty}` : "—") },
          ]}
          rows={data.users.map((u) => ({ ...u, key: u.id }))}
        />
      </div>
    </div>
  );
}

export default function Organization() {
  const [tab, setTab] = useState("profile");
  const [toast, setToast] = useState(null);
  const clearToast = useCallback(() => setToast(null), []);

  function onKey(e) {
    const i = TABS.findIndex(([k]) => k === tab);
    const next = e.key === "ArrowRight" ? (i + 1) % TABS.length : e.key === "ArrowLeft" ? (i - 1 + TABS.length) % TABS.length : null;
    if (next === null) return;
    e.preventDefault();
    setTab(TABS[next][0]);
    document.getElementById(`tab-${TABS[next][0]}`)?.focus();
  }

  return (
    <WorkspaceLayout>
      <header className="ops-header">
        <div>
          <h1 className="page-title">Organization</h1>
          <p className="page-sub">Profile, sites, departments, services and the provider directory patients are matched against. Every change is audited.</p>
        </div>
      </header>
      <div className="tabs" role="tablist" aria-label="Organization settings" onKeyDown={onKey}>
        {TABS.map(([k, label]) => (
          <button key={k} id={`tab-${k}`} type="button" role="tab" aria-selected={tab === k} aria-controls={`panel-${k}`}
                  tabIndex={tab === k ? 0 : -1} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>
      <section id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {tab === "profile" && <Profile toast={setToast} />}
        {tab === "locations" && (
          <Registry title="Locations" path="/org/locations" empty="No locations yet." toast={setToast} Form={LocationForm}
                    blank={{ name: "", kind: "physical", address: "", phone: "", step_free: false, active: true }}
                    columns={[
                      { key: "name", label: "Name" },
                      { key: "kind", label: "Type", render: (r) => (r.kind === "virtual" ? "Virtual" : r.address) },
                      { key: "step_free", label: "Step-free", render: (r) => (r.step_free ? "Yes" : "No") },
                      { key: "providers", label: "Providers", num: true },
                      { key: "active", label: "Status", render: (r) => <Status active={r.active} /> },
                    ]} />
        )}
        {tab === "departments" && (
          <Registry title="Departments" path="/org/departments" empty="No departments yet." toast={setToast} Form={DepartmentForm}
                    blank={{ name: "", specialty: "", location_id: "", hours: {}, active: true }}
                    columns={[
                      { key: "name", label: "Name" },
                      { key: "specialty", label: "Specialty" },
                      { key: "location_name", label: "Location", render: (r) => r.location_name || "—" },
                      { key: "hours", label: "Hours", render: (r) => <span className="small">{hoursSummary(r.hours)}</span> },
                      { key: "active", label: "Status", render: (r) => <Status active={r.active} /> },
                    ]} />
        )}
        {tab === "services" && (
          <Registry title="Services and appointment types" path="/org/services" empty="No services yet." toast={setToast} Form={ServiceForm}
                    blank={{ name: "", department_id: "", duration_min: 20, mode: "in_person", active: true }}
                    columns={[
                      { key: "name", label: "Name" },
                      { key: "department_name", label: "Department" },
                      { key: "duration_min", label: "Minutes", num: true },
                      { key: "mode", label: "Mode", render: (r) => MODE_LABEL[r.mode] },
                      { key: "active", label: "Status", render: (r) => <Status active={r.active} /> },
                    ]} />
        )}
        {tab === "providers" && (
          <Registry title="Provider directory" path="/org/providers" empty="No providers yet." toast={setToast} Form={ProviderForm}
                    blank={{ name: "", specialty: "", location_id: "", languages: ["English"], accessibility: [], accepted_plans: [], offers_telehealth: false }}
                    columns={[
                      { key: "name", label: "Name" },
                      { key: "specialty", label: "Specialty" },
                      { key: "location_name", label: "Location" },
                      { key: "languages", label: "Languages", render: (r) => listText(r.languages) },
                      { key: "offers_telehealth", label: "Telehealth", render: (r) => (r.offers_telehealth ? "Yes" : "No") },
                    ]} />
        )}
        {tab === "roles" && <Roles />}
      </section>
      <Toast message={toast} onDone={clearToast} />
    </WorkspaceLayout>
  );
}
