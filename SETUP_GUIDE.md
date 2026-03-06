# CFCG Webhook — Setup Guide

## What This Package Does

When someone signs up on your Action Network website, Action Network sends a webhook
to this service. The service looks up the new signup's zip code, finds their assigned
regional organizer, and automatically sends them a welcome email via SendGrid with
their organizer's name and contact info. It then updates the person's record in
Action Network with their region code.

The service runs on Google Cloud Run — it sleeps when not in use and wakes up
instantly when a webhook arrives. There is no server to manage.

---

## ⚠️ Personal Account vs Org Account — Read This First

The `centerforcommonground.org` Google organization has security policies that
block two things needed for this project:

1. **Making Cloud Run publicly accessible** — required so Action Network can call
   your webhook. Blocked by the org's `iam.allowedPolicyMemberDomains` policy.
2. **Creating service account keys** — required for GitHub Actions auto-deploy.
   Blocked by the org's `iam.disableServiceAccountKeyCreation` policy.

**Recommended approach: create the GCP project under your personal Google account**
(`centerforcommonground.tech@gmail.com`). Personal accounts have none of these restrictions.
The project can be transferred to the org later by a GCP org admin if needed.

Steps that should be done under your **personal account** (`centerforcommonground.tech@gmail.com`):
- Step 7 — Create the GCP project
- All `gcloud` commands in Parts 3–7 (log in as personal account)

Steps that require **org admin** (`centerforcommonground.org`) intervention
if staying under the org account:
- Step 25 Option A — granting `allUsers` public access to Cloud Run
- Option B — creating service account keys for GitHub Actions

---

## Conventions Used in This Guide

| Label | Meaning |
|---|---|
| **PyCharm terminal** | The terminal panel inside PyCharm (opens in the project folder automatically) |
| **Laptop terminal** | Any terminal on your Mac — including the PyCharm terminal |
| **GCP Console** | Browser at [console.cloud.google.com](https://console.cloud.google.com) |
| **Account: tech@** | Signed in as `tech@centerforcommonground.org` |
| **Account: you** | Your personal Google account (e.g. `centerforcommonground.tech@gmail.com`) |

---

## What You Need Before Starting

- A Google account (`tech@centerforcommonground.org`)
- A SendGrid account with an API key
- Your Action Network API key
- `gcloud` CLI installed on your laptop ([install here](https://cloud.google.com/sdk/docs/install))
- `uv` installed on your laptop ([install here](https://docs.astral.sh/uv/getting-started/installation/))
- PyCharm installed
- A GitHub account and a new empty repository for this project

---

## Part 1 — Install the Package Locally

### Step 1 — Unzip the project
Unzip `cfcg-an-webhook.zip` to a folder on your computer, for example:
```
~/Library/CloudStorage/Dropbox/Postcard Files/ROVPrograms/cfcg-an-webhook/
```

### Step 2 — Open in PyCharm
> **Where:** PyCharm

File → Open → select the `cfcg-an-webhook` folder.

### Step 3 — Create the virtual environment
> **Where:** PyCharm terminal · **Directory:** project folder

```bash
uv venv
```
```bash
uv sync
```
This creates a `.venv` folder and installs all dependencies from `pyproject.toml`.

### Step 4 — Point PyCharm to the virtual environment
> **Where:** PyCharm → Settings

- PyCharm → Settings → Project → Python Interpreter
- Click **Add Interpreter** → **Existing**
- Navigate to `.venv/bin/python` (Mac) or `.venv/Scripts/python.exe` (Windows)
- Click OK

### Step 5 — Create your local .env file
> **Where:** PyCharm terminal · **Directory:** project folder

```bash
cp .env .env
```
Open `.env` in PyCharm and fill in values as you complete the steps below.

---

## Part 2 — Create a New Google Cloud Project

### Step 6 — Sign in to GCP Console
> **Where:** GCP Console · **Account: tech@**

Go to [console.cloud.google.com](https://console.cloud.google.com) and sign in with
`tech@centerforcommonground.org`.

### Step 7 — Create a new project
> **Where:** GCP Console · **Account: personal (centerforcommonground.tech@gmail.com) — recommended**
> (see org policy note at top of this guide)

1. Click the project dropdown at the top of the page
2. Click **New Project**
3. Name it `cfcg-an-webhook`
4. Click **Create**
5. Note the **Project ID** it generates (e.g. `cfcg-an-webhook`) and the
   **Project Number** (a long number like `354456242651`) — you'll need both below

### Step 8 — Enable billing
> **Where:** GCP Console · **Account: tech@**

1. In the left menu go to **Billing**
2. Link the project to a credit card or existing billing account

> Cloud Run has a free tier of 2 million requests per month. This project will
> almost certainly cost $0.

### Step 9 — Update your .env file
> **Where:** PyCharm (editor)

Open `.env` and set:
```
CLOUD_PROJECT_ID=your-project-id-here
GCS_BUCKET=cfcg-an-webhook-storage-your-project-id-here
```
Replace with the actual Project ID from Step 7.

---

## Part 3 — Set Up GCP Resources

> **Where:** Laptop terminal (PyCharm terminal is fine) · **Account: personal (centerforcommonground.tech@gmail.com) — recommended**
>
> Replace `YOUR-PROJECT-ID` with your Project ID and `YOUR-PROJECT-NUMBER`
> with your Project Number (both from Step 7).
>
> **Tip:** If you ever get a "wrong project" error, run:
> ```bash
> gcloud config get-value project
> ```
> And fix it with:
> ```bash
> gcloud config set project YOUR-PROJECT-ID
> ```

### Step 10 — Log in to gcloud and set your project
> **Where:** Laptop terminal · **Account: tech@**

```bash
gcloud auth login
```
```bash
gcloud config set project YOUR-PROJECT-ID
```

### Step 11 — Enable the required APIs
> **Where:** Laptop terminal · **Account: tech@**

```bash
gcloud services enable run.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```
This takes about a minute.

### Step 12 — Create the service account
> **Where:** Laptop terminal · **Account: tech@**

This is the identity your app runs as in Cloud Run.
```bash
gcloud iam service-accounts create cfcg-an-webhook-sa --display-name "CFCG Webhook Service Account"
```

### Step 13 — Grant the service account access to Secret Manager
> **Where:** Laptop terminal · **Account: tech@**

```bash
gcloud projects add-iam-policy-binding YOUR-PROJECT-ID --member "serviceAccount:cfcg-an-webhook-sa@YOUR-PROJECT-ID.iam.gserviceaccount.com" --role "roles/secretmanager.secretAccessor"
```

### Step 14 — Grant the Cloud Build service account permissions
> **Where:** Laptop terminal · **Account: tech@**

Required for `gcloud run deploy --source .` to work. Use your Project Number
(not Project ID) from Step 7:
```bash
gcloud projects add-iam-policy-binding YOUR-PROJECT-ID --member "serviceAccount:YOUR-PROJECT-NUMBER-compute@developer.gserviceaccount.com" --role "roles/storage.objectAdmin"
```
```bash
gcloud projects add-iam-policy-binding YOUR-PROJECT-ID --member "serviceAccount:YOUR-PROJECT-NUMBER-compute@developer.gserviceaccount.com" --role "roles/cloudbuild.builds.builder"
```
```bash
gcloud projects add-iam-policy-binding YOUR-PROJECT-ID --member "serviceAccount:YOUR-PROJECT-NUMBER-compute@developer.gserviceaccount.com" --role "roles/artifactregistry.writer"
```
```bash
gcloud projects add-iam-policy-binding YOUR-PROJECT-ID --member "serviceAccount:YOUR-PROJECT-NUMBER-compute@developer.gserviceaccount.com" --role "roles/logging.logWriter"
```

### Step 15 — Create a Cloud Storage bucket
> **Where:** Laptop terminal · **Account: tech@**

This bucket stores the zip lookup file and future tracking files.
```bash
gsutil mb -l us-east1 gs://cfcg-an-webhook-storage-YOUR-PROJECT-ID
```

### Step 16 — Grant the service account access to the bucket
> **Where:** Laptop terminal · **Account: tech@**

```bash
gsutil iam ch serviceAccount:cfcg-an-webhook-sa@YOUR-PROJECT-ID.iam.gserviceaccount.com:objectAdmin gs://cfcg-an-webhook-storage-YOUR-PROJECT-ID
```

### Step 17 — Upload the zip lookup file to GCS
> **Account: tech@**

This file maps zip codes to organizers and must be uploaded before deploying.

**Option 1 — Upload via GCP Console (easiest)**
> **Where:** GCP Console

1. Go to GCP Console → **Cloud Storage → Buckets → cfcg-an-webhook-storage-YOUR-PROJECT-ID**
2. Click **Upload Files**
3. Select `zip_dict.json` from your laptop

**Option 2 — Upload via terminal**
> **Where:** Laptop terminal · **Directory:** anywhere

```bash
gsutil cp "/path/to/zip_dict.json" gs://cfcg-an-webhook-storage-YOUR-PROJECT-ID/zip_dict.json
```

To update the file in the future, just re-upload using either option above — no code
deploy needed. Then go to GCP Console → **Cloud Run → cfcg-an-webhook →
Edit & Deploy New Revision** and click Deploy to force a restart and reload.

---

## Part 4 — Add Your API Keys to Secret Manager

> **Where:** Laptop terminal · **Account: tech@**
>
> Replace the placeholder text inside the quotes with your actual key values.

### Step 18 — Create the SendGrid secret
```bash
echo -n "YOUR-SENDGRID-API-KEY" | gcloud secrets create SENDGRID_API_KEY --data-file=-
```

### Step 19 — Create the Action Network secret
```bash
echo -n "YOUR-ACTION-NETWORK-API-KEY" | gcloud secrets create AN_WEBHOOK_KEY --data-file=-
```

> To find or update these secrets later: GCP Console →
> **Security → Secret Manager**.

---

## Part 5 — Set Up Local Development Access

### Step 20 — Authenticate your laptop to GCP
> **Where:** Laptop terminal · **Account: tech@**

This is separate from `gcloud auth login` and is required for your local app to
reach Secret Manager from PyCharm.
```bash
gcloud auth application-default login
```
A browser window will open — sign in with `tech@centerforcommonground.org`.
You only need to do this once per laptop.

> **Note:** If you see a warning about "quota project", it can be ignored for
> local development.

### Step 21 — Grant your account access to Secret Manager for local development
> **Where:** Laptop terminal · **Account: tech@**

```bash
gcloud projects add-iam-policy-binding YOUR-PROJECT-ID --member "user:tech@centerforcommonground.org" --role "roles/secretmanager.secretAccessor"
```

### Step 22 — Fix Mac Python SSL certificates (Mac only, run once)
> **Where:** Laptop terminal · **Account:** any

```bash
/Applications/Python\ 3.12/Install\ Certificates.command
```
Adjust `3.12` to match your Python version if different.

---

## Part 6 — Test Locally

### Step 23 — Run the server
> **Where:** PyCharm terminal · **Directory:** project folder

```bash
python cfcg_an_webhook/main.py
```
You should see:
```
Loading zip lookup table from local file ...
Loaded 41,685 zip codes
Starting local dev server on http://localhost:8080
```

### Step 24 — Send a test webhook
> **Where:** PyCharm — open a **second** terminal tab · **Directory:** project folder

```bash
python test_local.py
```
You should see status 200 and `"Email sent to ..."` in the response.
Edit `test_local.py` to change the test zip code or email address.

> **Note:** Use a Gmail address for testing — Yahoo blocks emails from
> unverified senders.

---

## Part 7 — Deploy to Cloud Run

> **Where:** PyCharm terminal · **Directory:** project folder · **Account: tech@**
>
> **Important:** Run the deploy from your laptop (PyCharm terminal), not from
> Google Cloud Shell. Cloud Shell does not have your project files.

### Step 25 — Fix file timestamps (run once before first deploy)
```bash
find . -exec touch {} \;
```
This prevents a ZIP timestamp error during upload.

### Option A: Manual deploy (recommended)
Run this anytime you want to deploy:
```bash
gcloud run deploy cfcg-an-webhook --source . --region us-east1 --platform managed --allow-unauthenticated --service-account "cfcg-an-webhook-sa@YOUR-PROJECT-ID.iam.gserviceaccount.com" --set-env-vars "CLOUD_PROJECT_ID=YOUR-PROJECT-ID" --set-env-vars "FROM_EMAIL=centerforcommonground.tech@gmail.com" --set-env-vars "FROM_NAME=CFCG Team" --set-env-vars "SEND_RECIPIENT_EMAILS=true" --set-env-vars "SEND_NOTIFICATION_EMAILS=false" --set-env-vars "ALLOWED_RECIPIENT_EMAILS=" --set-env-vars "GCS_BUCKET=cfcg-an-webhook-storage-YOUR-PROJECT-ID"
```
> No Docker required — `--source .` uploads your code and Google builds it automatically.

When it finishes it will print your service URL, e.g.:
```
Service URL: https://cfcg-an-webhook-354456242651.us-east1.run.app
```

> **Org policy note:** If you see a warning about `Setting IAM policy failed`,
> your Google organization blocks granting public access to services. Run:
> ```bash
> gcloud beta run services add-iam-policy-binding --region=us-east1 --member=allUsers --role=roles/run.invoker cfcg-an-webhook
> ```
> If that also fails, ask your GCP org admin to allow `allUsers` on Cloud Run
> for this project.

### Option B: Auto-deploy via GitHub (push to deploy)
Every push to the `main` branch automatically deploys via the included
GitHub Actions workflow.

> **Note:** This requires creating a service account key. If your Google Cloud
> organization has the `constraints/iam.disableServiceAccountKeyCreation` policy
> enabled, key creation will be blocked and you will need to use Option A instead,
> or ask your GCP org admin to set up Workload Identity Federation.

**One-time GitHub setup:**
> **Where:** Browser (GitHub) and laptop terminal · **Account: tech@**

1. Push the project to your GitHub repository
2. Go to your repo → **Settings → Secrets and Variables → Actions**
3. Add these repository secrets:

| Secret Name | Value |
|---|---|
| `CLOUD_PROJECT_ID` | Your GCP project ID |
| `FROM_EMAIL` | `centerforcommonground.tech@gmail.com` (or whatever your from address is) |
| `GCP_SERVICE_ACCOUNT` | `cfcg-an-webhook-sa@YOUR-PROJECT-ID.iam.gserviceaccount.com` |
| `GCP_SA_KEY` | Contents of a service account JSON key (see below) |

**Create the service account key:**
> **Where:** Laptop terminal · **Account: tech@**

```bash
gcloud iam service-accounts keys create github-sa-key.json --iam-account "cfcg-an-webhook-sa@YOUR-PROJECT-ID.iam.gserviceaccount.com"
```
Open `github-sa-key.json`, copy the entire contents, and paste it as the
value of the `GCP_SA_KEY` GitHub secret. Then delete the file from your laptop.

**Grant the service account permission to deploy:**
> **Where:** Laptop terminal · **Account: tech@**

```bash
gcloud projects add-iam-policy-binding YOUR-PROJECT-ID --member "serviceAccount:cfcg-an-webhook-sa@YOUR-PROJECT-ID.iam.gserviceaccount.com" --role "roles/run.admin"
```
```bash
gcloud projects add-iam-policy-binding YOUR-PROJECT-ID --member "serviceAccount:cfcg-an-webhook-sa@YOUR-PROJECT-ID.iam.gserviceaccount.com" --role "roles/iam.serviceAccountUser"
```
```bash
gcloud projects add-iam-policy-binding YOUR-PROJECT-ID --member "serviceAccount:cfcg-an-webhook-sa@YOUR-PROJECT-ID.iam.gserviceaccount.com" --role "roles/storage.admin"
```

After this, every `git push` to `main` deploys automatically.

---

## Part 8 — Connect Action Network

### Step 26 — Register the webhook in Action Network
> **Where:** Action Network · **Account: tech@**

1. Log in to Action Network
2. Go to **Developer → Webhook** (or your group's API settings)
3. Create a new webhook pointing to your Cloud Run URL:
   ```
   https://cfcg-an-webhook-YOUR-PROJECT-NUMBER.us-east1.run.app/webhook
   ```
4. Set it to trigger on **Person Signups**
5. Save

Action Network will now POST to your service every time someone signs up.

---

## Part 9 — Your Day-to-Day Workflow

**Making changes:**
> **Where:** PyCharm terminal · **Directory:** project folder

1. Edit code in PyCharm
2. Test locally:
   ```bash
   python cfcg_an_webhook/main.py
   ```
   Then in a second terminal:
   ```bash
   python test_local.py
   ```
3. Deploy when ready (Option A above)

**Adding a Python package:**
> **Where:** PyCharm terminal · **Directory:** project folder

```bash
uv add package-name
```
This updates `pyproject.toml` automatically.

**Updating the zip lookup file:**
> **Where:** GCP Console or laptop terminal · **Account: tech@**

Upload the new `zip_dict.json` to GCS (Step 17), then redeploy or restart the
Cloud Run service to pick up the new file.

**Checking logs in production:**
> **Where:** Laptop terminal · **Account: tech@**

```bash
gcloud run services logs read cfcg-an-webhook --region us-east1
```
Or: GCP Console → **Cloud Run → cfcg-an-webhook → Logs**.

**Updating an API key:**
> **Where:** GCP Console · **Account: tech@**

GCP Console → **Security → Secret Manager** → click the secret →
**New Version** → paste the new value.

---

## Environment Variables Reference

These are set in your `.env` file locally and as Cloud Run environment variables
in production.

| Variable | Default | Description |
|---|---|---|
| `CLOUD_PROJECT_ID` | *(required)* | GCP project ID |
| `GCS_BUCKET` | *(required in Cloud Run)* | GCS bucket name for zip lookup file |
| `FROM_EMAIL` | `centerforcommonground.tech@gmail.com` | SendGrid from address |
| `FROM_NAME` | `CFCG Team` | SendGrid from name |
| `SEND_RECIPIENT_EMAILS` | `true` | Set `false` to disable all sending |
| `SEND_NOTIFICATION_EMAILS` | `false` | Set `true` for admin alert emails |
| `ALLOWED_RECIPIENT_EMAILS` | *(empty = all)* | Comma-separated test allow-list |
| `CHECK_IDEMPOTENCY` | `false` | Prevent duplicate processing — turn on for production |
| `CHECK_ALREADY_EMAILED` | `false` | Prevent duplicate emails — turn on for production |
