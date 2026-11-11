import tempfile
import unittest

from pathlib import Path

from src.mandate_store import (
    MandateStore,
    MandateStoreError
)


class TestMandateStore(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.store = MandateStore(self.db_path)

        self.mandate = {
            "mandate_id": "MANDATE001",
            "max_transactions": 3,
            "max_total_spending": 500.00,
            "max_transaction_amount": 300.00
        }

        self.store.register_mandate(self.mandate)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_mandate_registration(self):
        state = self.store.get_mandate_state("MANDATE001")

        self.assertIsNotNone(state)
        self.assertEqual(state["max_transactions"], 3)
        self.assertEqual(state["max_spending_minor"], 50000)
        self.assertEqual(state["max_transaction_minor"], 30000)
        self.assertEqual(state["transactions_used"], 0)

    def test_persistence_after_reopening(self):
        reopened_store = MandateStore(self.db_path)
        state = reopened_store.get_mandate_state("MANDATE001")

        self.assertIsNotNone(state)
        self.assertEqual(state["mandate_id"], "MANDATE001")
        self.assertEqual(state["max_transaction_minor"], 30000)

    def test_successful_reservation(self):
        result = self.store.reserve(
            "MANDATE001",
            "NONCE001",
            100,
            "RES001"
        )

        self.assertEqual(result["status"], "RESERVED")

        state = self.store.get_mandate_state("MANDATE001")
        self.assertEqual(state["transactions_used"], 1)
        self.assertEqual(state["spending_used_minor"], 10000)

    def test_duplicate_nonce_rejected(self):
        self.store.reserve(
            "MANDATE001", "NONCE001", 100, "RES001"
        )

        with self.assertRaises(MandateStoreError):
            self.store.reserve(
                "MANDATE001", "NONCE001", 50, "RES002"
            )

    def test_transaction_limit_enforced(self):
        self.store.reserve(
            "MANDATE001", "NONCE001", 10, "RES001"
        )
        self.store.reserve(
            "MANDATE001", "NONCE002", 10, "RES002"
        )
        self.store.reserve(
            "MANDATE001", "NONCE003", 10, "RES003"
        )

        with self.assertRaises(MandateStoreError):
            self.store.reserve(
                "MANDATE001", "NONCE004", 10, "RES004"
            )

    def test_spending_limit_enforced(self):
        self.store.reserve(
            "MANDATE001", "NONCE001", 300, "RES001"
        )

        with self.assertRaises(MandateStoreError):
            self.store.reserve(
                "MANDATE001", "NONCE002", 250, "RES002"
            )

    def test_per_transaction_limit_enforced(self):
        with self.assertRaises(MandateStoreError):
            self.store.reserve(
                "MANDATE001", "NONCE001", 300.01, "RES001"
            )

        state = self.store.get_mandate_state("MANDATE001")
        self.assertEqual(state["transactions_used"], 0)
        self.assertEqual(state["spending_used_minor"], 0)

    def test_transaction_at_exact_limit_allowed(self):
        result = self.store.reserve(
            "MANDATE001", "NONCE001", 300, "RES001"
        )

        self.assertEqual(result["status"], "RESERVED")
        self.assertEqual(result["amount"], 300.00)

    def test_completion_preserves_spending(self):
        self.store.reserve(
            "MANDATE001", "NONCE001", 100, "RES001"
        )

        self.store.complete("RES001")

        state = self.store.get_mandate_state("MANDATE001")
        self.assertEqual(state["transactions_used"], 1)
        self.assertEqual(state["spending_used_minor"], 10000)

        with self.assertRaises(MandateStoreError):
            self.store.complete("RES001")

    def test_release_rolls_back_spending(self):
        self.store.reserve(
            "MANDATE001", "NONCE001", 200, "RES001"
        )

        self.store.release("RES001")

        state = self.store.get_mandate_state("MANDATE001")
        self.assertEqual(state["transactions_used"], 0)
        self.assertEqual(state["spending_used_minor"], 0)

        with self.assertRaises(MandateStoreError):
            self.store.release("RES001")

    def test_released_nonce_cannot_be_reused(self):
        self.store.reserve(
            "MANDATE001", "NONCE001", 100, "RES001"
        )
        self.store.release("RES001")

        with self.assertRaises(MandateStoreError):
            self.store.reserve(
                "MANDATE001", "NONCE001", 100, "RES002"
            )

    def test_revoked_mandate_rejected(self):
        self.store.revoke_mandate("MANDATE001")

        with self.assertRaises(MandateStoreError):
            self.store.reserve(
                "MANDATE001", "NONCE001", 100, "RES001"
            )

    def test_mandate_limits_cannot_be_modified(self):
        modified_mandate = self.mandate.copy()
        modified_mandate["max_transaction_amount"] = 400.00

        with self.assertRaises(MandateStoreError):
            self.store.register_mandate(modified_mandate)

    def test_mandate_id_cannot_be_reused_by_another_agent(self):
        mandate = {
            "mandate_id": "MANDATE_AGENT",
            "agent_id": "agent_001",
            "nonce": "NONCE_AGENT_001",
            "expires_at": 2000000000,
            "max_transaction_amount": 300,
            "max_total_spending": 500,
            "max_transactions": 3
        }

        self.store.register_mandate(mandate)

        another_agent_mandate = mandate.copy()
        another_agent_mandate["agent_id"] = "agent_002"

        with self.assertRaises(MandateStoreError):
            self.store.register_mandate(
                another_agent_mandate
            )

    def test_signed_mandate_terms_cannot_be_modified(self):
        mandate = {
            "mandate_id": "MANDATE_TERMS",
            "agent_id": "agent_001",
            "nonce": "NONCE_TERMS_001",
            "expires_at": 2000000000,
            "max_transaction_amount": 300,
            "max_total_spending": 500,
            "max_transactions": 3
        }

        self.store.register_mandate(mandate)

        modified_mandate = mandate.copy()
        modified_mandate["expires_at"] = 2100000000

        with self.assertRaises(MandateStoreError):
            self.store.register_mandate(
                modified_mandate
            )


if __name__ == "__main__":
    unittest.main()
