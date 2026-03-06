# Issues — cfcg-an-webhook

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

## Pending Improvements

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
