import tempfile
import unittest

from pathlib import Path

from src.mandate_store import MandateStore
from src.payment_store import PaymentStore, PaymentStoreError


class TestPaymentStore(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"

        self.mandate_store = MandateStore(self.db_path)
        self.payment_store = PaymentStore(self.db_path)

        self.mandate_store.register_mandate({
            "mandate_id": "MANDATE001",
            "max_transactions": 3,
            "max_total_spending": 500,
            "max_transaction_amount": 300
        })

        self.mandate_store.reserve(
            "MANDATE001",
            "NONCE001",
            100,
            "RES001"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_payment_transaction(self):
        result = self.payment_store.create_transaction(
            "RES001",
            100,
            "USD",
            "TXN001"
        )

        self.assertEqual(result["transaction_id"], "TXN001")
        self.assertEqual(result["amount_minor"], 10000)
        self.assertEqual(result["status"], "CREATED")

    def test_payment_amount_must_match_reservation(self):
        with self.assertRaises(PaymentStoreError):
            self.payment_store.create_transaction(
                "RES001",
                150,
                "USD"
            )

    def test_transaction_requires_existing_reservation(self):
        with self.assertRaises(PaymentStoreError):
            self.payment_store.create_transaction(
                "UNKNOWN",
                100
            )

    def test_duplicate_transaction_rejected(self):
        self.payment_store.create_transaction(
            "RES001",
            100,
            "USD",
            "TXN001"
        )

        with self.assertRaises(PaymentStoreError):
            self.payment_store.create_transaction(
                "RES001",
                100,
                "USD",
                "TXN002"
            )

    def test_transaction_persistence(self):
        self.payment_store.create_transaction(
            "RES001",
            100,
            "USD",
            "TXN001"
        )

        reopened = PaymentStore(self.db_path)

        result = reopened.get_transaction("TXN001")

        self.assertIsNotNone(result)
        self.assertEqual(result["reservation_id"], "RES001")

    def test_transaction_update(self):
        self.payment_store.create_transaction(
            "RES001",
            100,
            "USD",
            "TXN001"
        )

        result = self.payment_store.update_transaction(
            "TXN001",
            status="AUTHORIZED",
            authorization_id="AUTH001"
        )

        self.assertEqual(result["status"], "AUTHORIZED")
        self.assertEqual(
            result["authorization_id"],
            "AUTH001"
        )

    def test_invalid_status_rejected(self):
        self.payment_store.create_transaction(
            "RES001",
            100,
            "USD",
            "TXN001"
        )

        with self.assertRaises(PaymentStoreError):
            self.payment_store.update_transaction(
                "TXN001",
                status="INVALID"
            )

    def test_atomic_create_order_claim_transitions_state(self):
        self.payment_store.create_transaction("RES001", 100, "USD", "TXNCLAIM1")
        operation = self.payment_store.claim_order_operation("TXNCLAIM1", "CREATE_ORDER")
        self.assertTrue(operation["idempotency_key"])
        self.assertEqual(self.payment_store.get_transaction("TXNCLAIM1")["status"], "EXECUTING_CREATE_ORDER")
        with self.assertRaises(PaymentStoreError):
            self.payment_store.claim_order_operation("TXNCLAIM1", "CREATE_ORDER")

    def test_atomic_authorize_claim_requires_approval_pending(self):
        self.payment_store.create_transaction("RES001", 100, "USD", "TXNCLAIM2")
        self.payment_store.update_transaction("TXNCLAIM2", status="APPROVAL_PENDING", paypal_order_id="ORDERCLAIM2")
        operation = self.payment_store.claim_order_operation("TXNCLAIM2", "AUTHORIZE")
        self.assertTrue(operation["idempotency_key"])
        self.assertEqual(self.payment_store.get_transaction("TXNCLAIM2")["status"], "EXECUTING_AUTHORIZE")
        with self.assertRaises(PaymentStoreError):
            self.payment_store.claim_order_operation("TXNCLAIM2", "AUTHORIZE")

    def test_prepare_operation_generates_stable_key(self):
        self.payment_store.create_transaction(
            "RES001",
            100,
            "USD",
            "TXN001"
        )

        first = self.payment_store.prepare_operation(
            "TXN001",
            "CREATE_ORDER"
        )

        second = self.payment_store.prepare_operation(
            "TXN001",
            "CREATE_ORDER"
        )

        self.assertEqual(
            first["idempotency_key"],
            second["idempotency_key"]
        )

    def test_different_operations_have_different_keys(self):
        self.payment_store.create_transaction(
            "RES001",
            100,
            "USD",
            "TXN001"
        )

        create = self.payment_store.prepare_operation(
            "TXN001",
            "CREATE_ORDER"
        )

        authorize = self.payment_store.prepare_operation(
            "TXN001",
            "AUTHORIZE"
        )

        self.assertNotEqual(
            create["idempotency_key"],
            authorize["idempotency_key"]
        )

    def test_operation_result_persistence(self):
        self.payment_store.create_transaction(
            "RES001",
            100,
            "USD",
            "TXN001"
        )

        self.payment_store.prepare_operation(
            "TXN001",
            "CREATE_ORDER"
        )

        self.payment_store.update_operation(
            "TXN001",
            "CREATE_ORDER",
            "SUCCEEDED",
            response={"id": "ORDER001"}
        )

        result = self.payment_store.get_operation(
            "TXN001",
            "CREATE_ORDER"
        )

        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(
            result["response"]["id"],
            "ORDER001"
        )

    def test_unknown_operation_is_pending_reconciliation(self):
        self.payment_store.create_transaction(
            "RES001",
            100,
            "USD",
            "TXN001"
        )

        self.payment_store.prepare_operation(
            "TXN001",
            "AUTHORIZE"
        )

        self.payment_store.update_operation(
            "TXN001",
            "AUTHORIZE",
            "UNKNOWN",
            error_message="Request timed out"
        )

        pending = self.payment_store.list_pending_operations()

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "UNKNOWN")

    def test_invalid_risk_score_rejected(self):
        self.payment_store.create_transaction(
            "RES001",
            100,
            "USD",
            "TXN001"
        )

        with self.assertRaises(PaymentStoreError):
            self.payment_store.update_transaction(
                "TXN001",
                risk_score=1.5
            )


if __name__ == "__main__":
    unittest.main()
