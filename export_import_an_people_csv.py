"""
Export Action Network people to a CSV, then manually import it back into AN
to bulk-update a custom field (e.g. group_key) for all ~50K people.

─── Why this two-step approach? ────────────────────────────────────────────────
Updating each person via the API (PUT /api/v2/people/<id>) would require ~50K
individual API calls, which takes roughly 3.5 hours. Instead, this script only
does ~2,000 GET requests to export the data (~10–15 min), then AN's own CSV
importer handles all the updates at once on their side.

─── Step 1 — Run this script ───────────────────────────────────────────────────
    uv run python export_import_an_people_csv.py

When prompted, either:
  - Select an existing AN people report CSV (fast — skips the API fetch), or
  - Cancel the dialog to fetch directly from the Action Network API instead

If fetching from the API, requires either:
  - CLOUD_PROJECT_ID env var set (pulls the AN API key from GCP Secret Manager), or
  - AN_API_KEY env var set directly

Produces: action_network_export.csv (or whatever OUTPUT_FILE is set to below)

─── Step 2 — Upload the CSV to Action Network ──────────────────────────────────
This script does NOT import — that step is manual:

    1. Go to Action Network → People → Import People
    2. Upload the CSV file produced by this script
    3. AN matches each row to an existing person record using the `email` column
    4. The `custom:group_key` column updates that custom field on each record
    5. The `person_id` column is ignored by AN's importer (it's included for
       your own reference only)

Custom field columns must use the format `field_name` as the header,
which this script sets automatically based on CUSTOM_FIELD_NAME below.
"""

# pull all people with address and group_key

# TODO: merge missing zips in from dict based on city and state.  add city, find lookup dict, mark filled for review

import csv
import json
import os

import requests

# ─── Constants — edit these before running ────────────────────────────────────

CLOUD_PROJECT_ID  = 'trim-sunlight-489423-h3'
OUTPUT_FILE       = "action_network_export.csv"
STATE_FILTER      = "Wyoming"    # set to None to export everyone (API fetch only)
CUSTOM_FIELD_NAME = "group_key"  # AN custom field key to populate
FIELDNAMES        = [
    "person_id",
    "email",
    "given_name",
    "family_name",
    "state",
    "zip_code",
    f"{CUSTOM_FIELD_NAME}",
]

BASE_URL = "https://actionnetwork.org/api/v2/people"

# ─── Functions ────────────────────────────────────────────────────────────────

def get_api_key() -> str:
    """Return the Action Network API key.

    Tries GCP Secret Manager first (secret name ``AN_WEBHOOK_KEY``).
    Falls back to the ``AN_API_KEY`` environment variable so the script
    works locally without GCP credentials.
    """
    try:
        project_id = CLOUD_PROJECT_ID
        if not project_id:
            raise ValueError("CLOUD_PROJECT_ID not set")
        from google.cloud import secretmanager
        client   = secretmanager.SecretManagerServiceClient()
        name     = f"projects/{project_id}/secrets/AN_WEBHOOK_KEY/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as exc:
        print(f"GCP Secret Manager unavailable ({exc}); falling back to AN_API_KEY env var")
        api_key = os.environ.get("AN_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "No API key found. Set CLOUD_PROJECT_ID (for GCP) or AN_API_KEY env var."
            ) from exc
        return api_key


def load_zip_dict(path: str = "zip_dict.json") -> dict:
    """Load the zip → organizer mapping from a local JSON file.

    Args:
        path: Path to zip_dict.json (default: current directory).

    Returns:
        Dict mapping 5-digit zip strings to organizer info dicts.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    print(f"Loaded {len(data):,} zip codes from {path}")
    return data


def load_people_from_report_csv(path: str) -> list[dict]:
    """Load people from a manually-exported AN report CSV.

    The AN report CSV uses different column names than the API:
      uuid         → person ID
      first_name   → given name
      last_name    → family name
      email        → email address
      zip_code     → postal code (may be ZIP+4 e.g. "10001-1234")

    Args:
        path: Path to the AN report CSV file.

    Returns:
        List of row dicts as read by csv.DictReader.
    """
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    print(f"Loaded {len(rows):,} people from {path}")
    return rows


def fetch_all_people(api_key: str, state_filter: str | None) -> list[dict]:
    """Page through GET /api/v2/people and return all matching person dicts.

    Args:
        api_key:      Action Network API key.
        state_filter: Only include people whose primary address region matches
                      this value (e.g. ``"New York"``). Pass ``None`` for everyone.

    Returns:
        Flat list of raw Action Network person dicts.
    """
    headers  = {"OSDI-API-Token": api_key}
    people   = []
    page_url = BASE_URL
    page_num = 0

    while page_url:
        response = requests.get(page_url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        page_num += 1
        if page_num % 10 == 0:
            print(f"  Fetched page {page_num} — {len(people):,} people so far …")

        for person in data.get("_embedded", {}).get("osdi:people", []):
            if state_filter:
                addresses = person.get("postal_addresses") or []
                primary   = next((a for a in addresses if a.get("primary")), None)
                if not primary or primary.get("region") != state_filter:
                    continue
            people.append(person)

        page_url = data.get("_links", {}).get("next", {}).get("href")

    print(f"Finished: {page_num} pages fetched, {len(people):,} people collected.")
    return people


def compute_field(person: dict, zip_dict: dict, field_name: str) -> str:
    """Look up the custom field value for a person based on their zip code.

    For raw AN API person dicts (output of fetch_all_people).
    Extracts the primary postal code, looks it up in zip_dict, and returns
    the ``region_key`` value (used as the group_key).

    Args:
        person:     Raw Action Network person dict.
        zip_dict:   Dict mapping zip strings to organizer info.
        field_name: Name of the field being populated (reserved for future use).

    Returns:
        The ``region_key`` string, or ``""`` if the zip is not found.
    """
    addresses = person.get("postal_addresses") or []
    primary   = next((a for a in addresses if a.get("primary")), addresses[0] if addresses else {})
    raw_zip   = (primary.get("postal_code") or "").strip()
    zip5      = raw_zip.split("-")[0].strip()
    entry     = zip_dict.get(zip5)
    return entry.get("region_key", "") if entry else ""


def export_to_csv(
    people:      list[dict],
    zip_dict:    dict,
    output_file: str,
    field_name:  str,
):
    """Write AN API people to a CSV file ready for Action Network import.

    Use this when people were fetched via fetch_all_people() (AN API format).
    For report CSV input, use export_report_rows_to_csv() instead.

    Args:
        people:      List of raw AN person dicts (output of fetch_all_people).
        zip_dict:    Dict mapping zip strings to organizer info.
        output_file: Path for the output CSV.
        field_name:  AN custom field key (used as ``<field_name>`` header).
    """
    no_zip_match = 0

    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES)
        writer.writeheader()

        for person in people:
            person_id = ""
            try:
                href      = person["_links"]["self"]["href"]
                person_id = href.rstrip("/").split("/")[-1]
            except (KeyError, TypeError):
                pass

            emails        = person.get("email_addresses") or []
            primary_email = next((e for e in emails if e.get("primary")), emails[0] if emails else {})
            email         = (primary_email.get("address") or "").strip()

            custom_value = compute_field(person, zip_dict, field_name)
            if not custom_value:
                no_zip_match += 1

            addresses = person.get("postal_addresses") or []
            primary   = next((a for a in addresses if a.get("primary")), addresses[0] if addresses else {})
            writer.writerow({
                "person_id":            person_id,
                "email":                email,
                "given_name":           (person.get("given_name")  or "").strip(),
                "family_name":          (person.get("family_name") or "").strip(),
                "state":                (primary.get("region")      or "").strip(),
                "zip_code":             (primary.get("postal_code") or "").strip(),
                f"{field_name}": custom_value,
            })

    _print_summary(output_file, len(people), no_zip_match)


def export_report_rows_to_csv(
    rows:        list[dict],
    zip_dict:    dict,
    output_file: str,
    field_name:  str,
):
    """Write AN report CSV rows to an output CSV ready for Action Network import.

    Use this when people were loaded via load_people_from_report_csv() (flat CSV
    format with columns: uuid, first_name, last_name, email, zip_code, …).

    Args:
        rows:        List of row dicts from the AN report CSV.
        zip_dict:    Dict mapping zip strings to organizer info.
        output_file: Path for the output CSV.
        field_name:  AN custom field key (used as ``<field_name>`` header).
    """
    no_zip_match = 0

    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES)
        writer.writeheader()

        for row in rows:
            raw_zip = (row.get("zip_code") or "").strip()
            zip5    = raw_zip.split("-")[0].strip()
            entry   = zip_dict.get(zip5)
            custom_value = entry.get("region_key", "") if entry else ""
            if not custom_value:
                no_zip_match += 1

            writer.writerow({
                "person_id":            (row.get("uuid")             or "").strip(),
                "email":                (row.get("email")            or "").strip(),
                "given_name":           (row.get("first_name")       or "").strip(),
                "family_name":          (row.get("last_name")        or "").strip(),
                "state":                (row.get("can2_user_state")  or "").strip(),
                "zip_code":             (row.get("zip_code")         or "").strip(),
                f"{field_name}": custom_value,
            })

    _print_summary(output_file, len(rows), no_zip_match)


def _print_summary(output_file: str, total: int, no_zip_match: int):
    print(f"CSV written to {output_file!r}")
    print(f"  Rows written:   {total:,}")
    print(f"  No zip match:   {no_zip_match:,}")
    print(f"  With zip match: {total - no_zip_match:,}")


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    """
    Display a file/directory selection dialog.

    Args:
        title: Window title
        start_dir: Initial directory to display
        files_like: Wildcard pattern for filtering (e.g., "*.txt")
        choices: List of two button labels [select_label, cancel_label]
        mode: "file" (select files), "dir" (select directories), or "both"
        title2: Optional subtitle displayed below the window title
        show_hiddenbutton: Show checkbox to toggle hidden files (default False)
        show_sortbutton: Show checkbox to toggle sort order (default False)

    Returns:
        Selected path as string, or None if cancelled
    """
    from uvbekutils import select_file

    zip_dict = load_zip_dict()

    print("Select an AN people report CSV to use as input…")
    print("(Cancel the dialog to fetch directly from the Action Network API instead.)")
    input_csv = select_file(
        title="Select AN People Report CSV",
        start_dir=os.getcwd(),
        files_like="*.csv",
        title2="Cancel to fetch from Action Network API instead",
    )

    if input_csv:
        output_file = os.path.join(os.path.dirname(input_csv), OUTPUT_FILE)
        print(f"Loading from file: {input_csv}")
        rows = load_people_from_report_csv(input_csv)
        if STATE_FILTER:
            before = len(rows)
            rows = [r for r in rows if (r.get("can2_user_state") or "").strip() == STATE_FILTER]
            print(f"State filter {STATE_FILTER!r}: {before:,} → {len(rows):,} people")
        export_report_rows_to_csv(rows, zip_dict, output_file, CUSTOM_FIELD_NAME)
    else:
        output_file = OUTPUT_FILE
        print("No file selected — fetching from Action Network API…")
        api_key = get_api_key()
        people  = fetch_all_people(api_key, STATE_FILTER)
        export_to_csv(people, zip_dict, output_file, CUSTOM_FIELD_NAME)

    print(f"\nDone. Upload {output_file!r} to Action Network → People → Import.")


if __name__ == "__main__":
    main()
