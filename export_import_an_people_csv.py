"""
Export Action Network people to a CSV, then manually import it back into AN
to bulk-update a custom field (e.g. group_key) for all ~50K people.

─── Why this approach? ─────────────────────────────────────────────────────────
Updating each person via the API would require ~50K individual PUT calls (~3.5 hrs).
Instead, produce the input CSV from AN's report tool (fast), run this script to
compute group_key from zip codes, then upload the output CSV via AN's importer.

─── Step 0 — Produce the input CSV from Action Network ─────────────────────────
    1. Go to Action Network → Reports
    2. Open the report named "pull all people include address and group_key"
    3. Click "Edit"
    4. Click "Save and Select Data"
    5. Click "Save and Get Results" — should show ~100K results
    6. Click "Generate" in the box on the right
    7. Refresh the page until the box shows the current date/time
    8. Click "Download" to get the CSV
    9. Move the CSV file to the folder where you want to run this script
       (the output file will be written to the same folder)

─── Step 1 — Run this script ───────────────────────────────────────────────────
    uv run python export_import_an_people_csv.py

When prompted, select the AN people report CSV you exported in Step 0.

Produces: action_network_export.csv in the same folder as your input file.

─── Step 2 — Upload the CSV to Action Network ──────────────────────────────────
This script does NOT import — that step is manual:

    1. Go to Action Network → People → Import People
    2. Upload the output CSV produced by this script
    3. AN matches each row to an existing person record using the `email` column
    4. The `custom:group_key` column updates that custom field on each record
    5. Columns prefixed with `my_` (my_person_id, my_group_key) are ignored by
       AN's importer — they are included for your reference and review only

─── Missing zip codes ──────────────────────────────────────────────────────────
For people with no zip code, the script attempts to find one using city + state,
looking up the purchased zip code database (MAIN_ZIP_FILE below).
The `zip_source` column in the output tells you how each zip was obtained:
  "original"         — zip came from the AN report as-is
  "city_state_lookup" — zip was filled in from the city/state lookup
  ""                 — no zip could be found
Rows with zip_source="city_state_lookup" should be reviewed before importing.
"""

import csv
import json
from pathlib import Path

import pandas as pd

# ─── Constants — edit these before running ────────────────────────────────────

OUTPUT_FILE       = "action_network_export.csv"
STATE_FILTER      = "WY"        # 2-letter state abbreviation, or None for everyone
STATE_FILTER      = ""        # 2-letter state abbreviation, or None for everyone
CUSTOM_FIELD_NAME = "group_key" # AN custom field key to populate
EXPORT_CSV_LIKE = 'an_report_pull-all-people-include-address-and-group_key'

# Column name for city in the AN report CSV (adjust if AN uses a different label)
CITY_COLUMN = "can2_user_city"

# Path to the purchased zip code database used for city+state → zip lookup
MAIN_ZIP_FILE = Path("~/Dropbox/Postcard Files/ROVPrograms/ROVCleaver_Production/"
                     "zip-codes-database-DELUXE-BUSINESS.csv").expanduser()

FIELDNAMES = [
    "person_id",                # uuid — AN uses this to match the record
    "my_email",                 # reference only — prefixed so AN importer ignores it
    "my_given_name",
    "my_family_name",
    "my_city",
    "my_state",
    "my_zip_code",
    "my_zip_source",            # "original" | "city_state_lookup" | ""
    "my_group_key",             # existing group_key from input — for reference, not imported
    "my_group_key_source",      # "zip_lookup" | "existing" | ""
    f"custom:{CUSTOM_FIELD_NAME}",  # new computed value — this IS imported by AN
]

# ─── Functions ────────────────────────────────────────────────────────────────

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


def build_city_state_to_zip_dict(zip_file: Path) -> dict:
    """Build a (state_abbrev, city) → zip5 lookup dict from the DELUXE zip database.

    Reads only the needed columns from the large zip database CSV. Both the
    primary city name and any alias city name are added as lookup keys so that
    common alternate city names are also matched.

    Args:
        zip_file: Path to zip-codes-database-DELUXE-BUSINESS.csv.

    Returns:
        Dict mapping (state_upper, city_upper) tuples to 5-digit zip strings.
        When a city maps to multiple zips, the primary record (PrimaryRecord='P')
        is preferred; otherwise the first one encountered is used.
    """
    print(f"Building city+state → zip lookup from {zip_file.name} …")
    df = pd.read_csv(
        zip_file,
        usecols=["ZipCode", "State", "City", "CityAliasName", "PrimaryRecord"],
        keep_default_na=False,
        dtype=str,
    )

    # Zero-pad zip to 5 digits
    df["zip5"] = df["ZipCode"].str.strip().str.zfill(5)

    # Primary records first so they win when a city has multiple zips
    df["is_primary"] = df["PrimaryRecord"].str.strip() == "P"
    df = df.sort_values("is_primary", ascending=False)

    # Normalize string columns (vectorized — no Python loop)
    df["State"]         = df["State"].str.strip().str.upper()
    df["City"]          = df["City"].str.strip().str.upper()
    df["CityAliasName"] = df["CityAliasName"].str.strip().str.upper()

    # Two DataFrames — one for primary city name, one for alias
    city_df  = df[df["City"] != ""][["State", "City", "zip5"]].rename(columns={"City": "city_key"})
    alias_df = df[df["CityAliasName"] != ""][["State", "CityAliasName", "zip5"]].rename(columns={"CityAliasName": "city_key"})

    # Stack, deduplicate (primary rows already first from the sort above)
    combined = pd.concat([city_df, alias_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["State", "city_key"], keep="first")

    # Build dict — keys are (state_upper, city_upper) tuples, same format as before
    lookup = combined.set_index(["State", "city_key"])["zip5"].to_dict()

    print(f"Loaded {len(lookup):,} city+state → zip mappings")
    return lookup


def load_people_from_report_csv(path: str) -> list[dict]:
    """Load people from a manually-exported AN report CSV.

    Expected columns from the AN report export (Step 0 in module docstring):
      uuid                   → person ID
      first_name             → given name
      last_name              → family name
      email                  → email address
      can2_user_city         → city name for zip lookup (CITY_COLUMN constant)
      zip_code               → postal code (may be ZIP+4 e.g. "10001-1234" or blank)
      can2_state_abbreviated → 2-letter state code (e.g. "NY")
      group_key              → existing group_key value (preserved as my_group_key)
      can2_county            → county (present in export, not used by this script)
      group_key_list         → tag list (present in export, not used by this script)
      Groups                 → groups (present in export, not used by this script)

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


def export_report_rows_to_csv(
    rows:            list[dict],
    zip_dict:        dict,
    city_state_dict: dict,
    output_file:     Path,
    field_name:      str,
):
    """Process AN report rows and write an output CSV ready for Action Network import.

    For each person:
    - If zip is present, uses it directly (zip_source = "original").
    - If zip is missing, looks up by city + state abbreviation
      (zip_source = "city_state_lookup"). Rows filled this way should be reviewed.
    - If neither works, zip stays blank (zip_source = "").

    The computed group_key is written as `custom:<field_name>` so AN's importer
    updates that custom field. The existing group_key from the input is preserved
    as `my_group_key` for reference.

    Args:
        rows:            List of row dicts from the AN report CSV.
        zip_dict:        Dict mapping zip5 strings to organizer info.
        city_state_dict: Dict mapping (state_abbrev_upper, city_upper) to zip5 strings.
        output_file:     Path for the output CSV.
        field_name:      AN custom field key (written as ``custom:<field_name>``).
    """
    count_original  = 0
    count_filled    = 0
    count_no_zip    = 0
    count_gk_match  = 0

    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES)
        writer.writeheader()

        for row in rows:
            raw_zip = (row.get("zip_code") or "").strip()
            zip5    = raw_zip.split("-")[0].strip()
            zip_source = ""

            # Blank out anything that isn't a 5-digit integer (e.g. "Millburn")
            if zip5 and not (len(zip5) == 5 and zip5.isdigit()):
                zip5 = ""

            if zip5:
                zip_source = "original"
                count_original += 1
            else:
                # Try city + state abbreviation lookup
                city  = (row.get(CITY_COLUMN) or "").strip().upper()
                state = (row.get("can2_state_abbreviated") or "").strip().upper()
                if city and state:
                    found = city_state_dict.get((state, city))
                    if found:
                        zip5       = found
                        zip_source = "city_state_lookup"
                        count_filled += 1
                    else:
                        count_no_zip += 1
                else:
                    count_no_zip += 1

            zip_key      = zip5.lstrip("0") or "0" if zip5 else None
            entry        = zip_dict.get(zip_key) if zip_key else None
            custom_value = entry.get("region_key", "") if entry else ""
            existing_gk  = (row.get("group_key") or "").strip()

            if custom_value:
                group_key_source = "zip_lookup"
                count_gk_match += 1
            else:
                # Zip didn't yield a group_key — try city+state for an alternate zip
                city  = (row.get(CITY_COLUMN) or "").strip().upper()
                state = (row.get("can2_state_abbreviated") or "").strip().upper()
                if city and state:
                    alt_zip = city_state_dict.get((state, city))
                    if alt_zip:
                        alt_key      = alt_zip.lstrip("0") or "0"
                        alt_entry    = zip_dict.get(alt_key)
                        custom_value = alt_entry.get("region_key", "") if alt_entry else ""
                if custom_value:
                    group_key_source = "city_state_gk_lookup"
                    count_gk_match += 1
                elif existing_gk:
                    custom_value     = existing_gk
                    group_key_source = "existing"
                else:
                    group_key_source = ""

            writer.writerow({
                "person_id":            (row.get("uuid")                   or "").strip(),
                "my_email":             (row.get("email")                  or "").strip(),
                "my_given_name":        (row.get("first_name")             or "").strip(),
                "my_family_name":       (row.get("last_name")              or "").strip(),
                "my_city":              (row.get(CITY_COLUMN)              or "").strip(),
                "my_state":             (row.get("can2_state_abbreviated") or "").strip(),
                "my_zip_code":          zip5,
                "my_zip_source":        zip_source,
                "my_group_key":         existing_gk,
                "my_group_key_source":  group_key_source,
                f"custom:{field_name}": custom_value,
            })

    total = len(rows)
    print(f"CSV written to {output_file}")
    print(f"  Rows written:            {total:,}")
    print(f"  Zip from original:       {count_original:,}")
    print(f"  Zip from city/state:     {count_filled:,}")
    print(f"  No zip found:            {count_no_zip:,}")
    print(f"  group_key matched:       {count_gk_match:,}")
    print(f"  group_key not matched:   {total - count_gk_match:,}")


# ─── Entry point ──────────────────────────────────────────────────────────────

INSTRUCTIONS = """\
Before running this script, export the people CSV from Action Network:

  1. Go to Action Network → Reports
  2. Open the report named:
       "pull all people include address and group_key"
  3. Click "Edit"
  4. Click "Save and Select Data"
  5. Click "Save and Get Results"
       (should show ~100K results)
  6. Click "Generate" in the box on the right
  7. Refresh the page until the box shows the current date/time
  8. Click "Download" to get the CSV
  9. Move the CSV file to the folder where you want the output file

Click Continue when your CSV is ready, or Exit to cancel.
"""


def main():
    from uvbekutils import select_file, exit_yes_no

    exit_yes_no(INSTRUCTIONS, title="Export/Import group_key — Step 1 of 2")

    zip_dict        = load_zip_dict()
    city_state_dict = build_city_state_to_zip_dict(MAIN_ZIP_FILE)

    print("Select the AN people report CSV (exported from AN Reports with city included)…")
    input_csv = select_file(
        title="Select AN People Report CSV",
        start_dir=Path.cwd(),
        files_like=f"{EXPORT_CSV_LIKE}*.csv",
        title2="Export from AN Reports → People with city field included",
    )

    if not input_csv:
        print("No file selected — exiting.")
        return

    output_file = Path(input_csv).parent / OUTPUT_FILE
    print(f"Loading from file: {input_csv}")
    rows = load_people_from_report_csv(input_csv)

    if STATE_FILTER:
        before = len(rows)
        rows = [r for r in rows if (r.get("can2_state_abbreviated") or "").strip() == STATE_FILTER]
        print(f"State filter {STATE_FILTER!r}: {before:,} → {len(rows):,} people")

    export_report_rows_to_csv(rows, zip_dict, city_state_dict, output_file, CUSTOM_FIELD_NAME)
    print(f"\nDone. Upload {output_file} to Action Network → People → Import.")


if __name__ == "__main__":
    main()
