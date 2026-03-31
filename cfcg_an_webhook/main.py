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
import pathlib
import threading
import time
from datetime import datetime, timezone

from flask import Flask, request
from loguru import logger
from sendgrid import SendGridAPIClient
import google.auth
from google.cloud import secretmanager, storage
from googleapiclient.discovery import build as _build_gapi_service

from config import (
    ZIP_DICT_PATH, CLOUD_PROJECT_ID, GCS_BUCKET,
    FROM_EMAIL, FROM_NAME, LOGO_URL,
    SEND_RECIPIENT_EMAILS, SEND_NOTIFICATION_EMAILS,
    TEST_MODE, TEST_RECIPIENT_EMAILS,
    ADMIN_ALERT_EMAILS, PAYLOAD_OBSERVER_EMAILS, EXCLUDED_PAYLOAD_OSDI,
    ALWAYS_CC_LIST, ALWAYS_BCC_LIST,
    CHECK_IDEMPOTENCY, CHECK_ALREADY_EMAILED, CHECK_SHEET_FOR_EMAIL,
    SEND_TO_EXISTING_EMAILS, UPDATE_GROUP_KEY,
    LOG_PAYLOADS, LOG_EMAILS,
    APPEND_TO_SHEET, GOOGLE_SHEET_ID, SHEET_TAB, TEST_SHEET_ID, TEST_SHEET_TAB,
    REMOVE_MULTI_IDENTIFIERS, TRANSACTION_WINDOW_SECONDS,
    ZIP_DICT_FIELDS, OSDI_TYPE_CONFIG, _STATE_ABBREV,
    PORT,
)

# ─── Runtime state ────────────────────────────────────────────────────────────

_processed_keys: set = set()   # in-memory idempotency store; no cleanup needed — the set is tiny for
                               # low-traffic use, and clears automatically when Cloud Run scales to zero
                               # (after ~15 min of inactivity) or on every redeploy.

_transaction_buffer: dict = {}  # txn_id -> {"recipients": [parsed_dict, ...], "first_seen": float}
_buffer_lock = threading.Lock()

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
        logger.info(f"Loading zip lookup table ZIP_TO_ORG from local file {ZIP_DICT_PATH}")
        with open(ZIP_DICT_PATH) as f:
            data = json.load(f)
    else:
        logger.info(f"Loading zip lookup table ZIP_TO_ORG from GCS bucket {GCS_BUCKET}")
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

# ─── Transaction Grouping ─────────────────────────────────────────────────────

def _get_transaction_id(record: dict) -> str | None:
    """Extract the Action Network transaction UUID from a raw webhook record.

    Looks inside the osdi:* object for an identifier like
    ``"action_network:32b6df18-..."``. Returns only the UUID portion.

    Args:
        record: One raw record from the Action Network webhook JSON array.

    Returns:
        Transaction UUID string, or None if no action_network identifier found.
    """
    for key, val in record.items():
        if key.startswith("osdi:") and isinstance(val, dict):
            for ident in (val.get("identifiers") or []):
                if ident.startswith("action_network:"):
                    return ident.split(":", 1)[1]
    return None


def _merge_recipients(recipients: list, transaction_id: str) -> dict:
    """Merge multiple parsed recipient dicts from one transaction into one combined dict.

    Args:
        recipients: List of parsed recipient dicts (output of ``parse_recipient()``).
        transaction_id: Shared transaction UUID used as the merged idempotency key.

    Returns:
        Single merged recipient dict.
    """
    merged = dict(recipients[0])

    person_fields = [
        "recipient_first_name", "recipient_last_name", "recipient_email",
        "recipient_phone", "recipient_phone_type", "recipient_address",
        "recipient_city", "recipient_state", "recipient_state_abbrev",
        "recipient_zip_raw", "recipient_zip", "recipient_organization",
        "person_id", "created_date", "modified_date",
    ]
    for r in recipients[1:]:
        for field in person_fields:
            if not merged.get(field) and r.get(field):
                merged[field] = r[field]

    all_tags = []
    for r in recipients:
        for tag in (r.get("recipient_tags") or "").split(", "):
            if tag and tag not in all_tags:
                all_tags.append(tag)
    merged["recipient_tags"] = ", ".join(all_tags)

    merged_cf_dict = {}
    for r in recipients:
        merged_cf_dict.update(r.get("custom_fields_dict") or {})
    merged["custom_fields_dict"] = merged_cf_dict
    merged["custom_fields"] = [
        f"{k}: {'Yes' if v == '1' else v}"
        for k, v in merged_cf_dict.items()
    ]

    dates = [r["created_date"] for r in recipients if r.get("created_date")]
    if dates:
        merged["created_date"] = min(dates)

    for r in recipients:
        jt = r.get("json_type")
        if jt and OSDI_TYPE_CONFIG.get(jt, {}).get("send_email", False):
            merged["json_type"] = jt
            break

    merged["idempotency_key"] = transaction_id

    types_combined = [r.get("json_type") for r in recipients]
    logger.info(
        f"[TRANSACTION] Combined {len(recipients)} payloads into one record "
        f"for {merged.get('recipient_email')!r} — "
        f"types combined: {types_combined} → processing as type={merged.get('json_type')!r} "
        f"(transaction {transaction_id!r})"
    )
    return merged


def _drain_expired_buffer():
    """Process and remove all expired transaction buffer entries.

    Called by the background drain thread and at the start of each webhook request.
    For each expired group: if any type has send_email=True, merge into one record
    and process; otherwise process each record individually.
    """
    now = time.time()
    with _buffer_lock:
        expired_ids = [
            tid for tid, entry in _transaction_buffer.items()
            if now - entry["first_seen"] >= TRANSACTION_WINDOW_SECONDS
        ]
        groups = {tid: _transaction_buffer.pop(tid) for tid in expired_ids}

    for tid, entry in groups.items():
        recipients = entry["recipients"]
        any_sends_email = any(
            OSDI_TYPE_CONFIG.get(r.get("json_type"), {}).get("send_email", False)
            for r in recipients
        )
        if len(recipients) > 1:
            types = [r.get("json_type") for r in recipients]
            if any_sends_email:
                logger.info(
                    f"[TRANSACTION] Processing grouped transaction {tid!r}: "
                    f"{len(recipients)} payloads ({types}) → merging into one record "
                    f"(email will be sent)"
                )
                to_process = [_merge_recipients(recipients, tid)]
            else:
                logger.info(
                    f"[TRANSACTION] Processing grouped transaction {tid!r}: "
                    f"{len(recipients)} payloads ({types}) — no type sends email, "
                    f"processing each individually"
                )
                to_process = recipients
        else:
            logger.info(
                f"[TRANSACTION] Processing single-record transaction {tid!r}: "
                f"type={recipients[0].get('json_type')!r} — no companion arrived within window"
            )
            to_process = recipients

        for recipient in to_process:
            # Idempotency already marked at arrival time — no re-check needed here
            msg, status = process_recipient(recipient)
            logger.info(f"[BUFFER] Processed {recipient.get('person_id')}: {msg} ({status})")


def _start_buffer_drain_thread():
    """Start a daemon thread that drains expired transaction buffer entries periodically."""
    def _loop():
        while True:
            time.sleep(TRANSACTION_WINDOW_SECONDS)
            try:
                _drain_expired_buffer()
            except Exception as exc:
                logger.error(f"Buffer drain thread error: {exc}")

    threading.Thread(target=_loop, daemon=True, name="buffer-drain").start()
    logger.info(f"Buffer drain thread started (window={TRANSACTION_WINDOW_SECONDS}s)")


if REMOVE_MULTI_IDENTIFIERS:
    _start_buffer_drain_thread()


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
        "custom_fields_dict":   {},
        "recipient_tags":         "",
        "recipient_state_abbrev": "",
        "recipient_organization": "",
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
        logger.info(f"osdi type {out['json_type']!r} is not coded (parsed=False)")

    if osdi_data is None:
        logger.warning("Bad osdi data: No 'osdi:' string found in payload")
        return out

    # NOTE: All OSDI types are parsed in the same way since only common elements person and custom fields are
    # common.  Type specific fields would require additional, specific programming.

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

    out["recipient_last_name"]      = (person.get("family_name") or "").title().strip()
    out["recipient_first_name"]     = (person.get("given_name")  or "").title().strip()
    out["recipient_organization"]   = (person.get("employer")    or "").strip()

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

    # Custom fields — keep raw dict for sheet mapping; build formatted list for welcome email
    custom = person.get("custom_fields") or {}
    out["custom_fields_dict"] = custom
    out["custom_fields"] = [
        f"{k}: {'Yes' if v == '1' else v}"
        for k, v in custom.items()
    ]

    # Tags (e.g. ["volunteer"]) — comma-joined string for the sheet
    out["recipient_tags"] = ", ".join(osdi_data.get("add_tags") or [])

    # State abbreviation (payload gives full name like "New York"; sheet wants "NY")
    out["recipient_state_abbrev"] = _STATE_ABBREV.get(out["recipient_state"], out["recipient_state"])

    out["recipient_zip"] = to_zip5(out["recipient_zip_raw"])

    logger.debug(f"Payload parsed: {out['recipient_first_name']} {out['recipient_last_name']} "
                 f"<{out['recipient_email']}> idempotency={out['idempotency_key']}  zip={out['recipient_zip']}")
    return out


# ─── Organizer Lookup ─────────────────────────────────────────────────────────

def lookup_organizer(recipient: dict) -> str:
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
               f"not found in zip_dict for {recipient.get('recipient_first_name')} "
               f"{recipient.get('recipient_last_name')} <{recipient.get('recipient_email')}>")
        logger.warning(msg)
        if SEND_NOTIFICATION_EMAILS:
            _send_notification(f"SEND_NOTIFICATION_EMAILS={SEND_NOTIFICATION_EMAILS} but zip not found in lookup "
                               f"table", msg)
        return "Zip not in zip_dict"

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
            ``lookup_organizer()``). Must contain ``recipient_first_name``,
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
        sub_items = "".join(f"<li>{cf}</li>" for cf in custom_fields)
        info_lines.append(f"Extra information:<ul>{sub_items}</ul>")

    items      = "".join(f"<li>{item}</li>" for item in info_lines if item)
    info_block = f"<ul>{items}</ul>"

    logo_tag = (f'<img src="{LOGO_URL}" alt="Center for Common Ground" '
                f'style="max-width:300px;display:block;margin-bottom:16px;">'
                if LOGO_URL else "")

    first = r["recipient_first_name"]
    name  = r["recipient_first_name"]
    body  = f"""<html><body style="font-family:Arial,sans-serif;font-size:12pt;color:#222;">
<div style="max-width:600px;margin:0 auto;">
{logo_tag}
<p>Hi{' ' + first if first else ''}!</p>
<p>Thanks for your interest in Center for Common Ground's important work in nonpartisan voter outreach. Below you'll 
find information for your primary contact who can help you get started postcarding, phone banking, and texting voters of color in voter suppression states.</p>
<div style="padding-left:20px;">
  <br>
  <span style="font-size:18px;">Organizer name: <strong>{r["org_name"]}</strong></span><br>
  <span style="font-size:18px;">Organizer email: <a href="mailto:{r["org_email"]}"><strong>{r["org_email"]}</strong></a></span>
  <br><br>
</div>
<p>Here is the information you entered. Please let us know if anything needs updating:</p>
{info_block}
<p>If you'd like to get more involved, please reach out to your organizer — they'd be happy to help! For issues that can't be addressed locally, contact <a href="mailto:rovgeneral@gmail.com">rovgeneral@gmail.com</a>.</p>
<p>Thousands of like-minded volunteers nationwide have taken action since 2018 to defend voting rights for all Americans. Together, we can make democracy work.</p>
<p>Sincerely,<br>The Center For Common Ground Team</p>
</div>
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

    In TEST_MODE, redirects the email to ``TEST_RECIPIENT_EMAILS`` instead of
    the real volunteer and prepends ``[TEST]`` to the subject line.

    Args:
        recipient: Recipient dict with organizer fields attached.

    Returns:
        Tuple of ``(message, http_status_code)`` where message is a
        human-readable result string and status code is the SendGrid response
        code (typically 202 on success).
    """
    to_email = recipient.get("recipient_email", "")

    if TEST_MODE:
        logger.info(f"TEST MODE: would have sent welcome email to {to_email!r} — redirecting to test recipients")

    api_key    = get_secret("SENDGRID_API_KEY")
    sg         = SendGridAPIClient(api_key=api_key)
    email_data = _build_welcome_email(recipient)

    if TEST_MODE:
        email_data["personalizations"][0]["to"] = [{"email": e} for e in TEST_RECIPIENT_EMAILS]
        email_data["personalizations"][0]["subject"] = "[TEST] " + email_data["personalizations"][0]["subject"]

    if LOG_EMAILS:
        p = email_data["personalizations"][0]
        body = email_data['content'][0]['value'].replace('\n', '\\n')
        logger.info(
            f"[EMAIL DETAIL LOG] Outgoing welcome email (contains personal info — "
            f"disable LOG_EMAILS when stable): "
            f"To={p.get('to')} CC={p.get('cc', [])} BCC={p.get('bcc', [])} "
            f"Subject={p.get('subject')!r} Body={body!r}"
        )

    logger.info(f"Sendgrid sending welcome email to {to_email}")
    response = sg.client.mail.send.post(request_body=email_data)
    status   = response.status_code
    logger.info(f"SendGrid status of send: {status}")
    return f"Email sent to {to_email}", status


def _send_notification(subject: str, message: str):
    """Send an admin notification email (errors, warnings, etc.).

    Sends to ``ADMIN_ALERT_EMAILS``. Failures are logged but not raised.

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
                "to": ADMIN_ALERT_EMAILS,
            }],
        }
        sg.client.mail.send.post(request_body=data)
    except Exception as exc:
        logger.error(f"*Exception - Failed to send notification email: {exc}")


def _send_payload_notification(payload, emails: list, types: list):
    """Send prettified payload JSON to PAYLOAD_OBSERVER_EMAILS on every webhook arrival."""
    if not PAYLOAD_OBSERVER_EMAILS:
        return
    if EXCLUDED_PAYLOAD_OSDI and types and all(t in EXCLUDED_PAYLOAD_OSDI for t in types):
        logger.debug(f"Payload notification suppressed — all types {types} are in EXCLUDED_PAYLOAD_OSDI")
        return
    try:
        api_key = get_secret("SENDGRID_API_KEY")
        sg = SendGridAPIClient(api_key=api_key)
        received_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        pretty_json = json.dumps(payload, indent=2)
        body = f"<p>Received: {received_at}</p><pre>{pretty_json}</pre>"
        email_label = ", ".join(emails) if emails else "unknown"
        type_label  = ", ".join(types)  if types  else "unknown"
        data = {
            "content": [{"type": "text/html", "value": body}],
            "from": {"email": FROM_EMAIL, "name": FROM_NAME},
            "personalizations": [{"to": PAYLOAD_OBSERVER_EMAILS}],
            "subject": f"Webhook - new payload — {email_label} ({type_label})",
        }
        sg.client.mail.send.post(request_body=data)
    except Exception as exc:
        logger.error(f"* Exception-Failed to send payload notification email: {exc}")


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
        logger.debug(f"GET AN people lookup response for {email!r}: {data}")
        return len(data.get("_embedded", {}).get("osdi:people", [])) > 0
    except Exception as exc:
        logger.warning(f"*Exception-AN person lookup failed for {email!r}: {exc}")
        return False


def _find_email_in_sheet(email: str) -> bool:
    """Return True if this email already appears in column C of the signup sheet."""
    if not GOOGLE_SHEET_ID:
        return False
    try:
        svc = _get_sheet_service()
        result = (svc.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f"{SHEET_TAB}!C:C",          # column C = email (see _append_to_sheet row order)
        ).execute())
        values = result.get("values", [])       # list of 1-element lists: [["email@x.com"], ...]
        flat   = {row[0].strip().lower() for row in values if row}
        return email.strip().lower() in flat
    except Exception as exc:
        logger.warning(f"*Exception-Sheet email lookup failed for {email!r}: {exc}")
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


# ─── Google Sheet Append ──────────────────────────────────────────────────────

def _get_sheet_service():
    """Build an authenticated Google Sheets API service using Application Default Credentials.

    Works locally (via `gcloud auth application-default login`) and in Cloud Run
    (via the attached service account). The service account must have Editor access
    on the target Google Sheet.
    """
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return _build_gapi_service("sheets", "v4", credentials=creds)


def _append_to_sheet(recipient: dict):
    """Append one signup row to the appropriate Google Sheet.

    Uses TEST_SHEET_ID/TEST_SHEET_TAB when TEST_MODE=true, otherwise
    GOOGLE_SHEET_ID/SHEET_TAB.

    Column order matches the AN report export:
    first_name | last_name | email | zip_code | can2_user_city | can2_county |
    can2_state_abbreviated | Volunteer_Postcard to voters |
    Volunteer_Text to voters | Volunteer_Phonebank to voters |
    can2_user_tags | can2_subscription_date | Organization

    Does nothing if APPEND_TO_SHEET=false or the relevant sheet ID is empty.
    """
    sheet_id = TEST_SHEET_ID if TEST_MODE else GOOGLE_SHEET_ID
    tab      = TEST_SHEET_TAB if TEST_MODE else SHEET_TAB
    if not APPEND_TO_SHEET or not sheet_id:
        return
    try:
        cf = recipient.get("custom_fields_dict") or {}
        created = recipient.get("created_date")
        row = [
            recipient.get("recipient_first_name", ""),
            recipient.get("recipient_last_name", ""),
            recipient.get("recipient_email", ""),
            str(recipient.get("recipient_zip", "")),
            recipient.get("recipient_city", ""),
            "",                                              # can2_county — not in payload
            recipient.get("recipient_state_abbrev", ""),
            cf.get("Volunteer_Postcard to voters", ""),
            cf.get("Volunteer_Text to voters", ""),
            cf.get("Volunteer_Phonebank to voters", ""),
            recipient.get("recipient_tags", ""),
            created.strftime("%Y-%m-%d %H:%M:%S") if created else "",
            recipient.get("recipient_organization", ""),
        ]
        headers = ["first_name", "last_name", "email", "zip_code", "city", "county",
                   "state", "Volunteer_Postcard", "Volunteer_Text", "Volunteer_Phonebank",
                   "tags", "date", "Organization"]
        logger.info(f"[SHEET ROW] {dict(zip(headers, row))}")
        svc = _get_sheet_service()
        (svc.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=tab,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute())
        logger.info(f"Appended sheet row for {recipient.get('recipient_email')}")
    except Exception as exc:
        logger.error(f"Failed to append to Google Sheet: {exc}")


# ─── Recipient Processing ─────────────────────────────────────────────────────

def process_recipient(recipient: dict) -> tuple:
    """Run the full pipeline for one recipient.

    Steps:
        1.  Look up organizer by zip (``lookup_organizer``).
        2.  Validate email address.
        3.  Skip if already in Action Network (``CHECK_ALREADY_EMAILED``).
        4.  Skip if already in Google Sheet (``CHECK_SHEET_FOR_EMAIL``).
        5.  Skip if osdi type is unknown or has send_email=False.
        6.  Skip if ``SEND_RECIPIENT_EMAILS=false``.
        7.  Append row to Google Sheet (``_append_to_sheet``).
        8.  Send welcome email (``_send_welcome_email``); in TEST_MODE, email
            is redirected to ``TEST_RECIPIENT_EMAILS`` instead of the volunteer.
        9.  Optionally update group_key in Action Network (``update_group_key``),
            controlled by the ``UPDATE_GROUP_KEY`` flag.

    Args:
        recipient: Flat recipient dict produced by ``parse_recipient()``.

    Returns:
        Tuple of ``(message, http_status_code)``.
    """
    error = lookup_organizer(recipient)
    if error:
        logger.warning(f"Could not find Org info {recipient.get('person_id')}: error={error!r}")
        return f"Skipped (error: {error})", 400

    if not recipient.get("recipient_email"):
        logger.warning(f"No email address for person {recipient.get('person_id')} — skipping")
        return "Skipped (no email address)", 400

    if CHECK_ALREADY_EMAILED:
        if _find_person_in_an(recipient["recipient_email"]):
            logger.info(f"Email {recipient['recipient_email']!r} already in Action Network system")
            if not SEND_TO_EXISTING_EMAILS:
                return "Flag set to skip existing; {recipient['recipient_email']!r} already in Action Network system", 200
            logger.info("Flag set to email existing AN so sending to {recipient['recipient_email']!r} Network system")

    if CHECK_SHEET_FOR_EMAIL:
        if _find_email_in_sheet(recipient["recipient_email"]):
            logger.info(f"Email {recipient['recipient_email']!r} already in Google Sheet — skipping")
            return f"Already in sheet; skipping {recipient['recipient_email']!r}", 200

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
        logger.info(f"osdi type {json_type!r} send_email=False, is configured but skipping")
        return f"Skipped (send_email=False for type {json_type!r})", 200

    if not SEND_RECIPIENT_EMAILS:
        logger.info(f"SEND_RECIPIENT_EMAILS: {SEND_RECIPIENT_EMAILS}; skipping {recipient.get('recipient_email')}")
        return "Email sending disabled", 200

    _append_to_sheet(recipient)

    msg, status = _send_welcome_email(recipient)

    if UPDATE_GROUP_KEY and status in (200, 202) and recipient.get("reg_key") and recipient.get("person_id"):
        try:
            update_group_key(recipient["reg_key"], recipient["person_id"])
        except Exception as exc:
            logger.error(f"* Exception-group_key update failed (non-fatal): {exc}")

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
        logger.warning(f"Payload rejected: type- {type(payload).__name__}, expected list")
        return {"error": "Expected a JSON array"}, 400

    if not payload or payload[0].get("action_network:sponsor") is None:
        logger.warning("Payload rejected: missing action_network:sponsor")
        return {"error": "Invalid Action Network payload"}, 400

    # Parse all records up front so email is available for logging and notification
    parsed_records = [parse_recipient(r) for r in payload]
    emails = [r.get("recipient_email", "") for r in parsed_records if r.get("recipient_email")]
    types  = [r.get("json_type", "") for r in parsed_records if r.get("json_type")]

    _send_payload_notification(payload, emails, types)

    if LOG_PAYLOADS:
        logger.warning(f"[***** PAYLOAD DETAIL LOG] {emails} "
                       f"(contains personal info — disable LOG_PAYLOADS when stable): "
                       f"{json.dumps(payload)}")

    results = []

    # Drain any expired buffer entries before processing the new payload
    if REMOVE_MULTI_IDENTIFIERS:
        _drain_expired_buffer()

    for record, recipient in zip(payload, parsed_records):
        if REMOVE_MULTI_IDENTIFIERS:
            tid = _get_transaction_id(record)
            if tid is not None:
                # recipient already parsed above — use it directly

                # 1. Check duplicate FIRST — before buffering
                if CHECK_IDEMPOTENCY:
                    ikey = recipient.get("idempotency_key")
                    if ikey and ikey in _processed_keys:
                        logger.warning(f"** Duplicate payload — idempotency_key {ikey!r} for"
                                       f" {recipient.get('recipient_email')} already in buffer or processed, skipping")
                        results.append({
                            "person_id": recipient.get("person_id"),
                            "email":     recipient.get("recipient_email"),
                            "result":    "Duplicate (skipped)",
                            "status":    200,
                        })
                        continue
                    # 2. Mark processed BEFORE returning 200 — blocks AN retries from re-buffering
                    if ikey:
                        _processed_keys.add(ikey)

                # 3. Buffer the record
                with _buffer_lock:
                    if tid not in _transaction_buffer:
                        _transaction_buffer[tid] = {"recipients": [recipient],
                                                    "first_seen": time.time()}
                        logger.info(f"Buffered new transaction {tid!r} for "
                                    f"{recipient.get('recipient_email')}")
                    else:
                        _transaction_buffer[tid]["recipients"].append(recipient)
                        logger.info(f"Added to existing transaction buffer {tid!r} "
                                    f"(now {len(_transaction_buffer[tid]['recipients'])} records)")

                # 4. Return 200 immediately — heavy work happens in drain thread
                results.append({
                    "person_id": recipient.get("person_id"),
                    "email":     recipient.get("recipient_email"),
                    "result":    "Buffered (transaction window)",
                    "status":    200,
                })
                continue   # drain thread handles processing after window expires

        # Non-buffered path (no identifier, or REMOVE_MULTI_IDENTIFIERS=False)
        # recipient already parsed above — use it directly
        if CHECK_IDEMPOTENCY:
            ikey = recipient.get("idempotency_key")
            if ikey and ikey in _processed_keys:
                logger.warning(f"** Duplicate payload — idempotency_key {ikey!r} for"
                               f" {recipient.get('recipient_email')} already processed, skipping")
                results.append({
                    "person_id": recipient.get("person_id"),
                    "email":     recipient.get("recipient_email"),
                    "result":    "Duplicate (skipped)",
                    "status":    200,
                })
                continue
            if ikey:
                _processed_keys.add(ikey)

        msg, status = process_recipient(recipient)
        results.append({
            "person_id": recipient.get("person_id"),
            "email":     recipient.get("recipient_email"),
            "result":    msg,
            "status":    status,
        })
        logger.info(f"Payload processed {recipient.get('person_id')}: {msg} ({status})")

    return {"processed": len(results), "results": results}, 200


@app.route("/health", methods=["GET"])
def health():
    """Health check — Cloud Run hits this to confirm the service is up."""
    return {"status": "ok", "zip_codes_loaded": len(ZIP_TO_ORG)}, 200


@app.route("/settings", methods=["GET"])
def settings_status():
    """Diagnostic — echo all env-var-driven configuration in one log line."""
    cfg = {
        "CLOUD_PROJECT_ID":           CLOUD_PROJECT_ID,
        "GCS_BUCKET":                 GCS_BUCKET,
        "FROM_EMAIL":                 FROM_EMAIL,
        "FROM_NAME":                  FROM_NAME,
        "SEND_RECIPIENT_EMAILS":      SEND_RECIPIENT_EMAILS,
        "SEND_NOTIFICATION_EMAILS":   SEND_NOTIFICATION_EMAILS,
        "TEST_MODE":                  TEST_MODE,
        "TEST_RECIPIENT_EMAILS":      TEST_RECIPIENT_EMAILS,
        "ADMIN_ALERT_EMAILS":         [e["email"] for e in ADMIN_ALERT_EMAILS],
        "PAYLOAD_OBSERVER_EMAILS":    [e["email"] for e in PAYLOAD_OBSERVER_EMAILS],
        "EXCLUDED_PAYLOAD_OSDI":      sorted(EXCLUDED_PAYLOAD_OSDI),
        "ALWAYS_CC_LIST":             [e for e, _ in ALWAYS_CC_LIST],
        "ALWAYS_BCC_LIST":            [e for e, _ in ALWAYS_BCC_LIST],
        "CHECK_IDEMPOTENCY":          CHECK_IDEMPOTENCY,
        "CHECK_ALREADY_EMAILED":      CHECK_ALREADY_EMAILED,
        "SEND_TO_EXISTING_EMAILS":    SEND_TO_EXISTING_EMAILS,
        "UPDATE_GROUP_KEY":           UPDATE_GROUP_KEY,
        "LOG_PAYLOADS":               LOG_PAYLOADS,
        "LOG_EMAILS":                 LOG_EMAILS,
        "APPEND_TO_SHEET":            APPEND_TO_SHEET,
        "GOOGLE_SHEET_ID":            GOOGLE_SHEET_ID,
        "TEST_SHEET_ID":              TEST_SHEET_ID,
        "TEST_SHEET_TAB":             TEST_SHEET_TAB,
        "REMOVE_MULTI_IDENTIFIERS":   REMOVE_MULTI_IDENTIFIERS,
        "TRANSACTION_WINDOW_SECONDS": TRANSACTION_WINDOW_SECONDS,
    }
    summary = f"[SETTINGS] {json.dumps(cfg)}"
    logger.info(summary)
    return summary, 200


@app.route("/idempotency", methods=["GET"])
def idempotency_status():
    """Diagnostic — show processed idempotency keys in one log line."""
    keys = sorted(_processed_keys)
    summary = f"[IDEMPOTENCY] {len(keys)} key(s): {json.dumps(keys)}"
    logger.info(summary)
    return summary, 200


@app.route("/buffer", methods=["GET"])
def buffer_status():
    """Diagnostic — show current transaction buffer contents in one log line."""
    with _buffer_lock:
        snapshot = {
            tid: {"emails": [r.get("recipient_email") for r in entry["recipients"]],
                  "age_s": round(time.time() - entry["first_seen"])}
            for tid, entry in _transaction_buffer.items()
        }
    summary = f"[BUFFER] {len(snapshot)} transaction(s): {json.dumps(snapshot)}"
    logger.info(summary)
    return summary, 200


if __name__ == "__main__":
    port = PORT
    logger.info(f"Starting local dev server on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
