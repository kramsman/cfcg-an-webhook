"""
Tests for cfcg_an_webhook/main.py

Run all:            pytest tests/ -s
Run integration:    pytest tests/ -s -m integration
Run unit only:      pytest tests/ -s -m "not integration"

SKIPPED (too simple to test):
  - to_zip5: single expression, no branching — covered implicitly via parse_recipient edge case tests
  - _add_copy_emails: thin list-append helper — covered implicitly via _build_welcome_email tests
  - health: one-liner Flask route returning a static dict
"""

import os
import pathlib
import pytest
from unittest.mock import MagicMock, patch


# ─── Imports (after .env is loaded by conftest) ────────────────────────────────

from cfcg_an_webhook import main


# ─── parse_recipient ───────────────────────────────────────────────────────────

class TestParseRecipient:

    def test_happy_path(self, sample_payload):
        """Parses a complete, well-formed Action Network record."""
        record = sample_payload[0]

        print(f"\n--- test_parse_recipient__happy_path ---")
        print(f"  Parameters : record keys={list(record.keys())}")
        print(f"  Input      : person=Jane Smith, zip=12207, email=jane.smith@example.com")

        result = main.parse_recipient(record)

        print(f"  Output     : {result}")

        assert result["recipient_first_name"] == "Jane"
        assert result["recipient_last_name"] == "Smith"
        assert result["recipient_email"] == "jane.smith@example.com"
        assert result["recipient_zip"] == 12207
        assert result["recipient_zip_raw"] == "12207"
        assert result["recipient_state"] == "NY"
        assert result["recipient_city"] == "Albany"
        assert result["recipient_phone"] == "555-867-5309"
        assert result["person_id"] == "abc-123-def-456"
        assert result["json_type"] == "attendance"

    def test_custom_fields_formatted(self, sample_payload):
        """Custom fields with value '1' are displayed as 'Yes'."""
        record = sample_payload[0]

        print(f"\n--- test_parse_recipient__custom_fields ---")
        print(f"  Parameters : record with custom_fields={{'volunteer': '1', 'newsletter': 'yes'}}")
        print(f"  Input      : raw custom_fields dict")

        result = main.parse_recipient(record)

        print(f"  Output     : custom_fields={result['custom_fields']}")

        assert "volunteer: Yes" in result["custom_fields"]
        assert "newsletter: yes" in result["custom_fields"]

    def test_missing_osdi_key(self):
        """Returns default empty dict when no osdi: key is present."""
        record = {"idempotency_key": "xyz", "action_network:sponsor": {}}

        print(f"\n--- test_parse_recipient__missing_osdi_key ---")
        print(f"  Parameters : record={record}")
        print(f"  Input      : record with no osdi: key")

        result = main.parse_recipient(record)

        print(f"  Output     : {result}")

        assert result["recipient_email"] == ""
        assert result["recipient_zip"] == 0
        assert result["person_id"] is None

    def test_missing_zip(self, sample_payload_missing_zip):
        """Returns zip=0 when postal_code is absent."""
        record = sample_payload_missing_zip[0]

        print(f"\n--- test_parse_recipient__missing_zip ---")
        print(f"  Parameters : record with no postal_code")
        print(f"  Input      : {record['osdi:attendance']['person']['postal_addresses']}")

        result = main.parse_recipient(record)

        print(f"  Output     : recipient_zip={result['recipient_zip']}, zip_raw={result['recipient_zip_raw']!r}")

        assert result["recipient_zip"] == 0
        assert result["recipient_zip_raw"] == ""

    def test_name_title_cased(self, sample_payload):
        """Names are title-cased regardless of input case."""
        record = sample_payload[0]
        record["osdi:attendance"]["person"]["given_name"] = "JANE"
        record["osdi:attendance"]["person"]["family_name"] = "smith"

        print(f"\n--- test_parse_recipient__title_case ---")
        print(f"  Parameters : given_name='JANE', family_name='smith'")
        print(f"  Input      : raw name strings in all-caps / lowercase")

        result = main.parse_recipient(record)

        print(f"  Output     : first={result['recipient_first_name']!r}, last={result['recipient_last_name']!r}")

        assert result["recipient_first_name"] == "Jane"
        assert result["recipient_last_name"] == "Smith"


# ─── attach_organizer ─────────────────────────────────────────────────────────

class TestAttachOrganizer:

    def test_happy_path(self, sample_payload, minimal_zip_dict, monkeypatch):
        """Attaches organizer fields when zip is found."""
        monkeypatch.setattr(main, "ZIP_TO_ORG", minimal_zip_dict)
        recipient = main.parse_recipient(sample_payload[0])

        print(f"\n--- test_attach_organizer__happy_path ---")
        print(f"  Parameters : recipient zip={recipient['recipient_zip']}")
        print(f"  Input      : ZIP_TO_ORG={minimal_zip_dict}")

        error = main.attach_organizer(recipient)

        print(f"  Output     : error={error!r}, org_email={recipient.get('org_email')!r}, "
              f"org_name={recipient.get('org_name')!r}, reg_key={recipient.get('reg_key')!r}")

        assert error == ""
        assert recipient["org_email"] == "organizer@example.com"
        assert recipient["org_name"] == "Test Organizer"
        assert recipient["reg_key"] == "NE"
        assert recipient["cc_org"] == "cc"

    def test_zip_not_found(self, sample_payload_bad_zip, minimal_zip_dict, monkeypatch):
        """Returns 'Z' error code when zip is not in lookup table."""
        monkeypatch.setattr(main, "ZIP_TO_ORG", minimal_zip_dict)
        recipient = main.parse_recipient(sample_payload_bad_zip[0])

        print(f"\n--- test_attach_organizer__zip_not_found ---")
        print(f"  Parameters : recipient zip={recipient['recipient_zip']}")
        print(f"  Input      : ZIP_TO_ORG keys={list(minimal_zip_dict.keys())}")

        error = main.attach_organizer(recipient)

        print(f"  Output     : error={error!r}")

        assert error == "Z"
        assert "org_email" not in recipient


# ─── _build_welcome_email ──────────────────────────────────────────────────────

class TestBuildWelcomeEmail:

    def test_email_structure(self, parsed_recipient):
        """Builds a valid SendGrid request body with correct fields."""
        print(f"\n--- test_build_welcome_email__structure ---")
        print(f"  Parameters : recipient first={parsed_recipient['recipient_first_name']!r}, "
              f"email={parsed_recipient['recipient_email']!r}")
        print(f"  Input      : parsed_recipient with org info attached")

        result = main._build_welcome_email(parsed_recipient)

        print(f"  Output     : keys={list(result.keys())}, "
              f"subject={result['personalizations'][0].get('subject')!r}")

        assert "content" in result
        assert "from" in result
        assert "personalizations" in result
        assert parsed_recipient["recipient_first_name"] in result["personalizations"][0]["subject"]
        assert result["from"]["email"] == main.FROM_EMAIL

    def test_organizer_in_body(self, parsed_recipient):
        """Email body contains organizer name and email."""
        print(f"\n--- test_build_welcome_email__organizer_in_body ---")
        print(f"  Parameters : org_name={parsed_recipient['org_name']!r}, "
              f"org_email={parsed_recipient['org_email']!r}")
        print(f"  Input      : parsed_recipient")

        result = main._build_welcome_email(parsed_recipient)
        body = result["content"][0]["value"]

        print(f"  Output     : body snippet=...{body[200:400]}...")

        assert parsed_recipient["org_name"] in body
        assert parsed_recipient["org_email"] in body

    def test_cc_org_applied(self, parsed_recipient):
        """Organizer is cc'd when cc_org='cc'."""
        parsed_recipient["cc_org"] = "cc"

        print(f"\n--- test_build_welcome_email__cc_org ---")
        print(f"  Parameters : cc_org='cc', org_email={parsed_recipient['org_email']!r}")
        print(f"  Input      : parsed_recipient with cc_org='cc'")

        result = main._build_welcome_email(parsed_recipient)
        personalization = result["personalizations"][0]

        print(f"  Output     : cc={personalization.get('cc')}")

        assert "cc" in personalization
        assert any(e["email"] == parsed_recipient["org_email"] for e in personalization["cc"])

    def test_bcc_org_applied(self, parsed_recipient):
        """Organizer is bcc'd when cc_org='bcc'."""
        parsed_recipient["cc_org"] = "bcc"

        print(f"\n--- test_build_welcome_email__bcc_org ---")
        print(f"  Parameters : cc_org='bcc', org_email={parsed_recipient['org_email']!r}")
        print(f"  Input      : parsed_recipient with cc_org='bcc'")

        result = main._build_welcome_email(parsed_recipient)
        personalization = result["personalizations"][0]

        print(f"  Output     : bcc={personalization.get('bcc')}")

        assert "bcc" in personalization
        assert any(e["email"] == parsed_recipient["org_email"] for e in personalization["bcc"])


# ─── process_recipient (integration) ──────────────────────────────────────────

class TestProcessRecipient:

    def test_bad_zip_returns_400(self, sample_payload_bad_zip, minimal_zip_dict, monkeypatch):
        """Full pipeline returns 400 when zip is not found."""
        monkeypatch.setattr(main, "ZIP_TO_ORG", minimal_zip_dict)
        monkeypatch.setattr(main, "SEND_RECIPIENT_EMAILS", True)
        recipient = main.parse_recipient(sample_payload_bad_zip[0])

        print(f"\n--- test_process_recipient__bad_zip ---")
        print(f"  Parameters : recipient zip={recipient['recipient_zip']}")
        print(f"  Input      : zip not present in ZIP_TO_ORG")

        msg, status = main.process_recipient(recipient)

        print(f"  Output     : msg={msg!r}, status={status}")

        assert status == 400
        assert "Skipped" in msg

    def test_email_disabled_returns_200(self, sample_payload, minimal_zip_dict, monkeypatch):
        """Full pipeline returns 200 without sending when SEND_RECIPIENT_EMAILS=False."""
        monkeypatch.setattr(main, "ZIP_TO_ORG", minimal_zip_dict)
        monkeypatch.setattr(main, "SEND_RECIPIENT_EMAILS", False)
        recipient = main.parse_recipient(sample_payload[0])

        print(f"\n--- test_process_recipient__email_disabled ---")
        print(f"  Parameters : SEND_RECIPIENT_EMAILS=False")
        print(f"  Input      : valid recipient with known zip")

        msg, status = main.process_recipient(recipient)

        print(f"  Output     : msg={msg!r}, status={status}")

        assert status == 200
        assert "disabled" in msg.lower()

    @pytest.mark.integration
    def test_full_pipeline_with_mock_sendgrid(self, sample_payload, minimal_zip_dict, monkeypatch):
        """
        Integration: runs parse → attach_organizer → _send_welcome_email as a pipeline.
        Mocks the SendGrid API call but exercises all other real code paths.
        """
        monkeypatch.setattr(main, "ZIP_TO_ORG", minimal_zip_dict)
        monkeypatch.setattr(main, "SEND_RECIPIENT_EMAILS", True)
        monkeypatch.setattr(main, "ALLOWED_RECIPIENT_EMAILS", [])
        monkeypatch.setattr(main, "UPDATE_GROUP_KEY", False)

        # Mock get_secret to return a fake API key
        monkeypatch.setattr(main, "get_secret", lambda name: "SG.fake-key-for-testing")

        # Mock SendGrid client response
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_sg = MagicMock()
        mock_sg.client.mail.send.post.return_value = mock_response

        recipient = main.parse_recipient(sample_payload[0])

        print(f"\n--- test_full_pipeline_with_mock_sendgrid ---")
        print(f"  Parameters : SEND_RECIPIENT_EMAILS=True, UPDATE_GROUP_KEY=False")
        print(f"  Input      : recipient={recipient['recipient_first_name']} {recipient['recipient_last_name']} "
              f"<{recipient['recipient_email']}>, zip={recipient['recipient_zip']}")

        with patch("cfcg_an_webhook.main.SendGridAPIClient", return_value=mock_sg):
            msg, status = main.process_recipient(recipient)

        print(f"  Output     : msg={msg!r}, status={status}")
        print(f"  Output     : SendGrid called={mock_sg.client.mail.send.post.called}")

        assert status == 202
        assert recipient["recipient_email"] in msg
        assert mock_sg.client.mail.send.post.called


# ─── webhook endpoint (integration) ───────────────────────────────────────────

class TestWebhookEndpoint:

    @pytest.fixture
    def client(self, minimal_zip_dict, monkeypatch):
        """Flask test client with mocked dependencies."""
        monkeypatch.setattr(main, "ZIP_TO_ORG", minimal_zip_dict)
        monkeypatch.setattr(main, "SEND_RECIPIENT_EMAILS", False)
        main.app.config["TESTING"] = True
        with main.app.test_client() as client:
            yield client

    def test_rejects_non_list_payload(self, client):
        """Returns 400 when payload is a dict instead of a list."""
        payload = {"bad": "payload"}

        print(f"\n--- test_webhook__rejects_non_list ---")
        print(f"  Parameters : POST /webhook")
        print(f"  Input      : payload={payload}")

        response = client.post("/webhook", json=payload)

        print(f"  Output     : status={response.status_code}, body={response.get_json()}")

        assert response.status_code == 400

    def test_rejects_missing_sponsor(self, client):
        """Returns 400 when action_network:sponsor is absent."""
        payload = [{"idempotency_key": "x"}]

        print(f"\n--- test_webhook__rejects_missing_sponsor ---")
        print(f"  Parameters : POST /webhook")
        print(f"  Input      : payload={payload}")

        response = client.post("/webhook", json=payload)

        print(f"  Output     : status={response.status_code}, body={response.get_json()}")

        assert response.status_code == 400

    @pytest.mark.integration
    def test_valid_payload_processed(self, client, sample_payload, minimal_zip_dict, monkeypatch):
        """
        Integration: valid payload flows through the full webhook handler.
        Email sending is disabled; verifies parsing, zip lookup, and response shape.
        """
        monkeypatch.setattr(main, "ZIP_TO_ORG", minimal_zip_dict)
        monkeypatch.setattr(main, "SEND_RECIPIENT_EMAILS", False)

        print(f"\n--- test_webhook__valid_payload ---")
        print(f"  Parameters : POST /webhook, SEND_RECIPIENT_EMAILS=False")
        print(f"  Input      : {len(sample_payload)} record(s), zip=12207")

        response = client.post("/webhook", json=sample_payload)
        body = response.get_json()

        print(f"  Output     : status={response.status_code}, body={body}")

        assert response.status_code == 200
        assert body["processed"] == 1
        assert body["results"][0]["email"] == "jane.smith@example.com"


# ─── parse_recipient edge cases ───────────────────────────────────────────────

class TestParseRecipientEdgeCases:

    def test_primary_email_not_first(self, sample_payload_multiple_contacts):
        """Primary email is second in list — must pick it, not index [0]."""
        record = sample_payload_multiple_contacts[0]

        print(f"\n--- test_primary_email_not_first ---")
        print(f"  Parameters : record with 2 emails, primary is index [1]")
        print(f"  Input      : emails={record['osdi:attendance']['person']['email_addresses']}")

        result = main.parse_recipient(record)

        print(f"  Output     : recipient_email={result['recipient_email']!r}")

        assert result["recipient_email"] == "jane.smith@example.com"

    def test_primary_phone_not_first(self, sample_payload_multiple_contacts):
        """Primary phone is second in list — must pick it, not index [0]."""
        record = sample_payload_multiple_contacts[0]

        print(f"\n--- test_primary_phone_not_first ---")
        print(f"  Parameters : record with 2 phones, primary is index [1]")
        print(f"  Input      : phones={record['osdi:attendance']['person']['phone_numbers']}")

        result = main.parse_recipient(record)

        print(f"  Output     : recipient_phone={result['recipient_phone']!r}, "
              f"type={result['recipient_phone_type']!r}")

        assert result["recipient_phone"] == "555-867-5309"
        assert result["recipient_phone_type"] == "Mobile"

    def test_primary_address_not_first(self, sample_payload_multiple_contacts):
        """Primary address is second in list — must pick it, not index [0]."""
        record = sample_payload_multiple_contacts[0]

        print(f"\n--- test_primary_address_not_first ---")
        print(f"  Parameters : record with 2 addresses, primary is index [1]")
        print(f"  Input      : addresses={record['osdi:attendance']['person']['postal_addresses']}")

        result = main.parse_recipient(record)

        print(f"  Output     : zip={result['recipient_zip']}, city={result['recipient_city']!r}, "
              f"address={result['recipient_address']!r}")

        assert result["recipient_zip"] == 12207
        assert result["recipient_city"] == "Albany"
        assert result["recipient_address"] == "123 Main St"

    def test_zip_plus_4_stripped(self, sample_payload):
        """ZIP+4 format '12207-1234' should parse to integer 12207."""
        record = sample_payload[0]
        record["osdi:attendance"]["person"]["postal_addresses"][0]["postal_code"] = "12207-1234"

        print(f"\n--- test_zip_plus_4_stripped ---")
        print(f"  Parameters : postal_code='12207-1234'")
        print(f"  Input      : raw ZIP+4 string")

        result = main.parse_recipient(record)

        print(f"  Output     : recipient_zip={result['recipient_zip']}, "
              f"zip_raw={result['recipient_zip_raw']!r}")

        assert result["recipient_zip"] == 12207
        assert result["recipient_zip_raw"] == "12207-1234"

    def test_unknown_osdi_type_still_parses(self, sample_payload):
        """Type not in OSDI_TYPE_CONFIG logs a warning but still parses the record."""
        record = sample_payload[0]
        # Replace osdi:attendance with an unknown type
        record["osdi:unknown_future_type"] = record.pop("osdi:attendance")

        print(f"\n--- test_unknown_osdi_type_still_parses ---")
        print(f"  Parameters : record with osdi:unknown_future_type key")
        print(f"  Input      : {list(record.keys())}")

        result = main.parse_recipient(record)

        print(f"  Output     : json_type={result['json_type']!r}, "
              f"email={result['recipient_email']!r}")

        assert result["json_type"] == "unknown_future_type"
        assert result["recipient_email"] == "jane.smith@example.com"

    def test_schema_canary(self):
        """Every expected output key is always present, even on a completely minimal payload.

        This test is the safety net — if parse_recipient ever drops a key (due to a
        code change or unexpected payload structure), this will catch it immediately.
        """
        minimal_record = {
            "idempotency_key": "x",
            "action_network:sponsor": {},
            "osdi:attendance": {},
        }
        expected_keys = {
            "idempotency_key", "json_type", "person_id", "created_date", "modified_date",
            "recipient_first_name", "recipient_last_name", "recipient_email",
            "recipient_phone", "recipient_phone_type", "recipient_address",
            "recipient_city", "recipient_state", "recipient_zip_raw",
            "recipient_zip", "custom_fields",
        }

        print(f"\n--- test_schema_canary ---")
        print(f"  Parameters : minimal record with empty osdi:attendance")
        print(f"  Input      : {minimal_record}")

        result = main.parse_recipient(minimal_record)

        print(f"  Output     : keys={sorted(result.keys())}")

        missing = expected_keys - set(result.keys())
        assert not missing, f"parse_recipient is missing expected keys: {missing}"


# ─── process_recipient: empty email guard ─────────────────────────────────────

class TestProcessRecipientValidation:

    def test_no_email_returns_400(self, sample_payload_no_email, minimal_zip_dict, monkeypatch):
        """Person with no email address is skipped — must not reach SendGrid."""
        monkeypatch.setattr(main, "ZIP_TO_ORG", minimal_zip_dict)
        monkeypatch.setattr(main, "SEND_RECIPIENT_EMAILS", True)

        # Give the no-email payload a valid zip so it passes the zip check
        addr = sample_payload_no_email[0]["osdi:attendance"]["person"]["postal_addresses"][0]
        addr["postal_code"] = "12207"
        recipient = main.parse_recipient(sample_payload_no_email[0])

        print(f"\n--- test_no_email_returns_400 ---")
        print(f"  Parameters : SEND_RECIPIENT_EMAILS=True")
        print(f"  Input      : recipient with empty email_addresses list, valid zip")

        msg, status = main.process_recipient(recipient)

        print(f"  Output     : msg={msg!r}, status={status}")

        assert status == 400
        assert "no email" in msg.lower()

    def test_send_email_false_skips_email(self, sample_payload, minimal_zip_dict, monkeypatch):
        """Type with send_email=False (signature) is skipped without calling SendGrid."""
        # Change payload type to signature
        sample_payload[0]["osdi:signature"] = sample_payload[0].pop("osdi:attendance")
        monkeypatch.setattr(main, "ZIP_TO_ORG", minimal_zip_dict)
        monkeypatch.setattr(main, "SEND_RECIPIENT_EMAILS", True)
        recipient = main.parse_recipient(sample_payload[0])

        print(f"\n--- test_send_email_false_skips_email ---")
        print(f"  Parameters : json_type='signature', send_email=False in OSDI_TYPE_CONFIG")
        print(f"  Input      : recipient json_type={recipient['json_type']!r}, zip={recipient['recipient_zip']}")

        msg, status = main.process_recipient(recipient)

        print(f"  Output     : msg={msg!r}, status={status}")

        assert status == 200
        assert "send_email=False" in msg

    def test_send_email_true_proceeds(self, sample_payload, minimal_zip_dict, monkeypatch):
        """Type with send_email=True (attendance) proceeds to the email step."""
        monkeypatch.setattr(main, "ZIP_TO_ORG", minimal_zip_dict)
        monkeypatch.setattr(main, "SEND_RECIPIENT_EMAILS", False)  # disable actual send
        recipient = main.parse_recipient(sample_payload[0])

        print(f"\n--- test_send_email_true_proceeds ---")
        print(f"  Parameters : json_type='attendance', send_email=True in OSDI_TYPE_CONFIG")
        print(f"  Input      : recipient json_type={recipient['json_type']!r}")

        msg, status = main.process_recipient(recipient)

        print(f"  Output     : msg={msg!r}, status={status}")

        # Reaches the SEND_RECIPIENT_EMAILS check (not blocked by send_email=False)
        assert msg == "Email sending disabled"
        assert status == 200

    def test_unknown_type_no_email_and_notifies(self, sample_payload, minimal_zip_dict, monkeypatch):
        """Type not in OSDI_TYPE_CONFIG: no email sent, notification fired if enabled."""
        sample_payload[0]["osdi:unknown_type"] = sample_payload[0].pop("osdi:attendance")
        monkeypatch.setattr(main, "ZIP_TO_ORG", minimal_zip_dict)
        monkeypatch.setattr(main, "SEND_RECIPIENT_EMAILS", True)
        monkeypatch.setattr(main, "SEND_NOTIFICATION_EMAILS", True)

        notified = {}
        def mock_notify(subject, message):
            notified["subject"] = subject
            notified["message"] = message
        monkeypatch.setattr(main, "_send_notification", mock_notify)

        recipient = main.parse_recipient(sample_payload[0])

        print(f"\n--- test_unknown_type_no_email_and_notifies ---")
        print(f"  Parameters : json_type='unknown_type', SEND_NOTIFICATION_EMAILS=True")
        print(f"  Input      : recipient json_type={recipient['json_type']!r}")

        msg, status = main.process_recipient(recipient)

        print(f"  Output     : msg={msg!r}, status={status}")
        print(f"  Output     : notification subject={notified.get('subject')!r}")
        print(f"  Output     : notification message={notified.get('message')!r}")

        assert status == 200
        assert "unknown type" in msg.lower()
        assert "subject" in notified, "Expected notification to be sent"
        assert "unknown_type" in notified["subject"]
        assert "OSDI_TYPE_CONFIG" in notified["message"]


# ─── webhook endpoint: additional edge cases ──────────────────────────────────

class TestWebhookEdgeCases:

    @pytest.fixture
    def client(self, minimal_zip_dict, monkeypatch):
        """Flask test client with email sending disabled."""
        monkeypatch.setattr(main, "ZIP_TO_ORG", minimal_zip_dict)
        monkeypatch.setattr(main, "SEND_RECIPIENT_EMAILS", False)
        main.app.config["TESTING"] = True
        with main.app.test_client() as client:
            yield client

    def test_empty_list_rejected(self, client):
        """Empty list [] is rejected — no action_network:sponsor to check."""
        payload = []

        print(f"\n--- test_empty_list_rejected ---")
        print(f"  Parameters : POST /webhook")
        print(f"  Input      : payload=[]")

        response = client.post("/webhook", json=payload)

        print(f"  Output     : status={response.status_code}, body={response.get_json()}")

        assert response.status_code == 400

    @pytest.mark.integration
    def test_multiple_records_processed(self, client, sample_payload, minimal_zip_dict, monkeypatch):
        """
        Integration: batch payload with 2 records — both are processed and
        reported in results. Email sending is disabled.
        """
        monkeypatch.setattr(main, "ZIP_TO_ORG", minimal_zip_dict)
        monkeypatch.setattr(main, "SEND_RECIPIENT_EMAILS", False)

        # Build a second record with a different email
        record2 = sample_payload[0].copy()
        record2["idempotency_key"] = "second-key"
        record2["osdi:attendance"] = {
            **sample_payload[0]["osdi:attendance"],
            "person": {
                **sample_payload[0]["osdi:attendance"]["person"],
                "given_name": "Bob",
                "family_name": "Jones",
                "email_addresses": [{"address": "bob.jones@example.com", "primary": True}],
            },
        }
        batch_payload = [sample_payload[0], record2]

        print(f"\n--- test_multiple_records_processed ---")
        print(f"  Parameters : POST /webhook, SEND_RECIPIENT_EMAILS=False")
        print(f"  Input      : batch of {len(batch_payload)} records")

        response = client.post("/webhook", json=batch_payload)
        body = response.get_json()

        print(f"  Output     : status={response.status_code}, processed={body.get('processed')}")
        print(f"  Output     : results={body.get('results')}")

        assert response.status_code == 200
        assert body["processed"] == 2
        emails = [r["email"] for r in body["results"]]
        assert "jane.smith@example.com" in emails
        assert "bob.jones@example.com" in emails


# ─── Snapshot: catches Action Network payload format changes ──────────────────

@pytest.mark.integration
class TestSnapshotParsing:

    def test_snapshot_parse_output(self, real_an_snapshot):
        """
        Integration: parses a fixed realistic AN payload and asserts the output
        matches exactly. If Action Network changes their payload structure,
        this test will fail and show precisely what changed.

        To update the snapshot: edit the `expected` dict below to match the
        new output, then verify the change is intentional.
        """
        record = real_an_snapshot[0]

        expected = {
            "idempotency_key":      "snapshot-key-abc123",
            "json_type":            "attendance",
            "person_id":            "snapshot-person-id",
            "recipient_first_name": "Robert",
            "recipient_last_name":  "Johnson",
            "recipient_email":      "robert.johnson@example.com",
            "recipient_phone":      "404-555-1212",
            "recipient_phone_type": "Mobile",
            "recipient_address":    "456 Peachtree St Ne",
            "recipient_city":       "Atlanta",
            "recipient_state":      "GA",
            "recipient_zip_raw":    "30308",
            "recipient_zip":        30308,
            "custom_fields":        ["volunteer: Yes"],
        }

        print(f"\n--- test_snapshot_parse_output ---")
        print(f"  Parameters : (none — uses real_an_snapshot fixture)")
        print(f"  Input      : {record['osdi:attendance']['person']['given_name']} "
              f"{record['osdi:attendance']['person']['family_name']}, zip=30308")

        result = main.parse_recipient(record)

        print(f"  Output     : {result}")

        for key, exp_val in expected.items():
            assert result[key] == exp_val, (
                f"Snapshot mismatch on key {key!r}: "
                f"expected {exp_val!r}, got {result[key]!r}"
            )


# ─── External service: GCS zip dict load (integration) ────────────────────────

class TestLoadZipDict:

    @pytest.mark.integration
    @pytest.mark.skipif(
        not os.environ.get("GCS_BUCKET"),
        reason="GCS_BUCKET not set — skipping live GCS test"
    )
    def test_load_from_gcs(self):
        """
        Integration: downloads zip_dict.json from the real GCS bucket and
        validates structure. Requires GCS_BUCKET env var and valid GCP credentials.
        """
        bucket = os.environ.get("GCS_BUCKET")

        print(f"\n--- test_load_zip_dict__from_gcs ---")
        print(f"  Parameters : (none — uses GCS_BUCKET env var)")
        print(f"  Input      : GCS_BUCKET={bucket!r}")

        # Temporarily rename local file if it exists so GCS path is triggered
        import pathlib
        local_path = pathlib.Path(__file__).parent.parent / "zip_dict.json"
        temp_path = local_path.with_suffix(".json.bak")
        renamed = False
        if local_path.exists():
            local_path.rename(temp_path)
            renamed = True

        try:
            result = main.load_zip_dict()
            print(f"  Output     : loaded {len(result):,} zip codes")
            print(f"  Output     : sample entry={next(iter(result.items()))}")
            assert len(result) > 1000
            sample = next(iter(result.values()))
            for field in main.ZIP_DICT_FIELDS:
                assert field in sample, f"Missing field: {field}"
        finally:
            if renamed:
                temp_path.rename(local_path)


# ─── External service: SendGrid live send (integration) ───────────────────────

class TestSendGridLive:

    @pytest.mark.integration
    @pytest.mark.skipif(
        not os.environ.get("CLOUD_PROJECT_ID"),
        reason="CLOUD_PROJECT_ID not set — skipping live SendGrid test"
    )
    def test_send_real_email(self, parsed_recipient, monkeypatch):
        """
        Integration: sends a real email via SendGrid using live credentials
        from Secret Manager. Only runs when CLOUD_PROJECT_ID is set and
        recipient is in ALLOWED_RECIPIENT_EMAILS.

        WARNING: sends an actual email. Use a test address in ALLOWED_RECIPIENT_EMAILS.
        """
        test_email = os.environ.get("ALLOWED_RECIPIENT_EMAILS", "").split(",")[0].strip()
        if not test_email:
            pytest.skip("ALLOWED_RECIPIENT_EMAILS not set — no safe test address available")

        parsed_recipient["recipient_email"] = test_email
        monkeypatch.setattr(main, "ALLOWED_RECIPIENT_EMAILS", [test_email])
        monkeypatch.setattr(main, "SEND_RECIPIENT_EMAILS", True)

        print(f"\n--- test_send_real_email ---")
        print(f"  Parameters : SEND_RECIPIENT_EMAILS=True")
        print(f"  Input      : recipient_email={test_email!r}, "
              f"org_name={parsed_recipient['org_name']!r}")
        print(f"  Calling    : SendGrid API (live)")

        msg, status = main._send_welcome_email(parsed_recipient)

        print(f"  Output     : msg={msg!r}, status={status}")

        assert status in (200, 202), f"Unexpected SendGrid status: {status}"


# ─── External service: Action Network update (integration) ────────────────────

class TestActionNetworkLive:

    @pytest.mark.integration
    @pytest.mark.skipif(
        not os.environ.get("CLOUD_PROJECT_ID"),
        reason="CLOUD_PROJECT_ID not set — skipping live Action Network test"
    )
    def test_update_group_key_live(self):
        """
        Integration: sends a real PUT request to Action Network to update
        group_key on a test person record. Requires a valid AN_WEBHOOK_KEY
        in Secret Manager and a known test person_id.

        Set TEST_AN_PERSON_ID in .env to a real person UUID for this test to run.
        """
        person_id = os.environ.get("TEST_AN_PERSON_ID")
        if not person_id:
            pytest.skip("TEST_AN_PERSON_ID not set — skipping live Action Network test")

        group_key = "NE"

        print(f"\n--- test_update_group_key_live ---")
        print(f"  Parameters : group_key={group_key!r}, person_id={person_id!r}")
        print(f"  Input      : (no payload — direct API call)")
        print(f"  Calling    : Action Network API PUT /people/{person_id}")

        # Should not raise
        main.update_group_key(group_key, person_id)

        print(f"  Output     : completed without error (check Action Network to confirm)")


# ─── Payload file coverage check ──────────────────────────────────────────────

class TestPayloadCoverage:

    def test_all_osdi_types_have_payload_files(self):
        """Every parsed=True type in OSDI_TYPE_CONFIG must have a payload file in tests/payloads/.

        Fails immediately if a verified type is added to OSDI_TYPE_CONFIG without
        a corresponding payload file, making the gap visible.
        Only checks parsed=True types — unverified types (parsed=False) don't have files yet.
        """
        payloads_dir = pathlib.Path(__file__).parent / "payloads"
        parsed_types = {t for t, cfg in main.OSDI_TYPE_CONFIG.items() if cfg["parsed"]}

        print(f"\n--- test_all_osdi_types_have_payload_files ---")
        print(f"  Parameters : (none)")
        print(f"  Input      : parsed types={sorted(parsed_types)}")

        missing = []
        for osdi_type in parsed_types:
            path = payloads_dir / f"{osdi_type}.json"
            if not path.exists():
                missing.append(osdi_type)

        print(f"  Output     : payload files found={sorted(parsed_types - set(missing))}")
        if missing:
            print(f"  Output     : MISSING={missing}")

        assert not missing, (
            f"No payload file for osdi type(s): {missing}. "
            f"Add tests/payloads/<type>.json with a captured AN payload for each."
        )

    def test_synthetic_payloads_flagged(self):
        """Report which payload files are still synthetic placeholders.

        Does NOT fail — just prints a warning so you know which types still
        need real captured payload data. Replace synthetic files by copying
        a real AN webhook payload into the corresponding JSON file.
        """
        payloads_dir = pathlib.Path(__file__).parent / "payloads"

        print(f"\n--- test_synthetic_payloads_flagged ---")
        print(f"  Parameters : (none)")
        print(f"  Input      : payload files in {payloads_dir}")

        import json
        synthetic = []
        real = []
        for osdi_type in sorted(t for t, cfg in main.OSDI_TYPE_CONFIG.items() if cfg["parsed"]):
            path = payloads_dir / f"{osdi_type}.json"
            if path.exists():
                data = json.loads(path.read_text())
                is_synthetic = data[0].get("_synthetic", False) if data else True
                (synthetic if is_synthetic else real).append(osdi_type)

        print(f"  Output     : real payloads    = {real}")
        print(f"  Output     : synthetic (TODO) = {synthetic}")

        if synthetic:
            import warnings
            warnings.warn(
                f"\nSynthetic payload files still need real AN data: {synthetic}\n"
                f"Capture a real webhook and replace the contents of "
                f"tests/payloads/<type>.json for each.",
                UserWarning,
                stacklevel=2,
            )


# ─── Payload file parse tests ─────────────────────────────────────────────────

class TestPayloadFileParsing:
    """Parse each payload file through parse_recipient() and assert schema is valid.

    These tests catch two things:
    1. The payload files themselves are well-formed (not broken JSON/structure)
    2. parse_recipient() can handle each osdi: type without crashing

    When you replace a synthetic payload with a real one, these tests
    confirm the real payload parses correctly.
    """

    EXPECTED_KEYS = {
        "idempotency_key", "json_type", "person_id", "created_date", "modified_date",
        "recipient_first_name", "recipient_last_name", "recipient_email",
        "recipient_phone", "recipient_phone_type", "recipient_address",
        "recipient_city", "recipient_state", "recipient_zip_raw",
        "recipient_zip", "custom_fields",
    }

    def _assert_parses(self, payload: list, osdi_type: str):
        record = payload[0]
        print(f"\n--- test_payload_file_parses: {osdi_type} ---")
        print(f"  Parameters : osdi_type={osdi_type!r}")
        print(f"  Input      : payload keys={list(record.keys())}")

        result = main.parse_recipient(record)

        print(f"  Output     : json_type={result['json_type']!r}, "
              f"email={result['recipient_email']!r}, zip={result['recipient_zip']}")

        missing_keys = self.EXPECTED_KEYS - set(result.keys())
        assert not missing_keys, f"parse_recipient missing keys for {osdi_type}: {missing_keys}"
        assert result["json_type"] == osdi_type, (
            f"Expected json_type={osdi_type!r}, got {result['json_type']!r}"
        )

    def test_attendance_payload_parses(self, payload_attendance):
        self._assert_parses(payload_attendance, "attendance")

    def test_submission_payload_parses(self, payload_submission):
        self._assert_parses(payload_submission, "submission")

    def test_signature_payload_parses(self, payload_signature):
        self._assert_parses(payload_signature, "signature")

    def test_donation_payload_parses(self, payload_donation):
        self._assert_parses(payload_donation, "donation")
