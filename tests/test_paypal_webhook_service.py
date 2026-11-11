import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock

from src.paypal_webhook_service import (
    PayPalWebhookService,
    PayPalWebhookError
)


class TestPayPalWebhookService(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(
            Path(self.temp_dir.name) / "webhook_test.db"
        )

        self.verify_fn = Mock(return_value=True)
        self.handler = Mock()

        self.service = PayPalWebhookService(
            verify_webhook_fn=self.verify_fn,
            event_handler=self.handler,
            db_path=self.db_path
        )

        self.headers = {
            "PAYPAL-TRANSMISSION-ID": "transmission_001",
            "PAYPAL-TRANSMISSION-TIME": "2026-11-08T10:00:00Z",
            "PAYPAL-CERT-URL": "https://example.com/cert",
            "PAYPAL-AUTH-ALGO": "SHA256withRSA",
            "PAYPAL-TRANSMISSION-SIG": "test_signature"
        }

        self.event = {
            "id": "WH-EVENT-001",
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "resource_type": "capture",
            "resource": {
                "id": "CAPTURE-001",
                "status": "COMPLETED"
            }
        }

        self.raw_body = json.dumps(self.event)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_verified_event_is_processed(self):
        result = self.service.receive(
            self.headers,
            self.raw_body
        )

        self.verify_fn.assert_called_once()
        self.handler.assert_called_once_with(self.event)

        self.assertTrue(result["processed"])
        self.assertEqual(result["status"], "PROCESSED")

        stored = self.service.get_event("WH-EVENT-001")
        self.assertEqual(stored["status"], "PROCESSED")

    def test_invalid_signature_is_rejected(self):
        self.verify_fn.return_value = False

        with self.assertRaises(PayPalWebhookError):
            self.service.receive(
                self.headers,
                self.raw_body
            )

        self.handler.assert_not_called()
        self.assertIsNone(
            self.service.get_event("WH-EVENT-001")
        )

    def test_duplicate_event_is_not_processed_twice(self):
        self.service.receive(
            self.headers,
            self.raw_body
        )

        self.handler.reset_mock()

        result = self.service.receive(
            self.headers,
            self.raw_body
        )

        self.handler.assert_not_called()
        self.assertEqual(result["status"], "DUPLICATE")

    def test_missing_required_header_is_rejected(self):
        headers = self.headers.copy()
        headers.pop("PAYPAL-TRANSMISSION-SIG")

        with self.assertRaises(PayPalWebhookError):
            self.service.receive(headers, self.raw_body)

        self.verify_fn.assert_not_called()
        self.handler.assert_not_called()

    def test_invalid_json_is_rejected(self):
        with self.assertRaises(PayPalWebhookError):
            self.service.receive(
                self.headers,
                "{invalid json"
            )

        self.verify_fn.assert_not_called()
        self.handler.assert_not_called()

    def test_missing_event_id_is_rejected(self):
        event = self.event.copy()
        event.pop("id")

        with self.assertRaises(PayPalWebhookError):
            self.service.receive(
                self.headers,
                json.dumps(event)
            )

        self.verify_fn.assert_not_called()

    def test_handler_failure_is_recorded(self):
        self.handler.side_effect = RuntimeError(
            "Simulated processing failure"
        )

        with self.assertRaises(PayPalWebhookError):
            self.service.receive(
                self.headers,
                self.raw_body
            )

        stored = self.service.get_event("WH-EVENT-001")

        self.assertEqual(stored["status"], "FAILED")
        self.assertIn(
            "Simulated processing failure",
            stored["last_error"]
        )

    def test_failed_event_can_be_retried(self):
        self.handler.side_effect = RuntimeError("Temporary failure")

        with self.assertRaises(PayPalWebhookError):
            self.service.receive(
                self.headers,
                self.raw_body
            )

        self.handler.side_effect = None
        self.handler.reset_mock()

        result = self.service.receive(
            self.headers,
            self.raw_body
        )

        self.handler.assert_called_once()
        self.assertEqual(result["status"], "PROCESSED")

        stored = self.service.get_event("WH-EVENT-001")
        self.assertEqual(stored["status"], "PROCESSED")

    def test_stale_processing_event_can_be_reclaimed(self):
        self.service.receive(self.headers, self.raw_body)
        self.handler.reset_mock()

        old_timestamp = (
            datetime.now(timezone.utc) - timedelta(minutes=10)
        ).isoformat()

        with self.service._connect() as connection:
            connection.execute(
                """
                UPDATE paypal_webhook_events
                SET status = 'PROCESSING',
                    processing_started_at = ?,
                    claim_token = 'old-worker'
                WHERE event_id = ?
                """,
                (old_timestamp, "WH-EVENT-001")
            )

        result = self.service.receive(self.headers, self.raw_body)

        self.handler.assert_called_once_with(self.event)
        self.assertEqual(result["status"], "PROCESSED")

    def test_active_processing_event_is_not_reclaimed(self):
        self.service.receive(self.headers, self.raw_body)
        self.handler.reset_mock()

        with self.service._connect() as connection:
            connection.execute(
                """
                UPDATE paypal_webhook_events
                SET status = 'PROCESSING',
                    processing_started_at = ?,
                    claim_token = 'active-worker'
                WHERE event_id = ?
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    "WH-EVENT-001"
                )
            )

        result = self.service.receive(self.headers, self.raw_body)

        self.handler.assert_not_called()
        self.assertEqual(result["status"], "DUPLICATE")

    def test_legacy_processing_event_without_timestamp_is_not_reclaimed(self):
        self.service.receive(self.headers, self.raw_body)
        self.handler.reset_mock()

        with self.service._connect() as connection:
            connection.execute(
                """
                UPDATE paypal_webhook_events
                SET status = 'PROCESSING',
                    processing_started_at = NULL,
                    claim_token = NULL
                WHERE event_id = ?
                """,
                ("WH-EVENT-001",)
            )

        result = self.service.receive(self.headers, self.raw_body)

        self.handler.assert_not_called()
        self.assertEqual(result["status"], "DUPLICATE")

    def test_old_worker_cannot_mark_reclaimed_event_processed(self):
        self.service.receive(self.headers, self.raw_body)

        with self.service._connect() as connection:
            connection.execute(
                """
                UPDATE paypal_webhook_events
                SET status = 'PROCESSING',
                    processing_started_at = ?,
                    claim_token = 'new-worker'
                WHERE event_id = ?
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    "WH-EVENT-001"
                )
            )

        with self.assertRaises(PayPalWebhookError):
            self.service._mark_processed(
                "WH-EVENT-001",
                "old-worker"
            )

        stored = self.service.get_event("WH-EVENT-001")
        self.assertEqual(stored["status"], "PROCESSING")
        self.assertEqual(stored["claim_token"], "new-worker")

    def test_event_is_not_processed_when_verification_raises(self):
        self.verify_fn.side_effect = RuntimeError(
            "Verification service unavailable"
        )

        with self.assertRaises(PayPalWebhookError):
            self.service.receive(
                self.headers,
                self.raw_body
            )

        self.handler.assert_not_called()
        self.assertIsNone(
            self.service.get_event("WH-EVENT-001")
        )


if __name__ == "__main__":
    unittest.main()
