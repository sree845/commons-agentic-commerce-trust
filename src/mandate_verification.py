import base64
import json
import time
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey
)


class MandateVerificationError(Exception):
    pass


class MandateVerifier:
    def __init__(self):
        self.used_nonces = set()
        self.revoked_mandates = set()
        self.transaction_counts = {}
        self.spending_totals = {}

    def verify(self, mandate, signature, public_key, order):
        mandate_id = mandate.get("mandate_id")
        nonce = mandate.get("nonce")

        if not mandate_id or not nonce:
            raise MandateVerificationError(
                "Missing mandate ID or nonce"
            )

        if mandate_id in self.revoked_mandates:
            raise MandateVerificationError("Mandate revoked")

        if nonce in self.used_nonces:
            raise MandateVerificationError("Replay detected")

        if time.time() >= mandate.get("expires_at", 0):
            raise MandateVerificationError("Mandate expired")

        try:
            key = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(public_key)
            )

            payload = json.dumps(
                mandate,
                sort_keys=True,
                separators=(",", ":")
            ).encode("utf-8")

            key.verify(
                base64.b64decode(signature),
                payload
            )

        except (ValueError, InvalidSignature):
            raise MandateVerificationError(
                "Invalid mandate signature"
            )

        amount = float(order.get("amount", 0))
        cap = float(mandate.get("max_transaction_amount", 0))
        spending_limit = float(
            mandate.get("max_total_spending", 0)
        )
        max_transactions = int(
            mandate.get("max_transactions", 0)
        )

        if amount <= 0:
            raise MandateVerificationError("Invalid order amount")

        if amount > cap:
            raise MandateVerificationError(
                "Transaction exceeds mandate cap"
            )

        current_count = self.transaction_counts.get(
            mandate_id, 0
        )

        if current_count >= max_transactions:
            raise MandateVerificationError(
                "Transaction limit exceeded"
            )

        current_spending = self.spending_totals.get(
            mandate_id, 0.0
        )

        if current_spending + amount > spending_limit:
            raise MandateVerificationError(
                "Total spending authority exceeded"
            )

        self.used_nonces.add(nonce)

        return {
            "valid": True,
            "mandate_id": mandate_id,
            "authorized_amount": amount,
            "remaining_transactions": (
                max_transactions - current_count - 1
            ),
            "remaining_spending": round(
                spending_limit - current_spending - amount,
                2
            )
        }
