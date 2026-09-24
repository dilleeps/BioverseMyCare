// Helpers shared by the operations, analytics, organization and pathways screens.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api.js";

// Date-only strings ("2026-09-18") are calendar days; parse them without a time-zone shift.
export function parseDay(iso) {
  if (!iso) return null;
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function fmtDay(iso, opts = { day: "numeric", month: "short" }) {
  const d = parseDay(iso);
  return d ? d.toLocaleDateString([], opts) : "";
}

export function fmtWeekday(iso) {
  return fmtDay(iso, { weekday: "long", day: "numeric", month: "long" });
}

export const fmtPct = (v) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(Number.isInteger(v) ? 0 : 1)}%`);

export function fmtHours(h) {
  if (h === null || h === undefined) return "—";
  if (h < 1) return `${Math.round(h * 60)} min`;
  if (h < 48) return `${Number(h).toFixed(h < 10 ? 1 : 0)} h`;
  return `${(h / 24).toFixed(1)} days`;
}

export function fmtTime(d) {
  return d ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
}

export function todayIso(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// Poll an endpoint. Keeps the last good data on screen while refreshing or after a failed refresh.
export function usePolling(path, intervalMs = 60000) {
  const [state, setState] = useState({ data: null, error: null, loading: true, updatedAt: null });
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setState((s) => ({ ...s, loading: true }));
    try {
      const data = await api(path);
      if (mine === seq.current) setState({ data, error: null, loading: false, updatedAt: new Date() });
    } catch (error) {
      if (mine === seq.current) setState((s) => ({ ...s, error, loading: false }));
    }
  }, [path]);

  useEffect(() => {
    load();
    if (!intervalMs) return undefined;
    const t = setInterval(() => {
      if (typeof document === "undefined" || document.visibilityState === "visible") load();
    }, intervalMs);
    return () => clearInterval(t);
  }, [load, intervalMs]);

  return { ...state, reload: load };
}

export function Definitions({ items, title = "How these numbers are calculated" }) {
  const entries = Object.entries(items || {}).filter(([, v]) => v);
  if (!entries.length) return null;
  return (
    <details className="definitions">
      <summary>{title}</summary>
      <dl>
        {entries.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

export function LoadingCard({ lines = 3 }) {
  return (
    <div className="card stack" aria-busy="true" aria-label="Loading">
      {Array.from({ length: lines }, (_, i) => <div key={i} className="skeleton" style={{ width: `${90 - i * 15}%` }} />)}
    </div>
  );
}

// Text field bound to one key of a form object.
export function Field({ id, label, hint, value, onChange, type = "text", ...rest }) {
  return (
    <div className="fld">
      <label htmlFor={id}>{label}</label>
      <input id={id} type={type} value={value ?? ""} onChange={(e) => onChange(e.target.value)}
             aria-describedby={hint ? `${id}-hint` : undefined} {...rest} />
      {hint && <span id={`${id}-hint`} className="hint">{hint}</span>}
    </div>
  );
}

export function Select({ id, label, value, onChange, options, hint, ...rest }) {
  return (
    <div className="fld">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value ?? ""} onChange={(e) => onChange(e.target.value)} {...rest}>
        {options.map((o) => <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>)}
      </select>
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}

export function Check({ id, label, checked, onChange, ...rest }) {
  return (
    <label className="check" htmlFor={id}>
      <input id={id} type="checkbox" checked={Boolean(checked)} onChange={(e) => onChange(e.target.checked)} {...rest} />
      {label}
    </label>
  );
}

// A save-with-feedback helper for admin forms.
export function useSave() {
  const [state, setState] = useState({ busy: false, error: null, saved: null });
  const run = useCallback(async (fn, savedMessage = "Saved") => {
    setState({ busy: true, error: null, saved: null });
    try {
      const out = await fn();
      setState({ busy: false, error: null, saved: savedMessage });
      return out;
    } catch (e) {
      setState({ busy: false, error: e.message, saved: null });
      return undefined;
    }
  }, []);
  const clear = useCallback(() => setState({ busy: false, error: null, saved: null }), []);
  return { ...state, run, clear };
}

export function Toast({ message, onDone }) {
  useEffect(() => {
    if (!message) return undefined;
    const t = setTimeout(onDone, 2600);
    return () => clearTimeout(t);
  }, [message, onDone]);
  if (!message) return null;
  return <div className="toast" role="status">{message}</div>;
}
