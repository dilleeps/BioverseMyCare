// The one place the React app talks to the Python API.
// Every request carries the signed-in demo identity in X-Bioverse-User.

const USER_KEY = "bioverse.user";

export function getUserId() {
  try {
    return localStorage.getItem(USER_KEY);
  } catch {
    return null;
  }
}

export function setUserId(id) {
  try {
    if (id) localStorage.setItem(USER_KEY, id);
    else localStorage.removeItem(USER_KEY);
  } catch {
    // Storage blocked: the identity lives for this page load only.
  }
  memoryUserId = id;
}

let memoryUserId = null;

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

function messageFrom(detail, status) {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail.message === "string") return detail.message;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join("; ");
  if (status >= 500) return "Something went wrong on our side. Please try again.";
  return `Request failed (${status})`;
}

export async function api(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/json" };
  const uid = getUserId() || memoryUserId;
  if (uid) headers["X-Bioverse-User"] = uid;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let res;
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("Can't reach Bioverse. Check that the API is running.", 0, null);
  }

  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data ? data.detail : null;
    throw new ApiError(messageFrom(detail, res.status), res.status, detail);
  }
  return data;
}
