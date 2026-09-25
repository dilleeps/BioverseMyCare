# Deploying Bioverse One to Google Cloud

Target project: **`bioverseone-509616`** · default region **`us-central1`** (change in `config.sh`).

## What gets created

| Resource | Name | Purpose |
| --- | --- | --- |
| Cloud Run service | `bioverse` | One container serving the React app and the FastAPI API on the same origin |
| Cloud Run job | `bioverse-migrate` | Applies database migrations before each deploy |
| Cloud Run job | `bioverse-seed` | Optional. Loads the demo tenant into an empty database |
| Cloud Run job | `bioverse-jobs` | Scheduled work: reminders, vital-sign alerts, notification delivery |
| Cloud Scheduler | `bioverse-jobs-tick` | Starts `bioverse-jobs` every five minutes |
| Cloud SQL | `bioverse-pg` | PostgreSQL 16, encrypted connections only, daily backups, point-in-time recovery, deletion protection |
| Artifact Registry | `bioverse` | Container images |
| Secret Manager | `bioverse-database-url` | Connection string with a generated password. Never printed or committed |
| Secret Manager | `bioverse-anthropic-api-key` | Optional. Without it the app runs its rules-based agents |
| Secret Manager | `bioverse-smtp-url`, `bioverse-email-from`, `bioverse-twilio-*`, `bioverse-outbound-allowlist` | Optional. Email and text notifications (see "Keys" below) |
| Service account | `bioverse-run` | Runtime identity for the service and jobs |
| Service account | `bioverse-scheduler` | Identity Cloud Scheduler uses to start `bioverse-jobs` |

## IAM roles

Grant these on the console's IAM page (IAM & Admin > IAM). `setup.sh` grants the service-account rows for you. The people rows are yours to assign.

| Principal | Role | Why |
| --- | --- | --- |
| `bioverse-run` service account | Cloud SQL Client (`roles/cloudsql.client`) | Connect to the database through the Cloud SQL socket |
| `bioverse-run` service account | Secret Manager Secret Accessor (`roles/secretmanager.secretAccessor`), on the two Bioverse secrets only | Read its own secrets, nothing else |
| `bioverse-scheduler` service account | Cloud Run Invoker (`roles/run.invoker`) | Start the scheduled-jobs runner |
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

## Single sign-on: Microsoft Entra ID, Okta, Google

Bioverse One signs people in with OpenID Connect (authorization code flow with PKCE). The identity
provider proves who someone is; their role and access stay in Bioverse (**People & sign-in** for admins).
A first sign-in links to the Bioverse user with the same email, when the provider confirms that email.

**Redirect URI** to register with every provider (`deploy.sh` prints it):
`https://bioverse-1057658446982.us-central1.run.app/api/auth/callback/<entra|okta|google>`

**Microsoft Entra ID** (Entra admin center > App registrations > New registration)
1. Supported account types: *this organizational directory only*. Redirect URI: platform **Web**, the URI above.
2. Certificates & secrets > New client secret. Note the **Application (client) ID** and **Directory (tenant) ID**.
3. Optional: Token configuration > add the `email` optional claim. Without it, the sign-in name (UPN) is used.

**Okta** (Admin console > Applications > Create App Integration)
1. OIDC, **Web Application**. Sign-in redirect URI: the URI above. Sign-out redirect URI: `.../signin`.
2. Grant type: Authorization Code. Assign the people or groups who may use Bioverse One.
3. Issuer: `https://<your-okta-domain>/oauth2/default` (or your custom authorization server).

**Google** (Google Cloud console > APIs & Services > Credentials > Create OAuth client ID)
1. Configure the OAuth consent screen (Google Auth Platform > Branding and Audience). **Internal** only admits
   your Workspace organization. **External** admits any Google account (needed for patients on personal Gmail);
   while it is in *Testing*, only the test users listed under Audience can sign in, so add them there or
   *Publish app*. The scopes used (`openid email profile`) need no Google verification.
2. Application type **Web application**; authorized redirect URI: the URI above.
3. Set `GOOGLE_ALLOWED_DOMAINS` to your Workspace domain to keep personal Gmail accounts out.

**Turn it on** in Cloud Shell:

```bash
./deploy/gcp/sso-secret.sh entra      # paste each client secret (hidden), one provider at a time
./deploy/gcp/sso-secret.sh okta
./deploy/gcp/sso-secret.sh google
ENTRA_TENANT_ID=<tenant-id> ENTRA_CLIENT_ID=<client-id> \
OKTA_ISSUER=https://<domain>/oauth2/default OKTA_CLIENT_ID=<client-id> \
GOOGLE_CLIENT_ID=<id>.apps.googleusercontent.com \
BOOTSTRAP_ADMINS=you@yourhospital.org AUTH_MODE=sso+demo \
./deploy/gcp/deploy.sh
```

Configure any one, two or all three. `BOOTSTRAP_ADMINS` makes your email an administrator on first
sign-in, so you can add everyone else under **People & sign-in**. `AUTH_MODE=sso+demo` keeps the demo
switcher while you test; set `AUTH_MODE=sso` (the default once a provider is set) to turn it off.

Sessions: an opaque HttpOnly, Secure, SameSite=Lax cookie; signed out after 60 minutes idle or 12 hours.
Sign-out also ends the provider session when the provider supports it (Entra, Okta).

### Adding many people: CSV import and directory groups

**People & sign-in > Import people** takes a CSV (`name, email, role, team, specialty, location, birth_date,
consult_fee`; download the template there). It always shows a dry run first, row by row, then imports in one
go: nothing is imported while any row has a problem, unless you choose to skip those rows. **Export CSV**
downloads everyone (cells that a spreadsheet would run as formulas are prefixed with `'`).

**People & sign-in > Sign-in rules** maps directory groups to roles, so accounts can be created on first
sign-in and staff roles and teams follow your directory. Both switches are off until you turn them on.
Patients are never created from a group. Make the provider send groups first:

- **Entra**: App registration > **Token configuration** > **Add groups claim** (choose *Groups assigned to the
  application* to stay under the 200-group limit). Rules match group **object ids** in `groups`. Or create
  **App roles** on the registration, assign them to groups (Enterprise applications > Users and groups) and
  match the `roles` claim.
- **Okta**: Security > API > Authorization servers > *default* > **Claims** > Add claim `groups`, include in
  the ID token, value type *Groups*, with a filter such as *Starts with* `Bioverse`. Rules match group names.
- **Google** sends no groups: match the Workspace domain (`hd` claim).

Use **Test a sign-in** on that screen with a token's claims (e.g. from https://jwt.ms) to check a rule.

### Patient invites and email sign-in

Administrators, the front desk and clinicians invite patients under **Invite a patient** (name, email, date
of birth, optional MRN and a short note). The patient gets a single-use link, `https://<service-url>/join/<token>`,
valid for 14 days by default; it is emailed when email is configured (`BIOVERSE_SMTP_URL`, respecting
`BIOVERSE_OUTBOUND_ALLOWLIST`) and always shown to staff to copy. On the join page the patient confirms their
date of birth (five wrong tries lock the invite until staff resend it), accepts the terms, and then signs in
with Google (or another configured provider) or a 6-digit code sent by email. The account and patient record
are created on that first sign-in, with whichever verified email they used. Staff can resend (new link) or revoke.

- Google for patients: leave `GOOGLE_ALLOWED_DOMAINS` empty, or personal Gmail accounts are refused.
  Staff are still safe: Google only links to an existing Bioverse user, or creates a patient from a valid invite.
- Email codes are for patients only and are on whenever single sign-on is allowed. `EMAIL_SIGNIN=off` turns
  them off; `EMAIL_SIGNIN=on` forces them on. They need `AUTH_MODE` `sso` or `sso+demo` (the session cookie
  is ignored in pure demo mode). Without a mail server, codes can't be delivered in `sso` mode; in `sso+demo`
  a copy of every email lands in a demo outbox that the sign-in page shows.
- `SELF_REGISTRATION=on` opens `/register` (name, date of birth, email code) to anyone. Off by default.

```bash
EMAIL_SIGNIN=on SELF_REGISTRATION=on ./deploy/gcp/deploy.sh    # values without commas
```

## AI: MedGemma, Google's medical model

The app's AI (triage, explanations, photo reading, summaries, check-ins, fact check, tutor) runs on
[MedGemma](https://developers.google.com/health-ai-developer-foundations/medgemma), Google's open medical
model, deployed from Vertex AI Model Garden into this project. Claude is the backup when a key is set;
without either, every feature uses its rules path.

```bash
./deploy/gcp/medgemma.sh                      # deploys MedGemma 1.5 4B (multimodal) on one NVIDIA L4
ALLOW_PUBLIC=true ./deploy/gcp/deploy.sh      # finds the endpoint and switches the app to it
./deploy/gcp/medgemma.sh --status             # what is deployed
./deploy/gcp/medgemma.sh --delete             # remove it and stop the GPU bill
```

- **Cost.** The endpoint holds a GPU around the clock and bills for every hour it exists, even with no
  traffic. Set a budget alert. The 27B variants (`MEDGEMMA_MODEL=google/medgemma@medgemma-27b-it`) need
  much larger GPUs and cost several times more.
- **Terms.** `--accept-eula` accepts the Health AI Developer Foundations terms. Read them first.
- **Validation.** MedGemma is a developer model, not a cleared medical device. Bioverse keeps its safety
  layers regardless of model: deterministic red-flag screening runs before any model, and clinical content
  for patients goes through clinician review.
- If the deploy fails on the model name or GPU quota, the script prints the commands to list MedGemma
  versions and deployment options, or deploy from the console and name the endpoint `bioverse-medgemma`.

## Keys: Claude, email and text messages

The app runs without any of these; each one turns a feature on.

**Copy them from AceSales** (Secret Manager in project `acesalesai`). The values go from one Secret Manager
to the other and are never printed:

```bash
./deploy/gcp/import-acesales-keys.sh                                   # Claude, Gmail, Twilio
ALLOWLIST="you@example.org,+15555550123" ./deploy/gcp/import-acesales-keys.sh   # also allow your phone
ALLOW_PUBLIC=true ./deploy/gcp/deploy.sh
```

Run it as an account that can read secrets in `acesalesai` (Secret Manager Secret Accessor) and manage
them here. `deploy.sh` wires every secret below that has a version into the service and the jobs.

| Secret | Turns on |
| --- | --- |
| `bioverse-anthropic-api-key` | Claude for triage, explanations, photo reading, check-ins and the rest; otherwise rules mode |
| `bioverse-smtp-url`, `bioverse-email-from` | Email notifications (Gmail SMTP with an app password) |
| `bioverse-twilio-account-sid`, `-auth-token`, `-from-number` | Text-message notifications |
| `bioverse-outbound-allowlist` | Who may receive email and texts (comma-separated). Required while the demo sign-in is public, since anyone can type any address into a demo account |

Emails and texts only say that something is waiting, never health details, and link back to the app
(`BIOVERSE_PUBLIC_URL`, set by `deploy.sh`).

## Mobile app and push notifications

Bioverse One installs on phones and computers straight from the browser (a web app with a manifest and a
service worker). There is no app store build.

- **iPhone and iPad:** open the site in Safari, tap **Share**, then **Add to Home Screen**, and open Bioverse
  One from the home screen. Push notifications need iOS 16.4 or later and only work in the installed app.
- **Android:** open the site in Chrome and tap **Install** in the prompt (or **Install app** in the ⋮ menu).
  Patients on phones also see a slim "Get the app" banner, which they can dismiss.
- **Computers:** Chrome and Edge show an install icon in the address bar.

The app must be reachable over HTTPS by the phone (Cloud Run's URL is). Offline, the app shows a "You're
offline" page; nothing from the API is ever stored on the device.

**Turn on push** (once per project):

```bash
./deploy/gcp/vapid-keys.sh          # creates the key pair, stores the private key as bioverse-vapid-private-key
./deploy/gcp/deploy.sh              # wires it into the service and the scheduled jobs
```

Optionally set `VAPID_SUBJECT` (`mailto:it@yourhospital.org`) in `config.sh`; push services use it to contact
you about problems. `vapid-keys.sh --rotate` replaces the key, after which every device has to turn push on
again. Locally, `python -m bioverse.webpush keygen` prints a key for `BIOVERSE_VAPID_PRIVATE_KEY` in `apps/api/.env`.

Each person then opens **Notifications → This device → Turn on push for this device**, and ticks **Phone push**
for the kinds of notification they want there. **Send a test** checks it end to end.

**Privacy:** a push says the notification's title and "Open Bioverse One to see the details", never clinical
detail, and is encrypted end to end to the device (RFC 8291). The server only contacts the push services of
Google, Mozilla, Apple and Microsoft.

## Before any real patient data

The demo identity switcher trusts a request header, so anyone who can reach the service can act as any user. Keep the service private (the default) and use seeded demo data only until all of these are done:

1. Turn on single sign-on (above) and set `AUTH_MODE=sso` so the demo identity switcher is off.
2. Sign Google Cloud's Business Associate Agreement and confirm every service in use is covered by it.
3. Put the service behind Identity-Aware Proxy or a load balancer with Cloud Armor, and restrict ingress.
4. Move Cloud SQL to a private IP with a Serverless VPC connector.
5. Review the controls in `docs/04-safety-and-governance.md`.

`setup.sh` asks Cloud Build which service account runs your builds. Newer projects use the Compute Engine default account, older ones the legacy Cloud Build account. To force a specific one, export `CLOUDBUILD_SA` before running it.

If `setup.sh` stops partway, fix what it reports and run it again. It keeps everything already created, including the database password.
