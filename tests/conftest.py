"""
Shared pytest fixtures for cfcg-an-webhook tests.
Load .env before importing main so all config vars are set.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO RUN TESTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Run all unit tests (no external services):
    pytest tests/ -s

Run integration tests only (hits real APIs/GCS — needs credentials):
    pytest tests/ -s -m integration

Run everything:
    pytest tests/ -s -m "integration or not integration"

Run a single test file:
    pytest tests/test_main.py -s

Run a single test by name:
    pytest tests/test_main.py::TestParseRecipient::test_happy_path -s

Verbose output (shows test names):
    pytest tests/ -s -v

MARKERS
    integration  Tests that call external services (SendGrid, Action Network, GCS).
                 Skipped automatically if required env vars are not set.

CREDENTIALS NEEDED FOR INTEGRATION TESTS
    CLOUD_PROJECT_ID   — enables Secret Manager access (set in .env)
    GCS_BUCKET         — enables GCS zip dict load test (set in .env)
    TEST_AN_PERSON_ID  — enables live Action Network update test (set in .env)
    ALLOWED_RECIPIENT_EMAILS — safe address(es) for live email send test (set in .env)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import os
import pathlib
import pytest
from dotenv import load_dotenv

PAYLOADS_DIR = pathlib.Path(__file__).parent / "payloads"

# Load .env before any test imports main (which reads env vars at module level)
load_dotenv()


# ─── Sample Data ──────────────────────────────────────────────────────────────

@pytest.fixture
def sample_payload():
    """Realistic Action Network webhook payload (single signup)."""
    return [
        {
            "idempotency_key": "test-idempotency-key-001",
            "action_network:sponsor": {"title": "CFCG Test"},
            "osdi:attendance": {
                "created_date": "2024-01-15T10:30:00Z",
                "modified_date": "2024-01-15T10:30:00Z",
                "_links": {
                    "osdi:person": {
                        "href": "https://actionnetwork.org/api/v2/people/abc-123-def-456"
                    }
                },
                "person": {
                    "given_name": "Jane",
                    "family_name": "Smith",
                    "email_addresses": [
                        {"address": "jane.smith@example.com", "primary": True}
                    ],
                    "phone_numbers": [
                        {"number": "555-867-5309", "number_type": "Mobile", "primary": True}
                    ],
                    "postal_addresses": [
                        {
                            "primary": True,
                            "address_lines": ["123 Main St"],
                            "locality": "Albany",
                            "region": "NY",
                            "postal_code": "12207",
                        }
                    ],
                    "custom_fields": {"volunteer": "1", "newsletter": "yes"},
                },
            },
        }
    ]


@pytest.fixture
def sample_payload_bad_zip(sample_payload):
    """Payload with a zip code not in the lookup table."""
    p = sample_payload[0]["osdi:attendance"]["person"]["postal_addresses"][0]
    p["postal_code"] = "00000"
    return sample_payload


@pytest.fixture
def sample_payload_missing_zip(sample_payload):
    """Payload with no zip code at all."""
    p = sample_payload[0]["osdi:attendance"]["person"]["postal_addresses"][0]
    p.pop("postal_code", None)
    return sample_payload


@pytest.fixture
def minimal_zip_dict():
    """Small in-memory zip dict covering the test zip (12207 = Albany, NY)."""
    return {
        "12207": {
            "region_key": "NE",
            "email": "organizer@example.com",
            "nickname": "Test Organizer",
            "cc_org": "cc",
        }
    }


@pytest.fixture
def sample_payload_multiple_contacts(sample_payload):
    """Payload with 2 emails, 2 phones, 2 addresses — primary is the SECOND item in each list.
    Tests that primary selection isn't just picking index [0].
    """
    person = sample_payload[0]["osdi:attendance"]["person"]
    person["email_addresses"] = [
        {"address": "jane.old@example.com", "primary": False},
        {"address": "jane.smith@example.com", "primary": True},
    ]
    person["phone_numbers"] = [
        {"number": "555-000-0000", "number_type": "Home", "primary": False},
        {"number": "555-867-5309", "number_type": "Mobile", "primary": True},
    ]
    person["postal_addresses"] = [
        {
            "primary": False,
            "address_lines": ["999 Old St"],
            "locality": "Troy",
            "region": "NY",
            "postal_code": "12180",
        },
        {
            "primary": True,
            "address_lines": ["123 Main St"],
            "locality": "Albany",
            "region": "NY",
            "postal_code": "12207",
        },
    ]
    return sample_payload


@pytest.fixture
def sample_payload_no_email(sample_payload):
    """Payload where email_addresses is an empty list — tests empty-email guard."""
    sample_payload[0]["osdi:attendance"]["person"]["email_addresses"] = []
    return sample_payload


@pytest.fixture
def real_an_snapshot():
    """
    A realistic Action Network webhook payload capturing the full structure
    as actually sent. Used for snapshot testing — if AN changes their format,
    parse_recipient output will diverge from the expected dict and the test will fail.
    """
    return [
        {
            "idempotency_key": "snapshot-key-abc123",
            "action_network:sponsor": {"title": "CFCG"},
            "osdi:attendance": {
                "created_date": "2024-06-01T14:22:00Z",
                "modified_date": "2024-06-01T14:22:00Z",
                "_links": {
                    "osdi:person": {
                        "href": "https://actionnetwork.org/api/v2/people/snapshot-person-id"
                    }
                },
                "person": {
                    "given_name": "Robert",
                    "family_name": "Johnson",
                    "email_addresses": [
                        {"address": "robert.johnson@example.com", "primary": True}
                    ],
                    "phone_numbers": [
                        {"number": "404-555-1212", "number_type": "Mobile", "primary": True}
                    ],
                    "postal_addresses": [
                        {
                            "primary": True,
                            "address_lines": ["456 Peachtree St NE"],
                            "locality": "Atlanta",
                            "region": "GA",
                            "postal_code": "30308",
                        }
                    ],
                    "custom_fields": {"volunteer": "1"},
                },
            },
        }
    ]


@pytest.fixture
def parsed_recipient(sample_payload, minimal_zip_dict, monkeypatch):
    """A fully parsed + organizer-attached recipient dict, ready for email building."""
    from cfcg_an_webhook import main
    monkeypatch.setattr(main, "ZIP_TO_ORG", minimal_zip_dict)

    recipient = main.parse_recipient(sample_payload[0])
    main.attach_organizer_info(recipient)
    return recipient


# ─── Payload file fixtures ────────────────────────────────────────────────────
# One fixture per osdi: type — loaded from tests/payloads/<type>.json.
# Replace synthetic placeholders with real captured AN payloads when available.
# Files marked "_synthetic": true are known placeholders, not real AN data.

def _load_payload(osdi_type: str) -> list:
    """Load a payload JSON file from tests/payloads/."""
    path = PAYLOADS_DIR / f"{osdi_type}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No payload file for osdi type '{osdi_type}'. "
            f"Add tests/payloads/{osdi_type}.json with a real captured AN payload."
        )
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def payload_attendance():
    """Real-shape osdi:attendance payload loaded from tests/payloads/attendance.json."""
    return _load_payload("attendance")


@pytest.fixture
def payload_submission():
    """Synthetic osdi:submission payload — replace with real captured AN data."""
    return _load_payload("submission")


@pytest.fixture
def payload_signature():
    """Synthetic osdi:signature payload — replace with real captured AN data."""
    return _load_payload("signature")


@pytest.fixture
def payload_donation():
    """Synthetic osdi:donation payload — replace with real captured AN data."""
    return _load_payload("donation")
