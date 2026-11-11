import tempfile
import unittest
from pathlib import Path

from src.trusted_feature_provider import TrustedFeatureProvider, TrustedFeatureError
from src.appeal_service import AppealService, AppealError
from src.audit_service import AuditService


class CommonsServicesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_legacy_unverified_context_is_rejected(self):
        provider = TrustedFeatureProvider(self.db_path)
        provider.record_order_context("tx-001", "agent-001", "merchant-001", "electronics")
        with self.assertRaises(TrustedFeatureError):
            provider({"transaction_id": "tx-001", "amount_minor": 5000, "mandate_cap": 100})

    def test_unavailable_order_context_is_rejected(self):
        provider = TrustedFeatureProvider(self.db_path)
        with self.assertRaises(TrustedFeatureError):
            provider({"transaction_id": "missing", "amount_minor": 5000, "mandate_cap": 100})

    def test_payment_retry_count_increments(self):
        provider = TrustedFeatureProvider(self.db_path)
        provider.record_order_context("tx-002", "agent-002", "merchant-001", "books")
        provider.record_payment_retry("tx-002")
        provider.record_payment_retry("tx-002")
        with provider._connect() as db:
            row = db.execute("SELECT payment_retry_count FROM commons_order_context WHERE transaction_id=?", ("tx-002",)).fetchone()
        self.assertEqual(row["payment_retry_count"], 2)

    def test_shared_agent_flag_count_is_persisted(self):
        provider = TrustedFeatureProvider(self.db_path)
        provider.record_order_context("tx-003", "agent-003", "merchant-001", "books")
        provider.set_shared_agent_flag_count("tx-003", 3)
        with provider._connect() as db:
            row = db.execute("SELECT shared_agent_flag_count FROM commons_order_context WHERE transaction_id=?", ("tx-003",)).fetchone()
        self.assertEqual(row["shared_agent_flag_count"], 3)

    def test_appeal_submission_and_review(self):
        service = AppealService(self.db_path)
        appeal = service.submit("tx-004", "merchant-001", "The order was incorrectly held.", "Order verification documents.")
        self.assertEqual(appeal["status"], "SUBMITTED")
        reviewed = service.review(appeal["appeal_id"], "APPROVED", "Evidence reviewed.")
        self.assertEqual(reviewed["status"], "APPROVED")

    def test_duplicate_active_appeal_is_rejected(self):
        service = AppealService(self.db_path)
        service.submit("tx-005", "merchant-001", "Please review this order.")
        with self.assertRaises(AppealError):
            service.submit("tx-005", "merchant-001", "Submitting another appeal.")

    def test_audit_chain_verifies_after_multiple_events(self):
        service = AuditService(self.db_path)
        service.record("ORDER_CREATED", {"amount": 50}, "tx-006")
        service.record("RISK_EVALUATED", {"decision": "HOLD"}, "tx-006")
        service.record("APPEAL_SUBMITTED", {"reason": "Review requested"}, "tx-006")
        self.assertTrue(service.verify_chain())
        self.assertEqual(len(service.list_events()), 3)

    def test_audit_chain_detects_payload_tampering(self):
        service = AuditService(self.db_path)
        service.record("ORDER_CREATED", {"amount": 50}, "tx-007")
        with service._connect() as db:
            db.execute("UPDATE audit_events SET payload=? WHERE transaction_id=?", ('{"amount":999}', "tx-007"))
        self.assertFalse(service.verify_chain())


if __name__ == "__main__":
    unittest.main()
