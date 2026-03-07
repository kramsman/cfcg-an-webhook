# Status — cfcg-an-webhook

## Current State
- GCP project: `trim-sunlight-489423-h3`
- Service deployed to: `https://cfcg-an-webhook-520473536006.us-east1.run.app`
- Service account: `cfcg-an-webhook-sa@trim-sunlight-489423-h3.iam.gserviceaccount.com`
- GCS bucket: `cfcg-an-webhook-storage-trim-sunlight-489423-h3`
- zip_dict.json: uploaded to GCS (41k zips, named-field format)
- Procfile: **fixed** — `cfcg_an_webhook.main:app` (was `main:app`, caused 503)
- GitHub Actions: blocked by org policy (service account key creation not allowed)

## Pending — Needs Confirmation
## Deployment Commands
Run these from the project root terminal. Two scripts handle all deployment needs:

**Deploy code + update env vars** (use when code has changed):
```bash
cd ~/Library/CloudStorage/Dropbox/Postcard\ Files/ROVPrograms/cfcg-an-webhook && ./deploy.sh
```
`deploy.sh` deploys the code to Cloud Run, then automatically runs `set-env-vars.sh`.

**Update env vars only, no redeploy** (use when only config has changed):
```bash
cd ~/Library/CloudStorage/Dropbox/Postcard\ Files/ROVPrograms/cfcg-an-webhook && ./set-env-vars.sh
```
`set-env-vars.sh` updates all environment variables in seconds without redeploying.

**Update a single env var quickly** — replace `LOG_PAYLOADS=true` with any `VAR=value`:
```bash
gcloud run services update cfcg-an-webhook \
  --region us-east1 \
  --update-env-vars "LOG_PAYLOADS=true" \
  --project trim-sunlight-489423-h3
```
Only the specified variable changes — everything else stays as-is.
- [ ] Verify health check after redeploy:
  `curl https://cfcg-an-webhook-520473536006.us-east1.run.app/health`
  Should return: `{"status": "ok", "zip_codes_loaded": 41000+}`
- [ ] Resolve `allUsers` public access (org policy blocks it — needs org admin or personal GCP account)
- [ ] Connect Action Network webhook (Step 26 in SETUP_GUIDE.md) — after deploy is confirmed working
- [ ] Push to GitHub (repo not yet pushed to remote)

## Known Issues
- Cloud Run org policy blocks `--allow-unauthenticated` — if redeploy fails on that, contact org admin
  or use personal Gmail account to create a new GCP project

## Completed
- [x] Project structure created
- [x] Flask app with zip lookup, SendGrid email, Action Network update
- [x] zip_dict.json uploaded to GCS (41k zips, named-field format)
- [x] GCP APIs enabled, service account created and granted permissions
- [x] Secrets added to Secret Manager (SENDGRID_API_KEY, AN_WEBHOOK_KEY)
- [x] Local dev tested successfully
- [x] Procfile fixed: `main:app` → `cfcg_an_webhook.main:app`
- [x] SETUP_GUIDE.md updated with all lessons learned during actual setup
- [x] Added `UPDATE_GROUP_KEY` feature flag (writes region key back to AN after emailing)
- [x] Added Google-style docstrings (Args/Returns) to all functions in main.py
- [x] Created global `/test_create` skill at `~/.claude/skills/test_create/SKILL.md`
- [x] Built full pytest test suite: `tests/conftest.py`, `tests/test_main.py` (32 unit + 10 integration)
- [x] Replaced `VALID_OSDI_TYPES` set with `OSDI_TYPE_CONFIG` dict (parsed + send_email flags per type)
- [x] Added `send_email` gate in `process_recipient()` — donation/signature skip email, attendance/submission send
- [x] Added warning + notification email when an unknown osdi type arrives
- [x] Created `tests/payloads/` with real captured AN payloads for all 4 types:
  - `attendance.json` — real payload
  - `signature.json` — real payload (John Smith, 6-digit zip, full state name)
  - `donation.json` — real payload (no given_name, District of Columbia)
  - `submission.json` — real payload (no given_name, District of Columbia)
- [x] Added snapshot tests for all 4 real payloads — will catch AN format changes
- [x] Documented AN webhook + REST API URLs in ISSUES.md for all resource types
- [x] Replaced file-existence check in `load_zip_dict()` with explicit `ZIP_DICT_PATH` env var
