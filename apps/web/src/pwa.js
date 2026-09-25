// Installable app and push support: platform checks and the browser's install prompt.

// iPadOS reports itself as a Mac; a Mac with a touch screen is an iPad.
export function isIOS() {
  if (typeof navigator === "undefined") return false;
  return /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

// Opened from the home screen / as an installed app rather than in a browser tab.
export function isStandalone() {
  if (typeof window === "undefined") return false;
  return window.matchMedia?.("(display-mode: standalone)").matches || window.navigator.standalone === true;
}

export function pushSupported() {
  return typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window
    && "Notification" in window;
}

export function urlBase64ToUint8Array(value) {
  const padded = (value + "=".repeat((4 - (value.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded);
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

export function bufferToBase64Url(buffer) {
  if (!buffer) return "";
  const bytes = new Uint8Array(buffer);
  let s = "";
  bytes.forEach((b) => { s += String.fromCharCode(b); });
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export async function sha256Hex(text) {
  if (!window.crypto?.subtle) return "";
  const digest = await window.crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

// Chrome and Edge fire `beforeinstallprompt` once, early. Keep it here (this module loads with the app)
// so a component mounted later can still offer the install button.
let deferredPrompt = null;
let installed = false;
const listeners = new Set();
const notify = () => listeners.forEach((fn) => fn());

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
    notify();
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    installed = true;
    notify();
  });
}

export function installState() {
  return { canPrompt: Boolean(deferredPrompt), installed: installed || isStandalone() };
}

export function onInstallChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export async function promptInstall() {
  const e = deferredPrompt;
  if (!e) return "unavailable";
  deferredPrompt = null;
  notify();
  e.prompt();
  const choice = await e.userChoice.catch(() => null);
  return choice?.outcome || "dismissed";
}

export function readFlag(key) {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

export function writeFlag(key) {
  try {
    window.localStorage.setItem(key, "1");
  } catch {
    // storage blocked: the choice lasts for this page load
  }
}
