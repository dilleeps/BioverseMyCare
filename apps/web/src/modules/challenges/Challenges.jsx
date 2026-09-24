import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { useSession } from "../../session.jsx";
import { Check, Chevron, Warning } from "../../icons.jsx";
import { Loading, Meter, num, shortDay, weekdayShort } from "../nutrition/charts.jsx";

const UNIT_LABEL = { steps: "steps", active_minutes: "minutes", bp_logged: "reading", veg_servings: "servings", water_ml: "ml" };

function Days({ progress, period }) {
  return (
    <ol className="ch-days" aria-label="Progress by day">
      {progress.periods.map((p) => {
        const state = p.met ? "met" : p.future ? "future" : p.today ? "today" : "missed";
        const label = period === "day" ? weekdayShort(p.start) : `Week of ${shortDay(p.start)}`;
        const words = { met: "target met", future: "still to come", today: "today, in progress", missed: "not met" }[state];
        return (
          <li key={p.start} className={`ch-day ${state}`} aria-label={`${label}: ${words}`}>
            <span className="dot">{p.met ? <Check size={14} /> : ""}</span>
            <span className="tiny">{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function QuickLog({ pid, c, onDone }) {
  const [value, setValue] = useState("");
  const [sys, setSys] = useState("");
  const [dia, setDia] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const metric = c.challenge.metric;
  if (metric === "veg_servings" || metric === "water_ml") {
    return (
      <Link className="btn sm" to="/nutrition" style={{ alignSelf: "flex-start" }}>
        {metric === "water_ml" ? "Log drinks in your food log" : "Log meals in your food log"} <Chevron size={14} />
      </Link>
    );
  }
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = metric === "bp_logged"
        ? { metric: "bp", systolic: Number(sys), diastolic: Number(dia) }
        : { metric, value: Number(value) };
      onDone(await api(`/challenges/patients/${pid}/log`, { method: "POST", body }));
      setValue(""); setSys(""); setDia("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  const id = `log-${c.id}`;
  return (
    <form className="wb-inline" onSubmit={save} aria-label={`Log for ${c.challenge.title}`}>
      {metric === "bp_logged" ? (
        <>
          <div className="wb-field"><label htmlFor={`${id}-s`}>Top number</label>
            <input id={`${id}-s`} type="number" min="50" max="300" required value={sys} onChange={(e) => setSys(e.target.value)} /></div>
          <div className="wb-field"><label htmlFor={`${id}-d`}>Bottom number</label>
            <input id={`${id}-d`} type="number" min="30" max="200" required value={dia} onChange={(e) => setDia(e.target.value)} /></div>
        </>
      ) : (
        <div className="wb-field"><label htmlFor={id}>{metric === "steps" ? "Steps today" : "Active minutes"}</label>
          <input id={id} type="number" min="0" required value={value} onChange={(e) => setValue(e.target.value)} /></div>
      )}
      <button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Log"}</button>
      {error && <div className="error-box small" style={{ width: "100%" }}>{error}</div>}
    </form>
  );
}

function ActiveChallenge({ pid, c, team, onChange }) {
  const p = c.progress;
  const [error, setError] = useState(null);
  async function leave() {
    setError(null);
    try {
      onChange(await api(`/challenges/enrollments/${c.id}/leave`, { method: "POST" }));
    } catch (e) {
      setError(e.message);
    }
  }
  const unit = UNIT_LABEL[c.challenge.metric];
  return (
    <article className="card stack" aria-labelledby={`ch-${c.id}`}>
      <div className="row between wrap" style={{ alignItems: "flex-start" }}>
        <div style={{ minWidth: 0 }}>
          <h3 id={`ch-${c.id}`} className="card-title">{c.challenge.title}</h3>
          <span className="tiny muted">{shortDay(c.started_on)} to {shortDay(c.ends_on)}{team ? " · family challenge" : ""}</span>
        </div>
        {p.current_streak > 1 && <span className="chip ok">{p.current_streak}-day streak</span>}
      </div>
      <Days progress={p} period={c.challenge.period} />
      <div className="stack" style={{ gap: 4 }}>
        <div className="row between small"><span className="strong">{p.periods_met} of {p.required} {c.challenge.period === "day" ? "days" : "weeks"} met</span>
          <span className="muted">{p.percent}%</span></div>
        <Meter value={p.periods_met} max={p.required} label={`${p.periods_met} of ${p.required} met`} />
      </div>
      {p.today_value != null && c.challenge.metric !== "bp_logged" && (
        <p className="small">{c.challenge.period === "day" ? "Today so far" : "This week so far"}: <span className="strong">{num(p.today_value, 0)} {unit}</span> of {num(c.challenge.target, 0)}</p>
      )}
      {p.today_value == null && <p className="small muted">Nothing counted {c.challenge.period === "day" ? "today" : "this week"} yet.</p>}
      <QuickLog pid={pid} c={c} onDone={onChange} />
      {team && (
        <div className="wb-muted-box stack" style={{ gap: 6 }}>
          <span className="small strong">Together: {team.together.met} of {team.together.needed} days met</span>
          <Meter value={team.together.met} max={team.together.needed || 1} label="Team progress" />
          <span className="tiny muted">{team.members.map((m) => `${m.name}${m.status === "joined" ? "" : ` (${m.status})`}`).join(", ")}</span>
        </div>
      )}
      {error && <div className="error-box">{error}</div>}
      <button className="btn ghost sm" style={{ alignSelf: "flex-start" }} onClick={leave}>Leave this challenge</button>
    </article>
  );
}

function JoinCard({ pid, c, family, joined, onChange }) {
  const [inviting, setInviting] = useState(false);
  const [who, setWho] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function go(body, path) {
    setBusy(true);
    setError(null);
    try {
      onChange(await api(path, { method: "POST", body }));
      setInviting(false);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="card stack" aria-labelledby={`def-${c.id}`}>
      <div>
        <h3 id={`def-${c.id}`} className="card-title">{c.title}</h3>
        <p className="small muted">{c.description}</p>
        <p className="tiny muted" style={{ marginTop: 4 }}>{c.points_per_period} points each {c.period === "day" ? "day" : "week"} you meet it, {c.points} bonus to finish.</p>
      </div>
      {joined ? <span className="chip ok" style={{ alignSelf: "flex-start" }}><Check size={12} /> You're doing this</span> : (
        <div className="row wrap" style={{ gap: 8 }}>
          <button className="btn primary sm" disabled={busy} onClick={() => go({ definition_id: c.id }, `/challenges/patients/${pid}/enrollments`)}>Join</button>
          {c.family_allowed && family.length > 0 && (
            <button className="btn sm" aria-expanded={inviting} onClick={() => setInviting((v) => !v)}>Do it with family</button>
          )}
        </div>
      )}
      {inviting && !joined && (
        <fieldset className="wb-field">
          <legend>Invite</legend>
          <div className="wb-choices">
            {family.map((f) => (
              <label key={f.patient_id} className="wb-choice">
                <input type="checkbox" checked={who.includes(f.patient_id)}
                       onChange={(e) => setWho((all) => (e.target.checked ? [...all, f.patient_id] : all.filter((x) => x !== f.patient_id)))} />
                {f.name}
              </label>
            ))}
          </div>
          <span className="tiny muted">They'll get an invitation and join only if they choose to. The team sees combined progress, never individual numbers.</span>
          <button className="btn primary sm" style={{ alignSelf: "flex-start" }} disabled={busy || who.length === 0}
                  onClick={() => go({ definition_id: c.id, invite: who }, `/challenges/patients/${pid}/teams`)}>Send invitations and start</button>
        </fieldset>
      )}
      {error && <div className="error-box">{error}</div>}
    </article>
  );
}

function Invitation({ team, onChange }) {
  const [error, setError] = useState(null);
  const starter = team.members.find((m) => m.status === "joined" && m.name !== "You");
  async function answer(accept) {
    setError(null);
    try {
      onChange(await api(`/challenges/teams/${team.id}/respond`, { method: "POST", body: { accept } }));
    } catch (e) {
      setError(e.message);
    }
  }
  return (
    <div className="card highlight stack">
      <span className="strong">{starter ? `${starter.name} invited you` : "You're invited"}: {team.challenge.title}</span>
      <span className="small muted">Runs {shortDay(team.started_on)} to {shortDay(team.ends_on)}. Joining shares your combined progress with the team, not your numbers.</span>
      <div className="row wrap" style={{ gap: 8 }}>
        <button className="btn primary sm" onClick={() => answer(true)}>Join</button>
        <button className="btn sm" onClick={() => answer(false)}>No thanks</button>
      </div>
      {error && <div className="error-box">{error}</div>}
    </div>
  );
}

function Rewards({ pid, catalog, data, onChange }) {
  const [confirm, setConfirm] = useState(null);
  const [done, setDone] = useState(null);
  const [error, setError] = useState(null);
  async function redeem(r) {
    setError(null);
    try {
      const res = await api(`/challenges/patients/${pid}/redemptions`, { method: "POST", body: { reward_id: r.id } });
      setDone(res.redeemed);
      setConfirm(null);
      onChange(res);
    } catch (e) {
      setError(e.message);
    }
  }
  return (
    <div className="stack">
      <p className="banner info">{catalog.reward_note}</p>
      {done && <div className="banner ok" role="status"><Check size={16} /> Redeemed: {done.title}. Demo code {done.code}.</div>}
      {error && <div className="error-box">{error}</div>}
      <div className="card list">
        {catalog.rewards.map((r) => (
          <div key={r.id} className="wb-row" style={{ flexWrap: "wrap" }}>
            <div className="grow">
              <div className="strong small">{r.title}</div>
              <div className="tiny muted">{r.description}</div>
            </div>
            {confirm === r.id ? (
              <span className="row" style={{ gap: 6 }}>
                <button className="btn primary sm" onClick={() => redeem(r)}>Use {r.cost} points</button>
                <button className="btn ghost sm" onClick={() => setConfirm(null)}>Cancel</button>
              </span>
            ) : (
              <button className="btn sm" disabled={data.points < r.cost} onClick={() => setConfirm(r.id)}
                      aria-label={`Redeem ${r.title} for ${r.cost} points`}>{r.cost} points</button>
            )}
          </div>
        ))}
      </div>
      {data.redemptions.length > 0 && (
        <div className="card stack">
          <h3 className="card-title">Redeemed</h3>
          {data.redemptions.map((r) => (
            <div key={r.id} className="wb-row small">
              <span className="grow">{r.title}<br /><span className="tiny muted">{shortDay(r.created_at)} · code {r.code}</span></span>
              <span className="muted">-{r.points}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Challenges() {
  const { me } = useSession();
  const pid = me.patient_id;
  const res = useApi(`/challenges/patients/${pid}`);
  const catalog = useApi("/challenges/catalog");
  const [data, setData] = useState(null);
  const [warning, setWarning] = useState(null);
  useEffect(() => {
    if (res.data) setData(res.data);
  }, [res.data]);
  function onChange(next) {
    setData(next);
    setWarning(next.warning || null);
  }

  const teamsById = Object.fromEntries((data?.teams || []).map((t) => [t.id, t]));
  const invites = (data?.teams || []).filter((t) => t.my_status === "invited");
  return (
    <main className="column">
      <div className="wb-head">
        <span className="eyebrow">Wellbeing</span>
        <h1 className="page-title">Challenges & rewards</h1>
        <span className="page-sub">Small goals, counted from what you log. Only you see your points. Joining is always your choice.</span>
      </div>
      {(res.error || catalog.error) && !data && <div className="error-box" style={{ marginTop: 16 }}>{(res.error || catalog.error).message}</div>}
      {!data && res.loading && <div style={{ marginTop: 16 }}><Loading /></div>}
      {warning && (
        <div className="wb-crisis" role="alert" style={{ marginTop: 14 }}>
          <span className="title"><Warning size={18} /> Check this reading</span>
          <p>{warning}</p>
        </div>
      )}
      {data && (
        <>
          <section className="wb-section card stack" aria-label="Points and badges">
            <div className="wb-stats">
              <div className="wb-stat"><div className="v">{data.points}</div><div className="l">Points</div></div>
              <div className="wb-stat"><div className="v">{data.badges.length}</div><div className="l">Badges</div></div>
              <div className="wb-stat"><div className="v">{data.active.length}</div><div className="l">Active</div></div>
            </div>
            {data.badges.length > 0 && (
              <div className="row wrap" style={{ gap: 6 }}>
                {data.badges.map((b) => <span key={b.badge} className="chip ok" title={`Earned ${shortDay(b.awarded_at)}`}>{b.title}</span>)}
              </div>
            )}
          </section>

          {invites.length > 0 && (
            <section className="wb-section stack" aria-label="Invitations">
              {invites.map((t) => <Invitation key={t.id} team={t} onChange={onChange} />)}
            </section>
          )}

          <section className="wb-section" aria-labelledby="mine-h">
            <div className="wb-section-head"><h2 id="mine-h" className="wb-section-title">My challenges</h2></div>
            {data.active.length === 0 && <div className="card empty">You're not doing a challenge right now. Pick one below if you'd like.</div>}
            <div className="stack">
              {data.active.map((c) => <ActiveChallenge key={c.id} pid={pid} c={c} team={c.team_id ? teamsById[c.team_id] : null} onChange={onChange} />)}
            </div>
            <p className="tiny muted" style={{ marginTop: 8 }}>Progress updates as soon as you log. Points and badges are added each morning.</p>
          </section>

          <section className="wb-section" aria-labelledby="join-h">
            <div className="wb-section-head"><h2 id="join-h" className="wb-section-title">Join a challenge</h2></div>
            {catalog.loading && !catalog.data && <Loading />}
            <div className="stack">
              {catalog.data?.challenges.map((c) => (
                <JoinCard key={c.id} pid={pid} c={c} family={data.family} joined={data.joined_ids.includes(c.id)} onChange={onChange} />
              ))}
            </div>
          </section>

          <section className="wb-section" aria-labelledby="rewards-h">
            <div className="wb-section-head"><h2 id="rewards-h" className="wb-section-title">Rewards</h2></div>
            {catalog.data && <Rewards pid={pid} catalog={catalog.data} data={data} onChange={onChange} />}
          </section>

          {data.past.length > 0 && (
            <section className="wb-section" aria-labelledby="past-h">
              <div className="wb-section-head"><h2 id="past-h" className="wb-section-title">Finished</h2></div>
              <div className="card list">
                {data.past.map((c) => (
                  <div key={c.id} className="wb-row small">
                    <span className="grow"><span className="strong">{c.challenge.title}</span><br />
                      <span className="tiny muted">{shortDay(c.started_on)} to {shortDay(c.ends_on)} · met {c.periods_met} of {c.challenge.required}</span></span>
                    {c.status === "completed" ? <span className="chip ok">Completed</span> : <span className="chip">Ended</span>}
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </main>
  );
}
