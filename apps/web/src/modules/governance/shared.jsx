import { getUserId } from "../../api.js";

// Fetch a file endpoint with the demo identity header and hand it to the browser as a download.
export async function download(path, fallbackName) {
  const res = await fetch(`/api${path}`, { headers: { "X-Bioverse-User": getUserId() || "" } });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const blob = await res.blob();
  const match = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "");
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = match ? match[1] : fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function humanize(value) {
  if (!value) return "";
  const s = String(value).replaceAll("_", " ");
  return s[0].toUpperCase() + s.slice(1);
}

export function fmtStamp(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString([], {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

export const SEVERITY_CHIP = { critical: "warn", high: "warn", moderate: "", low: "" };
export const STATUS_CHIP = { open: "warn", investigating: "", resolved: "ok" };

export function PageHeader({ eyebrow, title, sub, children }) {
  return (
    <header className="row between wrap" style={{ marginBottom: 18, gap: 12 }}>
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1 className="page-title">{title}</h1>
        {sub && <div className="page-sub">{sub}</div>}
      </div>
      {children && <div className="row wrap" style={{ gap: 8 }}>{children}</div>}
    </header>
  );
}
