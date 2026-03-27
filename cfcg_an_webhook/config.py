"""
Application configuration — reads all environment variables.
Import constants from here rather than reading os.environ directly in main.py.
"""

import os

from dotenv import load_dotenv
from loguru import logger

# Load .env file when running locally (no-op in Cloud Run)
load_dotenv()

# ─── GCP / Storage ────────────────────────────────────────────────────────────

ZIP_DICT_PATH    = os.environ.get("ZIP_DICT_PATH", "")
CLOUD_PROJECT_ID = os.environ["CLOUD_PROJECT_ID"]   # required — set in .env or Cloud Run env vars
GCS_BUCKET       = os.environ.get("GCS_BUCKET", "")  # required in Cloud Run; not needed locally if file exists

# ─── Email identity ───────────────────────────────────────────────────────────

FROM_EMAIL = os.environ.get("FROM_EMAIL", "centerforcommonground.tech@gmail.com")  # sender address shown on welcome emails
FROM_NAME  = os.environ.get("FROM_NAME",  "Center for Common Ground Team")           # sender name shown on welcome emails
LOGO_URL   = os.environ.get("LOGO_URL",   "")                                        # URL to org logo in email header; leave empty to omit logo

# ─── Email sending flags ──────────────────────────────────────────────────────

# Set SEND_RECIPIENT_EMAILS=false during testing to skip actual sends.
SEND_RECIPIENT_EMAILS    = os.environ.get("SEND_RECIPIENT_EMAILS",    "true").lower()  == "true"  # true = send welcome emails to new signups; set false during testing
SEND_NOTIFICATION_EMAILS = os.environ.get("SEND_NOTIFICATION_EMAILS", "false").lower() == "true"  # true = send admin alert emails on errors/warnings
logger.debug(f"SEND_RECIPIENT_EMAILS={SEND_RECIPIENT_EMAILS}")
logger.debug(f"SEND_NOTIFICATION_EMAILS={SEND_NOTIFICATION_EMAILS}")

# Comma-separated allow-list for testing. Leave empty to email everyone.
# Example:  ALLOWED_RECIPIENT_EMAILS=you@gmail.com,test@example.com
ALLOWED_RECIPIENT_EMAILS = [
    e.strip() for e in os.environ.get("ALLOWED_RECIPIENT_EMAILS", "").split(",") if e.strip()
]
NOTIFICATION_EMAIL_LIST = [                                                         # admin alert recipients; leave empty to disable notifications
    {"email": e.strip()} for e in os.environ.get("NOTIFICATION_EMAIL_LIST", "").split(",") if e.strip()
]
PAYLOAD_NOTIFICATION_LIST = [                                                       # receives a copy of every incoming webhook payload; leave empty to disable
    {"email": e.strip()} for e in os.environ.get("PAYLOAD_NOTIFICATION", "").split(",") if e.strip()
]
EXCLUDED_PAYLOAD_OSDI = {                                                           # suppress payload notification emails for these osdi types (e.g. attendance,outreach)
    t.strip() for t in os.environ.get("EXCLUDED_PAYLOAD_OSDI", "").split(",") if t.strip()
}


def _parse_email_name_list(raw: str) -> list:
    """Parse 'email:name,email:name' string into a list of (email, name) tuples."""
    pairs = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            email, name = item.split(":", 1)
            pairs.append((email.strip(), name.strip()))
        else:
            pairs.append((item, ""))
    return pairs


# CC or BCC if an admin wants to monitor what is going on. Format: email:name,email:name — leave empty to add no one.
ALWAYS_CC_LIST  = _parse_email_name_list(os.environ.get("ALWAYS_CC_LIST",  ""))  # added to every outgoing welcome email as CC
ALWAYS_BCC_LIST = _parse_email_name_list(os.environ.get("ALWAYS_BCC_LIST", ""))  # added to every outgoing welcome email as BCC

# ─── Duplicate / idempotency controls ─────────────────────────────────────────

CHECK_IDEMPOTENCY       = os.environ.get("CHECK_IDEMPOTENCY",       "false").lower() == "true"  # true = skip if this payload UUID was already processed
CHECK_ALREADY_EMAILED   = os.environ.get("CHECK_ALREADY_EMAILED",   "false").lower() == "true"  # true = look up AN record to see if welcome email was already sent
CHECK_SHEET_FOR_EMAIL   = os.environ.get("CHECK_SHEET_FOR_EMAIL",   "false").lower() == "true"  # true = look up the Google Sheet to skip emails already logged there
SEND_TO_EXISTING_EMAILS = os.environ.get("SEND_TO_EXISTING_EMAILS", "false").lower() == "true"  # true = email even if person already existed in AN (requires CHECK_ALREADY_EMAILED=true)
UPDATE_GROUP_KEY        = os.environ.get("UPDATE_GROUP_KEY",        "false").lower() == "true"  # true = write region group_key back to Action Network after emailing
LOG_PAYLOADS            = os.environ.get("LOG_PAYLOADS",            "false").lower() == "true"  # true = log raw webhook payload (contains personal info — disable when stable)
LOG_EMAILS              = os.environ.get("LOG_EMAILS",              "false").lower() == "true"  # true = log outgoing email details (contains personal info — disable when stable)
logger.debug(f"LOG_PAYLOADS={LOG_PAYLOADS}")
logger.debug(f"LOG_EMAILS={LOG_EMAILS}")

# ─── Google Sheets ────────────────────────────────────────────────────────────

APPEND_TO_SHEET = os.environ.get("APPEND_TO_SHEET", "false").lower() == "true"  # true = append signup row to Google Sheet (requires GOOGLE_SHEET_ID)
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")                         # alphanumeric ID from Sheet URL (/d/<ID>/edit); leave empty if APPEND_TO_SHEET=false
# SHEET_TAB       = "AN-2026-RAW-DATA"   # sheet tab name — update at start of each year; AN-2026-RAW-DATA production
SHEET_TAB       = "AN-JAN5-2026-START"   # sheet tab name; test in Copy: AN-JAN5-2026-START
logger.debug(f"APPEND_TO_SHEET={APPEND_TO_SHEET}  GOOGLE_SHEET_ID={'(set)' if GOOGLE_SHEET_ID else '(empty)'}")

# ─── Transaction buffering ────────────────────────────────────────────────────

REMOVE_MULTI_IDENTIFIERS   = os.environ.get("REMOVE_MULTI_IDENTIFIERS",   "true").lower()  == "true"  # true = buffer records sharing the same AN UUID and process as one transaction
TRANSACTION_WINDOW_SECONDS = float(os.environ.get("TRANSACTION_WINDOW_SECONDS", "10"))              # seconds to wait before processing a buffered group (e.g. 10 locally, 7200 in prod)
logger.debug(f"REMOVE_MULTI_IDENTIFIERS={REMOVE_MULTI_IDENTIFIERS}  TRANSACTION_WINDOW_SECONDS={TRANSACTION_WINDOW_SECONDS}")

# ─── Server ───────────────────────────────────────────────────────────────────

PORT = int(os.environ.get("PORT", "8080"))  # HTTP port Flask listens on; Cloud Run sets this automatically

# ─── Static lookup tables ─────────────────────────────────────────────────────

# Fields read from zip_dict.json — must match org_fields passed to
# create_organizer_info_by_zip_file() in the cfcg-reports generator project.
ZIP_DICT_FIELDS = ['region_key', 'email', 'nickname', 'cc_org']

# Registry of Action Network osdi: event types.
#
# parsed:     True  = parse_recipient() verified/tested for this type (payload file exists)
# send_email: True  = send a welcome email when this type arrives
#
# Types NOT in this table are UNKNOWN — a warning is logged and no email is sent.
# To add a new type: set flags here and add a payload file to tests/payloads/<type>.json
# Webhook docs: https://actionnetwork.org/docs/webhooks/<type>
# REST API docs: https://actionnetwork.org/docs/v2/<type>
#
# NOT included (admin/definition resources that don't arrive as person-action webhooks):
#   Advocacy Campaigns, Campaigns, Custom Fields, Embeds, Event Campaigns, Events,
#   Forms, Fundraising Pages, Items, Lists, Messages, Metadata, People, Petitions,
#   Queries, Surveys, Tags, Unique ID Lists, Wrappers
OSDI_TYPE_CONFIG = {
    # type           parsed      send_email
    'attendance':  {'parsed': True,  'send_email': False},  # event RSVP
    'submission':  {'parsed': True,  'send_email': True },  # form submission
    'signature':   {'parsed': True,  'send_email': False},  # petition signature
    'donation':    {'parsed': True,  'send_email': False},  # donation
    'outreach':    {'parsed': True, 'send_email': False},  # advocacy campaign action
    'response':    {'parsed': True, 'send_email': False},  # survey response
    'tagging':     {'parsed': True, 'send_email': False},  # tag applied to person
}

# US state full name → 2-letter abbreviation (used to convert payload region to sheet column)
_STATE_ABBREV = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME",
    "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE",
    "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
    "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
    "Puerto Rico": "PR", "Guam": "GU", "Virgin Islands": "VI",
    "American Samoa": "AS", "Northern Mariana Islands": "MP",
}
