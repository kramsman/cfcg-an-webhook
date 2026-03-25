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

FROM_EMAIL = os.environ.get("FROM_EMAIL", "centerforcommonground.tech@gmail.com")
FROM_NAME  = os.environ.get("FROM_NAME",  "Center for Common Ground Team")
LOGO_URL   = os.environ.get("LOGO_URL",   "")

# ─── Email sending flags ──────────────────────────────────────────────────────

# Set SEND_RECIPIENT_EMAILS=false during testing to skip actual sends.
SEND_RECIPIENT_EMAILS    = os.environ.get("SEND_RECIPIENT_EMAILS",    "true").lower()  == "true"
SEND_NOTIFICATION_EMAILS = os.environ.get("SEND_NOTIFICATION_EMAILS", "false").lower() == "true"
logger.debug(f"SEND_RECIPIENT_EMAILS={SEND_RECIPIENT_EMAILS}")
logger.debug(f"SEND_NOTIFICATION_EMAILS={SEND_NOTIFICATION_EMAILS}")

# Comma-separated allow-list for testing. Leave empty to email everyone.
# Example:  ALLOWED_RECIPIENT_EMAILS=you@gmail.com,test@example.com
ALLOWED_RECIPIENT_EMAILS = [
    e.strip() for e in os.environ.get("ALLOWED_RECIPIENT_EMAILS", "").split(",") if e.strip()
]
NOTIFICATION_EMAIL_LIST = [
    {"email": e.strip()} for e in os.environ.get("NOTIFICATION_EMAIL_LIST", "").split(",") if e.strip()
]
PAYLOAD_NOTIFICATION_LIST = [
    {"email": e.strip()} for e in os.environ.get("PAYLOAD_NOTIFICATION", "").split(",") if e.strip()
]
EXCLUDED_PAYLOAD_OSDI = {
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


# CC or BCC if an admin wants to monitor what is going on
ALWAYS_CC_LIST  = _parse_email_name_list(os.environ.get("ALWAYS_CC_LIST",  ""))
ALWAYS_BCC_LIST = _parse_email_name_list(os.environ.get("ALWAYS_BCC_LIST", ""))

# ─── Duplicate / idempotency controls ─────────────────────────────────────────

CHECK_IDEMPOTENCY       = os.environ.get("CHECK_IDEMPOTENCY",       "false").lower() == "true"
CHECK_ALREADY_EMAILED   = os.environ.get("CHECK_ALREADY_EMAILED",   "false").lower() == "true"
SEND_TO_EXISTING_EMAILS = os.environ.get("SEND_TO_EXISTING_EMAILS", "false").lower() == "true"
UPDATE_GROUP_KEY        = os.environ.get("UPDATE_GROUP_KEY",        "false").lower() == "true"
LOG_PAYLOADS            = os.environ.get("LOG_PAYLOADS",            "false").lower() == "true"
LOG_EMAILS              = os.environ.get("LOG_EMAILS",              "false").lower() == "true"
logger.debug(f"LOG_PAYLOADS={LOG_PAYLOADS}")
logger.debug(f"LOG_EMAILS={LOG_EMAILS}")

# ─── Google Sheets ────────────────────────────────────────────────────────────

APPEND_TO_SHEET = os.environ.get("APPEND_TO_SHEET", "false").lower() == "true"
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
# SHEET_TAB       = "AN-2026-RAW-DATA"   # sheet tab name — update at start of each year; AN-2026-RAW-DATA production
SHEET_TAB       = "AN-JAN5-2026-START"   # sheet tab name; test in Copy: AN-JAN5-2026-START
logger.debug(f"APPEND_TO_SHEET={APPEND_TO_SHEET}  GOOGLE_SHEET_ID={'(set)' if GOOGLE_SHEET_ID else '(empty)'}")

# ─── Transaction buffering ────────────────────────────────────────────────────

REMOVE_MULTI_IDENTIFIERS   = os.environ.get("REMOVE_MULTI_IDENTIFIERS",   "true").lower()  == "true"
TRANSACTION_WINDOW_SECONDS = float(os.environ.get("TRANSACTION_WINDOW_SECONDS", "10"))
logger.debug(f"REMOVE_MULTI_IDENTIFIERS={REMOVE_MULTI_IDENTIFIERS}  TRANSACTION_WINDOW_SECONDS={TRANSACTION_WINDOW_SECONDS}")

# ─── Server ───────────────────────────────────────────────────────────────────

PORT = int(os.environ.get("PORT", "8080"))

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
    'outreach':    {'parsed': False, 'send_email': False},  # advocacy campaign action
    'response':    {'parsed': False, 'send_email': False},  # survey response
    'tagging':     {'parsed': False, 'send_email': False},  # tag applied to person
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
