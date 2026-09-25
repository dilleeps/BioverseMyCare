#!/usr/bin/env bash
# Create the Web Push (VAPID) key pair and store the private key in Secret Manager. It never touches the
# screen or disk. Run once, then ./deploy/gcp/deploy.sh; phones and browsers can then turn push on.
#
#   ./deploy/gcp/vapid-keys.sh            # create the key (refuses if one already exists)
#   ./deploy/gcp/vapid-keys.sh --rotate   # replace it: every device has to turn push on again
set -euo pipefail
cd "$(dirname "$0")/../.."
source deploy/gcp/config.sh

name="bioverse-vapid-private-key"
rotate="${1:-}"
[[ -n "${rotate}" && "${rotate}" != "--rotate" ]] && { echo "Usage: $0 [--rotate]" >&2; exit 2; }
command -v openssl >/dev/null || { echo "openssl is required." >&2; exit 1; }

has_version() {
  gcloud secrets versions list "${name}" --project "${PROJECT_ID}" --filter="state=ENABLED" \
    --format="value(name)" 2>/dev/null | grep -q .
}
if has_version && [[ "${rotate}" != "--rotate" ]]; then
  echo "${name} already has a key. Push subscriptions are tied to it; use --rotate only to replace it." >&2
  exit 1
fi

# A P-256 private key in PEM form (the API accepts PEM or the raw base64url scalar).
key="$(openssl ecparam -name prime256v1 -genkey -noout 2>/dev/null)"
[[ -z "${key}" ]] && { echo "Key generation failed." >&2; exit 1; }
public="$(printf '%s\n' "${key}" | openssl ec -pubout -outform DER 2>/dev/null | tail -c 65 \
  | base64 | tr -d '\n=' | tr '/+' '_-')"

gcloud secrets describe "${name}" --project "${PROJECT_ID}" >/dev/null 2>&1 \
  || gcloud secrets create "${name}" --project "${PROJECT_ID}" --replication-policy=automatic >/dev/null
printf '%s\n' "${key}" | gcloud secrets versions add "${name}" --project "${PROJECT_ID}" --data-file=- >/dev/null
unset key
gcloud secrets add-iam-policy-binding "${name}" --project "${PROJECT_ID}" \
  --member="serviceAccount:${RUNTIME_SA}" --role="roles/secretmanager.secretAccessor" >/dev/null

echo "Stored ${name}."
echo "Public key (not secret; the app serves it at /api/push/config): ${public}"
echo "Optionally set VAPID_SUBJECT (mailto:you@yourdomain or https://yourdomain) in deploy/gcp/config.sh,"
echo "then run ./deploy/gcp/deploy.sh."
