"""
CFCG Action Network Webhook Receiver
--------------------------------------
Receives signup webhooks from Action Network, looks up the assigned support
person by zip code, and sends a welcome email via SendGrid.

Runs on Google Cloud Run. Secrets stored in GCP Secret Manager.
Zip-to-organizer lookup is bundled as zip_dict.json.

Local dev:
    1.  pip install -r requirements.txt
    2.  gcloud auth application-default login
    3.  cp .env.example .env  # fill in your values
    4.  python main.py
    5.  python test_local.py  (in a second terminal)
"""

import json
import os
import pathlib
import time
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, request
from loguru import logger
from sendgrid import SendGridAPIClient
from google.cloud import secretmanager, storage

# Load .env file when running locally (ignored in Cloud Run)
load_dotenv()

# ─── Configuration ────────────────────────────────────────────────────────────

# Path to local zip_dict.json for development. If empty, loads from GCS.
ZIP_DICT_PATH = os.environ.get("ZIP_DICT_PATH", "")

CLOUD_PROJECT_ID = os.environ["CLOUD_PROJECT_ID"]   # required - set in .env or Cloud Run env vars
GCS_BUCKET       = os.environ.get("GCS_BUCKET", "")  # required in Cloud Run; not needed locally if file exists
FROM_EMAIL       = os.environ.get("FROM_EMAIL", "centerforcommonground.tech@gmail.com")
FROM_NAME        = os.environ.get("FROM_NAME",  "Center for Common Ground Team")
LOGO_URL         = os.environ.get("LOGO_URL",   "")

# Set SEND_RECIPIENT_EMAILS=false during testing to skip actual sends. Converts string in .env to boolean.
SEND_RECIPIENT_EMAILS    = os.environ.get("SEND_RECIPIENT_EMAILS",    "true").lower()  == "true"
SEND_NOTIFICATION_EMAILS = os.environ.get("SEND_NOTIFICATION_EMAILS", "false").lower() == "true"
logger.debug(f"SEND_RECIPIENT_EMAILS= {SEND_RECIPIENT_EMAILS}")
logger.debug(f"SEND_NOTIFICATION_EMAILS= {SEND_NOTIFICATION_EMAILS}")

# Comma-separated allow-list for testing. Leave empty to email everyone.
# Example:  ALLOWED_RECIPIENT_EMAILS=you@gmail.com,test@example.com
_allow_raw = os.environ.get("ALLOWED_RECIPIENT_EMAILS", "")
ALLOWED_RECIPIENT_EMAILS = [e.strip() for e in _allow_raw.split(",") if e.strip()]

_notif_raw = os.environ.get("NOTIFICATION_EMAIL_LIST", "")
NOTIFICATION_EMAIL_LIST = [{"email": e.strip()} for e in _notif_raw.split(",") if e.strip()]

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

ALWAYS_CC_LIST  = _parse_email_name_list(os.environ.get("ALWAYS_CC_LIST",  ""))
ALWAYS_BCC_LIST = _parse_email_name_list(os.environ.get("ALWAYS_BCC_LIST", ""))

CHECK_IDEMPOTENCY     = os.environ.get("CHECK_IDEMPOTENCY",     "false").lower() == "true"
CHECK_ALREADY_EMAILED   = os.environ.get("CHECK_ALREADY_EMAILED",   "false").lower() == "true"
SEND_TO_EXISTING_EMAILS = os.environ.get("SEND_TO_EXISTING_EMAILS", "false").lower() == "true"
UPDATE_GROUP_KEY      = os.environ.get("UPDATE_GROUP_KEY",      "false").lower() == "true"
LOG_PAYLOADS          = os.environ.get("LOG_PAYLOADS",          "false").lower() == "true"
LOG_EMAILS            = os.environ.get("LOG_EMAILS",            "false").lower() == "true"
logger.debug(f"LOG_PAYLOADS= {LOG_PAYLOADS}")
logger.debug(f"LOG_EMAILS= {LOG_EMAILS}")

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
    # type           type parsed    send_email
    'attendance':  {'parsed': True,  'send_email': False },   # event RSVP
    'submission':  {'parsed': True,  'send_email': True },   # form submission
    'signature':   {'parsed': True,  'send_email': False},   # petition signature
    'donation':    {'parsed': True,  'send_email': False},   # donation
    'outreach':    {'parsed': False, 'send_email': False},   # advocacy campaign action
    'response':    {'parsed': False, 'send_email': False},   # survey response
    'tagging':     {'parsed': False, 'send_email': False},   # tag applied to person
}

# ─── GCP Secret Manager ───────────────────────────────────────────────────────

_secret_client = secretmanager.SecretManagerServiceClient()

def get_secret(secret_id: str) -> str:
    """Fetch a secret value from GCP Secret Manager.

    Uses the service account automatically (no OAuth flow needed).
    Locally: uses credentials from `gcloud auth application-default login`.

    Args:
        secret_id: The secret name in Secret Manager (e.g. ``SENDGRID_API_KEY``).

    Returns:
        The secret value as a plain string.
    """
    name = f"projects/{CLOUD_PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = _secret_client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

# ─── Zip → Organizer Lookup ───────────────────────────────────────────────────

def load_zip_dict() -> dict:
    """Load zip → organizer mapping.

    If ZIP_DICT_PATH env var is set, loads from that local file path (development).
    Otherwise downloads from GCS (Cloud Run production).

    Returns:
        Dict mapping 5-digit zip string to organizer info dict with keys
        matching ``ZIP_DICT_FIELDS``.

    Raises:
        ValueError: If the loaded file is missing any expected fields.
    """
    if ZIP_DICT_PATH:
        logger.info(f"Loading zip lookup table from local file {ZIP_DICT_PATH}")
        with open(ZIP_DICT_PATH) as f:
            data = json.load(f)
    else:
        logger.info(f"Loading zip lookup table from GCS bucket {GCS_BUCKET}")
        gcs_client = storage.Client()
        blob = gcs_client.bucket(GCS_BUCKET).blob("zip_dict.json")
        data = json.loads(blob.download_as_text())
    logger.info(f"Loaded {len(data):,} zip codes")

    # Validate that the file contains the expected fields
    sample = next(iter(data.values()))
    missing = [f for f in ZIP_DICT_FIELDS if f not in sample]
    if missing:
        raise ValueError(f"zip_dict.json is missing expected fields: {missing}. "
                         f"Check that org_fields in the generator matches ZIP_DICT_FIELDS.")

    return data

# Loaded once at startup — not re-read on every request
ZIP_TO_ORG: dict = load_zip_dict()

# ─── Helpers ──────────────────────────────────────────────────────────────────

def to_zip5(raw_zip: str) -> int:
    """Convert raw zip string to a 5-digit integer, or 0 if invalid.

    Args:
        raw_zip: Raw zip string from the payload (e.g. ``"10001"`` or ``"10001-1234"``).

    Returns:
        Integer zip code, or 0 if the input is missing, non-numeric, or out of range.
    """
    first = str(raw_zip or "").split("-")[0].strip()
    try:
        num = int(first)
        return num if num <= 99999 else 0
    except ValueError:
        return 0

# ─── Action Network Payload Parsing ───────────────────────────────────────────

def parse_recipient(record: dict) -> dict:
    """Parse one Action Network webhook record into a flat recipient dict.

    All fields default to empty strings or None so email templates never crash.

    Args:
        record: One element from the Action Network webhook JSON array,
            containing an ``osdi:*`` key with person and signup data.

    Returns:
        Flat dict with keys: ``idempotency_key``, ``json_type``, ``person_id``,
        ``created_date``, ``modified_date``, ``recipient_first_name``,
        ``recipient_last_name``, ``recipient_email``, ``recipient_phone``,
        ``recipient_phone_type``, ``recipient_address``, ``recipient_city``,
        ``recipient_state``, ``recipient_zip_raw``, ``recipient_zip``,
        ``custom_fields``.
    """
    out: dict = {
        "idempotency_key":     record.get("idempotency_key"),
        "json_type":           None,
        "person_id":           None,
        "created_date":        None,
        "modified_date":       None,
        "recipient_first_name": "",
        "recipient_last_name":  "",
        "recipient_email":      "",
        "recipient_phone":      "",
        "recipient_phone_type": "",
        "recipient_address":    "",
        "recipient_city":       "",
        "recipient_state":      "",
        "recipient_zip_raw":    "",
        "recipient_zip":        0,
        "custom_fields":        [],
    }

    # Find the osdi:* key (e.g. osdi:attendance, osdi:submission)
    osdi_data = None
    for key, val in record.items():
        if key.startswith("osdi:"):
            osdi_data = val
            out["json_type"] = key.split(":")[1]
            break

    if out["json_type"] and out["json_type"] not in OSDI_TYPE_CONFIG:
        logger.warning(f"Unknown osdi type: {out['json_type']!r} — not in OSDI_TYPE_CONFIG. "
                       f"Add it to the registry if this type should be handled.")
    elif out["json_type"] and not OSDI_TYPE_CONFIG[out["json_type"]]["parsed"]:
        logger.info(f"osdi type {out['json_type']!r} is known but not yet verified (parsed=False)")

    if osdi_data is None:
        logger.warning("No osdi: key found in webhook record")
        return out

    # Person ID from _links
    try:
        href = osdi_data["_links"]["osdi:person"]["href"]
        out["person_id"] = href.split("/")[-1]
    except (KeyError, TypeError):
        pass

    # Dates
    for field in ("created_date", "modified_date"):
        raw = osdi_data.get(field)
        if raw:
            try:
                out[field] = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                pass

    person = osdi_data.get("person") or {}

    out["recipient_last_name"]  = (person.get("family_name") or "").title().strip()
    out["recipient_first_name"] = (person.get("given_name")  or "").title().strip()

    # Primary postal address
    addresses = person.get("postal_addresses") or []
    addr = next((a for a in addresses if a.get("primary")), addresses[0] if addresses else {})
    out["recipient_zip_raw"] = (addr.get("postal_code") or "").strip()
    out["recipient_state"]   = (addr.get("region")      or "").strip()
    out["recipient_city"]    = (addr.get("locality")    or "").strip()
    lines = addr.get("address_lines") or []
    out["recipient_address"] = ", ".join(l.strip() for l in lines if l.strip())

    # Primary email
    emails = person.get("email_addresses") or []
    primary_email = next((e for e in emails if e.get("primary")), emails[0] if emails else {})
    out["recipient_email"] = (primary_email.get("address") or "").strip()

    # Primary phone
    phones = person.get("phone_numbers") or []
    primary_phone = next((p for p in phones if p.get("primary")), phones[0] if phones else {})
    out["recipient_phone"]      = primary_phone.get("number", "")
    out["recipient_phone_type"] = primary_phone.get("number_type", "")

    # Custom fields
    custom = person.get("custom_fields") or {}
    out["custom_fields"] = [
        f"{k}: {'Yes' if v == '1' else v}"
        for k, v in custom.items()
    ]

    out["recipient_zip"] = to_zip5(out["recipient_zip_raw"])

    logger.debug(f"Parsed: {out['recipient_first_name']} {out['recipient_last_name']} "
                 f"<{out['recipient_email']}> zip={out['recipient_zip']}")
    return out


# ─── Organizer Lookup ─────────────────────────────────────────────────────────

def attach_organizer(recipient: dict) -> str:
    """Look up organizer info by zip and add fields to the recipient dict.

    Adds ``org_email``, ``org_name``, ``reg_key``, and ``cc_org`` to the
    recipient dict in place on success.

    Args:
        recipient: Flat recipient dict produced by ``parse_recipient()``.
            Must contain ``recipient_zip``.

    Returns:
        Empty string on success, or an error code string on failure
        (``'Z'`` = zip code not found in lookup table).
    """
    zip_code = recipient.get("recipient_zip", 0)

    # Dict keys are strings in the JSON file
    entry = ZIP_TO_ORG.get(str(zip_code))

    if entry is None:
        msg = (f"Zip {zip_code!r} (raw: {recipient.get('recipient_zip_raw')!r}) "
               f"not found for {recipient.get('recipient_first_name')} "
               f"{recipient.get('recipient_last_name')} <{recipient.get('recipient_email')}>")
        logger.warning(msg)
        if SEND_NOTIFICATION_EMAILS:
            _send_notification("Zip not found in lookup table", msg)
        return "Z"

    recipient["org_email"] = entry["email"]
    recipient["org_name"]  = entry["nickname"]
    recipient["reg_key"]   = entry["region_key"]
    recipient["cc_org"]    = entry["cc_org"]
    return ""


# ─── Email Building & Sending ─────────────────────────────────────────────────

def _build_welcome_email(r: dict) -> dict:
    """Build a SendGrid request body dict for a recipient's welcome email.

    Args:
        r: Recipient dict with organizer fields attached (output of
            ``attach_organizer()``). Must contain ``recipient_first_name``,
            ``recipient_email``, ``org_name``, ``org_email``, and ``cc_org``.

    Returns:
        SendGrid mail send request body dict ready to pass to
        ``sg.client.mail.send.post()``.
    """
    # Build info block as <br>-separated lines — skip any that are None
    custom_fields = r.get("custom_fields") or []
    name_item  = f"{r['recipient_first_name']} {r['recipient_last_name']}".strip()
    city_state = ", ".join(filter(None, [r.get("recipient_city"), r.get("recipient_state")]))
    city_item  = (f"{city_state}  {r['recipient_zip_raw']}".strip()
                  if city_state or r.get("recipient_zip_raw") else None)

    info_lines = [
        name_item if name_item else None,
        r.get("recipient_address"),
        city_item,
        f"Email: {r['recipient_email']}" if r.get("recipient_email") else None,
        f"Phone: {r['recipient_phone']} ({r['recipient_phone_type']})" if r.get("recipient_phone") else None,
    ]
    if custom_fields:
        info_lines += ["Extra information:"] + [f"&nbsp;&nbsp;&nbsp;&nbsp;- {cf}" for cf in custom_fields]
    info_block = "<br>".join(f"&nbsp;&nbsp;&nbsp;&nbsp;{item}" for item in info_lines if item)

    logo_tag = (f'<img src="{LOGO_URL}" alt="Center for Common Ground" '
                f'style="max-width:300px;display:block;margin-bottom:16px;">'
                if LOGO_URL else "")

    first = r["recipient_first_name"]
    name  = r["recipient_first_name"]
    body  = f"""<html><body style="font-family:Arial,sans-serif;font-size:12pt;color:#222;">
{logo_tag}
<p>Hi{' ' + first if first else ''}!</p>
<p>Thanks for your interest in Center for Common Ground's important work in nonpartisan voter outreach. Below you'll find information for your primary contact who can help you get started phone banking, postcarding, and texting voters of color in voter suppression states.</p>
<p>
  Organizer name: {r["org_name"]}<br>
  Organizer email: <a href="mailto:{r["org_email"]}">{r["org_email"]}</a>
</p>
<p>Here is the information we have on file for you. Please let us know if anything needs updating:</p>
<p>{info_block}</p>
<p>If you'd like to get more involved, please reach out to your organizer — they'd be happy to help! For issues that can't be addressed locally, contact <a href="mailto:rovgeneral@gmail.com">rovgeneral@gmail.com</a>.</p>
<p>Thousands of like-minded volunteers nationwide have taken action since 2018 to defend voting rights for all Americans. Together, we can make democracy work.</p>
<p>Sincerely,<br>The Center For Common Ground Team</p>
</body></html>"""

    subject = (f"{name} — " if name else "") + "Welcome to Center for Common Ground!"

    email_data = {
        "content": [{"type": "text/html", "value": body}],
        "from":    {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{
            "subject": subject,
            "to": [{"email": r["recipient_email"], "name": r["recipient_first_name"]}],
        }],
    }

    _add_copy_emails(email_data["personalizations"][0], "cc",  ALWAYS_CC_LIST)
    _add_copy_emails(email_data["personalizations"][0], "bcc", ALWAYS_BCC_LIST)

    cc_org = r.get("cc_org", "")
    if cc_org in ("cc", "bcc"):
        _add_copy_emails(email_data["personalizations"][0], cc_org,
                         [(r["org_email"], r["org_name"])])

    return email_data


def _add_copy_emails(personalization: dict, copy_type: str, pairs: list):
    """Append (email, name) pairs as cc or bcc to a SendGrid personalization.

    Args:
        personalization: A SendGrid personalization dict (modified in place).
        copy_type: Either ``'cc'`` or ``'bcc'``.
        pairs: List of ``(email, name)`` tuples to add.
    """
    if not pairs:
        return
    entries = [{"email": email, "name": name} for email, name in pairs]
    if copy_type in personalization:
        personalization[copy_type].extend(entries)
    else:
        personalization[copy_type] = entries


def _send_welcome_email(recipient: dict) -> tuple:
    """Send the welcome email via SendGrid.

    Skips sending if the recipient is not in ``ALLOWED_RECIPIENT_EMAILS``
    (when that list is non-empty).

    Args:
        recipient: Recipient dict with organizer fields attached.

    Returns:
        Tuple of ``(message, http_status_code)`` where message is a
        human-readable result string and status code is the SendGrid response
        code (typically 202 on success).
    """
    to_email = recipient.get("recipient_email", "")

    if ALLOWED_RECIPIENT_EMAILS and to_email not in ALLOWED_RECIPIENT_EMAILS:
        logger.info(f"Would have sent (not in ALLOWED_RECIPIENT_EMAILS): {to_email}")
        return "Would have sent — not in allow-list", 200

    api_key    = get_secret("SENDGRID_API_KEY")
    sg         = SendGridAPIClient(api_key=api_key)
    email_data = _build_welcome_email(recipient)

    if LOG_EMAILS:
        p = email_data["personalizations"][0]
        body = email_data['content'][0]['value'].replace('\n', '\\n')
        logger.info(
            f"[EMAIL DETAIL LOG] Outgoing welcome email (contains personal info — "
            f"disable LOG_EMAILS when stable): "
            f"To={p.get('to')} CC={p.get('cc', [])} BCC={p.get('bcc', [])} "
            f"Subject={p.get('subject')!r} Body={body!r}"
        )

    logger.info(f"Sending welcome email → {to_email}")
    response = sg.client.mail.send.post(request_body=email_data)
    status   = response.status_code
    logger.info(f"SendGrid status: {status}")
    return f"Email sent to {to_email}", status


def _send_notification(subject: str, message: str):
    """Send an admin notification email (errors, warnings, etc.).

    Sends to ``NOTIFICATION_EMAIL_LIST``. Failures are logged but not raised.

    Args:
        subject: Short subject line (will be prefixed with ``[CFCG Webhook]``).
        message: Plain-text body of the notification.
    """
    try:
        api_key = get_secret("SENDGRID_API_KEY")
        sg      = SendGridAPIClient(api_key=api_key)
        data    = {
            "content": [{"type": "text/plain", "value": message}],
            "from":    {"email": FROM_EMAIL, "name": FROM_NAME},
            "personalizations": [{
                "subject": f"[CFCG Webhook] {subject}",
                "to": NOTIFICATION_EMAIL_LIST,
            }],
        }
        sg.client.mail.send.post(request_body=data)
    except Exception as exc:
        logger.error(f"Failed to send notification email: {exc}")


# ─── Action Network: Helpers ──────────────────────────────────────────────────

def _find_person_in_an(email: str) -> bool:
    """Return True if a person with this email already exists in Action Network."""
    import requests as req
    api_key = get_secret("AN_WEBHOOK_KEY")
    url     = "https://actionnetwork.org/api/v2/people"
    headers = {"OSDI-API-Token": api_key}
    params  = {"filter": f"email_address eq '{email}'"}
    try:
        r = req.get(url, headers=headers, params=params, timeout=5)
        r.raise_for_status()
        data = r.json()
        logger.debug(f"AN people lookup response for {email!r}: {data}")
        return len(data.get("_embedded", {}).get("osdi:people", [])) > 0
    except Exception as exc:
        logger.warning(f"AN person lookup failed for {email!r}: {exc}")
        return False


# ─── Action Network: Update group_key ────────────────────────────────────────

def update_group_key(group_key: str, person_id: str):
    """Write the region group_key back to the Action Network person record.

    Retries up to 3 times with exponential backoff. Logs an error and sends
    a notification email if all attempts fail. Only runs when
    ``UPDATE_GROUP_KEY`` is ``True``.

    Args:
        group_key: Region key string to write (e.g. ``'SE'``).
        person_id: Action Network person UUID.
    """
    import requests as req

    api_key = get_secret("AN_WEBHOOK_KEY")
    url     = f"https://actionnetwork.org/api/v2/people/{person_id}"
    headers = {"OSDI-API-Token": api_key}
    payload = {"custom_fields": {"group_key": group_key}}

    for attempt in range(3):
        time.sleep((10 ** attempt - 1) / 1000)   # 0 ms, 9 ms, 99 ms
        r = req.put(url, headers=headers, json=payload, timeout=5)
        if r.ok:
            logger.info(f"Updated group_key={group_key!r} for person {person_id}")
            return
        logger.warning(f"Attempt {attempt + 1}/3 failed: {r.status_code} {r.reason}")

    msg = f"Could not update group_key for person {person_id} after 3 attempts"
    logger.error(msg)
    if SEND_NOTIFICATION_EMAILS:
        _send_notification("group_key update failed", msg)


# ─── Recipient Processing ─────────────────────────────────────────────────────

def process_recipient(recipient: dict) -> tuple:
    """Run the full pipeline for one recipient.

    Steps:
        1. Look up organizer by zip (``attach_organizer``).
        2. Send welcome email (``_send_welcome_email``).
        3. Optionally update group_key in Action Network (``update_group_key``),
           controlled by the ``UPDATE_GROUP_KEY`` flag.

    Args:
        recipient: Flat recipient dict produced by ``parse_recipient()``.

    Returns:
        Tuple of ``(message, http_status_code)``.
    """
    error = attach_organizer(recipient)
    if error:
        logger.warning(f"Skipping {recipient.get('person_id')}: error={error!r}")
        return f"Skipped (error: {error})", 400

    if not recipient.get("recipient_email"):
        logger.warning(f"No email address for person {recipient.get('person_id')} — skipping")
        return "Skipped (no email address)", 400

    if CHECK_ALREADY_EMAILED:
        if _find_person_in_an(recipient["recipient_email"]):
            logger.info(f"Email {recipient['recipient_email']!r} already exists in Action Network system")
            if not SEND_TO_EXISTING_EMAILS:
                return "Skipped (email already in AN system)", 200
            logger.info("SEND_TO_EXISTING_EMAILS=true — sending email anyway")

    json_type = recipient.get("json_type")
    type_config = OSDI_TYPE_CONFIG.get(json_type, {})

    if json_type and json_type not in OSDI_TYPE_CONFIG:
        msg = (f"Unknown osdi type {json_type!r} received for person "
               f"{recipient.get('person_id')} <{recipient.get('recipient_email')}>. "
               f"This type is not in OSDI_TYPE_CONFIG — no email was sent. "
               f"Add it to the registry in main.py if it should be handled.")
        logger.warning(msg)
        if SEND_NOTIFICATION_EMAILS:
            _send_notification(f"Unknown osdi type received: {json_type!r}", msg)
        return f"Skipped (unknown type {json_type!r})", 200

    if not type_config.get("send_email", False):
        logger.info(f"osdi type {json_type!r} is configured send_email=False — skipping")
        return f"Skipped (send_email=False for type {json_type!r})", 200

    if not SEND_RECIPIENT_EMAILS:
        logger.info(f"Email disabled; skipping {recipient.get('recipient_email')}")
        return "Email sending disabled", 200

    msg, status = _send_welcome_email(recipient)

    if UPDATE_GROUP_KEY and status in (200, 202) and recipient.get("reg_key") and recipient.get("person_id"):
        try:
            update_group_key(recipient["reg_key"], recipient["person_id"])
        except Exception as exc:
            logger.error(f"group_key update failed (non-fatal): {exc}")

    return msg, status


# ─── Flask App ────────────────────────────────────────────────────────────────

app = Flask(__name__)


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Main endpoint. Action Network POSTs a JSON array of signup records here.
    Configure your Action Network webhook to point to:
        https://<your-cloud-run-url>/webhook
    """
    payload = request.get_json(silent=False)

    if not isinstance(payload, list):
        logger.warning(f"Rejected: payload is {type(payload).__name__}, expected list")
        return {"error": "Expected a JSON array"}, 400

    if not payload or payload[0].get("action_network:sponsor") is None:
        logger.warning("Rejected: missing action_network:sponsor")
        return {"error": "Invalid Action Network payload"}, 400

    if LOG_PAYLOADS:
        logger.info(f"[***** PAYLOAD DETAIL LOG] Raw webhook payload (contains personal info — "
                    f"disable LOG_PAYLOADS when stable): {json.dumps(payload)}")

    results = []
    for record in payload:
        recipient = parse_recipient(record)
        msg, status = process_recipient(recipient)
        results.append({
            "person_id": recipient.get("person_id"),
            "email":     recipient.get("recipient_email"),
            "result":    msg,
            "status":    status,
        })
        logger.info(f"Processed {recipient.get('person_id')}: {msg} ({status})")

    return {"processed": len(results), "results": results}, 200


@app.route("/health", methods=["GET"])
def health():
    """Health check — Cloud Run hits this to confirm the service is up."""
    return {"status": "ok", "zip_codes_loaded": len(ZIP_TO_ORG)}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting local dev server on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
