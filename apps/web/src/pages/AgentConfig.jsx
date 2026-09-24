import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useApi } from "../hooks.js";
import { ClinicianNav } from "./Clinician.jsx";
import { Close, Lock, Plus } from "../icons.jsx";

const LABELS = {
  emergency_guidance: "Emergency guidance",
  gather_then_escalate: "Gather details, then escalate",
  escalate_immediately: "Escalate immediately",
  answer_from_approved_content: "Answer from approved content",
  escalate: "Escalate",
  handle_via_scheduling: "Handle via scheduling",
  clinician_and_team_now: "You + care team, immediately",
  clinician_same_day: "Me, same day",
  nurse_triage: "Nurse triage",
  staff_if_unresolved: "Staff, if unresolved",
  clinician: "Me",
  front_desk: "Front desk",
};
const label = (v) => LABELS[v] || v;

export default function AgentConfig() {
  const { data, error, loading } = useApi("/clinician/agent-config");
  const [config, setConfig] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [saved, setSaved] = useState(false);
  const [newQuestion, setNewQuestion] = useState("");

  useEffect(() => {
    if (data) setConfig(structuredClone(data));
  }, [data]);

  function update(fn) {
    setConfig((c) => {
      const next = structuredClone(c);
      fn(next);
      return next;
    });
    setSaved(false);
  }

  async function save() {
    setSaving(true);
    setSaveError(null);
    try {
      const { active, previsit_questions, followup_protocol, escalation_rules, approval_requirements } = config;
      const result = await api("/clinician/agent-config", {
        method: "PUT",
        body: { active, previsit_questions, followup_protocol, escalation_rules, approval_requirements },
      });
      setConfig((c) => ({ ...c, ...result }));
      setSaved(true);
    } catch (e) {
      setSaveError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="workspace">
      <ClinicianNav />
      <main className="ws-main">
        {error && <div className="error-box">{error.message}</div>}
        {(loading || !config) && !error && <div className="card"><div className="skeleton" /></div>}
        {config && (
          <>
            <header className="row between wrap" style={{ marginBottom: 18, gap: 12 }}>
              <div>
                <div className="page-title">My Doctor Agent</div>
                <div className="page-sub">Active for {config.active_patients} patient{config.active_patients === 1 ? "" : "s"} · within your organization's rules</div>
              </div>
              <div className="row" style={{ gap: 8 }}>
                <label className="chip ok" style={{ cursor: "pointer" }}>
                  <input type="checkbox" checked={config.active} onChange={(e) => update((c) => { c.active = e.target.checked; })} />
                  {config.active ? "Active" : "Paused"}
                </label>
                <button className="btn primary" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save changes"}</button>
              </div>
            </header>
            {saveError && <div className="error-box" style={{ marginBottom: 12 }}>{saveError}</div>}
            {saved && <div className="banner ok" style={{ marginBottom: 12 }}>Saved. Your agent uses these settings from its next conversation.</div>}

            <div className="ws-grid">
              <section className="span-5 stack">
                <article className="card stack">
                  <span className="card-title">Pre-visit interview</span>
                  <span className="small muted">Asked in the 48 hours before each visit. Answers arrive in your pre-visit brief.</span>
                  {config.previsit_questions.map((q, i) => (
                    <div key={q.id} className="toggle-row">
                      <input id={`q-${q.id}`} type="checkbox" checked={q.enabled}
                             onChange={(e) => update((c) => { c.previsit_questions[i].enabled = e.target.checked; })} />
                      <label htmlFor={`q-${q.id}`}>{q.text}</label>
                      <span className="tiny strong" style={{ color: q.source === "clinician" ? "var(--accent-strong)" : "var(--muted)" }}>
                        {q.source === "clinician" ? "Mine" : "Specialty"}
                      </span>
                      {q.source === "clinician" && (
                        <button className="btn ghost sm" aria-label={`Remove "${q.text}"`}
                                onClick={() => update((c) => { c.previsit_questions.splice(i, 1); })}>
                          <Close size={14} />
                        </button>
                      )}
                    </div>
                  ))}
                  <form className="row" style={{ gap: 8 }} onSubmit={(e) => {
                    e.preventDefault();
                    const text = newQuestion.trim();
                    if (text.length < 3) return;
                    update((c) => { c.previsit_questions.push({ id: `q${Date.now()}`, text, source: "clinician", enabled: true }); });
                    setNewQuestion("");
                  }}>
                    <label htmlFor="newq" className="sr-only">New question</label>
                    <input id="newq" className="field" style={{ flexGrow: 1, minHeight: 40, borderRadius: 10, border: "1px solid var(--line)", padding: "0 12px" }}
                           placeholder="Add a question" value={newQuestion} onChange={(e) => setNewQuestion(e.target.value)} />
                    <button className="btn sm" type="submit" disabled={newQuestion.trim().length < 3}><Plus size={14} /> Add</button>
                  </form>
                </article>

                <article className="card stack">
                  <span className="card-title">Follow-up protocol</span>
                  <span className="small muted">After a new medication is started.</span>
                  {config.followup_protocol.map((s, i) => (
                    <div key={i} className="row" style={{ gap: 8 }}>
                      <label htmlFor={`day-${i}`} className="sr-only">Day</label>
                      <input id={`day-${i}`} type="number" min="0" max="365" value={s.day}
                             style={{ width: 72, minHeight: 38, borderRadius: 8, border: "1px solid var(--line)", padding: "0 8px" }}
                             onChange={(e) => update((c) => { c.followup_protocol[i].day = Number(e.target.value); })} />
                      <label htmlFor={`act-${i}`} className="sr-only">Action</label>
                      <input id={`act-${i}`} value={s.action}
                             style={{ flexGrow: 1, minHeight: 38, borderRadius: 8, border: "1px solid var(--line)", padding: "0 10px" }}
                             onChange={(e) => update((c) => { c.followup_protocol[i].action = e.target.value; })} />
                      <button className="btn ghost sm" aria-label={`Remove day ${s.day}`}
                              onClick={() => update((c) => { c.followup_protocol.splice(i, 1); })}><Close size={14} /></button>
                    </div>
                  ))}
                  <button className="btn sm" style={{ alignSelf: "flex-start" }}
                          onClick={() => update((c) => { c.followup_protocol.push({ day: 14, action: "Check in" }); })}>
                    <Plus size={14} /> Add step
                  </button>
                </article>
              </section>

              <section className="span-7 stack">
                <article className="card stack">
                  <span className="card-title">Escalation rules</span>
                  <span className="small muted">What the agent does with each kind of patient message. Red-flag symptoms always escalate to emergency guidance.</span>
                  <div className="config-table">
                    <div className="th">Message type</div><div className="th">Agent action</div><div className="th">Goes to</div>
                    {config.escalation_rules.map((r, i) => (
                      <RuleRow key={r.id} rule={r} choices={config.choices}
                               onChange={(field, v) => update((c) => { c.escalation_rules[i][field] = v; })} />
                    ))}
                  </div>
                </article>

                <article className="card stack">
                  <span className="card-title">Approval requirements</span>
                  {config.approval_requirements.map((a, i) => (
                    <div key={a.id} className="toggle-row">
                      <input id={`a-${a.id}`} type="checkbox" checked={a.required} disabled={a.locked}
                             onChange={(e) => update((c) => { c.approval_requirements[i].required = e.target.checked; })} />
                      <label htmlFor={`a-${a.id}`}>{a.label}</label>
                      <span className="tiny strong row" style={{ gap: 4, color: a.locked ? "var(--muted)" : "var(--accent-strong)" }}>
                        {a.locked ? <><Lock size={12} /> Required by your organization</> : "My choice"}
                      </span>
                    </div>
                  ))}
                </article>
              </section>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function RuleRow({ rule, choices, onChange }) {
  if (rule.locked) {
    return (
      <>
        <div className="strong">{rule.label}</div>
        <div className="strong row" style={{ gap: 6, color: "var(--alert-strong)" }}><Lock size={12} /> {label(rule.action)}</div>
        <div>{label(rule.route_to)}</div>
      </>
    );
  }
  const actions = choices.actions[rule.id] || [rule.action];
  const routes = choices.routes[rule.id] || [rule.route_to];
  return (
    <>
      <div className="strong">{rule.label}</div>
      <div>
        <label htmlFor={`act-${rule.id}`} className="sr-only">Action for {rule.label}</label>
        <select id={`act-${rule.id}`} value={rule.action} onChange={(e) => onChange("action", e.target.value)}>
          {actions.map((a) => <option key={a} value={a}>{label(a)}</option>)}
        </select>
      </div>
      <div>
        <label htmlFor={`route-${rule.id}`} className="sr-only">Recipient for {rule.label}</label>
        <select id={`route-${rule.id}`} value={rule.route_to} onChange={(e) => onChange("route_to", e.target.value)}>
          {routes.map((r) => <option key={r} value={r}>{label(r)}</option>)}
        </select>
      </div>
    </>
  );
}
