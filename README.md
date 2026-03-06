# CFCG Action Network Webhook

Receives signup webhooks from Action Network, looks up the assigned support
person by zip code, and sends a welcome email via SendGrid.

Runs on **Google Cloud Run** — no Docker knowledge required.

---

## How It Works

1. A new person signs up on Action Network
2. Action Network POSTs a JSON payload to your `/webhook` endpoint
3. This service parses the person's zip code
4. Looks up their assigned organizer in `zip_dict.json`
5. Sends a welcome email via SendGrid with the organizer's contact info
6. Updates the person's `group_key` field in Action Network

---

## Project Structure

```
cfcg-an-webhook/
├── cfcg_an_webhook/
│   └── main.py           # Flask app — all webhook logic
├── zip_dict.json    # Zip → organizer lookup table (41k zips)
├── pyproject.toml        # Python dependencies (managed by uv)
├── Procfile              # Tells Cloud Run how to start the app
├── .env                  # Environment variables (no secrets — safe to commit)
├── .gitignore
├── test_local.py         # Local test script
└── .github/
    └── workflows/
        └── deploy.yml    # Auto-deploy to Cloud Run on push to main
```

---

## Local Development

### 1. Set up the environment with uv
```bash
uv venv
uv sync
```
`uv sync` reads `pyproject.toml` and installs everything into `.venv` automatically.

Then point PyCharm to the interpreter at `.venv/bin/python` (Mac/Linux) or `.venv/Scripts/python.exe` (Windows):
Settings → Project → Python Interpreter → Add Interpreter → Existing → navigate to that path.

### 2. Set up GCP credentials locally
This lets the app access Secret Manager from your laptop:
```bash
gcloud auth application-default login
```

### 3. Fill in your .env file
Open `.env` and fill in your values (the file is already in the project).

### 4. Start the server
```bash
python main.py
```
You should see: `Starting local dev server on http://localhost:8080`

### 5. Send a test webhook (in a second terminal)
```bash
python test_local.py
```
Edit `test_local.py` to change the zip code, email, or other test data.

---

## GCP First-Time Setup

Run these commands once to set up your GCP project from scratch.
Replace `YOUR-PROJECT-ID` with the project ID from the GCP console (e.g. `cfcg-an-webhook-123456`).

```bash
# 1. Point gcloud at your new project
gcloud config set project YOUR-PROJECT-ID

# 2. Enable the required APIs
gcloud services enable \
  run.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com

# 3. Create the service account your app will run as
gcloud iam service-accounts create cfcg-an-webhook-sa \
  --display-name "CFCG Webhook Service Account"

# 4. Grant it permission to read secrets
gcloud projects add-iam-policy-binding YOUR-PROJECT-ID \
  --member "serviceAccount:cfcg-an-webhook-sa@YOUR-PROJECT-ID.iam.gserviceaccount.com" \
  --role "roles/secretmanager.secretAccessor"

# 5. Create a storage bucket for future tracking files (idempotency, emailed list)
gsutil mb -l us-east1 gs://cfcg-an-webhook-storage-YOUR-PROJECT-ID

# 6. Grant the service account access to that bucket
gsutil iam ch \
  serviceAccount:cfcg-an-webhook-sa@YOUR-PROJECT-ID.iam.gserviceaccount.com:objectAdmin \
  gs://cfcg-an-webhook-storage-YOUR-PROJECT-ID
```

Then create your two secrets in the GCP Console under **Security → Secret Manager**,
or via the CLI:
```bash
# Paste your actual key values when prompted
echo -n "YOUR-SENDGRID-KEY" | \
  gcloud secrets create SENDGRID_API_KEY --data-file=-

echo -n "YOUR-ACTION-NETWORK-KEY" | \
  gcloud secrets create AN_WEBHOOK_KEY --data-file=-
```

Finally, log in locally so your laptop can reach Secret Manager while developing:
```bash
gcloud auth application-default login
```

---

## Secrets in GCP Secret Manager

Two secrets must exist in your GCP project's Secret Manager before deploying:

| Secret Name       | What It Is                              |
|-------------------|-----------------------------------------|
| `SENDGRID_API_KEY` | Your SendGrid API key                  |
| `AN_WEBHOOK_KEY`   | Your Action Network API key            |

To create them:
1. Go to [GCP Console → Security → Secret Manager](https://console.cloud.google.com/security/secret-manager)
2. Click **Create Secret**
3. Name it exactly as shown above and paste the key value

---

## Deploy to Cloud Run

### Option A: Manual deploy from your terminal (one command)
```bash
gcloud run deploy cfcg-an-webhook \
  --source . \
  --region us-east1 \
  --platform managed \
  --allow-unauthenticated \
  --service-account "cfcg-an-webhook-sa@YOUR-PROJECT-ID.iam.gserviceaccount.com" \
  --set-env-vars "CLOUD_PROJECT_ID=YOUR-PROJECT-ID" \
  --set-env-vars "FROM_EMAIL=centerforcommonground.tech@gmail.com" \
  --set-env-vars "FROM_NAME=CFCG Team" \
  --set-env-vars "SEND_RECIPIENT_EMAILS=true" \
  --set-env-vars "ALLOWED_RECIPIENT_EMAILS="
```
> Replace `YOUR-PROJECT-ID` with your actual GCP project ID (e.g. `cfcg-an-webhook-123456`).
> No Dockerfile needed — `--source .` uses Google Cloud Buildpacks to build automatically.

### Option B: Auto-deploy via GitHub Actions (push to deploy)
1. Push this repo to GitHub
2. Add these **GitHub Secrets** (Settings → Secrets → Actions):

   | Secret | Value |
   |--------|-------|
   | `CLOUD_PROJECT_ID` | `poiz-403500` |
   | `FROM_EMAIL` | your from address |
   | `GCP_SERVICE_ACCOUNT` | e.g. `github-deployer@poiz-403500.iam.gserviceaccount.com` |
   | `GCP_WORKLOAD_IDENTITY_PROVIDER` | your WIF provider string |

3. Every push to `main` will automatically deploy.

> **Simpler alternative:** Use a GCP service account key JSON instead of Workload Identity.
> Replace the `auth` step in `deploy.yml` with:
> ```yaml
> - uses: google-github-actions/auth@v2
>   with:
>     credentials_json: ${{ secrets.GCP_SA_KEY }}
> ```
> And add `GCP_SA_KEY` as a GitHub secret containing the full JSON key file contents.

---

## Action Network Webhook Setup

1. In Action Network, go to **Developer → Webhooks**
2. Create a new webhook with your Cloud Run URL:
   `https://cfcg-an-webhook-xxxx-ue.a.run.app/webhook`
3. Set it to trigger on **Person Signups** (or whichever event you want)
4. No authentication secret needed (Cloud Run is publicly accessible via HTTPS)

---

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `CLOUD_PROJECT_ID` | *(required)* | GCP project ID |
| `FROM_EMAIL` | `centerforcommonground.tech@gmail.com` | SendGrid from address |
| `FROM_NAME` | `CFCG Team` | SendGrid from name |
| `SEND_RECIPIENT_EMAILS` | `true` | Set `false` to disable sending |
| `SEND_NOTIFICATION_EMAILS` | `false` | Set `true` for admin alerts |
| `ALLOWED_RECIPIENT_EMAILS` | *(empty = all)* | Comma-separated test allow-list |
| `GCS_BUCKET` | *(required in Cloud Run)* | GCS bucket name for zip lookup file |
| `CHECK_IDEMPOTENCY` | `false` | Enable for production |
| `CHECK_ALREADY_EMAILED` | `false` | Enable for production |
| `UPDATE_GROUP_KEY` | `false` | Set `true` to write region key back to Action Network after emailing |
