"""
Tests for cfcg_an_webhook/main.py

Run all:            pytest tests/ -s
Run integration:    pytest tests/ -s -m integration
Run unit only:      pytest tests/ -s -m "not integration"

SKIPPED (too simple to test):
  - to_zip5: single expression, no branching — covered implicitly via parse_recipient tests
  - _add_copy_emails: thin list-append helper — covered implicitly via _build_welcome_email tests
  - health: one-liner Flask route returning a static dict
"""

import os
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
