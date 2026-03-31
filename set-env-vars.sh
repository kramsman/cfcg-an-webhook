#!/bin/bash
# Update Cloud Run environment variables without redeploying.
# Run this from the project root: ./set-env-vars.sh
# Also called automatically by deploy.sh after every deploy.
#
# Each variable is one array entry so inline comments work correctly.
# The ^|^ prefix tells gcloud to use | as the separator instead of the
# default comma — necessary because some values contain commas (email lists).

ENV_VARS=(

  # ── Test mode ─────────────────────────────────────────────────────────────
  # TEST_MODE=true redirects welcome emails to TEST_RECIPIENT_EMAILS instead of real volunteers.
  # Set to false only when ready to go live.
  "TEST_MODE=true"
  "TEST_RECIPIENT_EMAILS=kramsman@yahoo.com"                                        # required when TEST_MODE=true; welcome emails go here instead of real volunteers

  # ── Email sending flags ────────────────────────────────────────────────────
  "SEND_RECIPIENT_EMAILS=true"                                                      # true = send welcome emails to new signups
  "SEND_NOTIFICATION_EMAILS=true"                                                   # true = send admin alert emails on errors/warnings (bad osdi type, zip not found, etc.)

  # ── Email notification lists ───────────────────────────────────────────────
  "ADMIN_ALERT_EMAILS=kramsman@yahoo.com"                                           # receives admin alert emails (errors, warnings); required when SEND_NOTIFICATION_EMAILS=true
  "PAYLOAD_OBSERVER_EMAILS=kramsman@yahoo.com"                                      # receives a copy of every incoming webhook payload; leave empty to disable
  "EXCLUDED_PAYLOAD_OSDI=attendance,outreach"                                       # suppress payload notification emails for these osdi types

  # ── CC / BCC on every welcome email ───────────────────────────────────────
  "ALWAYS_CC_LIST="                                                                 # added as CC to every welcome email; format: email:name,email:name — leave empty to add no one
  "ALWAYS_BCC_LIST="                                                                # added as BCC to every welcome email; leave empty to add no one

  # ── Duplicate / idempotency controls ──────────────────────────────────────
  "CHECK_IDEMPOTENCY=true"                                                          # true = skip if this payload UUID was already processed
  "CHECK_ALREADY_EMAILED=true"                                                      # true = look up AN record to see if welcome email was already sent
  "CHECK_SHEET_FOR_EMAIL=true"                                                      # true = look up the Google Sheet to skip emails already logged there
  "SEND_TO_EXISTING_EMAILS=false"                                                   # true = email even if person already existed in AN (requires CHECK_ALREADY_EMAILED=true)
  "UPDATE_GROUP_KEY=false"                                                          # true = write region group_key back to Action Network after emailing

  # ── Logging ────────────────────────────────────────────────────────────────
  "LOG_PAYLOADS=true"                                                               # true = log raw webhook payload (contains personal info — disable when stable)
  "LOG_EMAILS=true"                                                                 # true = log outgoing email details (contains personal info — disable when stable)

  # ── Google Sheets ──────────────────────────────────────────────────────────
  "APPEND_TO_SHEET=true"                                                            # true = append signup row to Google Sheet
  "GOOGLE_SHEET_ID=15vrphBaWAGPgsF4PlzligEwF-J7IShQVMMqidxvjsp0"                  # jsp0 — PRODUCTION sheet (used when TEST_MODE=false)
  "SHEET_TAB=AN-2026-RAW-DATA"                                                      # production sheet tab name — update at start of each year
  "TEST_SHEET_ID=1TSQ4OEyAETpYV3FPfqiFgDvpH6lN3kscMTOfTkvYI58"                    # YI58 — test sheet (used when TEST_MODE=true); required when APPEND_TO_SHEET=true and TEST_MODE=true
  "TEST_SHEET_TAB=AN-2026-RAW-DATA"                                                 # test sheet tab name

  # ── Email identity ─────────────────────────────────────────────────────────
  "FROM_EMAIL=centerforcommonground.tech@gmail.com"                                 # sender address shown on welcome emails
  "FROM_NAME=Center for Common Ground Team"                                         # sender name shown on welcome emails
  "LOGO_URL=https://storage.googleapis.com/cfcg-an-webhook-storage-trim-sunlight-489423-h3/CFCG_logo.png"  # URL to org logo in email header; leave empty to omit

  # ── Transaction buffering ──────────────────────────────────────────────────
  "REMOVE_MULTI_IDENTIFIERS=true"                                                   # true = buffer records sharing the same AN UUID and process as one transaction
  "TRANSACTION_WINDOW_SECONDS=60"                                                   # seconds to wait before processing a buffered group

  # ── GCP / Storage ──────────────────────────────────────────────────────────
  "CLOUD_PROJECT_ID=trim-sunlight-489423-h3"                                        # GCP project ID (required)
  "GCS_BUCKET=cfcg-an-webhook-storage-trim-sunlight-489423-h3"                     # Cloud Storage bucket where zip_dict.json is stored
)

# Join array with | separator and pass to gcloud
IFS='|'
gcloud run services update cfcg-an-webhook \
  --region us-east1 \
  --update-env-vars "^|^${ENV_VARS[*]}" \
  --project trim-sunlight-489423-h3
