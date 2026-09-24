import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api.js";

// Load a GET endpoint and optionally refresh it every `intervalMs`.
// Unlike useApi, a failed refresh keeps the last good data on screen and reports the error beside it.
export function usePoll(path, intervalMs = 0) {
  const [state, setState] = useState({ data: null, error: null, loading: Boolean(path), updatedAt: null });
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (!path) return;
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
  }, [load]);

  useEffect(() => {
    if (!intervalMs) return undefined;
    const id = setInterval(() => {
      if (document.visibilityState !== "hidden") load();
    }, intervalMs);
    return () => clearInterval(id);
  }, [load, intervalMs]);

  return { ...state, reload: load };
}

export function fmtTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
