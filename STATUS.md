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
- [ ] **Redeploy after Procfile fix** — run in PyCharm terminal:
  ```bash
  find . -exec touch {} \; && gcloud run deploy cfcg-an-webhook \
    --source . \
    --region us-east1 \
    --platform managed \
    --allow-unauthenticated \
    --service-account "cfcg-an-webhook-sa@trim-sunlight-489423-h3.iam.gserviceaccount.com" \
    --set-env-vars "CLOUD_PROJECT_ID=trim-sunlight-489423-h3" \
    --set-env-vars "FROM_EMAIL=centerforcommonground.tech@gmail.com" \
    --set-env-vars "FROM_NAME=CFCG Team" \
    --set-env-vars "SEND_RECIPIENT_EMAILS=true" \
    --set-env-vars "SEND_NOTIFICATION_EMAILS=false" \
    --set-env-vars "ALLOWED_RECIPIENT_EMAILS=" \
    --set-env-vars "GCS_BUCKET=cfcg-an-webhook-storage-trim-sunlight-489423-h3"
  ```
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
