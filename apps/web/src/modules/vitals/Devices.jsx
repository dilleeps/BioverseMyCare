import { useState } from "react";
import { api } from "../../api.js";
import { fmtDateTime } from "../../format.js";
import { Upload } from "./icons.jsx";
import { SafetyMessage } from "./shared.jsx";

const FORMATS = [
  { key: "apple_health", label: "Apple Health export (export.xml)", accept: ".xml,text/xml" },
  { key: "csv", label: "CSV file", accept: ".csv,text/csv" },
  { key: "json", label: "JSON file", accept: ".json,application/json" },
];
const MEASURE_LABEL = { bp: "blood pressure", heart_rate: "heart rate", spo2: "oxygen", temperature: "temperature",
  glucose: "glucose", weight: "weight", steps: "steps", sleep: "sleep" };

// Read-only device list for clinicians; patients also get connect, disconnect and import.
export function DeviceList({ devices, editable, onChanged }) {
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);

  async function toggle(d) {
    setBusy(d.id);
    setErr(null);
    try {
      await api(`/vitals/devices/${d.id}/${d.status === "connected" ? "disconnect" : "connect"}`, { method: "POST" });
      await onChanged();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  }

  if (!devices.length) return <p className="small muted">No devices connected yet.</p>;
  return (
    <>
      <ul className="list vt-list vt-devices">
        {devices.map((d) => (
          <li key={d.id} className="row between wrap">
            <span>
              <span className="strong">{d.label}</span>
              <br />
              <span className="tiny muted">
                {d.kind_label} · {d.integration_label}
                {d.last_sync ? ` · last reading ${fmtDateTime(d.last_sync)}` : " · no readings yet"} · {d.readings} readings
              </span>
            </span>
            <span className="row" style={{ gap: 6 }}>
              <span className={`chip ${d.status === "connected" ? "ok" : ""}`}>{d.status === "connected" ? "Connected" : "Disconnected"}</span>
              {d.simulated && <span className="chip">Demo</span>}
              {editable && (
                <button className="btn sm" disabled={busy === d.id} onClick={() => toggle(d)}>
                  {d.status === "connected" ? "Disconnect" : "Reconnect"}
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>
      {err && <div className="error-box small">{err}</div>}
    </>
  );
}

export function ConnectDevice({ meta, onDone }) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ kind: "bp_cuff", integration: "bluetooth", vendor: "", model: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api("/vitals/devices", { method: "POST", body: { ...f, vendor: f.vendor || null, model: f.model || null } });
      setOpen(false);
      setF({ kind: "bp_cuff", integration: "bluetooth", vendor: "", model: "" });
      await onDone("Device connected (demo pairing)");
    } catch (e2) {
      setErr(e2.message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) return <button className="btn" onClick={() => setOpen(true)}>Connect a device</button>;
  return (
    <form className="stack vt-subform" style={{ gap: 10 }} onSubmit={submit}>
      <div className="banner info">{meta.demo_pairing_notice}</div>
      <div className="vt-fields">
        <div className="vt-field">
          <label htmlFor="dev-kind" className="small strong">Device</label>
          <select id="dev-kind" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
            {meta.device_kinds.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
          </select>
        </div>
        <div className="vt-field">
          <label htmlFor="dev-int" className="small strong">Connects through</label>
          <select id="dev-int" value={f.integration} onChange={(e) => setF({ ...f, integration: e.target.value })}>
            {meta.integrations.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
          </select>
        </div>
        <div className="vt-field">
          <label htmlFor="dev-vendor" className="small strong">Brand (optional)</label>
          <input id="dev-vendor" maxLength={80} value={f.vendor} onChange={(e) => setF({ ...f, vendor: e.target.value })} />
        </div>
        <div className="vt-field">
          <label htmlFor="dev-model" className="small strong">Model (optional)</label>
          <input id="dev-model" maxLength={80} value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })} />
        </div>
      </div>
      {err && <div className="error-box small">{err}</div>}
      <div className="row wrap" style={{ gap: 8 }}>
        <button className="btn primary" disabled={busy}>{busy ? "Pairing…" : "Pair (demo)"}</button>
        <button type="button" className="btn ghost" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </form>
  );
}

export function ImportReadings({ devices, onDone }) {
  const [format, setFormat] = useState("apple_health");
  const [deviceId, setDeviceId] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [res, setRes] = useState(null);
  const fmt = FORMATS.find((x) => x.key === format);
  const connected = devices.filter((d) => d.status === "connected");

  async function onFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      setErr("Files can be 5 MB at most. For a large Apple Health export, trim it to recent months first.");
      return;
    }
    setBusy(true);
    setErr(null);
    setRes(null);
    try {
      const content = await file.text();
      const r = await api("/vitals/import", { method: "POST", body: { format, content, device_id: deviceId || null } });
      setRes(r);
      await onDone(null);
    } catch (e2) {
      setErr(e2.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="vt-fields">
        <div className="vt-field">
          <label htmlFor="imp-format" className="small strong">File type</label>
          <select id="imp-format" value={format} onChange={(e) => setFormat(e.target.value)}>
            {FORMATS.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
          </select>
        </div>
        {connected.length > 0 && (
          <div className="vt-field">
            <label htmlFor="imp-device" className="small strong">From device (optional)</label>
            <select id="imp-device" value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
              <option value="">Not linked to a device</option>
              {connected.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
            </select>
          </div>
        )}
      </div>
      <div className="vt-photo-row">
        <label className="btn" htmlFor="imp-file" aria-disabled={busy}>
          <Upload size={18} /> {busy ? "Importing…" : "Choose file to import"}
        </label>
        <input id="imp-file" type="file" accept={fmt.accept} className="sr-only" onChange={onFile} disabled={busy} />
      </div>
      <p className="tiny muted">
        {format === "csv" && "Columns: measure, taken_at, and value, or systolic and diastolic (pulse, unit and context optional). "}
        Readings already in Bioverse (same time and value) are skipped.
      </p>
      {err && <div className="error-box small" role="alert">{err}</div>}
      {res?.safety && <SafetyMessage safety={res.safety} onClose={() => setRes({ ...res, safety: null })} />}
      {res && (
        <div className="banner ok" role="status" style={{ flexDirection: "column", alignItems: "flex-start" }}>
          <span>Imported {res.imported} reading{res.imported === 1 ? "" : "s"}; skipped {res.skipped} already here
            {res.rejected_count ? `; ${res.rejected_count} couldn't be read` : ""}.</span>
          {Object.keys(res.by_measure).length > 0 && (
            <span className="tiny">{Object.entries(res.by_measure).map(([k, n]) => `${n} ${MEASURE_LABEL[k]}`).join(", ")}</span>
          )}
          {res.rejected.slice(0, 5).map((r) => <span key={r.row} className="tiny">Row {r.row}: {r.reason}</span>)}
        </div>
      )}
    </div>
  );
}
