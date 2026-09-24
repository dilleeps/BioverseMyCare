// File transfer for the records module. api() in src/api.js sends JSON only, so uploads (raw file body)
// and the record download (FHIR JSON as a file) use fetch directly with the same identity header.
import { ApiError, getUserId } from "../../api.js";

function identity() {
  const uid = getUserId();
  return uid ? { "X-Bioverse-User": uid } : {};
}

async function failure(res) {
  const data = await res.json().catch(() => null);
  const detail = data?.detail ?? data?.issue?.[0]?.diagnostics;
  const message = typeof detail === "string" ? detail
    : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ")
    : res.status >= 500 ? "Something went wrong on our side. Please try again." : `Request failed (${res.status})`;
  return new ApiError(message, res.status, detail);
}

export async function uploadFile(file) {
  let res;
  try {
    res = await fetch(`/api/documents?filename=${encodeURIComponent(file.name)}`, {
      method: "POST",
      headers: { ...identity(), Accept: "application/json", "Content-Type": file.type || "application/octet-stream" },
      body: file,
    });
  } catch {
    throw new ApiError("Can't reach Bioverse. Check that the API is running.", 0, null);
  }
  if (!res.ok) throw await failure(res);
  return res.json();
}

export async function downloadRecord(patientId) {
  let res;
  try {
    res = await fetch(`/api/fhir/R4/Patient/${patientId}/$everything`, {
      headers: { ...identity(), Accept: "application/fhir+json" },
    });
  } catch {
    throw new ApiError("Can't reach Bioverse. Check that the API is running.", 0, null);
  }
  if (!res.ok) throw await failure(res);
  const bundle = await res.json();
  const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/fhir+json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `bioverse-record-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return bundle.entry?.length ?? 0;
}
