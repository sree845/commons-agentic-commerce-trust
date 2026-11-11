import base64
import json
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from src.trusted_agent_registry import (
    TrustedAgentRegistryError,
    load_trusted_public_keys,
)


class TrustedAgentRegistryTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry_path = Path(self.temp_dir.name) / "trusted_agents.json"

        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.public_key = base64.b64encode(public_key).decode("ascii")

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_registry(self, agents, version=1):
        self.registry_path.write_text(
            json.dumps({"version": version, "agents": agents}),
            encoding="utf-8",
        )

    def test_empty_registry_returns_empty_dictionary(self):
        self.write_registry([])
        self.assertEqual(load_trusted_public_keys(self.registry_path), {})

    def test_active_agent_is_loaded(self):
        self.write_registry([
            {
                "agent_id": "agent_001",
                "public_key": self.public_key,
                "status": "ACTIVE",
            }
        ])
        self.assertEqual(
            load_trusted_public_keys(self.registry_path),
            {"agent_001": self.public_key},
        )

    def test_revoked_agent_is_not_loaded(self):
        self.write_registry([
            {
                "agent_id": "agent_001",
                "public_key": self.public_key,
                "status": "REVOKED",
            }
        ])
        self.assertEqual(load_trusted_public_keys(self.registry_path), {})

    def test_duplicate_agent_ids_are_rejected(self):
        agent = {
            "agent_id": "agent_001",
            "public_key": self.public_key,
            "status": "ACTIVE",
        }
        self.write_registry([agent, agent])
        with self.assertRaises(TrustedAgentRegistryError):
            load_trusted_public_keys(self.registry_path)

    def test_invalid_base64_is_rejected(self):
        self.write_registry([
            {
                "agent_id": "agent_001",
                "public_key": "not-valid-base64!",
                "status": "ACTIVE",
            }
        ])
        with self.assertRaises(TrustedAgentRegistryError):
            load_trusted_public_keys(self.registry_path)

    def test_wrong_public_key_length_is_rejected(self):
        short_key = base64.b64encode(b"short").decode("ascii")
        self.write_registry([
            {
                "agent_id": "agent_001",
                "public_key": short_key,
                "status": "ACTIVE",
            }
        ])
        with self.assertRaises(TrustedAgentRegistryError):
            load_trusted_public_keys(self.registry_path)

    def test_unknown_status_is_rejected(self):
        self.write_registry([
            {
                "agent_id": "agent_001",
                "public_key": self.public_key,
                "status": "PENDING",
            }
        ])
        with self.assertRaises(TrustedAgentRegistryError):
            load_trusted_public_keys(self.registry_path)

    def test_unsupported_version_is_rejected(self):
        self.write_registry([], version=2)
        with self.assertRaises(TrustedAgentRegistryError):
            load_trusted_public_keys(self.registry_path)

    def test_missing_registry_is_rejected(self):
        with self.assertRaises(TrustedAgentRegistryError):
            load_trusted_public_keys(
                Path(self.temp_dir.name) / "missing.json"
            )

    def test_invalid_json_is_rejected(self):
        self.registry_path.write_text("{invalid", encoding="utf-8")
        with self.assertRaises(TrustedAgentRegistryError):
            load_trusted_public_keys(self.registry_path)


if __name__ == "__main__":
    unittest.main()
