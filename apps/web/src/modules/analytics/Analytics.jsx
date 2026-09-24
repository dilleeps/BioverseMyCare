import { Link } from "react-router-dom";
import { WorkspaceLayout } from "../../layouts.jsx";
import { useApi } from "../../hooks.js";
import { useSession } from "../../session.jsx";
import { fmtDate } from "../../format.js";
import { ChartCard, ColumnChart, DataTable, HBars, Kpi, Legend, LineChart, specialtyColors, ACCENT } from "./charts.jsx";
import { Definitions, LoadingCard, fmtDay, fmtHours, fmtPct } from "./kit.jsx";

const URGENCY_LABELS = { emergency: "Emergency", urgent: "Urgent", routine: "Routine", self_care: "Self-care" };

function weekLabel(w) {
  return { label: fmtDay(w.start), long: `Week of ${fmtDay(w.start)} to ${fmtDay(w.end)}` };
}

function OrganizationAnalytics() {
  const { data, error, loading } = useApi("/analytics/organization");
  if (error) return <div className="error-box" role="alert">{error.message}</div>;
  if (loading || !data) return <LoadingCard lines={4} />;

  const { trends, leakage } = data;
  const weeks = trends.weeks;
  const t = trends.totals;
  const colors = specialtyColors(trends.specialties);
  const series = trends.specialties.map((s) => ({ key: s, label: s, color: colors[s] }));
  const noData = t.intakes === 0 && t.bookings === 0;

  const intakeRows = weeks.map((w) => ({ ...weekLabel(w), values: w.by_specialty }));
  const bookingRows = weeks.map((w) => ({ ...weekLabel(w), values: { bookings: w.bookings } }));
  const escalation = weeks.map((w) => ({ ...weekLabel(w), value: w.intakes ? w.escalation_rate_pct : null }));
  const turnaround = weeks.map((w) => ({ ...weekLabel(w), value: w.review_turnaround_median_hours }));
  const urgencyRows = Object.entries(t.urgency_mix).map(([k, v]) => ({
    key: k, label: URGENCY_LABELS[k], value: v, display: `${v} · ${fmtPct(t.intakes ? Math.round((1000 * v) / t.intakes) / 10 : null)}`,
  }));

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="kpis">
        <Kpi label="Intakes" value={t.intakes} sub="Last 13 weeks" />
        <Kpi label="Bookings" value={t.bookings} sub="Appointments created, not cancelled" />
        <Kpi label="Escalation rate" value={fmtPct(t.escalation_rate_pct)} sub={`${t.escalations} red-flag escalations`} />
        <Kpi label="Review turnaround" value={fmtHours(t.review_turnaround_median_hours)} sub={`Median of ${t.reviews_resolved} resolved items`} />
        <Kpi label="Referral leakage" value={fmtPct(leakage.rate_pct)} sub={`${leakage.leaked} of ${leakage.eligible} routed intakes not booked in 14 days`}
             tone={leakage.rate_pct >= 25 ? "alert" : undefined} />
      </div>

      {noData && <div className="card empty">No intakes or bookings in the last 13 weeks yet.</div>}

      <div className="ws-grid">
        <div className="span-8">
          <ChartCard
            title="Intakes by specialty"
            subtitle="Per week, stacked by the specialty the front door routed to"
            legend={<Legend items={series.map((s) => ({ label: s.label, color: s.color }))} />}
            table={{
              caption: "Intakes per week by specialty",
              columns: [{ key: "week", label: "Week of" }, ...series.map((s) => ({ key: s.key, label: s.label, num: true })), { key: "total", label: "Total", num: true }],
              rows: weeks.map((w) => ({ key: w.start, week: fmtDay(w.start), ...Object.fromEntries(series.map((s) => [s.key, w.by_specialty[s.key] || 0])), total: w.intakes })),
            }}
          >
            <ColumnChart data={intakeRows} series={series} height={240} label="Weekly intakes by specialty, last 13 weeks" />
          </ChartCard>
        </div>
        <div className="span-4">
          <ChartCard
            title="Urgency mix"
            subtitle="All intakes, last 13 weeks"
            table={{ caption: "Intakes by urgency", columns: [{ key: "label", label: "Urgency" }, { key: "value", label: "Intakes", num: true }, { key: "display", label: "Share", num: true, render: (r) => fmtPct(t.intakes ? Math.round((1000 * r.value) / t.intakes) / 10 : null) }], rows: urgencyRows }}
          >
            <HBars rows={urgencyRows} label="Intakes by urgency" />
          </ChartCard>
        </div>

        <div className="span-6">
          <ChartCard
            title="Bookings"
            subtitle="Appointments created per week"
            table={{ caption: "Bookings per week", columns: [{ key: "week", label: "Week of" }, { key: "bookings", label: "Bookings", num: true }],
                     rows: weeks.map((w) => ({ key: w.start, week: fmtDay(w.start), bookings: w.bookings })) }}
          >
            <ColumnChart data={bookingRows} series={[{ key: "bookings", label: "Bookings", color: ACCENT }]} label="Bookings per week" />
          </ChartCard>
        </div>
        <div className="span-6">
          <ChartCard
            title="Escalation rate"
            subtitle="Red-flag escalations as a share of intakes, per week"
            table={{ caption: "Escalation rate per week", columns: [{ key: "week", label: "Week of" }, { key: "esc", label: "Escalations", num: true }, { key: "intakes", label: "Intakes", num: true }, { key: "rate", label: "Rate", num: true }],
                     rows: weeks.map((w) => ({ key: w.start, week: fmtDay(w.start), esc: w.escalations, intakes: w.intakes, rate: fmtPct(w.escalation_rate_pct) })) }}
          >
            <LineChart data={escalation} seriesLabel="Escalation rate" format={fmtPct} label="Escalation rate per week" />
          </ChartCard>
        </div>

        <div className="span-6">
          <ChartCard
            title="Review turnaround"
            subtitle="Median hours from a review item arriving to being resolved, by week resolved"
            table={{ caption: "Median review turnaround per week", columns: [{ key: "week", label: "Week of" }, { key: "n", label: "Resolved", num: true }, { key: "median", label: "Median", num: true }],
                     rows: weeks.map((w) => ({ key: w.start, week: fmtDay(w.start), n: w.reviews_resolved, median: fmtHours(w.review_turnaround_median_hours) })) }}
          >
            <LineChart data={turnaround} seriesLabel="Median turnaround" format={fmtHours} label="Median review turnaround per week" />
          </ChartCard>
        </div>
        <div className="span-6">
          <ChartCard
            title="Referral leakage by specialty"
            subtitle="Routed intakes with no booking in that specialty within 14 days"
            table={{ caption: "Referral leakage by specialty", columns: [{ key: "specialty", label: "Specialty" }, { key: "leaked", label: "Not booked", num: true }, { key: "eligible", label: "Routed", num: true }, { key: "rate", label: "Leakage", num: true, render: (r) => fmtPct(r.rate_pct) }],
                     rows: leakage.by_specialty.map((r) => ({ ...r, key: r.specialty })) }}
          >
            {leakage.by_specialty.length === 0
              ? <p className="small muted">No routed intakes are old enough to measure yet.</p>
              : <HBars max={100} label="Referral leakage by specialty"
                       rows={leakage.by_specialty.map((r) => ({ key: r.specialty, label: r.specialty, value: r.rate_pct || 0, display: fmtPct(r.rate_pct), sub: `${r.leaked} of ${r.eligible} not booked` }))} />}
          </ChartCard>
        </div>
      </div>

      <Definitions items={{ "Weeks and bookings": trends.definition, "Referral leakage": leakage.definition }} />
    </div>
  );
}

function ClinicianAnalytics() {
  const { data, error, loading } = useApi("/analytics/clinician");
  if (error) return <div className="error-box" role="alert">{error.message}</div>;
  if (loading || !data) return <LoadingCard lines={4} />;
  const s = data.summary;
  if (s.patients === 0) {
    return <div className="card empty">Nobody is on your panel yet. Patients appear here once they have a care plan or an appointment with you.</div>;
  }
  const withDue = data.patients.filter((p) => p.tasks_due > 0);

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="kpis">
        <Kpi label="Patients on your panel" value={s.patients} />
        <Kpi label="Care-plan adherence" value={fmtPct(s.adherence_pct)} sub={`${s.tasks_done} of ${s.tasks_due} due tasks done`} />
        <Kpi label="Overdue tasks" value={s.overdue_tasks} tone={s.overdue_tasks ? "alert" : undefined} />
        <Kpi label="Open care gaps" value={s.open_care_gaps} />
        <Kpi label="Abnormal results to explain" value={s.unexplained_abnormal_results} tone={s.unexplained_abnormal_results ? "alert" : undefined}
             sub="No approved explanation yet" />
      </div>

      <div className="ws-grid">
        <div className="span-6">
          <ChartCard
            title="Adherence by patient"
            subtitle="Done out of due tasks in your active care plans"
            table={{ caption: "Care-plan adherence by patient", columns: [{ key: "name", label: "Patient" }, { key: "tasks_done", label: "Done", num: true }, { key: "tasks_due", label: "Due", num: true }, { key: "adh", label: "Adherence", num: true, render: (r) => fmtPct(r.adherence_pct) }],
                     rows: withDue.map((p) => ({ ...p, key: p.id })) }}
          >
            {withDue.length === 0
              ? <p className="small muted">No care-plan tasks are due yet.</p>
              : <HBars max={100} label="Adherence by patient"
                       rows={withDue.map((p) => ({ key: p.id, label: p.name, sub: p.plan_title, value: p.adherence_pct || 0, display: `${p.tasks_done}/${p.tasks_due}` }))} />}
          </ChartCard>
        </div>
        <div className="span-6 stack">
          <article className="card stack">
            <h2 className="card-title">Overdue tasks</h2>
            {data.overdue_tasks.length === 0 ? <p className="small muted">Nothing overdue.</p> : (
              <DataTable
                columns={[{ key: "patient_name", label: "Patient" }, { key: "title", label: "Task" }, { key: "due", label: "Due", num: true, render: (r) => fmtDay(r.due_on) }]}
                rows={data.overdue_tasks.map((r) => ({ ...r, key: r.id }))}
              />
            )}
          </article>
          <article className="card stack">
            <h2 className="card-title">Abnormal results without an approved explanation</h2>
            {data.unexplained_results.length === 0 ? <p className="small muted">Every abnormal result has an approved explanation.</p> : (
              <DataTable
                columns={[
                  { key: "patient_name", label: "Patient" },
                  { key: "name", label: "Report", render: (r) => <Link to={`/results/${r.id}`}>{r.name}</Link> },
                  { key: "status", label: "Explanation", render: (r) => (r.explanation_status === "none" ? "Not drafted" : r.explanation_status === "pending_review" ? "Awaiting your review" : "Rejected") },
                  { key: "collected", label: "Collected", num: true, render: (r) => fmtDate(r.collected_at) },
                ]}
                rows={data.unexplained_results.map((r) => ({ ...r, key: r.id }))}
              />
            )}
          </article>
          <article className="card stack">
            <h2 className="card-title">Open care gaps</h2>
            {data.care_gaps.length === 0 ? <p className="small muted">No open care gaps.</p> : (
              <DataTable
                columns={[{ key: "patient_name", label: "Patient" }, { key: "title", label: "Gap" }, { key: "specialty", label: "Specialty" }]}
                rows={data.care_gaps.map((r) => ({ ...r, key: r.id }))}
              />
            )}
          </article>
        </div>
      </div>

      <article className="card stack">
        <h2 className="card-title">Your panel</h2>
        <DataTable
          columns={[
            { key: "name", label: "Patient" },
            { key: "age", label: "Age", num: true },
            { key: "plan_title", label: "Active plan", render: (r) => r.plan_title || "—" },
            { key: "adh", label: "Adherence", num: true, render: (r) => (r.tasks_due ? `${fmtPct(r.adherence_pct)} (${r.tasks_done}/${r.tasks_due})` : "—") },
            { key: "tasks_overdue", label: "Overdue", num: true },
            { key: "open_gaps", label: "Gaps", num: true },
            { key: "unexplained_abnormal", label: "Results to explain", num: true },
          ]}
          rows={data.patients.map((p) => ({ ...p, key: p.id }))}
        />
      </article>

      <Definitions items={{ Panel: data.definitions.panel, Adherence: data.definitions.adherence, Overdue: data.definitions.overdue, "Results to explain": data.definitions.unexplained }} />
    </div>
  );
}

export default function Analytics() {
  const { me } = useSession();
  const admin = me?.role === "admin";
  return (
    <WorkspaceLayout>
      <div className="viz-root">
        <header className="ops-header">
          <div>
            <h1 className="page-title">{admin ? "Analytics" : "My panel"}</h1>
            <p className="page-sub">
              {admin ? "Organization trends over the last 13 weeks, in rolling weeks ending today." : "Care-plan adherence and follow-up gaps for patients on your panel, as of today."}
            </p>
          </div>
        </header>
        {admin ? <OrganizationAnalytics /> : <ClinicianAnalytics />}
      </div>
    </WorkspaceLayout>
  );
}
