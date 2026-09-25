#!/usr/bin/env bash
# Build, migrate, deploy. Run from your machine, or from Cloud Build (cloudbuild.yaml calls this).
#
#   ./deploy/gcp/deploy.sh                 # builds with Cloud Build, then migrates and deploys
#   IMAGE_TAG=abc123 SKIP_BUILD=1 ./deploy/gcp/deploy.sh   # deploy an image that already exists
#   SEED_DEMO=1 ./deploy/gcp/deploy.sh     # also load the demo tenant (empty databases only)
#
set -euo pipefail
cd "$(dirname "$0")/../.."
source deploy/gcp/config.sh

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# Refuse to start until setup.sh has finished, instead of failing halfway with a confusing error.
missing=()
gcloud artifacts repositories describe "${REPO}" --project "${PROJECT_ID}" --location "${REGION}" >/dev/null 2>&1 \
  || missing+=("Artifact Registry repository '${REPO}'")
gcloud sql instances describe "${SQL_INSTANCE}" --project "${PROJECT_ID}" >/dev/null 2>&1 \
  || missing+=("Cloud SQL instance '${SQL_INSTANCE}'")
gcloud secrets describe "${SECRET_DB_URL}" --project "${PROJECT_ID}" >/dev/null 2>&1 \
  || missing+=("secret '${SECRET_DB_URL}'")
if (( ${#missing[@]} )); then
  echo "Setup has not finished. Missing:" >&2
  printf '  - %s\n' "${missing[@]}" >&2
  echo "Run ./deploy/gcp/setup.sh until it prints 'Done', then run this again." >&2
  exit 1
fi

IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
IMAGE_REF="${IMAGE}:${IMAGE_TAG}"

if [[ -z "${SKIP_BUILD:-}" ]]; then
  say "Building ${IMAGE_REF}"
  gcloud builds submit --project "${PROJECT_ID}" --region "${REGION}" --tag "${IMAGE_REF}" .
fi

has_version() {
  gcloud secrets versions list "$1" --project "${PROJECT_ID}" --filter="state=ENABLED" \
    --format="value(name)" 2>/dev/null | grep -q .
}

SECRETS="DATABASE_URL=${SECRET_DB_URL}:latest"
if has_version "${SECRET_ANTHROPIC}"; then
  SECRETS="${SECRETS},ANTHROPIC_API_KEY=${SECRET_ANTHROPIC}:latest"
fi
for pair in "${OPTIONAL_SECRETS[@]}"; do
  if has_version "${pair#*=}"; then
    SECRETS="${SECRETS},${pair}:latest"
    echo "Using secret ${pair#*=} for ${pair%%=*}"
  fi
done

# Links in emails and texts, and sign-in redirect URIs, use this address. Cloud Run serves the service at
# https://SERVICE-PROJECTNUMBER.REGION.run.app (stable, predictable); override with PUBLIC_URL (custom domain).
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)' 2>/dev/null || true)"
if [[ -z "${PUBLIC_URL:-}" && -n "${PROJECT_NUMBER}" ]]; then
  PUBLIC_URL="https://${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"
fi
ENV_VARS="BIOVERSE_AI=auto,BIOVERSE_MODEL=claude-opus-5,BIOVERSE_CLINIC_TZ=America/New_York"
[[ -n "${PUBLIC_URL}" ]] && ENV_VARS="${ENV_VARS},BIOVERSE_PUBLIC_URL=${PUBLIC_URL}"

# Single sign-on settings (client ids are not secret; client secrets come from Secret Manager above).
add_env() { [[ -n "$2" ]] && ENV_VARS="${ENV_VARS},$1=$2" || true; }
add_env BIOVERSE_AUTH_MODE "${AUTH_MODE}"
add_env BIOVERSE_ENTRA_TENANT_ID "${ENTRA_TENANT_ID}"
add_env BIOVERSE_ENTRA_CLIENT_ID "${ENTRA_CLIENT_ID}"
add_env BIOVERSE_OKTA_ISSUER "${OKTA_ISSUER}"
add_env BIOVERSE_OKTA_CLIENT_ID "${OKTA_CLIENT_ID}"
add_env BIOVERSE_GOOGLE_CLIENT_ID "${GOOGLE_CLIENT_ID}"
[[ "${GOOGLE_ALLOWED_DOMAINS}" == *,* || "${BOOTSTRAP_ADMINS}" == *,* ]] && {
  echo "Use one value for GOOGLE_ALLOWED_DOMAINS and BOOTSTRAP_ADMINS here (commas split --set-env-vars)." >&2; exit 1; }
add_env BIOVERSE_GOOGLE_ALLOWED_DOMAINS "${GOOGLE_ALLOWED_DOMAINS}"
add_env BIOVERSE_BOOTSTRAP_ADMINS "${BOOTSTRAP_ADMINS}"
add_env BIOVERSE_EMAIL_SIGNIN "${EMAIL_SIGNIN:-}"
add_env BIOVERSE_SELF_REGISTRATION "${SELF_REGISTRATION:-}"
add_env BIOVERSE_VAPID_SUBJECT "${VAPID_SUBJECT:-}"
if [[ -n "${ENTRA_CLIENT_ID}${OKTA_CLIENT_ID}${GOOGLE_CLIENT_ID}" ]]; then
  echo "Single sign-on redirect URIs to register:"
  for p in entra okta google; do echo "  ${PUBLIC_URL:-https://<service-url>}/api/auth/callback/${p}"; done
fi

# MedGemma: when medgemma.sh has deployed the endpoint, the app uses it first and Claude (if a key is set)
# as the backup. Otherwise Claude alone, or rules mode.
MG_ENDPOINT="$(gcloud ai endpoints list --project "${PROJECT_ID}" --region "${MEDGEMMA_REGION}" --billing-project "${PROJECT_ID}" \
  --filter="displayName=${MEDGEMMA_ENDPOINT_NAME}" --format="value(name)" 2>/dev/null | head -1 || true)"
if [[ -n "${MG_ENDPOINT}" ]]; then
  MG_ID="${MG_ENDPOINT##*/}"
  MG_DNS="$(gcloud ai endpoints describe "${MG_ID}" --project "${PROJECT_ID}" --region "${MEDGEMMA_REGION}" --billing-project "${PROJECT_ID}" \
    --format="value(dedicatedEndpointDns)" 2>/dev/null || true)"
  MG_LABEL="${MEDGEMMA_MODEL##*@}"
  MG_MULTI=true; [[ "${MG_LABEL}" == *text* ]] && MG_MULTI=false
  # The default provider order is MedGemma first, then Claude. No need to set BIOVERSE_AI_PROVIDER
  # (its commas would also clash with the comma-separated --set-env-vars list).
  ENV_VARS="${ENV_VARS},GOOGLE_CLOUD_PROJECT=${PROJECT_ID}"
  ENV_VARS="${ENV_VARS},BIOVERSE_MEDGEMMA_ENDPOINT=${MG_ID},BIOVERSE_MEDGEMMA_REGION=${MEDGEMMA_REGION}"
  ENV_VARS="${ENV_VARS},BIOVERSE_MEDGEMMA_MODEL=${MG_LABEL},BIOVERSE_MEDGEMMA_MULTIMODAL=${MG_MULTI}"
  [[ -n "${MG_DNS}" ]] && ENV_VARS="${ENV_VARS},BIOVERSE_MEDGEMMA_DNS=${MG_DNS}"
  echo "AI: MedGemma (${MG_LABEL}) at endpoint ${MG_ID}"
fi

# define_job NAME MODULE: create or update a Cloud Run job that runs `python -m MODULE`.
define_job() {
  local name="$1" args="$2"
  local common=(--project "${PROJECT_ID}" --region "${REGION}" --image "${IMAGE_REF}"
    --service-account "${RUNTIME_SA}" --set-cloudsql-instances "${SQL_CONNECTION}"
    --set-secrets "${SECRETS}" --set-env-vars "${ENV_VARS}" --command python --args="-m,${args}" --max-retries 0 --task-timeout 300)
  if gcloud run jobs describe "${name}" --project "${PROJECT_ID}" --region "${REGION}" >/dev/null 2>&1; then
    gcloud run jobs update "${name}" "${common[@]}"
  else
    gcloud run jobs create "${name}" "${common[@]}"
  fi
}

run_job() {
  say "Job $1: python -m $2"
  define_job "$1" "$2"
  gcloud run jobs execute "$1" --project "${PROJECT_ID}" --region "${REGION}" --wait
}

# Migrations never use --reset in the cloud. They only apply files not yet recorded.
run_job "${SERVICE}-migrate" "bioverse.db.migrate"
if [[ -n "${SEED_DEMO:-}" ]]; then
  run_job "${SERVICE}-seed" "bioverse.db.seed"
fi

say "Scheduled jobs: ${SERVICE}-jobs every five minutes"
define_job "${SERVICE}-jobs" "bioverse.jobs"
RUN_URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${SERVICE}-jobs:run"
sched=(--project "${PROJECT_ID}" --location "${REGION}" --schedule "${JOBS_SCHEDULE}" --time-zone "Etc/UTC"
  --uri "${RUN_URI}" --http-method POST --oauth-service-account-email "${SCHEDULER_SA}")
if gcloud scheduler jobs describe "${SERVICE}-jobs-tick" --project "${PROJECT_ID}" --location "${REGION}" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "${SERVICE}-jobs-tick" "${sched[@]}" \
    || echo "Could not update the scheduler (needs Cloud Scheduler Admin). Jobs still run from the admin screen."
elif gcloud iam service-accounts describe "${SCHEDULER_SA}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud scheduler jobs create http "${SERVICE}-jobs-tick" "${sched[@]}" \
    || echo "Could not create the scheduler (needs Cloud Scheduler Admin). Jobs still run from the admin screen."
else
  echo "Scheduler identity missing: run ./deploy/gcp/setup.sh again to schedule jobs. They still run from the admin screen."
fi

say "Deploying Cloud Run service ${SERVICE}"
AUTH_FLAG="--no-allow-unauthenticated"
[[ "${ALLOW_PUBLIC}" == "true" ]] && AUTH_FLAG="--allow-unauthenticated"

gcloud run deploy "${SERVICE}" \
  --project "${PROJECT_ID}" --region "${REGION}" --image "${IMAGE_REF}" \
  --service-account "${RUNTIME_SA}" \
  --set-cloudsql-instances "${SQL_CONNECTION}" \
  --set-secrets "${SECRETS}" \
  --set-env-vars "${ENV_VARS}" \
  --cpu 1 --memory 512Mi --concurrency 40 --min-instances 0 --max-instances 3 \
  --ingress all "${AUTH_FLAG}"

URL="${PUBLIC_URL:-$(gcloud run services describe "${SERVICE}" --project "${PROJECT_ID}" --region "${REGION}" --format='value(status.url)')}"
say "Deployed: ${URL}"
if [[ "${ALLOW_PUBLIC}" != "true" ]]; then
  echo "The service is private. Open it through an authenticated local proxy:"
  echo "  gcloud run services proxy ${SERVICE} --project ${PROJECT_ID} --region ${REGION} --port 8080"
  echo "  then browse http://localhost:8080"
fi
