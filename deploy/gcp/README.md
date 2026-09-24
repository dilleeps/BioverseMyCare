# Deploying Bioverse One to Google Cloud

Target project: **`bioverseone-509616`** · default region **`us-central1`** (change in `config.sh`).

## What gets created

| Resource | Name | Purpose |
| --- | --- | --- |
| Cloud Run service | `bioverse` | One container serving the React app and the FastAPI API on the same origin |
| Cloud Run job | `bioverse-migrate` | Applies database migrations before each deploy |
| Cloud Run job | `bioverse-seed` | Optional. Loads the demo tenant into an empty database |
| Cloud SQL | `bioverse-pg` | PostgreSQL 16, encrypted connections only, daily backups, point-in-time recovery, deletion protection |
| Artifact Registry | `bioverse` | Container images |
| Secret Manager | `bioverse-database-url` | Connection string with a generated password. Never printed or committed |
| Secret Manager | `bioverse-anthropic-api-key` | Optional. Without it the app runs its rules-based agents |
| Service account | `bioverse-run` | Runtime identity for the service and jobs |

## IAM roles

Grant these on the console's IAM page (IAM & Admin > IAM). `setup.sh` grants the service-account rows for you. The people rows are yours to assign.

| Principal | Role | Why |
| --- | --- | --- |
| `bioverse-run` service account | Cloud SQL Client (`roles/cloudsql.client`) | Connect to the database through the Cloud SQL socket |
| `bioverse-run` service account | Secret Manager Secret Accessor (`roles/secretmanager.secretAccessor`), on the two Bioverse secrets only | Read its own secrets, nothing else |
| Cloud Build service account | Storage Object Viewer (`roles/storage.objectViewer`) | Read the source that `gcloud builds submit` uploads |
| Cloud Build service account | Logs Writer (`roles/logging.logWriter`) | Write build logs |
| Cloud Build service account | Artifact Registry Writer (`roles/artifactregistry.writer`) | Push images |
| Cloud Build service account | Cloud Run Developer (`roles/run.developer`) | Deploy the service and run migration jobs, when using `cloudbuild.yaml` |
| Cloud Build service account | Service Account User (`roles/iam.serviceAccountUser`), on `bioverse-run` only | Deploy as the runtime identity, and no other |
| Cloud Build service account | Secret Manager Viewer (`roles/secretmanager.viewer`), on the Anthropic secret only | See whether a key version exists. Cannot read the value |
| Cloud Build service account | Cloud Run Admin (`roles/run.admin`) | Only when `ALLOW_PUBLIC=true`, to make the service public |
| Whoever runs `setup.sh` | Owner, or Editor plus Project IAM Admin and Secret Manager Admin | Create the resources and bindings above |
| Each person who should open the app | Cloud Run Invoker (`roles/run.invoker`) on the `bioverse` service | The service is private by default |

No custom role is needed. Every grant above is a predefined role, scoped as narrowly as the resource allows.

## Before you start

The project needs a **billing account linked**. Without one, Google refuses to turn on Cloud Run, Cloud SQL and the other services, and `setup.sh` stops with instructions. Link one at [Billing > Linked account](https://console.cloud.google.com/billing/linkedaccount?project=bioverseone-509616), or in Cloud Shell:

```bash
gcloud billing accounts list
gcloud billing projects link bioverseone-509616 --billing-account=XXXXXX-XXXXXX-XXXXXX
```

Cloud Run scales to zero when idle. Cloud SQL bills for every hour the instance exists, even with no traffic. Set a budget alert under Billing > Budgets & alerts.

## Steps

Easiest from [Cloud Shell](https://shell.cloud.google.com/?project=bioverseone-509616), which is already signed in as you. The `&&` makes each step run only if the previous one succeeded.

```bash
git clone -b claude/stoic-dirac-cvyp79 https://github.com/dilleeps/BioverseMyCare && cd BioverseMyCare \
  && ./deploy/gcp/setup.sh \
  && SEED_DEMO=1 ./deploy/gcp/deploy.sh
```

`setup.sh` runs once and takes about ten minutes because of Cloud SQL. To use Claude instead of rules mode, run it as `ANTHROPIC_API_KEY=sk-ant-... ./deploy/gcp/setup.sh`. For later releases, run `./deploy/gcp/deploy.sh` on its own. `SEED_DEMO=1` is for the first release only, on an empty database.

Or run the same pipeline on Cloud Build, and connect it to a trigger on `main` later:

```bash
gcloud builds submit --config cloudbuild.yaml --region us-central1
```

Open the private service through an authenticated local proxy:

```bash
gcloud run services proxy bioverse --project bioverseone-509616 --region us-central1 --port 8080
# then browse http://localhost:8080
```

Give a colleague access:

```bash
gcloud run services add-iam-policy-binding bioverse --region us-central1 \
  --member=user:colleague@example.com --role=roles/run.invoker
```

## Before any real patient data

The demo identity switcher trusts a request header, so anyone who can reach the service can act as any user. Keep the service private (the default) and use seeded demo data only until all of these are done:

1. Replace the demo sign-in with real authentication, for example Identity Platform or your hospital's identity provider over OIDC, in `apps/api/bioverse/auth.py`.
2. Sign Google Cloud's Business Associate Agreement and confirm every service in use is covered by it.
3. Put the service behind Identity-Aware Proxy or a load balancer with Cloud Armor, and restrict ingress.
4. Move Cloud SQL to a private IP with a Serverless VPC connector.
5. Review the controls in `docs/04-safety-and-governance.md`.

`setup.sh` asks Cloud Build which service account runs your builds. Newer projects use the Compute Engine default account, older ones the legacy Cloud Build account. To force a specific one, export `CLOUDBUILD_SA` before running it.

If `setup.sh` stops partway, fix what it reports and run it again. It keeps everything already created, including the database password.
