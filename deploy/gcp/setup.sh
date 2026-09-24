#!/usr/bin/env bash
# One-time infrastructure for Bioverse on Google Cloud. Safe to re-run: existing resources are kept.
#
#   gcloud auth login
#   ANTHROPIC_API_KEY=sk-ant-... ./deploy/gcp/setup.sh      # key optional; without it the app runs in rules mode
#
set -euo pipefail
cd "$(dirname "$0")"
source ./config.sh

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
exists() { "$@" >/dev/null 2>&1; }

say "Project ${PROJECT_ID}, region ${REGION}"
gcloud config set project "${PROJECT_ID}" >/dev/null
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
# Projects created since 2024 may run builds as the Compute Engine default account instead.
# Check Cloud Build > Settings, and export CLOUDBUILD_SA if yours differs.
CLOUDBUILD_SA="${CLOUDBUILD_SA:-${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com}"

say "Enabling APIs"
gcloud services enable \
  run.googleapis.com sqladmin.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com secretmanager.googleapis.com iam.googleapis.com

say "Artifact Registry repository '${REPO}'"
exists gcloud artifacts repositories describe "${REPO}" --location "${REGION}" || \
  gcloud artifacts repositories create "${REPO}" --repository-format=docker --location "${REGION}" \
    --description="Bioverse container images"

say "Cloud SQL for PostgreSQL 16: '${SQL_INSTANCE}' (takes several minutes the first time)"
if ! exists gcloud sql instances describe "${SQL_INSTANCE}"; then
  gcloud sql instances create "${SQL_INSTANCE}" \
    --database-version=POSTGRES_16 --edition=ENTERPRISE --tier="${SQL_TIER}" --region="${REGION}" \
    --storage-auto-increase --backup-start-time=03:00 --enable-point-in-time-recovery \
    --ssl-mode=ENCRYPTED_ONLY --deletion-protection
fi
exists gcloud sql databases describe "${DB_NAME}" --instance "${SQL_INSTANCE}" || \
  gcloud sql databases create "${DB_NAME}" --instance "${SQL_INSTANCE}"

say "Database user and connection secret"
if ! exists gcloud secrets describe "${SECRET_DB_URL}"; then
  DB_PASSWORD="$(openssl rand -hex 24)"
  if exists gcloud sql users describe "${DB_USER}" --instance "${SQL_INSTANCE}"; then
    gcloud sql users set-password "${DB_USER}" --instance "${SQL_INSTANCE}" --password "${DB_PASSWORD}"
  else
    gcloud sql users create "${DB_USER}" --instance "${SQL_INSTANCE}" --password "${DB_PASSWORD}"
  fi
  # Cloud Run reaches Cloud SQL through the unix socket it mounts at /cloudsql.
  printf 'postgresql://%s:%s@/%s?host=/cloudsql/%s' "${DB_USER}" "${DB_PASSWORD}" "${DB_NAME}" "${SQL_CONNECTION}" | \
    gcloud secrets create "${SECRET_DB_URL}" --replication-policy=automatic --data-file=-
  unset DB_PASSWORD
else
  echo "Secret ${SECRET_DB_URL} exists; leaving the database password unchanged."
fi

if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  say "Anthropic API key secret"
  exists gcloud secrets describe "${SECRET_ANTHROPIC}" || \
    gcloud secrets create "${SECRET_ANTHROPIC}" --replication-policy=automatic
  printf '%s' "${ANTHROPIC_API_KEY}" | gcloud secrets versions add "${SECRET_ANTHROPIC}" --data-file=-
else
  echo "ANTHROPIC_API_KEY not set: skipping. The app will run its rules-based agents."
fi

say "Runtime service account ${RUNTIME_SA}"
exists gcloud iam service-accounts describe "${RUNTIME_SA}" || \
  gcloud iam service-accounts create "${RUNTIME_SA_NAME}" --display-name="Bioverse runtime"

# Least privilege: the runtime can connect to Cloud SQL and read only its own two secrets.
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUNTIME_SA}" --role="roles/cloudsql.client" --condition=None >/dev/null
for s in "${SECRET_DB_URL}" "${SECRET_ANTHROPIC}"; do
  exists gcloud secrets describe "$s" && \
    gcloud secrets add-iam-policy-binding "$s" \
      --member="serviceAccount:${RUNTIME_SA}" --role="roles/secretmanager.secretAccessor" >/dev/null
done

say "Cloud Build deployer permissions (${CLOUDBUILD_SA})"
for role in roles/run.developer roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${CLOUDBUILD_SA}" --role="${role}" --condition=None >/dev/null
done
# Cloud Build may deploy as the runtime account, and nothing else.
gcloud iam service-accounts add-iam-policy-binding "${RUNTIME_SA}" \
  --member="serviceAccount:${CLOUDBUILD_SA}" --role="roles/iam.serviceAccountUser" >/dev/null
# deploy.sh checks whether the Anthropic key has a version. Metadata only, never the value.
exists gcloud secrets describe "${SECRET_ANTHROPIC}" && \
  gcloud secrets add-iam-policy-binding "${SECRET_ANTHROPIC}" \
    --member="serviceAccount:${CLOUDBUILD_SA}" --role="roles/secretmanager.viewer" >/dev/null
# Needed only when ALLOW_PUBLIC=true, to grant allUsers the invoker role on the service.
if [[ "${ALLOW_PUBLIC}" == "true" ]]; then
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${CLOUDBUILD_SA}" --role="roles/run.admin" --condition=None >/dev/null
fi

say "Done. Next: ./deploy/gcp/deploy.sh (or: gcloud builds submit --config cloudbuild.yaml)"
