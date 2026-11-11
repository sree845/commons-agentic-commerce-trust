import tempfile
import unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from src.mandate_issuer import MandateIssuer
from src.verified_mandate_terms import VerifiedMandateTermsStore


class CompletionPackTests(unittest.TestCase):
    def test_issuer_signs_canonical_mandate(self):
        issuer = MandateIssuer(Ed25519PrivateKey.generate())
        result = issuer.create_mandate(
            "agent_test", 100, 500, 5, ["electronics", "books"], 3600
        )
        self.assertEqual(result["mandate"]["agent_id"], "agent_test")
        self.assertEqual(sorted(result["mandate"]["allowed_categories"]),
                         ["books", "electronics"])
        self.assertTrue(result["signature"])

    def test_verified_terms_are_persisted_and_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = VerifiedMandateTermsStore(Path(tmp) / "state.db")
            mandate = {
                "mandate_id": "m1", "agent_id": "a1", "nonce": "n1",
                "issued_at": 1800000000, "expires_at": 1800003600,
                "max_transaction_amount": "100.00",
                "max_total_spending": "500.00", "max_transactions": 5,
                "allowed_categories": ["books"],
            }
            store.save_verified(mandate)
            self.assertEqual(store.get("m1")["max_transaction_minor"], 10000)
            changed = dict(mandate, allowed_categories=["electronics"])
            with self.assertRaises(Exception):
                store.save_verified(changed)


if __name__ == "__main__":
    unittest.main()
