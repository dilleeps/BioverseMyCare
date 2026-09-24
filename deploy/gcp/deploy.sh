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

IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
IMAGE_REF="${IMAGE}:${IMAGE_TAG}"

if [[ -z "${SKIP_BUILD:-}" ]]; then
  say "Building ${IMAGE_REF}"
  gcloud builds submit --project "${PROJECT_ID}" --region "${REGION}" --tag "${IMAGE_REF}" .
fi

SECRETS="DATABASE_URL=${SECRET_DB_URL}:latest"
if gcloud secrets versions list "${SECRET_ANTHROPIC}" --project "${PROJECT_ID}" --filter="state=ENABLED" \
     --format="value(name)" 2>/dev/null | grep -q .; then
  SECRETS="${SECRETS},ANTHROPIC_API_KEY=${SECRET_ANTHROPIC}:latest"
fi

run_job() {
  local name="$1"; shift
  local args="$1"
  say "Job ${name}: python -m ${args}"
  local common=(--project "${PROJECT_ID}" --region "${REGION}" --image "${IMAGE_REF}"
    --service-account "${RUNTIME_SA}" --set-cloudsql-instances "${SQL_CONNECTION}"
    --set-secrets "${SECRETS}" --command python --args="-m,${args}" --max-retries 0 --task-timeout 300)
  if gcloud run jobs describe "${name}" --project "${PROJECT_ID}" --region "${REGION}" >/dev/null 2>&1; then
    gcloud run jobs update "${name}" "${common[@]}"
  else
    gcloud run jobs create "${name}" "${common[@]}"
  fi
  gcloud run jobs execute "${name}" --project "${PROJECT_ID}" --region "${REGION}" --wait
}

# Migrations never use --reset in the cloud. They only apply files not yet recorded.
run_job "${SERVICE}-migrate" "bioverse.db.migrate"
if [[ -n "${SEED_DEMO:-}" ]]; then
  run_job "${SERVICE}-seed" "bioverse.db.seed"
fi

say "Deploying Cloud Run service ${SERVICE}"
AUTH_FLAG="--no-allow-unauthenticated"
[[ "${ALLOW_PUBLIC}" == "true" ]] && AUTH_FLAG="--allow-unauthenticated"

gcloud run deploy "${SERVICE}" \
  --project "${PROJECT_ID}" --region "${REGION}" --image "${IMAGE_REF}" \
  --service-account "${RUNTIME_SA}" \
  --set-cloudsql-instances "${SQL_CONNECTION}" \
  --set-secrets "${SECRETS}" \
  --set-env-vars "BIOVERSE_AI=auto,BIOVERSE_MODEL=claude-opus-5,BIOVERSE_CLINIC_TZ=America/New_York" \
  --cpu 1 --memory 512Mi --concurrency 40 --min-instances 0 --max-instances 3 \
  --ingress all "${AUTH_FLAG}"

URL="$(gcloud run services describe "${SERVICE}" --project "${PROJECT_ID}" --region "${REGION}" --format='value(status.url)')"
say "Deployed: ${URL}"
if [[ "${ALLOW_PUBLIC}" != "true" ]]; then
  echo "The service is private. Open it through an authenticated local proxy:"
  echo "  gcloud run services proxy ${SERVICE} --project ${PROJECT_ID} --region ${REGION} --port 8080"
  echo "  then browse http://localhost:8080"
fi
