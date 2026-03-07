#!/bin/bash
# Deploy cfcg-an-webhook to Google Cloud Run.
# Run this from the project root: ./deploy.sh
# After deploying, automatically runs set-env-vars.sh to update all env vars.

gcloud run deploy cfcg-an-webhook \
  --source . \
  --region us-east1 \
  --platform managed \
  --allow-unauthenticated \
  --service-account "cfcg-an-webhook-sa@trim-sunlight-489423-h3.iam.gserviceaccount.com" \
  --project trim-sunlight-489423-h3

echo ""
echo "Deploy complete. Updating environment variables..."
./set-env-vars.sh
