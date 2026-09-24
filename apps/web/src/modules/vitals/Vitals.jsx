import { useEffect, useState } from "react";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { PatientPage } from "../../layouts.jsx";
import { fmtDateTime, fmtShortDate } from "../../format.js";
import { Plus, Warning } from "../../icons.jsx";
import { Sparkline, SlotStrip } from "./charts.jsx";
import { ConnectDevice, DeviceList, ImportReadings } from "./Devices.jsx";
import { Clock, Device, Pulse } from "./icons.jsx";
import LogReading from "./LogReading.jsx";
import { MeasureDetail, StatusChip, readingValue, useToast } from "./shared.jsx";

function Section({ id, title, icon: Icon, aside, children }) {
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

function Tiles({ tiles, selected, onSelect }) {
  return (
    <ul className="vt-tiles" aria-label="Your measurements">
      {tiles.map((t) => {
        const off = t.latest?.status && t.latest.status !== "in_range";
        return (
          <li key={t.measure}>
            <button className={`vt-tile ${off ? "off" : ""}`} aria-pressed={selected === t.measure} onClick={() => onSelect(t.measure)}>
              <span className="small strong">{t.label}</span>
              {t.latest ? (
                <>
                  <span className="vt-tile-value">{readingValue(t.measure, t.latest)} <span className="tiny muted">{t.unit}</span></span>
                  <span className="tiny muted">{fmtShortDate(t.latest.at)}{t.week.count ? ` · 7-day avg ${t.week.average}` : ""}</span>
                  <span className="row between" style={{ gap: 6 }}>
                    <StatusChip status={t.latest.status} />
                    <Sparkline values={t.spark} alert={off} width={72} />
                  </span>
                </>
              ) : (
                <span className="tiny muted">No readings yet</span>
              )}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

const ALERT_COPY = {
  critical: "A very high or low reading. Your care team was told right away.",
  warning: "A pattern in your recent readings. Your care team was told and will contact you if anything needs to change.",
};

export default function Vitals() {
  const { data, error, loading, reload } = useApi("/vitals/summary");
  const [selected, setSelected] = useState("bp");
  const [logFor, setLogFor] = useState("bp");
  const [version, setVersion] = useState(0);
  const [toast, setToast] = useToast();

  useEffect(() => { document.title = "Vitals · Bioverse"; }, []);

  async function refresh(message) {
    await reload();
    setVersion((v) => v + 1);
    if (message) setToast(message);
  }

  async function onDelete(r) {
    if (!window.confirm("Delete this reading? This can't be undone.")) return;
    try {
      await api(`/vitals/readings/${r.id}`, { method: "DELETE" });
      await refresh("Reading deleted");
    } catch (e) {
      setToast(e.message);
    }
  }

  if (error) return <PatientPage wide><div className="error-box">{error.message}</div></PatientPage>;
  if (loading && !data) return <PatientPage wide><div className="card" aria-busy="true"><div className="skeleton" /></div></PatientPage>;

  const tile = data.tiles.find((t) => t.measure === selected);
  const open = data.alerts.filter((a) => a.status === "open");
  const plans = data.plans.filter((p) => p.status === "active");

  return (
    <PatientPage wide>
      <div className="page-head">
        <div>
          <h1 className="page-title">Vitals & devices</h1>
          <p className="page-sub">Your home readings, what your care team asked you to measure, and your connected devices.</p>
        </div>
      </div>

      {open.length > 0 && (
        <div className="stack" style={{ gap: 8, marginBottom: 16 }}>
          {open.map((a) => (
            <div key={a.id} className={`banner ${a.severity === "critical" ? "warn" : "info"}`} role="status">
              <Warning size={16} />
              <span><strong>{a.title}.</strong> {ALERT_COPY[a.severity]}</span>
            </div>
          ))}
        </div>
      )}

      <div className="vt-grid">
        <div className="stack">
          <Tiles tiles={data.tiles} selected={selected} onSelect={(m) => { setSelected(m); setLogFor(m); }} />
          <Section id="vt-detail" title={tile.label} icon={Pulse}>
            <MeasureDetail measure={selected} version={version} canDelete onDelete={onDelete} />
          </Section>
        </div>

        <div className="stack">
          <Section id="vt-log" title="Log a reading" icon={Plus}>
            <LogReading meta={data} initialMeasure={logFor} onSaved={() => refresh(null)} />
          </Section>

          {plans.length > 0 && (
            <Section id="vt-plans" title="Asked by your care team" icon={Clock}>
              {plans.map((p) => (
                <div key={p.id} className="stack" style={{ gap: 8 }}>
                  <div>
                    <div className="strong">{p.label}</div>
                    <div className="small muted">
                      {p.practitioner_name} · at {p.times.join(" and ")} · until {fmtShortDate(p.end_on)}
                    </div>
                  </div>
                  {p.instructions && <p className="small">{p.instructions}</p>}
                  {p.adherence.today.length > 0 && (
                    <div className="row wrap" style={{ gap: 6 }}>
                      <span className="small strong">Today:</span>
                      {p.adherence.today.map((s, i) => (
                        <span key={s.due} className={`chip ${s.status === "done" ? "ok" : s.status === "missed" ? "warn" : ""}`}>
                          {p.times[i]} ·{" "}
                          {{ done: "logged", missed: "missed", due: "due now", upcoming: "later" }[s.status]}
                        </span>
                      ))}
                    </div>
                  )}
                  <SlotStrip days={p.adherence.days} times={p.times} />
                  <p className="small muted">
                    {p.adherence.expected
                      ? `${p.adherence.done} of ${p.adherence.expected} readings logged so far (${p.adherence.pct}%).`
                      : "Your first reading is coming up."}
                    {" "}We'll remind you at each time.
                  </p>
                </div>
              ))}
            </Section>
          )}

          <Section id="vt-devices" title="Devices" icon={Device}>
            <DeviceList devices={data.devices} editable onChanged={() => refresh(null)} />
            <ConnectDevice meta={data} onDone={refresh} />
            <details className="vt-explain">
              <summary className="small strong">Import readings from a file</summary>
              <div style={{ marginTop: 8 }}>
                <ImportReadings devices={data.devices} onDone={refresh} />
              </div>
            </details>
          </Section>

          {data.alerts.some((a) => a.status === "acknowledged") && (
            <Section id="vt-history" title="Reviewed by your care team">
              <ul className="list vt-list">
                {data.alerts.filter((a) => a.status === "acknowledged").map((a) => (
                  <li key={a.id} className="small" style={{ padding: "8px 0" }}>
                    {a.title}
                    <br />
                    <span className="tiny muted">Reviewed {fmtDateTime(a.acknowledged_at)}{a.acknowledged_by_name ? ` by ${a.acknowledged_by_name}` : ""}</span>
                  </li>
                ))}
              </ul>
            </Section>
          )}
        </div>
      </div>
      {toast && <div className="toast" role="status">{toast}</div>}
    </PatientPage>
  );
}
