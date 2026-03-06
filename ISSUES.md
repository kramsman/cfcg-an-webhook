# Issues — cfcg-an-webhook

## Action Network API Documentation

Reference pages for each osdi: event type handled by this service.
Use these when implementing Pydantic models, debugging payload parsing, or
replacing synthetic payload files in `tests/payloads/` with real captured data.

### Webhook payload structures (what AN actually POSTs to /webhook)
These are the most useful pages — they show the exact JSON this service receives.

| osdi: type    | Webhook payload docs                                          |
|---------------|---------------------------------------------------------------|
| `attendance`  | https://actionnetwork.org/docs/webhooks/attendance            |
| `submission`  | https://actionnetwork.org/docs/webhooks/submission            |
| `signature`   | https://actionnetwork.org/docs/webhooks/signature             |
| `donation`    | https://actionnetwork.org/docs/webhooks/donation              |

### REST API docs (GET/POST/PUT — not webhook format, but shows full field definitions)
URL pattern: `https://actionnetwork.org/docs/v2/<resource>`

★ = directly relevant to this service

| Resource               | URL                                                                        |
|------------------------|----------------------------------------------------------------------------|
| ★ People               | https://actionnetwork.org/docs/v2/people                                   |
| ★ Attendances          | https://actionnetwork.org/docs/v2/attendances                              |
| ★ Submissions          | https://actionnetwork.org/docs/v2/submissions                              |
| ★ Signatures           | https://actionnetwork.org/docs/v2/signatures                               |
| ★ Donations            | https://actionnetwork.org/docs/v2/donations                                |
| Advocacy Campaigns     | https://actionnetwork.org/docs/v2/advocacy_campaigns                       |
| API Entry Point (AEP)  | https://actionnetwork.org/docs/v2/aep                                      |
| Campaigns              | https://actionnetwork.org/docs/v2/campaigns                                |
| Custom Fields          | https://actionnetwork.org/docs/v2/custom_fields                            |
| Embeds                 | https://actionnetwork.org/docs/v2/embeds                                   |
| Event Campaigns        | https://actionnetwork.org/docs/v2/event_campaigns                          |
| Events                 | https://actionnetwork.org/docs/v2/events                                   |
| Forms                  | https://actionnetwork.org/docs/v2/forms                                    |
| Fundraising Pages      | https://actionnetwork.org/docs/v2/fundraising_pages                        |
| Items                  | https://actionnetwork.org/docs/v2/items                                    |
| Lists                  | https://actionnetwork.org/docs/v2/lists                                    |
| Messages               | https://actionnetwork.org/docs/v2/messages                                 |
| Metadata               | https://actionnetwork.org/docs/v2/metadata                                 |
| Outreaches             | https://actionnetwork.org/docs/v2/outreaches                               |
| Petitions              | https://actionnetwork.org/docs/v2/petitions                                |
| Queries                | https://actionnetwork.org/docs/v2/queries                                  |
| Responses              | https://actionnetwork.org/docs/v2/responses                                |
| Surveys                | https://actionnetwork.org/docs/v2/surveys                                  |
| Tags                   | https://actionnetwork.org/docs/v2/tags                                     |
| Taggings               | https://actionnetwork.org/docs/v2/taggings                                 |
| Unique ID Lists        | https://actionnetwork.org/docs/v2/unique_id_lists                          |
| Wrappers               | https://actionnetwork.org/docs/v2/wrappers                                 |

### Confirmed attendance webhook structure (from docs)
The outer wrapper for `osdi:attendance` payloads:
```
{
  "idempotency_key": string,
  "action_network:sponsor": { "title": string, "url": string },
  "osdi:attendance": {
    "created_date": datetime,
    "modified_date": datetime,
    "status": declined|tentative|accepted|needs action,
    "identifiers": [string],
    "tickets": [{ title, description, amount, currency }],  ← ticketed events only
    "action_network:referrer_data": { source, referrer, website },
    "add_tags": [string],
    "_links": {
      "self": { "href": string },
      "osdi:person": { "href": string },
      "osdi:event": { "href": string }
    },
    "person": { ... }   ← see Person object docs above
  }
}
```

## Decisions Made
- **Project location**: `~/Library/CloudStorage/Dropbox/Postcard Files/ROVPrograms/cfcg-an-webhook`
- **Project name**: `cfcg-an-webhook` (hyphen, with `-an-`); Python package `cfcg_an_webhook` (underscores)
- **Deployment target**: Google Cloud Run
- **Python package manager**: `uv`
- **IDE**: PyCharm
- **VCS**: Git / GitHub, with auto-deploy via GitHub Actions on push to `main`

## What Was Done
- Created project structure with `cfcg_an_webhook/main.py` as the Flask app
- Created `pyproject.toml`, `Procfile`, `.env.example`, `test_local.py`, `zip_dict.json`
- Created `.github/workflows/deploy.yml` for auto-deploy to Cloud Run
- Created `README.md` and `SETUP_GUIDE.md`
- Updated `SETUP_GUIDE.md`: corrected project path to Dropbox location
- Updated `README.md` and `SETUP_GUIDE.md`: replaced all `cfcg-webhook` → `cfcg-an-webhook`
- Updated directory structure diagram in `README.md` to match actual folder layout
- Staged all files for first commit in PyCharm (not yet committed)

## Decisions — Dependencies & Packages
- **`functions-framework`** — considered but rejected. It's for Google Cloud Functions, not Cloud Run. This project uses Flask directly, which is the correct approach for Cloud Run.

## Decisions — Feature Flags
All feature flags default to `false` and are set in `.env` (local) or as Cloud Run env vars (production).

| Flag | Default | What it does |
|------|---------|--------------|
| `SEND_RECIPIENT_EMAILS` | `true` | Send welcome email to new signups |
| `SEND_NOTIFICATION_EMAILS` | `false` | Send admin alerts on errors/warnings |
| `CHECK_IDEMPOTENCY` | `false` | Skip duplicate webhook events |
| `CHECK_ALREADY_EMAILED` | `false` | Skip people already emailed |
| `UPDATE_GROUP_KEY` | `false` | Write region key back to Action Network after emailing |

## Test Suite

### How payload JSON files are read and tested

Payload files in `tests/payloads/` are loaded by fixtures in `conftest.py` and
tested in two ways in `tests/test_main.py`:

**1. `TestPayloadFileParsing` — smoke test for all 4 types**
Calls `parse_recipient()` on each payload file and confirms it doesn't crash.
Checks that `json_type`, `email`, and `zip` are present in the result.
Runs for: `attendance`, `submission`, `signature`, `donation`.

**2. `TestSnapshotParsing` — exact field-by-field assertions**
Parses a fixed payload and asserts every field matches an expected dict.
If Action Network changes their payload structure, this test fails and shows
exactly which field changed. Two snapshot tests exist:
- `test_snapshot_parse_output` — Robert Johnson, Atlanta GA (synthetic fixture)
- `test_snapshot_real_signature_payload` — John Smith (real captured AN payload)

**How files are loaded** (`conftest.py`):
```
JSON file → _load_payload() → fixture (e.g. payload_signature) → test calls parse_recipient() → assertions
```

**Real vs synthetic payloads** — each JSON file has a `_synthetic` flag:
- `_synthetic: false` = real captured AN data (attendance, signature)
- `_synthetic: true` = placeholder, needs replacing with real data (submission, donation)
  A test warning is issued listing which types still need real payloads.

**Snapshot tests are marked `@pytest.mark.integration`** and are skipped when
running `pytest -m "not integration"`. Run them with `pytest tests/ -s`.

---

## Pending Improvements

- **`parse_recipient()` — replace nested `.get()` chains with Pydantic models**
  Currently uses 80+ lines of nested `.get()` calls to parse the Action Network payload.
  Pydantic models would define the expected structure explicitly, validate types, handle
  missing/null fields via defaults automatically, and give precise error messages when a field
  is missing or the wrong type — rather than silently returning `""` or `None`.
  Adds `pydantic` as a dependency. This is the right long-term fix for payload parsing.
  See `cfcg_an_webhook/main.py` → `parse_recipient()`.

- **`parse_recipient()` — consider glom for safer nested access (lighter alternative to Pydantic)**
  `glom` is a library specifically for navigating nested data structures. It gives precise
  error messages showing exactly which key in a nested path failed, rather than a generic
  `KeyError` or silent `None`. Could be added incrementally without rewriting `parse_recipient()`
  from scratch. Lighter than Pydantic if full model validation isn't needed.
  Example: `glom(record, Coalesce("osdi:attendance.person.email_addresses.0.address", default=""))`
  See `cfcg_an_webhook/main.py` → `parse_recipient()`.

- **`parse_recipient()` — consider Pydantic for payload parsing**
  Currently uses 80+ lines of nested `.get()` calls to parse the Action Network payload.
  Pydantic models would define the expected structure explicitly, handle missing/null fields
  via defaults automatically, and shrink the function significantly. Adds `pydantic` as a
  dependency. Worth doing if payload fields are extended or if maintainability is a priority.
  Not urgent — current code works correctly.
  See `cfcg_an_webhook/main.py` → `parse_recipient()`.
- **`load_zip_dict()` — use explicit env var instead of file existence check**
  Currently the function checks if `zip_dict.json` exists locally; if not, falls back to GCS.
  A cleaner approach: add a `ZIP_DICT_PATH` env var in `.env` pointing to the local file.
  If set, load from that path. If empty (as in Cloud Run), load from GCS.
  This makes the behavior explicit and allows easy testing with different files.
  See `cfcg_an_webhook/main.py` → `load_zip_dict()`.

## Files Committed to VCS
- `.idea/.gitignore`, `.idea/misc.xml`, `.idea/vcs.xml` — included (non-personal PyCharm settings)
- `.idea/workspace.xml` — excluded (personal workspace state)
- `Procfile` — included (required for Cloud Run deployment)
