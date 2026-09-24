#!/usr/bin/env bash
# Copy the keys Bioverse One can use from the AceSales project's Secret Manager into this project's.
# Values go straight from one Secret Manager to the other through a pipe: they are never printed,
# written to disk, or passed on a command line.
#
#   ./deploy/gcp/import-acesales-keys.sh
#   ALLOWLIST="you@example.org,+15555550123" ./deploy/gcp/import-acesales-keys.sh
#
# Then run ./deploy/gcp/deploy.sh: it wires every secret that has a version into the service and jobs.
#
# What is copied (AceSales secret -> Bioverse secret):
#   ANTHROPIC_API_KEY (or anthropic-key)          -> bioverse-anthropic-api-key   Claude instead of rules mode
#   MAIL_ADDRESS + MAIL_PASSWORD (Gmail)          -> bioverse-smtp-url, bioverse-email-from
#   TWILIO_ACCOUNT_SID / _AUTH_TOKEN / _FROM_NUMBER -> bioverse-twilio-*
# and bioverse-outbound-allowlist: who may receive email and texts while the demo sign-in is in place.
# It defaults to the AceSales mail address only. Add your phone with ALLOWLIST=... to receive texts.
#
# You need Secret Manager Secret Accessor on the AceSales project and Secret Manager Admin here.
set -euo pipefail
cd "$(dirname "$0")/../.."
source deploy/gcp/config.sh

SOURCE_PROJECT="${SOURCE_PROJECT:-acesalesai}"
say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# read_source NAME [FALLBACK_NAME]: print the latest value of a secret in the source project, or nothing.
read_source() {
  local name
  for name in "$@"; do
    if gcloud secrets versions access latest --secret="${name}" --project="${SOURCE_PROJECT}" 2>/dev/null; then
      return 0
    fi
  done
  return 1
}

# put_secret NAME: store stdin as a new version of NAME in this project and let the runtime read it.
put_secret() {
  local name="$1"
  gcloud secrets describe "${name}" --project "${PROJECT_ID}" >/dev/null 2>&1 \
    || gcloud secrets create "${name}" --project "${PROJECT_ID}" --replication-policy=automatic >/dev/null
  gcloud secrets versions add "${name}" --project "${PROJECT_ID}" --data-file=- >/dev/null
  gcloud secrets add-iam-policy-binding "${name}" --project "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_SA}" --role="roles/secretmanager.secretAccessor" >/dev/null
  echo "  stored ${name}"
}

# copy SOURCE_NAMES... -> DEST: pipe a value across if it exists and is non-empty.
copy() {
  local dest="${@: -1}" value
  local sources=("${@:1:$#-1}")
  if value="$(read_source "${sources[@]}")" && [[ -n "${value}" ]]; then
    printf '%s' "${value}" | put_secret "${dest}"
  else
    echo "  not found in ${SOURCE_PROJECT}: ${sources[*]} (skipped)"
  fi
  unset value
}

gcloud secrets list --project "${SOURCE_PROJECT}" --limit 1 >/dev/null 2>&1 || {
  echo "Can't read Secret Manager in project '${SOURCE_PROJECT}' as $(gcloud config get-value account 2>/dev/null)." >&2
  echo "Switch to the account that owns AceSales (gcloud config set account ...) or grant this one" >&2
  echo "Secret Manager Secret Accessor there, then run this again." >&2
  exit 1
}

say "Claude"
copy ANTHROPIC_API_KEY anthropic-key "${SECRET_ANTHROPIC}"

say "Email (Gmail SMTP with an app password)"
MAIL_ADDRESS_VALUE="$(read_source MAIL_ADDRESS || true)"
MAIL_PASSWORD_VALUE="$(read_source MAIL_PASSWORD gmail-app-password || true)"
if [[ -n "${MAIL_ADDRESS_VALUE}" && -n "${MAIL_PASSWORD_VALUE}" ]]; then
  MAIL_HOST_VALUE="$(read_source MAIL_HOST || echo smtp.gmail.com)"
  MAIL_PORT_VALUE="$(read_source MAIL_PORT || echo 587)"
  # Percent-encode user and password for the URL (python3 is in Cloud Shell); values arrive on stdin.
  printf '%s\n%s\n%s\n%s' "${MAIL_ADDRESS_VALUE}" "${MAIL_PASSWORD_VALUE}" "${MAIL_HOST_VALUE}" "${MAIL_PORT_VALUE}" \
    | python3 -c 'import sys, urllib.parse as u
user, pw, host, port = sys.stdin.read().split("\n")
sys.stdout.write(f"smtp://{u.quote(user, safe=str())}:{u.quote(pw, safe=str())}@{host}:{port}")' \
    | put_secret bioverse-smtp-url
  printf '%s' "${MAIL_ADDRESS_VALUE}" | put_secret bioverse-email-from
else
  echo "  MAIL_ADDRESS / MAIL_PASSWORD not found in ${SOURCE_PROJECT} (skipped)"
fi
unset MAIL_PASSWORD_VALUE

say "Text messages (Twilio)"
copy TWILIO_ACCOUNT_SID bioverse-twilio-account-sid
copy TWILIO_AUTH_TOKEN bioverse-twilio-auth-token
copy TWILIO_FROM_NUMBER bioverse-twilio-from-number

say "Who may receive email and texts"
ALLOWLIST="${ALLOWLIST:-${MAIL_ADDRESS_VALUE:-}}"
if [[ -n "${ALLOWLIST}" ]]; then
  printf '%s' "${ALLOWLIST}" | put_secret bioverse-outbound-allowlist
  echo "  only these recipients get email or texts: ${ALLOWLIST}"
else
  echo "  no allowlist set: email and texts stay off until you set ALLOWLIST=..." >&2
  printf '%s' "nobody@invalid" | put_secret bioverse-outbound-allowlist
fi

say "Done"
echo "Now run: ALLOW_PUBLIC=true ./deploy/gcp/deploy.sh"
