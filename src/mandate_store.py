import sqlite3
import hashlib
import json

from decimal import Decimal, InvalidOperation
from pathlib import Path
from contextlib import contextmanager


DB_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "commons_state.db"
)


class MandateStoreError(Exception):
    pass


class MandateStore:

    def __init__(self, db_path=DB_PATH):
        self.db_path = str(db_path)

        Path(self.db_path).parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self.initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(
            self.db_path,
            timeout=10,
            isolation_level="DEFERRED"
        )

        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")

        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def to_minor_units(value):
        try:
            amount = Decimal(str(value))

            if not amount.is_finite() or amount < 0:
                raise ValueError

            if amount != amount.quantize(Decimal("0.01")):
                raise ValueError

            return int(amount * 100)

        except (InvalidOperation, ValueError, TypeError):
            raise MandateStoreError(
                "Invalid monetary amount"
            )

    @staticmethod
    def _validate_identifier(value, field_name):
        if (
            not isinstance(value, str)
            or not value.strip()
        ):
            raise MandateStoreError(
                f"Invalid {field_name}"
            )

        return value.strip()

    @staticmethod
    def _validate_transaction_limit(value):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
        ):
            raise MandateStoreError(
                "Invalid transaction limit"
            )

        return value

    @staticmethod
    def _calculate_fingerprint(mandate):
        if not isinstance(mandate, dict):
            raise MandateStoreError("Invalid mandate")

        fingerprint_data = {
            key: value
            for key, value in mandate.items()
            if key != "nonce"
        }

        try:
            canonical_mandate = json.dumps(
                fingerprint_data,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False
            )

            return hashlib.sha256(
                canonical_mandate.encode("utf-8")
            ).hexdigest()

        except (TypeError, ValueError):
            raise MandateStoreError(
                "Mandate contains invalid fingerprint data"
            )

    def initialize(self):
        with self.connect() as connection:

            connection.execute("""
                CREATE TABLE IF NOT EXISTS mandate_state (
                    mandate_id TEXT PRIMARY KEY,
                    max_transactions INTEGER NOT NULL,
                    max_spending_minor INTEGER NOT NULL,
                    max_transaction_minor INTEGER,
                    transactions_used INTEGER NOT NULL DEFAULT 0,
                    spending_used_minor INTEGER NOT NULL DEFAULT 0,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    agent_id TEXT,
                    mandate_fingerprint TEXT
                )
            """)

            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(mandate_state)"
                ).fetchall()
            }

            if "max_transaction_minor" not in columns:
                connection.execute("""
                    ALTER TABLE mandate_state
                    ADD COLUMN max_transaction_minor INTEGER
                """)

            if "agent_id" not in columns:
                connection.execute("""
                    ALTER TABLE mandate_state
                    ADD COLUMN agent_id TEXT
                """)

            if "mandate_fingerprint" not in columns:
                connection.execute("""
                    ALTER TABLE mandate_state
                    ADD COLUMN mandate_fingerprint TEXT
                """)

            connection.execute("""
                CREATE TABLE IF NOT EXISTS mandate_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    mandate_id TEXT NOT NULL,
                    nonce TEXT NOT NULL UNIQUE,
                    amount_minor INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (mandate_id)
                        REFERENCES mandate_state(mandate_id)
                )
            """)

            connection.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_mandate_reservations_mandate
                ON mandate_reservations(mandate_id)
            """)

            connection.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_mandate_reservations_status
                ON mandate_reservations(status)
            """)

    def register_mandate(self, mandate):
        if not isinstance(mandate, dict):
            raise MandateStoreError("Invalid mandate")

        mandate_id = self._validate_identifier(
            mandate.get("mandate_id"),
            "mandate ID"
        )

        agent_id = mandate.get("agent_id")

        if agent_id is not None:
            agent_id = self._validate_identifier(
                agent_id,
                "agent ID"
            )

        mandate_fingerprint = self._calculate_fingerprint(
            mandate
        )

        max_transactions = self._validate_transaction_limit(
            mandate.get("max_transactions")
        )

        max_spending = self.to_minor_units(
            mandate.get("max_total_spending")
        )

        max_transaction = self.to_minor_units(
            mandate.get("max_transaction_amount")
        )

        if max_spending <= 0:
            raise MandateStoreError(
                "Invalid total spending limit"
            )

        if max_transaction <= 0:
            raise MandateStoreError(
                "Invalid per-transaction limit"
            )

        if max_transaction > max_spending:
            raise MandateStoreError(
                "Per-transaction limit exceeds total spending limit"
            )

        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            existing = connection.execute("""
                SELECT *
                FROM mandate_state
                WHERE mandate_id = ?
            """, (mandate_id,)).fetchone()

            if existing:
                if (
                    existing["max_transactions"] != max_transactions
                    or existing["max_spending_minor"] != max_spending
                ):
                    raise MandateStoreError(
                        "Registered mandate limits do not match"
                    )

                stored_transaction_limit = existing[
                    "max_transaction_minor"
                ]

                if stored_transaction_limit is None:
                    connection.execute("""
                        UPDATE mandate_state
                        SET max_transaction_minor = ?
                        WHERE mandate_id = ?
                    """, (
                        max_transaction,
                        mandate_id
                    ))

                elif stored_transaction_limit != max_transaction:
                    raise MandateStoreError(
                        "Registered per-transaction limit does not match"
                    )

                stored_agent_id = existing["agent_id"]
                stored_fingerprint = existing[
                    "mandate_fingerprint"
                ]

                if (
                    stored_agent_id is None
                    and stored_fingerprint is None
                ):
                    connection.execute("""
                        UPDATE mandate_state
                        SET
                            agent_id = ?,
                            mandate_fingerprint = ?
                        WHERE mandate_id = ?
                    """, (
                        agent_id,
                        mandate_fingerprint,
                        mandate_id
                    ))

                elif (
                    stored_fingerprint is None
                    or stored_agent_id != agent_id
                    or stored_fingerprint != mandate_fingerprint
                ):
                    raise MandateStoreError(
                        "Mandate identity or signed terms do not match"
                    )

                return

            connection.execute("""
                INSERT INTO mandate_state (
                    mandate_id,
                    max_transactions,
                    max_spending_minor,
                    max_transaction_minor,
                    agent_id,
                    mandate_fingerprint
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                mandate_id,
                max_transactions,
                max_spending,
                max_transaction,
                agent_id,
                mandate_fingerprint
            ))

    def revoke_mandate(self, mandate_id):
        mandate_id = self._validate_identifier(
            mandate_id,
            "mandate ID"
        )

        with self.connect() as connection:
            cursor = connection.execute("""
                UPDATE mandate_state
                SET revoked = 1
                WHERE mandate_id = ?
            """, (mandate_id,))

            if cursor.rowcount == 0:
                raise MandateStoreError("Unknown mandate")

    def reserve(
        self,
        mandate_id,
        nonce,
        amount,
        reservation_id
    ):
        mandate_id = self._validate_identifier(
            mandate_id,
            "mandate ID"
        )

        nonce = self._validate_identifier(
            nonce,
            "nonce"
        )

        reservation_id = self._validate_identifier(
            reservation_id,
            "reservation ID"
        )

        amount_minor = self.to_minor_units(amount)

        if amount_minor <= 0:
            raise MandateStoreError(
                "Invalid reservation amount"
            )

        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            state = connection.execute("""
                SELECT *
                FROM mandate_state
                WHERE mandate_id = ?
            """, (mandate_id,)).fetchone()

            if state is None:
                raise MandateStoreError("Unknown mandate")

            if state["revoked"]:
                raise MandateStoreError("Mandate revoked")

            if state["max_transaction_minor"] is None:
                raise MandateStoreError(
                    "Per-transaction limit not registered"
                )

            if amount_minor > state["max_transaction_minor"]:
                raise MandateStoreError(
                    "Per-transaction spending limit exceeded"
                )

            if (
                state["transactions_used"]
                >= state["max_transactions"]
            ):
                raise MandateStoreError(
                    "Transaction limit exceeded"
                )

            if (
                state["spending_used_minor"] + amount_minor
                > state["max_spending_minor"]
            ):
                raise MandateStoreError(
                    "Total spending authority exceeded"
                )

            try:
                connection.execute("""
                    INSERT INTO mandate_reservations (
                        reservation_id,
                        mandate_id,
                        nonce,
                        amount_minor,
                        status
                    )
                    VALUES (?, ?, ?, ?, 'RESERVED')
                """, (
                    reservation_id,
                    mandate_id,
                    nonce,
                    amount_minor
                ))

            except sqlite3.IntegrityError as exc:
                raise MandateStoreError(
                    "Duplicate nonce or reservation ID"
                ) from exc

            cursor = connection.execute("""
                UPDATE mandate_state
                SET
                    transactions_used = transactions_used + 1,
                    spending_used_minor =
                        spending_used_minor + ?
                WHERE mandate_id = ?
                AND revoked = 0
                AND transactions_used < max_transactions
                AND spending_used_minor + ? <= max_spending_minor
                AND max_transaction_minor >= ?
            """, (
                amount_minor,
                mandate_id,
                amount_minor,
                amount_minor
            ))

            if cursor.rowcount != 1:
                raise MandateStoreError(
                    "Mandate reservation could not be committed"
                )

            return {
                "reservation_id": reservation_id,
                "mandate_id": mandate_id,
                "amount": amount_minor / 100,
                "status": "RESERVED"
            }

    def complete(self, reservation_id):
        reservation_id = self._validate_identifier(
            reservation_id,
            "reservation ID"
        )

        with self.connect() as connection:
            cursor = connection.execute("""
                UPDATE mandate_reservations
                SET status = 'COMPLETED'
                WHERE reservation_id = ?
                AND status = 'RESERVED'
            """, (reservation_id,))

            if cursor.rowcount == 0:
                raise MandateStoreError(
                    "Reservation not found or not pending"
                )

    def release(self, reservation_id):
        reservation_id = self._validate_identifier(
            reservation_id,
            "reservation ID"
        )

        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            reservation = connection.execute("""
                SELECT *
                FROM mandate_reservations
                WHERE reservation_id = ?
                AND status = 'RESERVED'
            """, (reservation_id,)).fetchone()

            if reservation is None:
                raise MandateStoreError(
                    "Reservation not found or not pending"
                )

            cursor = connection.execute("""
                UPDATE mandate_reservations
                SET status = 'RELEASED'
                WHERE reservation_id = ?
                AND status = 'RESERVED'
            """, (reservation_id,))

            if cursor.rowcount != 1:
                raise MandateStoreError(
                    "Reservation release failed"
                )

            cursor = connection.execute("""
                UPDATE mandate_state
                SET
                    transactions_used = transactions_used - 1,
                    spending_used_minor =
                        spending_used_minor - ?
                WHERE mandate_id = ?
                AND transactions_used > 0
                AND spending_used_minor >= ?
            """, (
                reservation["amount_minor"],
                reservation["mandate_id"],
                reservation["amount_minor"]
            ))

            if cursor.rowcount != 1:
                raise MandateStoreError(
                    "Mandate usage rollback failed"
                )

    def get_mandate_state(self, mandate_id):
        mandate_id = self._validate_identifier(
            mandate_id,
            "mandate ID"
        )

        with self.connect() as connection:
            row = connection.execute("""
                SELECT *
                FROM mandate_state
                WHERE mandate_id = ?
            """, (mandate_id,)).fetchone()

            return dict(row) if row else None

    def get_reservation(self, reservation_id):
        reservation_id = self._validate_identifier(
            reservation_id,
            "reservation ID"
        )

        with self.connect() as connection:
            row = connection.execute("""
                SELECT *
                FROM mandate_reservations
                WHERE reservation_id = ?
            """, (reservation_id,)).fetchone()

            return dict(row) if row else None
