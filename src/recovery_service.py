
"""Recourse receipts, evidence receipts, appeals and recovery analytics.

These receipts are immutable application snapshots. They are not
cryptographic proof of PayPal settlement. The audit chain remains
a separate control.
"""

import hashlib
import json
import uuid

from datetime import datetime, timezone
from pathlib import Path

from src.sqlite_utils import connect_sqlite


ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "commons_recovery.db"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str
    )


class RecoveryService:

    def __init__(self, db_path=DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self):
        return connect_sqlite(self.db_path)

    def initialize(self):
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS recourse_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    transaction_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason_codes TEXT NOT NULL,
                    correction_options TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolution TEXT
                );

                CREATE TABLE IF NOT EXISTS evidence_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    transaction_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS appeals (
                    appeal_id TEXT PRIMARY KEY,
                    transaction_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reviewer_note TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_recourse_tx
                ON recourse_receipts(transaction_id);

                CREATE INDEX IF NOT EXISTS idx_evidence_tx
                ON evidence_receipts(transaction_id);

                CREATE INDEX IF NOT EXISTS idx_appeals_tx
                ON appeals(transaction_id);
            """)

    def create_recourse(
        self,
        transaction_id,
        reason_codes,
        correction_options
    ):
        if (
            not transaction_id
            or not isinstance(reason_codes, list)
            or not isinstance(correction_options, list)
        ):
            raise ValueError("Invalid recourse receipt fields")

        receipt_id = "rr_" + uuid.uuid4().hex

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO recourse_receipts (
                    receipt_id,
                    transaction_id,
                    status,
                    reason_codes,
                    correction_options,
                    created_at,
                    resolved_at,
                    resolution
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    receipt_id,
                    transaction_id,
                    "OPEN",
                    _canonical(reason_codes),
                    _canonical(correction_options),
                    _now(),
                ),
            )

        return self.get_recourse(receipt_id)

    def get_recourse(self, receipt_id):
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM recourse_receipts
                WHERE receipt_id = ?
                """,
                (receipt_id,),
            ).fetchone()

        if not row:
            return None

        result = dict(row)
        result["reason_codes"] = json.loads(result["reason_codes"])
        result["correction_options"] = json.loads(
            result["correction_options"]
        )

        return result

    def create_evidence(self, transaction_id, evidence):
        if not transaction_id or not isinstance(evidence, dict):
            raise ValueError("Invalid evidence receipt")

        payload = _canonical(evidence)
        receipt_id = "der_" + uuid.uuid4().hex
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO evidence_receipts (
                    receipt_id,
                    transaction_id,
                    payload,
                    payload_sha256,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    transaction_id,
                    payload,
                    digest,
                    _now(),
                ),
            )

        return self.get_evidence(receipt_id)

    def get_evidence(self, receipt_id):
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM evidence_receipts
                WHERE receipt_id = ?
                """,
                (receipt_id,),
            ).fetchone()

        if not row:
            return None

        result = dict(row)
        result["payload"] = json.loads(result["payload"])

        return result

    def submit_appeal(
        self,
        transaction_id,
        reason,
        evidence=None
    ):
        if (
            not transaction_id
            or not isinstance(reason, str)
            or len(reason.strip()) < 8
        ):
            raise ValueError(
                "Provide a clear appeal reason (at least 8 characters)"
            )

        evidence = evidence or {}

        if not isinstance(evidence, dict):
            raise ValueError("Appeal evidence must be a JSON object")

        evidence_receipt_id = evidence.get("evidence_receipt_id")

        if evidence_receipt_id is not None:
            if not isinstance(evidence_receipt_id, str) or not evidence_receipt_id.strip():
                raise ValueError("Invalid evidence receipt ID")

            with self.connect() as connection:
                receipt = connection.execute(
                    """
                    SELECT transaction_id
                    FROM evidence_receipts
                    WHERE receipt_id = ?
                    """,
                    (evidence_receipt_id.strip(),),
                ).fetchone()

            if not receipt:
                raise ValueError("Evidence receipt not found")

            if receipt["transaction_id"] != transaction_id:
                raise ValueError(
                    "Evidence receipt belongs to a different transaction"
                )

            evidence["evidence_receipt_id"] = evidence_receipt_id.strip()

        appeal_id = "ap_" + uuid.uuid4().hex
        now = _now()

        with self.connect() as connection:
            active = connection.execute(
                """
                SELECT 1
                FROM appeals
                WHERE transaction_id = ?
                AND status IN ('SUBMITTED', 'UNDER_REVIEW')
                """,
                (transaction_id,),
            ).fetchone()

            if active:
                raise ValueError(
                    "An active appeal already exists for this transaction"
                )

            connection.execute(
                """
                INSERT INTO appeals (
                    appeal_id,
                    transaction_id,
                    reason,
                    evidence,
                    status,
                    reviewer_note,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    appeal_id,
                    transaction_id,
                    reason.strip(),
                    _canonical(evidence or {}),
                    "SUBMITTED",
                    None,
                    now,
                    now,
                ),
            )

        return self.get_appeal(appeal_id)

    def get_appeal(self, appeal_id):
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM appeals
                WHERE appeal_id = ?
                """,
                (appeal_id,),
            ).fetchone()

        if not row:
            return None

        result = dict(row)
        result["evidence"] = json.loads(result["evidence"])

        return result

    def review_appeal(
        self,
        appeal_id,
        outcome,
        reviewer_note
    ):
        allowed_outcomes = (
            "UPHELD",
            "OVERTURNED",
            "NEEDS_INFORMATION",
        )

        if outcome not in allowed_outcomes:
            raise ValueError("Invalid appeal outcome")

        if (
            not isinstance(reviewer_note, str)
            or len(reviewer_note.strip()) < 4
        ):
            raise ValueError("Reviewer note is required")

        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE appeals
                SET
                    status = ?,
                    reviewer_note = ?,
                    updated_at = ?
                WHERE appeal_id = ?
                AND status IN ('SUBMITTED', 'UNDER_REVIEW')
                """,
                (
                    outcome,
                    reviewer_note.strip(),
                    _now(),
                    appeal_id,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "Appeal not found or no longer reviewable"
                )

        return self.get_appeal(appeal_id)

    def analytics(self):
        with self.connect() as connection:
            appeals = connection.execute(
                """
                SELECT status, COUNT(*) AS n
                FROM appeals
                GROUP BY status
                """
            ).fetchall()

            recourse = connection.execute(
                """
                SELECT status, COUNT(*) AS n
                FROM recourse_receipts
                GROUP BY status
                """
            ).fetchall()

            evidence = connection.execute(
                """
                SELECT COUNT(*) AS n
                FROM evidence_receipts
                """
            ).fetchone()["n"]

        return {
            "appeals": {
                row["status"]: row["n"]
                for row in appeals
            },
            "recourse": {
                row["status"]: row["n"]
                for row in recourse
            },
            "evidence_receipts": evidence,
        }
