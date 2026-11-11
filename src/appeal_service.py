
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timezone
from src.sqlite_utils import connect_sqlite

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "commons_state.db"


class AppealError(Exception):
    pass


class AppealService:

    def __init__(self, db_path=DEFAULT_DB):
        self.db_path = str(db_path)
        self._initialize()

    def _connect(self):
        return connect_sqlite(self.db_path)

    def _initialize(self):
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS appeals (
                    appeal_id TEXT PRIMARY KEY,
                    transaction_id TEXT NOT NULL,
                    appellant_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    evidence TEXT,
                    status TEXT NOT NULL,
                    reviewer_note TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            db.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_appeals_transaction
                ON appeals(transaction_id)
            """)

    def submit(
        self,
        transaction_id,
        appellant_id,
        reason,
        evidence=""
    ):
        if not all([
            transaction_id,
            appellant_id,
            reason
        ]):
            raise AppealError(
                "Transaction, appellant and reason are required."
            )

        now = datetime.now(timezone.utc).isoformat()
        appeal_id = str(uuid.uuid4())

        with self._connect() as db:
            existing = db.execute("""
                SELECT appeal_id
                FROM appeals
                WHERE transaction_id = ?
                  AND status IN ('SUBMITTED', 'UNDER_REVIEW')
            """, (transaction_id,)).fetchone()

            if existing:
                raise AppealError(
                    "An active appeal already exists for this order."
                )

            db.execute("""
                INSERT INTO appeals (
                    appeal_id,
                    transaction_id,
                    appellant_id,
                    reason,
                    evidence,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'SUBMITTED', ?, ?)
            """, (
                appeal_id,
                transaction_id,
                appellant_id,
                reason.strip(),
                evidence,
                now,
                now
            ))

        return self.get(appeal_id)

    def get(self, appeal_id):
        with self._connect() as db:
            row = db.execute("""
                SELECT *
                FROM appeals
                WHERE appeal_id = ?
            """, (appeal_id,)).fetchone()

        return dict(row) if row else None

    def list_all(self):
        with self._connect() as db:
            rows = db.execute("""
                SELECT *
                FROM appeals
                ORDER BY created_at DESC
            """).fetchall()

        return [dict(row) for row in rows]

    def review(self, appeal_id, decision, reviewer_note):
        if decision not in ("APPROVED", "REJECTED"):
            raise AppealError(
                "Decision must be APPROVED or REJECTED."
            )

        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as db:
            result = db.execute("""
                UPDATE appeals
                SET status = ?,
                    reviewer_note = ?,
                    updated_at = ?
                WHERE appeal_id = ?
                  AND status IN ('SUBMITTED', 'UNDER_REVIEW')
            """, (
                decision,
                reviewer_note,
                now,
                appeal_id
            ))

            if result.rowcount != 1:
                raise AppealError(
                    "Appeal not found or already reviewed."
                )

        return self.get(appeal_id)
