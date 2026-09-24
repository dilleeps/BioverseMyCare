// Display preferences: senior mode, text size, contrast, motion, read-aloud.
//
// The server (GET/PUT /api/accessibility/preferences) is the source of truth, so preferences follow the
// person across devices. A per-user copy in localStorage paints the first frame correctly before the
// server answers. The root <html> element carries the result as attributes that styles.css reads:
//   data-senior="true"  data-high-contrast="true"  data-reduce-motion="true"  --a11y-scale: <number>
import { useEffect, useSyncExternalStore } from "react";
import { api, getUserId } from "../../api.js";

export const DEFAULTS = {
  senior_mode: false,
  text_scale: 1,
  high_contrast: false,
  reduce_motion: false,
  read_aloud: false,
};
export const SCALE_MIN = 1;
export const SCALE_MAX = 1.6;
const SENIOR_BASE = 1.25; // senior mode: about 20px body text, then text_scale on top

const keyFor = (userId) => `bioverse.display.${userId || "anonymous"}`;

function readCache(userId) {
  try {
    const raw = localStorage.getItem(keyFor(userId));
    return raw ? { ...DEFAULTS, ...JSON.parse(raw) } : { ...DEFAULTS };
  } catch {
    return { ...DEFAULTS };
  }
}

function writeCache(userId, prefs) {
  try {
    localStorage.setItem(keyFor(userId), JSON.stringify(pick(prefs)));
  } catch {
    // Storage blocked: the server copy still applies on the next load.
  }
}

function pick(p) {
  return Object.fromEntries(Object.keys(DEFAULTS).map((k) => [k, p[k] ?? DEFAULTS[k]]));
}

function clampScale(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return 1;
  return Math.min(SCALE_MAX, Math.max(SCALE_MIN, Math.round(v * 100) / 100));
}

export function scaleOf(p) {
  return (p.senior_mode ? SENIOR_BASE : 1) * clampScale(p.text_scale);
}

export function applyToRoot(p) {
  if (typeof document === "undefined") return;
  const el = document.documentElement;
  const set = (name, on) => (on ? el.setAttribute(name, "true") : el.removeAttribute(name));
  set("data-senior", p.senior_mode);
  set("data-high-contrast", p.high_contrast);
  set("data-reduce-motion", p.reduce_motion);
  const scale = scaleOf(p);
  set("data-a11y-scale", scale !== 1);
  el.style.setProperty("--a11y-scale", String(Math.round(scale * 1000) / 1000));
}

// --- A tiny store shared by every component (no provider needed) ------------------------------------

let owner = getUserId();
let state = { ...readCache(owner), loaded: false, saving: false, error: null };
const listeners = new Set();
applyToRoot(state); // first paint, before React renders

function emit(next) {
  state = next;
  applyToRoot(state);
  listeners.forEach((l) => l());
}

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useDisplayPrefs() {
  return useSyncExternalStore(subscribe, () => state, () => state);
}

// Load the signed-in person's preferences: their cached copy at once, then the server's.
export async function loadFor(userId) {
  owner = userId;
  emit({ ...readCache(userId), loaded: false, saving: false, error: null });
  if (!userId) return;
  try {
    const server = await api("/accessibility/preferences");
    if (owner !== userId) return; // switched identity meanwhile
    const next = pick(server);
    writeCache(userId, next);
    emit({ ...next, loaded: true, saving: false, error: null });
  } catch (e) {
    if (owner === userId) emit({ ...state, loaded: true, error: e.message });
  }
}

// Save a change. Applied at once (and cached), then confirmed by the server.
export async function savePrefs(changes) {
  const userId = owner;
  const clean = { ...changes };
  if ("text_scale" in clean) clean.text_scale = clampScale(clean.text_scale);
  const optimistic = { ...state, ...clean, saving: true, error: null };
  writeCache(userId, optimistic);
  emit(optimistic);
  try {
    const server = await api("/accessibility/preferences", { method: "PUT", body: clean });
    if (owner !== userId) return;
    const next = pick(server);
    writeCache(userId, next);
    emit({ ...state, ...next, saving: false, error: null });
  } catch (e) {
    if (owner === userId) emit({ ...state, saving: false, error: `Saved on this device only. ${e.message}` });
  }
}

// Mounted once at the app root: loads (and applies) the signed-in person's preferences whenever they change.
export function useSyncDisplayPrefs(userId) {
  useEffect(() => {
    loadFor(userId || null);
  }, [userId]);
}
