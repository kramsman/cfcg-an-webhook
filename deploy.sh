#!/bin/bash
# Deploy cfcg-an-webhook to Google Cloud Run.
# Run this from the project root: ./deploy.sh

gcloud run deploy cfcg-an-webhook \
  --source . \
  --region us-east1 \
  --platform managed \
  --allow-unauthenticated \
  --service-account "cfcg-an-webhook-sa@trim-sunlight-489423-h3.iam.gserviceaccount.com" \
  --set-env-vars "CLOUD_PROJECT_ID=trim-sunlight-489423-h3" \
  --set-env-vars "GCS_BUCKET=cfcg-an-webhook-storage-trim-sunlight-489423-h3" \
  --set-env-vars "FROM_EMAIL=centerforcommonground.tech@gmail.com" \
  --set-env-vars "FROM_NAME=Center for Common Ground Team" \
  --set-env-vars "SEND_RECIPIENT_EMAILS=true" \
  --set-env-vars "SEND_NOTIFICATION_EMAILS=false" \
  --set-env-vars "ALLOWED_RECIPIENT_EMAILS=" \
  --set-env-vars "NOTIFICATION_EMAIL_LIST=rovmailtester@gmail.com,kramsman@yahoo.com" \
  --set-env-vars "ALWAYS_CC_LIST=" \
  --set-env-vars "ALWAYS_BCC_LIST=" \
  --set-env-vars "CHECK_IDEMPOTENCY=false" \
  --set-env-vars "CHECK_ALREADY_EMAILED=false" \
  --set-env-vars "UPDATE_GROUP_KEY=false" \
  --set-env-vars "LOG_PAYLOADS=false" \
  --set-env-vars "LOG_EMAILS=false" \
  --project trim-sunlight-489423-h3
