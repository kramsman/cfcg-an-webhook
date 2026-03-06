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

TEST_PAYLOAD = [
    {
        "osdi:attendance": {
            "created_date": "2025-04-21T19:14:50Z",
            "modified_date": "2025-04-21T19:14:50Z",
            "identifiers": [
                "action_network:0564993e-9b4c-4ee6-b84c-f6f8614b492d"
            ],
            "person": {
                "family_name": "Test",
                "given_name": "Kramer",
                "postal_addresses": [
                    {
                        "primary": True,
                        "locality": "New York",
                        "region": "New York",
                        "postal_code": "10023",   # ← change this to test different orgs
                        "country": "US",
                        "address_lines": ["123 Main St"]
                    }
                ],
                "email_addresses": [
                    {
                        "primary": True,
                        "address": "briank@kramericore.com"   # ← use your test email
                    }
                ],
                "phone_numbers": [
                    {
                        "primary": True,
                        "number": "212-555-1234",
                        "number_type": "Mobile"
                    }
                ],
                "custom_fields": {
                    "Volunteer Interest": "Postcarding",
                    "Referred By": "Friend"
                }
            },
            "_links": {
                "osdi:person": {
                    "href": "https://actionnetwork.org/api/v2/people/test-person-id-12345"
                }
            }
        },
        "action_network:sponsor": {
            "title": "Center for Common Ground",
            "url": "https://actionnetwork.org/groups/center-for-common-ground"
        },
        "idempotency_key": "test-idem-key-abc123"
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
