import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";
import { useSession } from "../../session.jsx";

const POLL_MS = 60000;

function BellIcon({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z" /><path d="M10 20a2 2 0 0 0 4 0" />
    </svg>
  );
}

// Unread count in the top bar. When the person has allowed browser alerts, new high-priority
// items also show as a system notification while Bioverse One is open.
export default function Bell() {
  const { me } = useSession();
  const [unread, setUnread] = useState(0);
  const seen = useRef(null);

  useEffect(() => {
    if (!me) return undefined;
    let stopped = false;
    seen.current = null;
    async function poll() {
      if (document.visibilityState === "hidden" && seen.current !== null) return;
      try {
        const data = await api("/notifications?unread=true&limit=20");
        if (stopped) return;
        setUnread(data.unread);
        const ids = new Set(data.items.map((n) => n.id));
        if (seen.current !== null && "Notification" in window && Notification.permission === "granted") {
          data.items
            .filter((n) => !seen.current.has(n.id) && (n.priority === "high" || n.priority === "urgent"))
            .forEach((n) => new Notification(`Bioverse One: ${n.title}`, { tag: n.id }));
        }
        seen.current = ids;
      } catch {
        // The bell stays as it was; the page itself reports connection problems.
      }
    }
    poll();
    const t = setInterval(poll, POLL_MS);
    const onRefresh = () => poll();
    window.addEventListener("bioverse:notifications", onRefresh);
    return () => { stopped = true; clearInterval(t); window.removeEventListener("bioverse:notifications", onRefresh); };
  }, [me?.id]);

  if (!me) return null;
  const label = unread ? `Notifications, ${unread} unread` : "Notifications";
  return (
    <Link to="/notifications" className="bell" aria-label={label} title={label}>
      <BellIcon />
      {unread > 0 && <span className="bell-count" aria-hidden="true">{unread > 99 ? "99+" : unread}</span>}
    </Link>
  );
}
