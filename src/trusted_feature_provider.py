"""Build model features from persisted order context and verified mandate state."""
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.risk_engine import REQUIRED_FEATURES
from src.sqlite_utils import connect_sqlite
from src.verified_mandate_terms import VerifiedMandateTermsStore

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "commons_state.db"


class TrustedFeatureError(RuntimeError):
    pass


class TrustedFeatureProvider:
    def __init__(self, db_path=DEFAULT_DB):
        self.db_path = str(db_path)
        self.terms = VerifiedMandateTermsStore(self.db_path)
        self._initialize()

    def _connect(self):
        return connect_sqlite(self.db_path)

    def _initialize(self):
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS commons_order_context (
                    transaction_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    merchant_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    previous_address_hash TEXT,
                    current_address_hash TEXT,
                    payment_retry_count INTEGER NOT NULL DEFAULT 0,
                    shared_agent_flag_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_commons_context_agent_created
                ON commons_order_context(agent_id, created_at)
            """)

    def record_order_context(
        self, transaction_id, agent_id, merchant_id, category,
        previous_address_hash=None, current_address_hash=None
    ):
        if not all(isinstance(x, str) and x.strip() for x in
                   (transaction_id, agent_id, merchant_id, category)):
            raise TrustedFeatureError("Required order context is missing.")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute("""
                INSERT INTO commons_order_context
                (transaction_id, agent_id, merchant_id, category,
                 previous_address_hash, current_address_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (transaction_id, agent_id, merchant_id, category.strip().lower(),
                  previous_address_hash, current_address_hash, now))

    def record_payment_retry(self, transaction_id):
        with self._connect() as db:
            cur = db.execute("""
                UPDATE commons_order_context
                SET payment_retry_count=payment_retry_count+1
                WHERE transaction_id=?
            """, (transaction_id,))
            if cur.rowcount != 1:
                raise TrustedFeatureError("Order context was not found.")

    def set_shared_agent_flag_count(self, transaction_id, count):
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise TrustedFeatureError("Flag count must be a non-negative integer.")
        with self._connect() as db:
            cur = db.execute("""
                UPDATE commons_order_context SET shared_agent_flag_count=?
                WHERE transaction_id=?
            """, (count, transaction_id))
            if cur.rowcount != 1:
                raise TrustedFeatureError("Order context was not found.")

    def __call__(self, transaction):
        txid = transaction.get("transaction_id")
        reservation_id = transaction.get("reservation_id")
        if not txid or not reservation_id:
            raise TrustedFeatureError("Transaction or mandate reservation ID is missing.")
        with self._connect() as db:
            context = db.execute(
                "SELECT * FROM commons_order_context WHERE transaction_id=?", (txid,)
            ).fetchone()
            reservation = db.execute("""
                SELECT r.mandate_id, r.amount_minor, r.status,
                       m.agent_id, m.max_transaction_minor, m.revoked,
                       t.issued_at, t.allowed_categories_json,
                       t.mandate_fingerprint, t.max_transaction_minor AS signed_cap
                FROM mandate_reservations r
                JOIN mandate_state m ON m.mandate_id=r.mandate_id
                JOIN commons_verified_mandate_terms t ON t.mandate_id=r.mandate_id
                WHERE r.reservation_id=?
            """, (reservation_id,)).fetchone()
            hourly = None
            if context:
                hourly = db.execute("""
                    SELECT COUNT(*) AS total FROM commons_order_context
                    WHERE agent_id=? AND created_at>=?
                """, (context["agent_id"],
                      (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat())).fetchone()
        if context is None or reservation is None:
            raise TrustedFeatureError("Trusted order context or verified mandate terms are unavailable.")
        if reservation["status"] not in ("RESERVED", "COMPLETED") or reservation["revoked"]:
            raise TrustedFeatureError("Mandate reservation is not valid for evaluation.")
        if context["agent_id"] != reservation["agent_id"]:
            raise TrustedFeatureError("Order agent does not match the reserved mandate.")
        try:
            amount_minor = int(reservation["amount_minor"])
            amount = amount_minor / 100.0
            mandate_cap = int(reservation["signed_cap"]) / 100.0
            issued = datetime.fromtimestamp(int(reservation["issued_at"]), tz=timezone.utc)
            age_days = max(0, (datetime.now(timezone.utc)-issued).days)
            categories = json.loads(reservation["allowed_categories_json"])
        except (TypeError, ValueError, json.JSONDecodeError, OverflowError) as exc:
            raise TrustedFeatureError("Persisted mandate terms are invalid.") from exc
        if amount_minor <= 0 or not categories:
            raise TrustedFeatureError("Verified mandate amount or categories are invalid.")
        address_changed = int(bool(context["previous_address_hash"])
                              and bool(context["current_address_hash"])
                              and context["previous_address_hash"] != context["current_address_hash"])
        features = {
            "amount": amount,
            "mandate_cap": mandate_cap,
            "category_allowed": int(context["category"].lower() in categories),
            "mandate_age_days": age_days,
            "orders_per_hour": int(hourly["total"]),
            "address_changed": address_changed,
            "payment_retries": int(context["payment_retry_count"]),
            "amount_vs_merchant_norm": amount / 75.0,
            "shared_agent_flag_count": int(context["shared_agent_flag_count"]),
        }
        if set(features) != set(REQUIRED_FEATURES):
            raise TrustedFeatureError("Feature contract does not match the risk model.")
        for key, value in features.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TrustedFeatureError(f"Invalid numeric feature: {key}")
        return features
