import requests
import csv

API_KEY = "YOUR_ACTION_NETWORK_API_KEY"
BASE_URL = "https://actionnetwork.org/api/v2/people"
HEADERS = {"OSDI-API-Token": API_KEY}

OUTPUT_FILE = "action_network_export_ny.csv"
FIELDNAMES = [
    "email",
    "given_name",
    "family_name",
    "custom:my_field"
]

STATE_FILTER = "New York"  # only export people from this state

with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES)
    writer.writeheader()

    page_url = BASE_URL
    while page_url:
        response = requests.get(page_url, headers=HEADERS)
        data = response.json()

        for person in data.get("_embedded", {}).get("osdi:people", []):
            # Find primary address
            primary_address = next((a for a in person.get("postal_addresses", []) if a.get("primary")), None)

            # Skip if no address or state doesn't match
            if not primary_address or primary_address.get("region") != STATE_FILTER:
                continue

            row = {
                "email": next((e["address"] for e in person.get("email_addresses", []) if e.get("primary")), ""),
                "given_name": person.get("given_name", ""),
                "family_name": person.get("family_name", ""),
                "custom:my_field": person.get("custom_fields", {}).get("my_field", "")
            }
            writer.writerow(row)

        # Pagination
        page_url = data.get("_links", {}).get("next", {}).get("href")
