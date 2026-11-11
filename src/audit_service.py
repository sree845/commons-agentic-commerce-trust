
import sqlite3
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from src.sqlite_utils import connect_sqlite

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "commons_state.db"


class AuditError(Exception):
    pass


class AuditService:

    def __init__(self, db_path=DEFAULT_DB):
        self.db_path = str(db_path)
        self._initialize()

    def _connect(self):
        return connect_sqlite(self.db_path)

    def _initialize(self):
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS audit_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    transaction_id TEXT,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

    @staticmethod
    def _hash(value):
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":")
        ).encode("utf-8")

        return hashlib.sha256(encoded).hexdigest()

    def record(self, event_type, payload, transaction_id=None):
        if not event_type or not isinstance(payload, dict):
            raise AuditError("Invalid audit event.")

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")

            previous = db.execute("""
                SELECT event_hash
                FROM audit_events
                ORDER BY sequence DESC
                LIMIT 1
            """).fetchone()

            previous_hash = (
                previous["event_hash"]
                if previous else "GENESIS"
            )

            created_at = datetime.now(
                timezone.utc
            ).isoformat()

            event = {
                "transaction_id": transaction_id,
                "event_type": event_type,
                "payload": payload,
                "previous_hash": previous_hash,
                "created_at": created_at
            }

            event_hash = self._hash(event)
            event_id = self._hash({
                "event": event,
                "event_hash": event_hash
            })

            db.execute("""
                INSERT INTO audit_events (
                    event_id,
                    transaction_id,
                    event_type,
                    payload,
                    previous_hash,
                    event_hash,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                event_id,
                transaction_id,
                event_type,
                json.dumps(payload, sort_keys=True),
                previous_hash,
                event_hash,
                created_at
            ))

            return {
                "event_id": event_id,
                "event_hash": event_hash,
                "previous_hash": previous_hash,
                "created_at": created_at
            }

    def list_events(self, limit=100):
        limit = max(1, min(int(limit), 1000))

        with self._connect() as db:
            rows = db.execute("""
                SELECT *
                FROM audit_events
                ORDER BY sequence DESC
                LIMIT ?
            """, (limit,)).fetchall()

        return [dict(row) for row in rows]

    def verify_chain(self):
        with self._connect() as db:
            rows = db.execute("""
                SELECT *
                FROM audit_events
                ORDER BY sequence ASC
            """).fetchall()

        expected_previous = "GENESIS"

        for row in rows:
            payload = json.loads(row["payload"])

            event = {
                "transaction_id": row["transaction_id"],
                "event_type": row["event_type"],
                "payload": payload,
                "previous_hash": expected_previous,
                "created_at": row["created_at"]
            }

            calculated = self._hash(event)

            if row["previous_hash"] != expected_previous:
                return False

            if row["event_hash"] != calculated:
                return False

            expected_previous = row["event_hash"]

        return True
