import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api.js";
import { useApi } from "../../hooks.js";
import { useSession } from "../../session.jsx";
import { Back, Check, Chevron, Close, Plus, Warning } from "../../icons.jsx";
import { DataTable, DayBars, Loading, Meter, localDay, num, shortDay } from "./charts.jsx";

const MEALS = ["breakfast", "lunch", "dinner", "snack"];
const KEY_TARGETS = ["sodium_mg", "fiber_g", "veg_servings", "sugar_g", "protein_g", "kcal", "water_ml"];

function iso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function shift(dayIso, n) {
  const d = localDay(dayIso);
  d.setDate(d.getDate() + n);
  return iso(d);
}
function dayLabel(dayIso, todayIso) {
  if (dayIso === todayIso) return "Today";
  if (dayIso === shift(todayIso, -1)) return "Yesterday";
  return localDay(dayIso).toLocaleDateString([], { weekday: "long", day: "numeric", month: "short" });
}

// Shrink a photo in the browser before upload (max 1600 px, JPEG). The photo is only sent for this scan.
async function photoToBase64(file) {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = reject;
      i.src = url;
    });
    const scale = Math.min(1, 1600 / Math.max(img.width, img.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.width * scale);
    canvas.height = Math.round(img.height * scale);
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
    return { image: dataUrl.split(",")[1], media_type: "image/jpeg" };
  } finally {
    URL.revokeObjectURL(url);
  }
}

// --- Targets ----------------------------------------------------------------------------------------------

function Targets({ targets }) {
  const [all, setAll] = useState(false);
  const shown = (all ? targets : targets.filter((t) => KEY_TARGETS.slice(0, 4).includes(t.nutrient)))
    .sort((a, b) => KEY_TARGETS.indexOf(a.nutrient) - KEY_TARGETS.indexOf(b.nutrient));
  return (
    <div className="card stack" style={{ gap: 4 }}>
      <div className="row between wrap">
        <h2 className="card-title">Today against your targets</h2>
        <button className="btn ghost sm" onClick={() => setAll((v) => !v)} aria-expanded={all}>
          {all ? "Show fewer" : "Show all targets"}
        </button>
      </div>
      {shown.map((t) => {
        const over = t.status === "over";
        const under = t.status === "under";
        return (
          <div key={t.nutrient} className="wb-target">
            <div className="row between wrap small" style={{ gap: 6 }}>
              <span className="strong">{t.label}</span>
              <span className={over ? "strong" : "muted"} style={over ? { color: "var(--alert-strong)" } : undefined}>
                {num(t.amount, 0)} {t.kind === "max" ? "of under" : "of at least"} {num(t.value, 0)} {t.unit}
              </span>
            </div>
            <Meter value={t.amount} max={t.value} alert={over}
                   label={`${t.label}: ${num(t.amount, 0)} of ${num(t.value, 0)} ${t.unit}`} />
            {over && <span className="tiny" style={{ color: "var(--alert-strong)" }}><Warning size={12} /> Over today's target</span>}
            {under && t.nutrient !== "kcal" && <span className="tiny muted">Not there yet today</span>}
            {t.set_by === "clinician" && <span className="tiny"><span className="chip ok">Set by your care team</span> {t.reason}</span>}
            {t.set_by === "rule" && t.reason && <span className="tiny muted">{t.reason}</span>}
          </div>
        );
      })}
      <details className="wb-table-wrap">
        <summary>Where these targets come from</summary>
        <ul className="small muted" style={{ paddingLeft: 18, margin: "4px 0" }}>
          {targets.map((t) => <li key={t.nutrient}>{t.label}: {t.source}.</li>)}
        </ul>
      </details>
    </div>
  );
}

// --- Adding food ---------------------------------------------------------------------------------------------

function useFoodSearch(query) {
  const [state, setState] = useState({ results: [], loading: false, error: null });
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setState({ results: [], loading: false, error: null });
      return undefined;
    }
    let live = true;
    setState((s) => ({ ...s, loading: true }));
    const t = setTimeout(async () => {
      try {
        const results = await api(`/nutrition/foods?q=${encodeURIComponent(q)}&limit=12`);
        if (live) setState({ results, loading: false, error: null });
      } catch (e) {
        if (live) setState({ results: [], loading: false, error: e });
      }
    }, 220);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [query]);
  return state;
}

function ServingsInput({ id, value, onChange, label }) {
  return (
    <>
      <label htmlFor={id} className="sr-only">{label}</label>
      <input id={id} className="wb-servings" type="number" min="0.25" max="20" step="0.25" inputMode="decimal"
             value={value} onChange={(e) => onChange(e.target.value)} />
    </>
  );
}

function AddFood({ patientId, day, initialMeal, onSaved, onClose, autoFocus, intro }) {
  const [meal, setMeal] = useState(initialMeal || "lunch");
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const search = useFoodSearch(query);
  const inputRef = useRef(null);
  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

  function add(food) {
    setPicked((p) => [...p, { key: `${food.id}-${Date.now()}`, food, servings: 1 }]);
    setQuery("");
    inputRef.current?.focus();
  }

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const items = picked.map((p) => ({ food_id: p.food.id, servings: Number(p.servings) }));
      if (items.some((i) => !(i.servings > 0))) throw new Error("Each item needs an amount above zero");
      await onSaved(await api(`/nutrition/patients/${patientId}/meals`, { method: "POST", body: { eaten_on: day, meal, items } }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card wb-form" onSubmit={save} aria-label="Add food">
      <div className="row between">
        <h2 className="card-title">Add food</h2>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close"><Close size={18} /></button>
      </div>
      {intro && <p className="banner info">{intro}</p>}
      <fieldset className="wb-field">
        <legend>Meal</legend>
        <div className="wb-choices">
          {MEALS.map((m) => (
            <label key={m} className="wb-choice">
              <input type="radio" name="meal" value={m} checked={meal === m} onChange={() => setMeal(m)} />
              {m[0].toUpperCase() + m.slice(1)}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="wb-field">
        <label htmlFor="food-search">Search foods</label>
        <input id="food-search" ref={inputRef} type="search" placeholder="e.g. oatmeal, turkey sandwich, water"
               value={query} onChange={(e) => setQuery(e.target.value)} autoComplete="off" />
      </div>
      {search.error && <div className="error-box">{search.error.message}</div>}
      {query.trim().length >= 2 && (
        <div className="wb-results" role="list" aria-label="Matching foods">
          {search.loading && search.results.length === 0 && <div className="small muted" style={{ padding: 12 }}>Searching…</div>}
          {!search.loading && search.results.length === 0 && (
            <div className="small muted" style={{ padding: 12 }}>No matches. Try a simpler word, like "chicken" or "soup".</div>
          )}
          {search.results.map((f) => (
            <button type="button" key={f.id} className="wb-result" role="listitem" onClick={() => add(f)}>
              <span style={{ minWidth: 0 }}>
                <span className="strong small" style={{ display: "block" }}>{f.name}</span>
                <span className="tiny muted">{f.serving} · {num(f.kcal, 0)} kcal · {num(f.sodium_mg, 0)} mg sodium</span>
              </span>
              <Plus size={16} />
            </button>
          ))}
        </div>
      )}
      {picked.length > 0 && (
        <div className="stack" style={{ gap: 0 }} aria-label="Items to save">
          {picked.map((p, i) => (
            <div key={p.key} className="wb-food">
              <span className="name small"><span className="strong">{p.food.name}</span><br /><span className="muted tiny">servings of {p.food.serving}</span></span>
              <span className="row" style={{ gap: 6 }}>
                <ServingsInput id={`sv-${p.key}`} label={`Servings of ${p.food.name}`} value={p.servings}
                               onChange={(v) => setPicked((all) => all.map((x, j) => (j === i ? { ...x, servings: v } : x)))} />
                <button type="button" className="icon-btn" aria-label={`Remove ${p.food.name}`}
                        onClick={() => setPicked((all) => all.filter((_, j) => j !== i))}><Close size={16} /></button>
              </span>
            </div>
          ))}
        </div>
      )}
      {error && <div className="error-box">{error}</div>}
      <button className="btn primary" disabled={busy || picked.length === 0}>
        {busy ? "Saving…" : picked.length ? `Save ${picked.length} item${picked.length > 1 ? "s" : ""} to ${meal}` : "Pick at least one food"}
      </button>
    </form>
  );
}

// --- Photo scan -------------------------------------------------------------------------------------------------

function ScanReview({ patientId, day, scan, onSaved, onCancel }) {
  const [meal, setMeal] = useState("lunch");
  const [rows, setRows] = useState(() => scan.items.filter((i) => i.food).map((i, n) => ({
    key: n, seen: i.seen, portion: i.portion, confidence: i.confidence, options: [i.food, ...i.alternatives],
    foodId: i.food.id, servings: i.servings, keep: true,
  })));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const unmatched = scan.items.filter((i) => !i.food);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const items = rows.filter((r) => r.keep).map((r) => ({ food_id: r.foodId, servings: Number(r.servings) }));
      await onSaved(await api(`/nutrition/patients/${patientId}/meals`, {
        method: "POST", body: { eaten_on: day, meal, items, source: "photo" },
      }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const kept = rows.filter((r) => r.keep).length;
  return (
    <section className="card stack" aria-labelledby="scan-review">
      <h2 id="scan-review" className="card-title">Check what we found</h2>
      <p className="small muted">{scan.message} Your photo was not saved.</p>
      <fieldset className="wb-field">
        <legend>Meal</legend>
        <div className="wb-choices">
          {MEALS.map((m) => (
            <label key={m} className="wb-choice">
              <input type="radio" name="scan-meal" checked={meal === m} onChange={() => setMeal(m)} />
              {m[0].toUpperCase() + m.slice(1)}
            </label>
          ))}
        </div>
      </fieldset>
      {rows.map((r, i) => (
        <div key={r.key} className="wb-muted-box stack" style={{ gap: 8 }}>
          <div className="row between wrap">
            <span className="small"><span className="strong">Looks like: {r.seen}</span> · {r.portion}
              {r.confidence === "low" && <span className="chip warn" style={{ marginLeft: 6 }}>Not sure</span>}</span>
            <label className="row small" style={{ gap: 6, minHeight: 44 }}>
              <input type="checkbox" checked={r.keep} style={{ width: 20, height: 20, accentColor: "var(--accent)" }}
                     onChange={(e) => setRows((all) => all.map((x, j) => (j === i ? { ...x, keep: e.target.checked } : x)))} />
              Include
            </label>
          </div>
          <div className="wb-inline">
            <div className="wb-field">
              <label htmlFor={`scan-food-${i}`}>Food</label>
              <select id={`scan-food-${i}`} value={r.foodId}
                      onChange={(e) => setRows((all) => all.map((x, j) => (j === i ? { ...x, foodId: e.target.value } : x)))}>
                {r.options.map((o) => <option key={o.id} value={o.id}>{o.name} ({o.serving})</option>)}
              </select>
            </div>
            <div className="wb-field" style={{ flex: "0 0 auto" }}>
              <label htmlFor={`scan-sv-${i}`}>Servings</label>
              <input id={`scan-sv-${i}`} className="wb-servings" type="number" min="0.25" max="20" step="0.25" value={r.servings}
                     onChange={(e) => setRows((all) => all.map((x, j) => (j === i ? { ...x, servings: e.target.value } : x)))} />
            </div>
          </div>
        </div>
      ))}
      {unmatched.length > 0 && (
        <p className="small muted">Not in our food list: {unmatched.map((u) => u.seen).join(", ")}. Add them with search after saving.</p>
      )}
      {error && <div className="error-box">{error}</div>}
      <div className="row wrap">
        <button className="btn primary" onClick={save} disabled={busy || kept === 0}>{busy ? "Saving…" : `Save ${kept} item${kept === 1 ? "" : "s"}`}</button>
        <button className="btn ghost" onClick={onCancel}>Cancel</button>
      </div>
    </section>
  );
}

function ScanButton({ patientId, onResult }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);

  async function onFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const body = await photoToBase64(file);
      onResult(await api(`/nutrition/patients/${patientId}/scan`, { method: "POST", body }));
    } catch (err) {
      setError(err.message || "That photo couldn't be read.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ gap: 6 }}>
      <input ref={inputRef} id="food-photo" type="file" accept="image/*" capture="environment" className="sr-only" onChange={onFile} tabIndex={-1} />
      <button className="btn" onClick={() => inputRef.current?.click()} disabled={busy}>
        {busy ? "Looking at your photo…" : "Scan a meal photo"}
      </button>
      {error && <div className="error-box small">{error}</div>}
    </div>
  );
}

// --- Meals ------------------------------------------------------------------------------------------------------

function Meals({ data, onChanged, onAdd }) {
  const [error, setError] = useState(null);
  async function removeItem(meal, item) {
    setError(null);
    try {
      onChanged(await api(`/nutrition/meals/${meal.id}/items/${item.id}`, { method: "DELETE" }));
    } catch (e) {
      setError(e.message);
    }
  }
  return (
    <div className="stack" style={{ gap: 10 }}>
      {error && <div className="error-box">{error}</div>}
      {MEALS.map((m) => {
        const meals = data.meals.filter((x) => x.meal === m);
        const items = meals.flatMap((x) => x.items.map((it) => ({ meal: x, item: it })));
        const kcal = meals.reduce((s, x) => s + x.totals.kcal, 0);
        const sodium = meals.reduce((s, x) => s + x.totals.sodium_mg, 0);
        return (
          <article key={m} className="card" aria-labelledby={`meal-${m}`}>
            <div className="row between wrap">
              <h3 id={`meal-${m}`} className="wb-meal-title">{m}</h3>
              {items.length > 0 && <span className="tiny muted">{num(kcal, 0)} kcal · {num(sodium, 0)} mg sodium</span>}
            </div>
            {items.length === 0 && <p className="small muted" style={{ padding: "6px 0" }}>Nothing logged.</p>}
            {items.map(({ meal, item }) => (
              <div key={item.id} className="wb-food">
                <span className="name small">
                  <span className="strong">{item.name}</span>
                  {meal.source === "photo" && <span className="chip" style={{ marginLeft: 6 }}>From photo</span>}
                  <br />
                  <span className="tiny muted">{num(item.servings, 2)} × {item.serving} · {num(item.kcal, 0)} kcal · {num(item.sodium_mg, 0)} mg sodium</span>
                </span>
                <button className="icon-btn" aria-label={`Remove ${item.name} from ${m}`} onClick={() => removeItem(meal, item)}>
                  <Close size={16} />
                </button>
              </div>
            ))}
            <button className="btn ghost sm" onClick={() => onAdd(m)}><Plus size={14} /> Add to {m}</button>
          </article>
        );
      })}
    </div>
  );
}

// --- Week ------------------------------------------------------------------------------------------------------

function Week({ week }) {
  const { data, error, loading } = week;
  if (error) return <div className="error-box">{error.message}</div>;
  if (loading && !data) return <Loading />;
  const sodium = data.targets.find((t) => t.nutrient === "sodium_mg");
  const days = data.days.map((d) => ({ date: d.date, value: d.totals ? d.totals.sodium_mg : null }));
  return (
    <div className="stack">
      <div className="card stack">
        <h3 className="card-title">Sodium, last 7 days</h3>
        <DayBars days={days} target={sodium.value} unit="mg" label={`Sodium per day for the last 7 days against a target of ${sodium.value} mg`} />
        <DataTable caption="Sodium per day" columns={["Day", "Sodium (mg)"]}
                   rows={days.map((d) => [shortDay(d.date), d.value == null ? "—" : num(d.value, 0)])} />
      </div>
      <div className="card stack">
        <h3 className="card-title">Patterns this week</h3>
        {!data.enough_data && <p className="small muted">Log at least 3 days to see your patterns. You've logged {data.logged_days} of the last 7.</p>}
        {data.patterns.map((p) => (
          <p key={p.nutrient} className="small row" style={{ alignItems: "flex-start", gap: 8 }}>
            <span style={{ color: p.nutrient === "sodium_mg" || p.nutrient === "sugar_g" ? "var(--alert)" : "var(--accent)", marginTop: 2 }}><Warning size={14} /></span>
            <span>{p.text}</span>
          </p>
        ))}
        {data.enough_data && data.patterns.length === 0 && <p className="small"><Check size={14} /> No patterns to flag this week.</p>}
        {data.tips.length > 0 && (
          <div className="stack" style={{ gap: 10 }}>
            <span className="eyebrow">Tips</span>
            {data.tips.map((t) => (
              <div key={t.text} className="wb-tip-card small">
                <p>{t.text}</p>
                <a className="tiny" href={t.url} target="_blank" rel="noreferrer">Source: {t.source}</a>
              </div>
            ))}
            <p className="tiny muted">General information from public health sources, not personal medical advice.</p>
          </div>
        )}
      </div>
    </div>
  );
}

// --- Page ------------------------------------------------------------------------------------------------------

export default function Nutrition() {
  const { me } = useSession();
  const pid = me.patient_id;
  const [params, setParams] = useSearchParams();
  const [day, setDay] = useState(null);
  const view = useApi(`/nutrition/patients/${pid}/day${day ? `?day=${day}` : ""}`);
  const week = useApi(`/nutrition/patients/${pid}/week`);
  const [data, setData] = useState(null);
  const [adding, setAdding] = useState(null); // { meal, intro }
  const [scan, setScan] = useState(null);
  const [saved, setSaved] = useState(null);
  const scanRequested = params.get("scan") === "1";

  useEffect(() => {
    if (view.data) setData(view.data);
  }, [view.data]);

  const today = data?.today;
  const current = data?.date;

  function onSaved(next) {
    setData(next);
    setAdding(null);
    setScan(null);
    setSaved("Saved to your food log.");
    week.reload();
  }
  function onScan(result) {
    if (params.get("scan")) setParams({}, { replace: true });
    if (result.mode === "rules" || result.items.length === 0) {
      setScan(null);
      setAdding({ meal: "lunch", intro: result.message });
    } else {
      setScan(result);
      setAdding(null);
    }
  }

  return (
    <main className="column">
      <div className="wb-head">
        <span className="eyebrow">Wellbeing</span>
        <h1 className="page-title">Food & nutrition</h1>
        <span className="page-sub">Log meals, see today against your targets, and spot patterns over the week.</span>
      </div>

      {view.error && !data && <div className="error-box" style={{ marginTop: 16 }}>{view.error.message}</div>}
      {!data && view.loading && <div style={{ marginTop: 16 }}><Loading /></div>}

      {data && (
        <>
          <div className="row between wrap" style={{ marginTop: 18 }}>
            <div className="row" style={{ gap: 6 }}>
              <button className="icon-btn" aria-label="Previous day" onClick={() => setDay(shift(current, -1))}><Back size={18} /></button>
              <span className="strong" aria-live="polite" style={{ minWidth: 100, textAlign: "center" }}>{dayLabel(current, today)}</span>
              <button className="icon-btn" aria-label="Next day" disabled={current >= today} onClick={() => setDay(shift(current, 1))}>
                <Chevron size={18} />
              </button>
            </div>
            <Link className="small strong" to="/weight">Weight coach <Chevron size={14} /></Link>
          </div>

          {scanRequested && !scan && !adding && (
            <div className="card highlight stack" style={{ marginTop: 12 }}>
              <span className="strong">Scan your food</span>
              <span className="small muted">Take or choose a photo of your meal. You'll check every item before anything is saved, and the photo isn't kept.</span>
              <ScanButton patientId={pid} onResult={onScan} />
            </div>
          )}

          {saved && <div className="banner ok" role="status" style={{ marginTop: 12 }}><Check size={16} /> {saved}</div>}

          <section className="wb-section" aria-label="Targets">
            <Targets targets={data.targets} />
          </section>

          <section className="wb-section" aria-labelledby="meals-h">
            <div className="wb-section-head">
              <h2 id="meals-h" className="wb-section-title">Meals</h2>
              <div className="row wrap" style={{ gap: 8 }}>
                {!scanRequested && <ScanButton patientId={pid} onResult={onScan} />}
                <button className="btn primary" onClick={() => { setSaved(null); setAdding({ meal: "lunch" }); }}><Plus size={16} /> Add food</button>
              </div>
            </div>
            {scan && <ScanReview patientId={pid} day={current} scan={scan} onSaved={onSaved} onCancel={() => setScan(null)} />}
            {adding && (
              <AddFood key={`${adding.meal}-${adding.intro || ""}`} patientId={pid} day={current} initialMeal={adding.meal}
                       intro={adding.intro} autoFocus onSaved={onSaved} onClose={() => setAdding(null)} />
            )}
            <div style={{ marginTop: 12 }}>
              <Meals data={data} onChanged={(next) => { setData(next); week.reload(); }}
                     onAdd={(m) => { setSaved(null); setAdding({ meal: m }); }} />
            </div>
            <p className="tiny muted" style={{ marginTop: 8 }}>{data.note}</p>
          </section>

          <section className="wb-section" aria-labelledby="week-h">
            <div className="wb-section-head"><h2 id="week-h" className="wb-section-title">Your week</h2></div>
            <Week week={week} />
          </section>
        </>
      )}
    </main>
  );
}
