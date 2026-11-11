
"""Persistent signed mandate terms used by risk-feature construction."""

import hashlib
import json
from pathlib import Path

from src.sqlite_utils import connect_sqlite


class VerifiedMandateTermsError(RuntimeError):
    pass


class VerifiedMandateTermsStore:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self):
        db = connect_sqlite(self.db_path, timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def initialize(self):
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS commons_verified_mandate_terms (
                    mandate_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    mandate_fingerprint TEXT NOT NULL,
                    issued_at INTEGER NOT NULL,
                    allowed_categories_json TEXT NOT NULL,
                    max_transaction_minor INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

    @staticmethod
    def fingerprint(mandate):
        data = {
            key: value
            for key, value in mandate.items()
            if key != "nonce"
        }
        raw = json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def save_verified(self, mandate):
        required = (
            "mandate_id",
            "agent_id",
            "issued_at",
            "allowed_categories",
            "max_transaction_amount",
        )

        if not isinstance(mandate, dict):
            raise VerifiedMandateTermsError(
                "Verified mandate terms are incomplete."
            )

        if any(key not in mandate for key in required):
            raise VerifiedMandateTermsError(
                "Verified mandate terms are incomplete."
            )

        if not isinstance(mandate["issued_at"], int):
            raise VerifiedMandateTermsError(
                "Mandate issued_at must be an integer timestamp."
            )

        if not isinstance(mandate["mandate_id"], str) or not mandate["mandate_id"].strip():
            raise VerifiedMandateTermsError("Invalid mandate ID.")

        if not isinstance(mandate["agent_id"], str) or not mandate["agent_id"].strip():
            raise VerifiedMandateTermsError("Invalid agent ID.")

        categories = mandate["allowed_categories"]

        if (
            not isinstance(categories, list)
            or not categories
            or any(
                not isinstance(item, str) or not item.strip()
                for item in categories
            )
        ):
            raise VerifiedMandateTermsError(
                "Mandate categories are invalid."
            )

        try:
            amount = float(mandate["max_transaction_amount"])

            if not amount > 0:
                raise ValueError("Amount must be positive.")

            cap_minor = int(round(amount * 100))

            if cap_minor <= 0:
                raise ValueError("Amount is too small.")

            categories_json = json.dumps(
                sorted(set(item.strip().lower() for item in categories))
            )

            fingerprint = self.fingerprint(mandate)

        except (TypeError, ValueError, OverflowError) as exc:
            raise VerifiedMandateTermsError(
                "Mandate terms are invalid."
            ) from exc

        with self._connect() as db:
            existing = db.execute(
                """
                SELECT mandate_fingerprint
                FROM commons_verified_mandate_terms
                WHERE mandate_id = ?
                """,
                (mandate["mandate_id"],),
            ).fetchone()

            if existing and existing["mandate_fingerprint"] != fingerprint:
                raise VerifiedMandateTermsError(
                    "Mandate ID is already bound to different signed terms."
                )

            db.execute(
                """
                INSERT OR IGNORE INTO commons_verified_mandate_terms
                (
                    mandate_id,
                    agent_id,
                    mandate_fingerprint,
                    issued_at,
                    allowed_categories_json,
                    max_transaction_minor
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    mandate["mandate_id"],
                    mandate["agent_id"],
                    fingerprint,
                    mandate["issued_at"],
                    categories_json,
                    cap_minor,
                ),
            )

    def get(self, mandate_id):
        with self._connect() as db:
            row = db.execute(
                """
                SELECT *
                FROM commons_verified_mandate_terms
                WHERE mandate_id = ?
                """,
                (mandate_id,),
            ).fetchone()

        return dict(row) if row else None
