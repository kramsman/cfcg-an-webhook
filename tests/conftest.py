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

import os
import pytest
from dotenv import load_dotenv

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
def parsed_recipient(sample_payload, minimal_zip_dict, monkeypatch):
    """A fully parsed + organizer-attached recipient dict, ready for email building."""
    from cfcg_an_webhook import main
    monkeypatch.setattr(main, "ZIP_TO_ORG", minimal_zip_dict)

    recipient = main.parse_recipient(sample_payload[0])
    main.attach_organizer(recipient)
    return recipient
