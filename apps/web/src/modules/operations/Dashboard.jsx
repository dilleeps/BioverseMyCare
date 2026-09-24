import { useState } from "react";
import { Link } from "react-router-dom";
import { WorkspaceLayout } from "../../layouts.jsx";
import { Sparkle, Warning } from "../../icons.jsx";
import { ChartCard, DataTable, HBars, Kpi, Meter } from "../analytics/charts.jsx";
import { Definitions, LoadingCard, fmtHours, fmtPct, fmtTime, fmtWeekday, usePolling } from "../analytics/kit.jsx";

const REFRESH_MS = 60000;
const STATUS = {
  short: { label: "Short", cls: "chip warn" },
  tight: { label: "Tight", cls: "chip" },
  ok: { label: "OK", cls: "chip ok" },
};

function CapacityCard({ today, week }) {
  const [win, setWin] = useState("next_7_days");
  const data = win === "today" ? today : week;
  const rows = data.rows.filter((r) => r.capacity > 0 || r.departments.length > 0);
  const windowLabel = win === "today" ? "today" : "the next 7 days";
  return (
    <ChartCard
      title="Appointment capacity"
      subtitle={`Booked out of all slots ${windowLabel}, by specialty`}
      actions={(
        <div className="seg" role="group" aria-label="Time window">
          <button type="button" aria-pressed={win === "today"} onClick={() => setWin("today")}>Today</button>
          <button type="button" aria-pressed={win === "next_7_days"} onClick={() => setWin("next_7_days")}>Next 7 days</button>
        </div>
      )}
      table={{
        caption: `Capacity ${windowLabel}`,
        columns: [
          { key: "specialty", label: "Specialty" },
          { key: "departments", label: "Department", render: (r) => r.departments.join(", ") || "—" },
          { key: "capacity", label: "Slots", num: true },
          { key: "booked", label: "Booked", num: true },
          { key: "free", label: "Free", num: true },
          { key: "u", label: "Utilization", num: true, render: (r) => fmtPct(r.utilization_pct) },
        ],
        rows: rows.map((r) => ({ ...r, key: r.specialty })),
      }}
    >
      {rows.length === 0 ? <p className="small muted">No appointment slots {windowLabel}.</p> : (
        <div className="stack" style={{ gap: 12 }}>
          {rows.map((r) => (
            <div key={r.specialty} className="stack" style={{ gap: 4 }}>
              <div className="row between small">
                <span className="strong">{r.specialty}{r.departments.some((d) => d !== r.specialty) ? <span className="muted" style={{ fontWeight: 500 }}> · {r.departments.join(", ")}</span> : null}</span>
                <span style={{ fontVariantNumeric: "tabular-nums" }}>
                  <span className="strong">{fmtPct(r.utilization_pct)}</span>
                  <span className="muted"> · {r.booked} of {r.capacity} booked · {r.free} free</span>
                </span>
              </div>
              <Meter value={r.booked} max={r.capacity} label={`${r.specialty}: ${r.booked} of ${r.capacity} slots booked`} />
            </div>
          ))}
          <p className="tiny muted">Total: {data.totals.booked} of {data.totals.capacity} booked ({fmtPct(data.totals.utilization_pct)}), {data.totals.free} free.</p>
        </div>
      )}
    </ChartCard>
  );
}

function DemandCard({ demand }) {
  return (
    <article className="card stack">
      <div>
        <h2 className="card-title">Demand vs capacity</h2>
        <p className="small muted">Routed intakes in the last 7 days against free slots in the next 7 days</p>
      </div>
      {demand.rows.length === 0 ? <p className="small muted">No specialties configured.</p> : (
        <DataTable
          columns={[
            { key: "specialty", label: "Specialty" },
            { key: "demand_last_7_days", label: "Demand", num: true },
            { key: "free_next_7_days", label: "Free slots", num: true },
            { key: "status", label: "Status", render: (r) => (
              <span className={STATUS[r.status].cls}>
                {r.status === "short" && <Warning size={12} />}
                {r.status === "short" ? `Short by ${r.shortfall}` : STATUS[r.status].label}
              </span>
            ) },
          ]}
          rows={demand.rows.map((r) => ({ ...r, key: r.specialty }))}
        />
      )}
    </article>
  );
}

function IntakesCard({ intakes, flags }) {
  const u = intakes.by_urgency;
  return (
    <article className="card stack">
      <div>
        <h2 className="card-title">Intakes today</h2>
        <p className="small muted">{intakes.total} so far: {u.emergency} emergency, {u.urgent} urgent, {u.routine} routine, {u.self_care} self-care</p>
      </div>
      {flags.count > 0 && (
        <div className={`banner ${flags.waiting ? "warn" : "info"}`} role={flags.waiting ? "alert" : undefined}>
          <Warning size={15} />
          {flags.count} red-flag escalation{flags.count === 1 ? "" : "s"} today · {flags.acknowledged} acknowledged
          {flags.waiting ? ` · ${flags.waiting} waiting${flags.oldest_waiting_minutes != null ? ` (oldest ${fmtHours(flags.oldest_waiting_minutes / 60)})` : ""}` : ""}
        </div>
      )}
      {intakes.total === 0 ? <p className="small muted">No intakes yet today.</p> : (
        <DataTable
          columns={[
            { key: "specialty", label: "Specialty", render: (r) => `${r.specialty} (${r.total})` },
            { key: "emergency", label: "Emergency", num: true },
            { key: "urgent", label: "Urgent", num: true },
            { key: "routine", label: "Routine", num: true },
            { key: "self_care", label: "Self-care", num: true },
          ]}
          rows={intakes.by_specialty.map((r) => ({ ...r, key: r.specialty }))}
        />
      )}
    </article>
  );
}

function WorkloadCard({ workload }) {
  const rows = workload.rows;
  const withItems = rows.filter((r) => r.open_items > 0);
  return (
    <ChartCard
      title="Review backlog and workload"
      subtitle={`${workload.total_open} open review items across clinicians`}
      table={{
        caption: "Clinician workload",
        columns: [
          { key: "name", label: "Clinician" },
          { key: "specialty", label: "Specialty" },
          { key: "open_items", label: "Open items", num: true },
          { key: "urgent_items", label: "Urgent", num: true },
          { key: "oldest", label: "Oldest open", num: true, render: (r) => fmtHours(r.oldest_open_hours) },
          { key: "booked_next_7_days", label: "Visits next 7 days", num: true },
        ],
        rows: rows.map((r) => ({ ...r, key: r.practitioner_id })),
      }}
    >
      {withItems.length === 0 ? <p className="small muted">Every review queue is clear.</p> : (
        <HBars label="Open review items by clinician"
               rows={withItems.map((r) => ({
                 key: r.practitioner_id, label: r.name, value: r.open_items,
                 sub: `${r.specialty} · oldest ${fmtHours(r.oldest_open_hours)}${r.urgent_items ? ` · ${r.urgent_items} urgent` : ""}`,
               }))} />
      )}
    </ChartCard>
  );
}

export default function Dashboard() {
  const { data, error, loading, updatedAt, reload } = usePolling("/ops/dashboard", REFRESH_MS);

  return (
    <WorkspaceLayout>
      <div className="viz-root">
        <header className="ops-header">
          <div>
            <h1 className="page-title">Operations</h1>
            <p className="page-sub">
              {data ? fmtWeekday(data.today) : "Today"}
              {updatedAt ? ` · updated ${fmtTime(updatedAt)} · refreshes every minute` : ""}
            </p>
          </div>
          <div className="row" style={{ gap: 8 }}>
            <Link className="btn" to="/ops/assistant"><Sparkle size={16} /> Ask the Hospital Agent</Link>
            <button type="button" className="btn dark" onClick={reload} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>
          </div>
        </header>

        {error && (
          <div className="error-box" role="alert" style={{ marginBottom: 12 }}>
            {data ? `Couldn't refresh: ${error.message} Showing the last update.` : error.message}
          </div>
        )}
        {!data && !error && <LoadingCard lines={5} />}

        {data && (
          <div className={`stack ${loading ? "refreshing" : ""}`} style={{ gap: 16 }} aria-busy={loading}>
            {data.demand_vs_capacity.rows.filter((r) => r.status === "short").map((r) => (
              <div key={r.specialty} className="banner warn" role="status"><Warning size={15} /> {r.message}</div>
            ))}

            <div className="kpis">
              <Kpi label="Utilization today" value={fmtPct(data.capacity_today.totals.utilization_pct)}
                   sub={`${data.capacity_today.totals.booked} of ${data.capacity_today.totals.capacity} slots booked`} />
              <Kpi label="Free slots, next 7 days" value={data.capacity_next_7_days.totals.free}
                   sub={`of ${data.capacity_next_7_days.totals.capacity} · ${fmtPct(data.capacity_next_7_days.totals.utilization_pct)} booked`} />
              <Kpi label="Intakes today" value={data.intakes_today.total} sub={`${data.intakes_today.by_urgency.urgent} urgent`} />
              <Kpi label="Red-flag escalations today" value={data.red_flags_today.count}
                   sub={data.red_flags_today.waiting ? `${data.red_flags_today.waiting} waiting for a clinician` : "All acknowledged"}
                   tone={data.red_flags_today.waiting ? "alert" : undefined} />
              <Kpi label="Open review items" value={data.clinician_workload.total_open}
                   sub={data.clinician_workload.rows[0]?.open_items ? `Most: ${data.clinician_workload.rows[0].name}` : "Queues clear"} />
            </div>

            <div className="ws-grid">
              <div className="span-6"><CapacityCard today={data.capacity_today} week={data.capacity_next_7_days} /></div>
              <div className="span-6"><DemandCard demand={data.demand_vs_capacity} /></div>
              <div className="span-7"><IntakesCard intakes={data.intakes_today} flags={data.red_flags_today} /></div>
              <div className="span-5"><WorkloadCard workload={data.clinician_workload} /></div>
            </div>

            <Definitions items={{
              Capacity: data.capacity_next_7_days.definition,
              "Demand vs capacity": data.demand_vs_capacity.definition,
              Intakes: data.intakes_today.definition,
              "Red-flag escalations": data.red_flags_today.definition,
              Workload: data.clinician_workload.definition,
              "Time zone": `Days follow the clinic's time zone (${data.timezone}).`,
            }} />
          </div>
        )}
      </div>
    </WorkspaceLayout>
  );
}
