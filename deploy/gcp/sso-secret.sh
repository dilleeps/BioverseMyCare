#!/usr/bin/env bash
# Store an identity provider's client secret in Secret Manager without it touching the screen or disk.
#
#   ./deploy/gcp/sso-secret.sh entra     # then paste the secret and press Enter
#   ./deploy/gcp/sso-secret.sh okta
#   ./deploy/gcp/sso-secret.sh google
set -euo pipefail
cd "$(dirname "$0")/../.."
source deploy/gcp/config.sh

provider="${1:-}"
case "${provider}" in entra|okta|google) ;; *) echo "Usage: $0 entra|okta|google" >&2; exit 2 ;; esac
name="bioverse-${provider}-client-secret"

read -r -s -p "Client secret for ${provider} (input hidden): " value; echo
[[ -z "${value}" ]] && { echo "Nothing entered." >&2; exit 1; }

gcloud secrets describe "${name}" --project "${PROJECT_ID}" >/dev/null 2>&1 \
  || gcloud secrets create "${name}" --project "${PROJECT_ID}" --replication-policy=automatic >/dev/null
printf '%s' "${value}" | gcloud secrets versions add "${name}" --project "${PROJECT_ID}" --data-file=- >/dev/null
unset value
gcloud secrets add-iam-policy-binding "${name}" --project "${PROJECT_ID}" \
  --member="serviceAccount:${RUNTIME_SA}" --role="roles/secretmanager.secretAccessor" >/dev/null
echo "Stored ${name}. Set the client id in deploy/gcp/config.sh (or export it) and run ./deploy/gcp/deploy.sh."
