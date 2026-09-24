# Shared settings for the GCP scripts. Override any value by exporting it first.

PROJECT_ID="${PROJECT_ID:-bioverseone-509616}"
REGION="${REGION:-us-central1}"

SERVICE="${SERVICE:-bioverse}"
REPO="${REPO:-bioverse}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}"

SQL_INSTANCE="${SQL_INSTANCE:-bioverse-pg}"
SQL_TIER="${SQL_TIER:-db-g1-small}"
DB_NAME="${DB_NAME:-bioverse}"
DB_USER="${DB_USER:-bioverse}"
SQL_CONNECTION="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}"

# Runtime identity for the service and the migration job.
RUNTIME_SA_NAME="${RUNTIME_SA_NAME:-bioverse-run}"
RUNTIME_SA="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Identity Cloud Scheduler uses to start the scheduled-jobs runner.
SCHEDULER_SA_NAME="${SCHEDULER_SA_NAME:-bioverse-scheduler}"
SCHEDULER_SA="${SCHEDULER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
JOBS_SCHEDULE="${JOBS_SCHEDULE:-*/5 * * * *}"

# MedGemma (Google's medical model) on Vertex AI. See medgemma.sh.
MEDGEMMA_MODEL="${MEDGEMMA_MODEL:-google/medgemma@medgemma-1.5-4b-it}"
MEDGEMMA_REGION="${MEDGEMMA_REGION:-${REGION}}"
MEDGEMMA_ENDPOINT_NAME="${MEDGEMMA_ENDPOINT_NAME:-bioverse-medgemma}"

# Secret Manager names.
SECRET_DB_URL="bioverse-database-url"
SECRET_ANTHROPIC="bioverse-anthropic-api-key"

# Optional secrets, wired into the service and jobs when they have a version (see import-acesales-keys.sh).
# Format: ENV_VAR=secret-name
OPTIONAL_SECRETS=(
  "BIOVERSE_SMTP_URL=bioverse-smtp-url"
  "BIOVERSE_EMAIL_FROM=bioverse-email-from"
  "TWILIO_ACCOUNT_SID=bioverse-twilio-account-sid"
  "TWILIO_AUTH_TOKEN=bioverse-twilio-auth-token"
  "TWILIO_FROM_NUMBER=bioverse-twilio-from-number"
  "BIOVERSE_OUTBOUND_ALLOWLIST=bioverse-outbound-allowlist"
)

# Private by default: only principals with roles/run.invoker can reach the app.
# The demo sign-in is a header anyone can set, so do not make it public with real patient data.
ALLOW_PUBLIC="${ALLOW_PUBLIC:-false}"
