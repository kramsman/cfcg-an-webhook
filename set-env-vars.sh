#!/bin/bash
# Update Cloud Run environment variables without redeploying.
# Run this from the project root: ./set-env-vars.sh
# Also called automatically by deploy.sh after every deploy.
#
# Note: ^|^ tells gcloud to use | as the separator between variables instead
# of the default comma — necessary because some values contain commas (email lists).

gcloud run services update cfcg-an-webhook \
  --region us-east1 \
  --update-env-vars "^|^CLOUD_PROJECT_ID=trim-sunlight-489423-h3\
|GCS_BUCKET=cfcg-an-webhook-storage-trim-sunlight-489423-h3\
|FROM_EMAIL=centerforcommonground.tech@gmail.com\
|FROM_NAME=Center for Common Ground Team\
|LOGO_URL=https://storage.googleapis.com/cfcg-an-webhook-storage-trim-sunlight-489423-h3/CFCG_logo.png\
|SEND_RECIPIENT_EMAILS=true\
|SEND_NOTIFICATION_EMAILS=true\
|ALLOWED_RECIPIENT_EMAILS=rovmailtester@gmail.com,kramsman@yahoo.com\
|NOTIFICATION_EMAIL_LIST=kramsman@yahoo.com\
|ALWAYS_CC_LIST=\
|ALWAYS_BCC_LIST=\
|CHECK_IDEMPOTENCY=false\
|CHECK_ALREADY_EMAILED=true\
|SEND_TO_EXISTING_EMAILS=true\
|UPDATE_GROUP_KEY=false\
|LOG_PAYLOADS=true\
|LOG_EMAILS=true" \
  --project trim-sunlight-489423-h3
