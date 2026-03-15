"""
Local test script for the CFCG webhook.

Usage:
    1.  Start the server:   python main.py
    2.  In another terminal: python test_local.py

You can edit the TEST_PAYLOAD below to test different scenarios:
    - Change postal_code to test different zip → organizer assignments
    - Change email to one in your ALLOWED_RECIPIENT_EMAILS list to receive a real email
    - Set send_real_email=True below to actually send via SendGrid
"""

import json
import requests

SERVER_URL = "http://localhost:8080"

# ── Sample Action Network webhook payload ─────────────────────────────────────
# This mirrors the real payload AN sends. Edit as needed for your tests.

TEST_PAYLOAD =[
    {
        "osdi:submission": {
            "created_date": "2026-03-11T16:05:37Z",
            "modified_date": "2026-03-11T16:05:37Z",
            "identifiers": [
                "action_network:a2319f88-532b-434b-8dd1-829a83747007"
            ],
            "person": {
                "created_date": "2026-03-11T16:05:37Z",
                "modified_date": "2026-03-11T16:06:18Z",
                "family_name": "testkramer",
                "given_name": "testbrian",
                "postal_addresses": [
                    {
                        "primary": True,
                        "locality": "new york",
                        "region": "New York",
                        "postal_code": "10023",
                        "country": "US",
                        "location": {
                            "latitude": 40.7764,
                            "longitude": -73.9827,
                            "accuracy": "Approximate"
                        }
                    }
                ],
                "email_addresses": [
                    {
                        "primary": True,
                        "address": "rovmailtester@gmail.com"
                    }
                ],
                "phone_numbers": [
                    {
                        "primary": True,
                        "status": "subscribed",
                        "number_type": "Mobile"
                    }
                ],
                "custom_fields": {
                    "Mobile Phone": "9175551234",
                    "textarea": "4thu",
                    "Volunteer_Sign petitions": "1",
                    "Volunteer_Call/email/tweet my legislator": "1",
                    "Volunteer_Meet with my legislator": "1",
                    "Volunteer_Phonebank to voters": "1",
                    "Volunteer_Postcard to voters": "1",
                    "Volunteer_Text to voters": "1",
                    "Volunteer_Host actions/events": "1",
                    "Volunteer_Canvass": "1",
                    "Volunteer_Drive Voters to the Polls": "1",
                    "checkboxes_Alabama": "1",
                    "checkboxes_Georgia": "1",
                    "checkboxes_North Carolina": "1",
                    "checkboxes_Texas": "1",
                    "checkboxes_Virginia": "1"
                },
                "languages_spoken": [
                    "en"
                ]
            },
            "add_tags": [
                "volunteer"
            ],
            "action_network:referrer_data": {
                "source": "widget",
                "website": "www.centerforcommonground.org"
            },
            "_links": {
                "self": {
                    "href": "https://actionnetwork.org/api/v2/forms/cdab2748-7f19-418f-a989-539362b9ecf3/submissions/a2319f88-532b-434b-8dd1-829a83747007"
                },
                "osdi:form": {
                    "href": "https://actionnetwork.org/api/v2/forms/cdab2748-7f19-418f-a989-539362b9ecf3"
                },
                "osdi:person": {
                    "href": "https://actionnetwork.org/api/v2/people/1d774b1a-8017-43e0-9ba3-4514262eb8c5"
                }
            }
        },
        "action_network:sponsor": {
            "title": "Center for Common Ground",
            "url": "https://actionnetwork.org/groups/center-for-common-ground"
        },
        "idempotency_key": "8222b5db14bb49a060b3f0f6cab321e6"
    }
]


def run_test(payload=TEST_PAYLOAD, path="/webhook"):
    print(f"\n{'='*60}")
    print(f"POST {SERVER_URL}{path}")
    print(f"Payload zip: {payload[0]['osdi:attendance']['person']['postal_addresses'][0]['postal_code']}")
    print(f"Payload email: {payload[0]['osdi:attendance']['person']['email_addresses'][0]['address']}")
    print("="*60)

    try:
        response = requests.post(
            f"{SERVER_URL}{path}",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        print(f"Status:   {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
    except requests.exceptions.ConnectionError:
        print("ERROR: Could not connect. Is the server running?")
        print("  Run:  python main.py")


def test_health():
    print(f"\n{'='*60}")
    print(f"GET {SERVER_URL}/health")
    print("="*60)
    try:
        r = requests.get(f"{SERVER_URL}/health", timeout=5)
        print(f"Status:   {r.status_code}")
        print(f"Response: {json.dumps(r.json(), indent=2)}")
    except requests.exceptions.ConnectionError:
        print("ERROR: Could not connect. Is the server running?")


def test_bad_payload():
    """Test that bad payloads are rejected cleanly."""
    print(f"\n{'='*60}")
    print("Testing bad payload (not a list)...")
    r = requests.post(f"{SERVER_URL}/webhook", json={"bad": "data"}, timeout=5)
    print(f"Status: {r.status_code}  (expected 400)")

    print("\nTesting empty list...")
    r = requests.post(f"{SERVER_URL}/webhook", json=[], timeout=5)
    print(f"Status: {r.status_code}  (expected 400)")


if __name__ == "__main__":
    test_health()
    run_test()
    test_bad_payload()
