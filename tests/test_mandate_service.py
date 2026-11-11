import base64
import json
import tempfile
import time
import unittest

from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat
)

from src.mandate_store import MandateStore
from src.mandate_service import (
    MandateService,
    MandateServiceError
)


class TestMandateService(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "service_test.db"

        self.store = MandateStore(db_path)
        self.private_key = Ed25519PrivateKey.generate()

        public_key = base64.b64encode(
            self.private_key.public_key().public_bytes(
                Encoding.Raw,
                PublicFormat.Raw
            )
        ).decode("utf-8")

        self.service = MandateService(
            {"agent_001": public_key},
            self.store
        )

        self.mandate = {
            "mandate_id": "MANDATE001",
            "agent_id": "agent_001",
            "nonce": "NONCE001",
            "expires_at": time.time() + 3600,
            "max_transaction_amount": 500,
            "max_total_spending": 1000,
            "max_transactions": 5
        }

        self.order = {"amount": 100}
        self.signature = self.sign(self.mandate)

    def tearDown(self):
        self.temp_dir.cleanup()

    def sign(self, mandate):
        payload = json.dumps(
            mandate,
            sort_keys=True,
            separators=(",", ":")
        ).encode("utf-8")

        return base64.b64encode(
            self.private_key.sign(payload)
        ).decode("utf-8")

    def test_valid_order_reservation(self):
        result = self.service.reserve_order(
            self.mandate,
            self.signature,
            self.order
        )

        self.assertTrue(result["valid"])
        self.assertEqual(result["status"], "RESERVED")

        state = self.store.get_mandate_state("MANDATE001")
        self.assertEqual(state["transactions_used"], 1)
        self.assertEqual(state["spending_used_minor"], 10000)

    def test_untrusted_agent_rejected(self):
        mandate = self.mandate.copy()
        mandate["agent_id"] = "unknown_agent"

        with self.assertRaises(MandateServiceError):
            self.service.reserve_order(
                mandate,
                self.sign(mandate),
                self.order
            )

    def test_invalid_signature_rejected(self):
        with self.assertRaises(MandateServiceError):
            self.service.reserve_order(
                self.mandate,
                "invalid_signature",
                self.order
            )

    def test_duplicate_nonce_rejected(self):
        self.service.reserve_order(
            self.mandate,
            self.signature,
            self.order
        )

        with self.assertRaises(MandateServiceError):
            self.service.reserve_order(
                self.mandate,
                self.signature,
                self.order
            )

    def test_transaction_cap_enforced(self):
        with self.assertRaises(MandateServiceError):
            self.service.reserve_order(
                self.mandate,
                self.signature,
                {"amount": 600}
            )

    def test_reservation_completion(self):
        result = self.service.reserve_order(
            self.mandate,
            self.signature,
            self.order
        )

        completed = self.service.complete_reservation(
            result["reservation_id"]
        )

        self.assertEqual(completed["status"], "COMPLETED")

    def test_reservation_release(self):
        result = self.service.reserve_order(
            self.mandate,
            self.signature,
            self.order
        )

        released = self.service.release_reservation(
            result["reservation_id"]
        )

        self.assertEqual(released["status"], "RELEASED")

        state = self.store.get_mandate_state("MANDATE001")
        self.assertEqual(state["transactions_used"], 0)
        self.assertEqual(state["spending_used_minor"], 0)

    def test_tampered_mandate_rejected(self):
        tampered = self.mandate.copy()
        tampered["max_total_spending"] = 5000

        with self.assertRaises(MandateServiceError):
            self.service.reserve_order(
                tampered,
                self.signature,
                self.order
            )


if __name__ == "__main__":
    unittest.main()
