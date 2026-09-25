import { useEffect, useState } from "react";
import { useSession } from "../session.jsx";
import { installState, isIOS, isStandalone, onInstallChange, promptInstall, readFlag, writeFlag } from "../pwa.js";
import "./pwa.css";

const DISMISS_KEY = "bioverse.installBanner.dismissed";

export function useInstall() {
  const [state, setState] = useState(installState);
  useEffect(() => onInstallChange(() => setState(installState())), []);
  const iosHint = isIOS() && !isStandalone();
  return { ...state, iosHint, offer: !state.installed && (state.canPrompt || iosHint) };
}

function ShareIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="pwa-share-icon">
      <path d="M12 3v12" /><path d="M8 7l4-4 4 4" /><path d="M5 11v8a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-8" />
    </svg>
  );
}

function IOSSteps() {
  return (
    <span>Tap <ShareIcon /><span className="sr-only">Share</span> Share, then <strong>Add to Home Screen</strong>.</span>
  );
}

// Settings card: install Bioverse One as an app on this phone or computer.
export default function InstallApp() {
  const { installed, canPrompt, iosHint } = useInstall();
  const [outcome, setOutcome] = useState(null);

  let body;
  if (installed) {
    body = <p className="small muted">Bioverse One is installed on this device.</p>;
  } else if (canPrompt) {
    body = (
      <div className="row between wrap">
        <p className="small muted">Open Bioverse One from your home screen, full screen, like any other app.</p>
        <button type="button" className="btn primary sm" onClick={async () => setOutcome(await promptInstall())}>
          Install app
        </button>
      </div>
    );
  } else if (iosHint) {
    body = <p className="small muted"><IOSSteps /> You need this on iPhone and iPad to get push notifications.</p>;
  } else {
    body = (
      <p className="small muted">
        On Android, open this page in Chrome and choose <strong>Install app</strong> from the menu. On iPhone, open it
        in Safari, tap Share, then <strong>Add to Home Screen</strong>.
      </p>
    );
  }
  return (
    <section className="card stack pwa-card" aria-labelledby="install-h">
      <h2 id="install-h" className="card-title">Bioverse One app</h2>
      {body}
      {outcome === "dismissed" && <p className="small muted" role="status">No problem. You can install it later.</p>}
    </section>
  );
}

// Slim banner for patients on phones. Hidden on larger screens by CSS; dismissal is remembered.
export function InstallBanner() {
  const { me } = useSession();
  const { offer, canPrompt, iosHint } = useInstall();
  const [dismissed, setDismissed] = useState(() => readFlag(DISMISS_KEY));
  if (me?.role !== "patient" || !offer || dismissed) return null;
  const dismiss = () => { writeFlag(DISMISS_KEY); setDismissed(true); };
  return (
    <div className="pwa-banner" role="region" aria-label="Install the app">
      <img src="/icon-192.png" alt="" width="28" height="28" />
      <div className="pwa-banner-text small">
        {canPrompt ? <span><strong>Get the app.</strong> Reminders and results on your home screen.</span>
          : iosHint ? <span><strong>Get the app:</strong> <IOSSteps /></span> : null}
      </div>
      {canPrompt && (
        <button type="button" className="btn primary sm" onClick={async () => {
          if ((await promptInstall()) === "accepted") dismiss();
        }}>Install</button>
      )}
      <button type="button" className="pwa-banner-close" onClick={dismiss} aria-label="Dismiss">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"
             strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
      </button>
    </div>
  );
}
