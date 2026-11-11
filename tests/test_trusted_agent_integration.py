import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.mandate_service import MandateService, MandateServiceError
from src.mandate_store import MandateStore


class TrustedAgentIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        self.registry_path = self.temp_path / "trusted_agents.json"
        self.database_path = self.temp_path / "integration.db"

        # Generate an isolated ephemeral test key. Tests must not depend on a
        # developer workstation's LOCALAPPDATA or a committed private key.
        self.private_key = Ed25519PrivateKey.generate()

        public_key = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )

        public_key_b64 = base64.b64encode(public_key).decode("ascii")

        self.registry_path.write_text(
            json.dumps({
                "version": 1,
                "agents": [{
                    "agent_id": "agent_001",
                    "public_key": public_key_b64,
                    "status": "ACTIVE"
                }]
            }),
            encoding="utf-8"
        )

        self.store = MandateStore(self.database_path)

        self.service = MandateService(
            store=self.store,
            registry_path=self.registry_path
        )

        self.mandate = {
            "mandate_id": "INTEGRATION_MANDATE_001",
            "agent_id": "agent_001",
            "nonce": "INTEGRATION_NONCE_001",
            "expires_at": __import__("time").time() + 3600,
            "max_transaction_amount": 500,
            "max_total_spending": 1000,
            "max_transactions": 5
        }

        self.order = {"amount": 100}

    def tearDown(self):
        self.temp_dir.cleanup()

    def sign_mandate(self, mandate):
        canonical = json.dumps(
            mandate,
            sort_keys=True,
            separators=(",", ":")
        ).encode("utf-8")

        signature = self.private_key.sign(canonical)
        return base64.b64encode(signature).decode("ascii")

    def test_registry_loaded_and_valid_mandate_reserved(self):
        signature = self.sign_mandate(self.mandate)

        result = self.service.reserve_order(
            self.mandate,
            signature,
            self.order
        )

        self.assertTrue(result["valid"])
        self.assertEqual(result["agent_id"], "agent_001")
        self.assertEqual(result["status"], "RESERVED")
        self.assertEqual(result["authorized_amount"], 100)

        reservation = self.store.get_reservation(
            result["reservation_id"]
        )

        self.assertIsNotNone(reservation)
        self.assertEqual(reservation["status"], "RESERVED")

    def test_replayed_nonce_is_rejected(self):
        signature = self.sign_mandate(self.mandate)

        self.service.reserve_order(
            self.mandate,
            signature,
            self.order
        )

        with self.assertRaises(MandateServiceError):
            self.service.reserve_order(
                self.mandate,
                signature,
                self.order
            )

    def test_revoked_agent_is_rejected(self):
        registry = json.loads(
            self.registry_path.read_text(encoding="utf-8")
        )
        registry["agents"][0]["status"] = "REVOKED"

        self.registry_path.write_text(
            json.dumps(registry),
            encoding="utf-8"
        )

        revoked_service = MandateService(
            store=MandateStore(
                self.temp_path / "revoked_test.db"
            ),
            registry_path=self.registry_path
        )

        signature = self.sign_mandate(self.mandate)

        with self.assertRaises(MandateServiceError):
            revoked_service.reserve_order(
                self.mandate,
                signature,
                self.order
            )


if __name__ == "__main__":
    unittest.main()
