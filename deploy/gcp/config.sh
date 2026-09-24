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

# Secret Manager names.
SECRET_DB_URL="bioverse-database-url"
SECRET_ANTHROPIC="bioverse-anthropic-api-key"

# Private by default: only principals with roles/run.invoker can reach the app.
# The demo sign-in is a header anyone can set, so do not make it public with real patient data.
ALLOW_PUBLIC="${ALLOW_PUBLIC:-false}"
