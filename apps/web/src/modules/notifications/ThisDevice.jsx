import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../../api.js";
import { fmtDateTime } from "../../format.js";
import { bufferToBase64Url, isIOS, isStandalone, pushSupported, sha256Hex, urlBase64ToUint8Array } from "../../pwa.js";
import "../../components/pwa.css";

// The service worker registers on page load in production; give it a moment on the first visit.
async function registration() {
  let reg = await navigator.serviceWorker.getRegistration();
  if (!reg && import.meta.env.PROD) {
    reg = await Promise.race([navigator.serviceWorker.ready, new Promise((r) => setTimeout(() => r(null), 4000))]);
  }
  return reg || null;
}

function subscriptionBody(sub) {
  const json = sub.toJSON();
  return { endpoint: json.endpoint, keys: json.keys };
}

// Background push for this phone or computer: works even when Bioverse One is closed.
export default function ThisDevice() {
  const [state, setState] = useState("checking");
  const [config, setConfig] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);
  const [devices, setDevices] = useState([]);
  const [mine, setMine] = useState(null);

  const loadDevices = useCallback(async () => {
    try { setDevices((await api("/push/subscriptions")).items); } catch { /* the list is optional */ }
  }, []);

  const check = useCallback(async () => {
    if (isIOS() && !isStandalone()) return setState("ios_install");
    if (!pushSupported()) return setState("unsupported");
    let cfg;
    try {
      cfg = await api("/push/config");
    } catch {
      return setState("error");
    }
    setConfig(cfg);
    loadDevices();
    if (!cfg.enabled) return setState("not_configured");
    const reg = await registration();
    if (!reg) return setState("no_worker");
    if (Notification.permission === "denied") return setState("blocked");
    const sub = await reg.pushManager.getSubscription();
    if (!sub || Notification.permission !== "granted") return setState("off");
    // A subscription made with an older server key can't receive anything: start over.
    if (bufferToBase64Url(sub.options?.applicationServerKey) !== cfg.public_key) {
      await sub.unsubscribe().catch(() => {});
      return setState("off");
    }
    // Keep the server in step: the device may have been removed there, or someone else signed in here.
    try {
      const saved = await api("/push/subscriptions", { method: "POST", body: subscriptionBody(sub) });
      setMine(saved.fingerprint);
    } catch { /* shown as on; a test will tell */ }
    loadDevices();
    return setState("on");
  }, [loadDevices]);

  useEffect(() => { check(); }, [check]);

  async function turnOn() {
    setBusy(true);
    setNote(null);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setState(permission === "denied" ? "blocked" : "off");
        return;
      }
      const reg = await registration();
      if (!reg) { setState("no_worker"); return; }
      // Some browsers without a working push service never settle this promise; don't spin forever.
      const sub = await Promise.race([
        reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(config.public_key) }),
        new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), 20000)),
      ]);
      const saved = await api("/push/subscriptions", { method: "POST", body: subscriptionBody(sub) });
      setMine(saved.fingerprint);
      setState("on");
      setNote("Push is on for this device.");
      loadDevices();
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : "Couldn't turn on push on this device. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function turnOff() {
    setBusy(true);
    setNote(null);
    try {
      const reg = await registration();
      const sub = reg && await reg.pushManager.getSubscription();
      if (sub) {
        try {
          await api("/push/subscriptions", { method: "DELETE", body: { endpoint: sub.endpoint } });
        } catch (e) {
          if (!(e instanceof ApiError && e.status === 404)) throw e;
        }
        await sub.unsubscribe();
      }
      setMine(null);
      setState("off");
      setNote("Push is off for this device.");
      loadDevices();
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : "Couldn't turn push off. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function sendTest() {
    setBusy(true);
    setNote(null);
    try {
      const r = await api("/push/test", { method: "POST" });
      setNote(r.sent > 0
        ? `Sent to ${r.sent} ${r.sent === 1 ? "device" : "devices"}. It should arrive in a few seconds.`
        : r.removed > 0
          ? "The push service no longer accepts this device's registration. Turn push off and on again."
          : "Nothing could be delivered. Try again in a minute, or turn push off and on again.");
      loadDevices();
    } catch (e) {
      setNote(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function removeDevice(d) {
    try {
      await api(`/push/subscriptions/${d.id}`, { method: "DELETE" });
    } catch { /* already gone */ }
    if (d.fingerprint === mine) await check(); else loadDevices();
  }

  // Which of the listed devices is this one.
  useEffect(() => {
    if (state !== "on" || mine) return;
    (async () => {
      const reg = await registration();
      const sub = reg && await reg.pushManager.getSubscription();
      if (sub) setMine((await sha256Hex(sub.endpoint)).slice(0, 16));
    })();
  }, [state, mine]);

  const MESSAGES = {
    checking: "Checking this device…",
    ios_install: "On iPhone and iPad, push works in the installed app. In Safari, tap Share, then Add to Home Screen, and open Bioverse One from your home screen (iOS 16.4 or later).",
    unsupported: "This browser can't receive push notifications. Try Chrome, Edge, Firefox or Safari, or install the app.",
    not_configured: "Your administrator hasn't turned on push yet.",
    no_worker: "Push works in the installed app and the published site. This development build doesn't run the background service it needs.",
    blocked: "Notifications are blocked for Bioverse One. Allow them in your browser or phone settings, then come back here.",
    off: "Get reminders and alerts on this device even when Bioverse One is closed. They only say that something is waiting, never health details.",
    on: "On. Notifications reach this device even when Bioverse One is closed.",
    error: "Couldn't check push settings right now.",
  };

  const others = devices.filter((d) => d.fingerprint !== mine);
  return (
    <section className="card stack pwa-card" aria-labelledby="device-h">
      <div className="row between wrap">
        <h2 id="device-h" className="card-title">This device</h2>
        <span className={`pwa-status ${state === "on" ? "on" : ""}`}>{state === "on" ? "Push on" : "Push off"}</span>
      </div>
      <p className="small muted" role="status">{MESSAGES[state]}</p>
      {state === "off" && (
        <div className="row wrap">
          <button type="button" className="btn primary" onClick={turnOn} disabled={busy || !config?.public_key}>
            {busy ? "Turning on…" : "Turn on push for this device"}
          </button>
        </div>
      )}
      {state === "on" && (
        <div className="row wrap">
          <button type="button" className="btn sm" onClick={sendTest} disabled={busy}>Send a test</button>
          <button type="button" className="btn sm ghost" onClick={turnOff} disabled={busy}>Turn off</button>
        </div>
      )}
      {note && <p className="small" role="status">{note}</p>}
      {others.length > 0 && (
        <div className="stack" style={{ gap: 6 }}>
          <div className="small strong">Your other devices</div>
          <ul className="pwa-devices">
            {others.map((d) => (
              <li key={d.id}>
                <span className="stack" style={{ gap: 0, minWidth: 0 }}>
                  <span className="small strong">{d.device}</span>
                  <span className="tiny muted">
                    Added {fmtDateTime(d.created_at)}
                    {d.last_success_at ? ` · last delivered ${fmtDateTime(d.last_success_at)}` : ""}
                  </span>
                </span>
                <button type="button" className="btn sm ghost" onClick={() => removeDevice(d)}
                        aria-label={`Remove ${d.device}`}>Remove</button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="tiny muted">Choose which notifications go to your phone in the "Phone push" column below.</p>
    </section>
  );
}
