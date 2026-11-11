"""Ed25519 issuer for Commons agent spending mandates.

The private key belongs to the agent/operator, never to the merchant service.
Store COMMONS_AGENT_PRIVATE_KEY_B64 in the environment or inject a key object.
"""
import base64
import json
import os
import time
import uuid
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class MandateIssuerError(ValueError):
    pass


def load_agent_private_key():
    encoded = os.environ.get("COMMONS_AGENT_PRIVATE_KEY_B64")
    if not encoded:
        raise MandateIssuerError(
            "COMMONS_AGENT_PRIVATE_KEY_B64 is not configured."
        )
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) != 32:
            raise ValueError("Expected 32 raw bytes.")
        return Ed25519PrivateKey.from_private_bytes(raw)
    except (ValueError, TypeError) as exc:
        raise MandateIssuerError("Invalid Ed25519 private key.") from exc


def public_key_b64(private_key):
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


class MandateIssuer:
    def __init__(self, private_key=None):
        self.private_key = private_key or load_agent_private_key()
        if not isinstance(self.private_key, Ed25519PrivateKey):
            raise MandateIssuerError("A valid Ed25519 private key is required.")

    def create_mandate(
        self,
        agent_id,
        max_transaction_amount,
        max_total_spending,
        max_transactions,
        allowed_categories,
        validity_seconds=3600,
    ):
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise MandateIssuerError("agent_id is required.")
        if isinstance(max_transactions, bool) or not isinstance(max_transactions, int) or max_transactions < 1:
            raise MandateIssuerError("max_transactions must be a positive integer.")
        if isinstance(validity_seconds, bool) or not isinstance(validity_seconds, int) or validity_seconds < 60:
            raise MandateIssuerError("validity_seconds must be at least 60.")
        try:
            per_order = round(float(max_transaction_amount), 2)
            total = round(float(max_total_spending), 2)
        except (TypeError, ValueError) as exc:
            raise MandateIssuerError("Spending limits must be numeric.") from exc
        if per_order <= 0 or total <= 0 or per_order > total:
            raise MandateIssuerError("Spending limits are invalid.")
        if not isinstance(allowed_categories, (list, tuple)) or not allowed_categories:
            raise MandateIssuerError("At least one category is required.")
        categories = sorted({
            str(value).strip().lower()
            for value in allowed_categories
            if isinstance(value, str) and value.strip()
        })
        if len(categories) != len(allowed_categories):
            raise MandateIssuerError("Categories must be non-empty strings without duplicates.")
        issued_at = int(time.time())
        mandate = {
            "mandate_id": str(uuid.uuid4()),
            "agent_id": agent_id.strip(),
            "nonce": str(uuid.uuid4()),
            "issued_at": issued_at,
            "expires_at": issued_at + validity_seconds,
            "max_transaction_amount": f"{per_order:.2f}",
            "max_total_spending": f"{total:.2f}",
            "max_transactions": max_transactions,
            "allowed_categories": categories,
        }
        payload = json.dumps(
            mandate, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        signature = self.private_key.sign(payload)
        return {
            "mandate": mandate,
            "signature": base64.b64encode(signature).decode("ascii"),
        }
