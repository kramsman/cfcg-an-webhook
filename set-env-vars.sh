#!/bin/bash
# Update Cloud Run environment variables without redeploying.
# Run this from the project root: ./set-env-vars.sh
# Also called automatically by deploy.sh after every deploy.

gcloud run services update cfcg-an-webhook \
  --region us-east1 \
  --update-env-vars "CLOUD_PROJECT_ID=trim-sunlight-489423-h3" \
  --update-env-vars "GCS_BUCKET=cfcg-an-webhook-storage-trim-sunlight-489423-h3" \
  --update-env-vars "FROM_EMAIL=centerforcommonground.tech@gmail.com" \
  --update-env-vars "FROM_NAME=Center for Common Ground Team" \
  --update-env-vars "SEND_RECIPIENT_EMAILS=false" \
  --update-env-vars "SEND_NOTIFICATION_EMAILS=false" \
  --update-env-vars "ALLOWED_RECIPIENT_EMAILS=rovmailtester@gmail.com,kramsman@yahoo.com" \
  --update-env-vars "^|^NOTIFICATION_EMAIL_LIST=rovmailtester@gmail.com,kramsman@yahoo.com" \
  --update-env-vars "ALWAYS_CC_LIST=" \
  --update-env-vars "ALWAYS_BCC_LIST=" \
  --update-env-vars "CHECK_IDEMPOTENCY=false" \
  --update-env-vars "CHECK_ALREADY_EMAILED=false" \
  --update-env-vars "UPDATE_GROUP_KEY=false" \
  --update-env-vars "LOG_PAYLOADS=true" \
  --update-env-vars "LOG_EMAILS=true" \
  --project trim-sunlight-489423-h3
