import base64
import time
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat
)

from src.mandate_verification import (
    MandateVerifier,
    MandateVerificationError
)


class TestMandateVerification(unittest.TestCase):

    def setUp(self):
        self.verifier = MandateVerifier()
        self.private_key = Ed25519PrivateKey.generate()

        self.public_key = base64.b64encode(
            self.private_key.public_key().public_bytes(
                Encoding.Raw,
                PublicFormat.Raw
            )
        ).decode("utf-8")

        self.mandate = {
            "mandate_id": "MANDATE001",
            "nonce": "NONCE001",
            "expires_at": time.time() + 3600,
            "max_transaction_amount": 500,
            "max_total_spending": 1000,
            "max_transactions": 5
        }

        self.order = {"amount": 100}

        self.signature = self.sign(self.mandate)

    def sign(self, mandate):
        payload = __import__("json").dumps(
            mandate,
            sort_keys=True,
            separators=(",", ":")
        ).encode("utf-8")

        return base64.b64encode(
            self.private_key.sign(payload)
        ).decode("utf-8")

    def test_valid_mandate(self):
        result = self.verifier.verify(
            self.mandate,
            self.signature,
            self.public_key,
            self.order
        )
        self.assertTrue(result["valid"])

    def test_tampered_mandate(self):
        tampered = self.mandate.copy()
        tampered["max_transaction_amount"] = 1000

        with self.assertRaises(MandateVerificationError):
            self.verifier.verify(
                tampered,
                self.signature,
                self.public_key,
                self.order
            )

    def test_expired_mandate(self):
        expired = self.mandate.copy()
        expired["expires_at"] = time.time() - 100

        with self.assertRaises(MandateVerificationError):
            self.verifier.verify(
                expired,
                self.sign(expired),
                self.public_key,
                self.order
            )

    def test_transaction_cap_exceeded(self):
        with self.assertRaises(MandateVerificationError):
            self.verifier.verify(
                self.mandate,
                self.signature,
                self.public_key,
                {"amount": 600}
            )

    def test_total_spending_exceeded(self):
        self.verifier.spending_totals["MANDATE001"] = 950

        with self.assertRaises(MandateVerificationError):
            self.verifier.verify(
                self.mandate,
                self.signature,
                self.public_key,
                self.order
            )

    def test_transaction_count_exceeded(self):
        self.verifier.transaction_counts["MANDATE001"] = 5

        with self.assertRaises(MandateVerificationError):
            self.verifier.verify(
                self.mandate,
                self.signature,
                self.public_key,
                self.order
            )

    def test_replay_detection(self):
        self.verifier.verify(
            self.mandate,
            self.signature,
            self.public_key,
            self.order
        )

        with self.assertRaises(MandateVerificationError):
            self.verifier.verify(
                self.mandate,
                self.signature,
                self.public_key,
                self.order
            )


if __name__ == "__main__":
    unittest.main()
