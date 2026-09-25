import { ApiError, getUserId } from "../../api.js";

// Download a file from the API (CSV export, template). Sent the same way api() sends requests, so it works
// with the sign-in cookie and with the demo identity header.
export async function downloadFile(path, fallbackName) {
  const headers = { "X-Bioverse-Client": "web" };
  const uid = getUserId();
  if (uid) headers["X-Bioverse-User"] = uid;
  let res;
  try {
    res = await fetch(`/api${path}`, { headers });
  } catch {
    throw new ApiError("Can't reach Bioverse. Check that the API is running.", 0, null);
  }
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new ApiError(typeof data?.detail === "string" ? data.detail : `Download failed (${res.status})`, res.status, data?.detail);
  }
  const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") || "")?.[1] || fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
