import json
import sqlite3
import uuid

from pathlib import Path
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation


DB_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "commons_state.db"
)


class PaymentStoreError(Exception):
    pass


class PaymentStore:

    PAYMENT_STATUSES = {
        "CREATED",
        "APPROVAL_PENDING",
        "APPROVED",
        "AUTHORIZATION_PENDING",
        "AUTHORIZED",
        "RISK_PENDING",
        "EXECUTING_CREATE_ORDER",
        "EXECUTING_AUTHORIZE",
        "EXECUTING_CAPTURE",
        "EXECUTING_VOID",
        "AUTHORIZED_PENDING_REVIEW",
        "CAPTURE_PENDING",
        "CAPTURED",
        "VOID_PENDING",
        "VOIDED",
        "FAILED",
        "RECONCILIATION_REQUIRED"
    }

    OPERATION_STATUSES = {
        "PREPARED",
        "SUCCEEDED",
        "UNKNOWN",
        "FAILED"
    }

    OPERATIONS = {
        "CREATE_ORDER",
        "AUTHORIZE",
        "CAPTURE",
        "VOID"
    }

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
    def _identifier(value, field):
        if not isinstance(value, str) or not value.strip():
            raise PaymentStoreError(f"Invalid {field}")

        return value.strip()

    @staticmethod
    def _amount_minor(value):
        try:
            amount = Decimal(str(value))

            if not amount.is_finite() or amount <= 0:
                raise ValueError

            if amount != amount.quantize(Decimal("0.01")):
                raise ValueError

            return int(amount * 100)

        except (InvalidOperation, ValueError, TypeError):
            raise PaymentStoreError("Invalid payment amount")

    @staticmethod
    def _json(value):
        try:
            return json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False
            )
        except (TypeError, ValueError):
            raise PaymentStoreError("Value is not valid JSON data")

    def initialize(self):
        with self.connect() as connection:

            connection.execute("""
                CREATE TABLE IF NOT EXISTS payment_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    reservation_id TEXT NOT NULL UNIQUE,
                    amount_minor INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL,
                    paypal_order_id TEXT UNIQUE,
                    authorization_id TEXT UNIQUE,
                    capture_id TEXT UNIQUE,
                    risk_decision TEXT,
                    risk_score REAL,
                    model_version TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (reservation_id)
                        REFERENCES mandate_reservations(reservation_id)
                )
            """)

            connection.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_payment_transactions_status
                ON payment_transactions(status)
            """)

            connection.execute("""
                CREATE TABLE IF NOT EXISTS payment_operations (
                    operation_id TEXT PRIMARY KEY,
                    transaction_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    response_json TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(transaction_id, operation),
                    FOREIGN KEY (transaction_id)
                        REFERENCES payment_transactions(transaction_id)
                )
            """)

            connection.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_payment_operations_status
                ON payment_operations(status)
            """)

    def create_transaction(
        self,
        reservation_id,
        amount,
        currency="USD",
        transaction_id=None
    ):
        reservation_id = self._identifier(
            reservation_id,
            "reservation ID"
        )

        amount_minor = self._amount_minor(amount)

        if (
            not isinstance(currency, str)
            or len(currency) != 3
            or not currency.isalpha()
        ):
            raise PaymentStoreError("Invalid currency code")

        currency = currency.upper()
        transaction_id = transaction_id or str(uuid.uuid4())

        transaction_id = self._identifier(
            transaction_id,
            "transaction ID"
        )

        with self.connect() as connection:
            reservation = connection.execute("""
                SELECT reservation_id, amount_minor, status
                FROM mandate_reservations
                WHERE reservation_id = ?
            """, (reservation_id,)).fetchone()

            if reservation is None:
                raise PaymentStoreError(
                    "Mandate reservation does not exist"
                )

            if reservation["status"] != "RESERVED":
                raise PaymentStoreError(
                    "Mandate reservation is not active"
                )

            if reservation["amount_minor"] != amount_minor:
                raise PaymentStoreError(
                    "Payment amount does not match mandate reservation"
                )

            try:
                connection.execute("""
                    INSERT INTO payment_transactions (
                        transaction_id,
                        reservation_id,
                        amount_minor,
                        currency,
                        status
                    )
                    VALUES (?, ?, ?, ?, 'CREATED')
                """, (
                    transaction_id,
                    reservation_id,
                    amount_minor,
                    currency
                ))

            except sqlite3.IntegrityError as error:
                raise PaymentStoreError(
                    "Transaction or reservation already exists"
                ) from error

        return self.get_transaction(transaction_id)

    def get_transaction(self, transaction_id):
        transaction_id = self._identifier(
            transaction_id,
            "transaction ID"
        )

        with self.connect() as connection:
            row = connection.execute("""
                SELECT *
                FROM payment_transactions
                WHERE transaction_id = ?
            """, (transaction_id,)).fetchone()

            return dict(row) if row else None

    def get_transaction_by_order(self, order_id):
        order_id = self._identifier(order_id, "PayPal order ID")

        with self.connect() as connection:
            row = connection.execute("""
                SELECT *
                FROM payment_transactions
                WHERE paypal_order_id = ?
            """, (order_id,)).fetchone()

            return dict(row) if row else None

    def get_transaction_by_authorization(self, authorization_id):
        authorization_id = self._identifier(
            authorization_id,
            "authorization ID"
        )

        with self.connect() as connection:
            row = connection.execute("""
                SELECT *
                FROM payment_transactions
                WHERE authorization_id = ?
            """, (authorization_id,)).fetchone()

            return dict(row) if row else None

    def update_transaction(self, transaction_id, **fields):
        transaction_id = self._identifier(
            transaction_id,
            "transaction ID"
        )

        allowed_fields = {
            "status",
            "paypal_order_id",
            "authorization_id",
            "capture_id",
            "risk_decision",
            "risk_score",
            "model_version",
            "last_error"
        }

        if not fields or not set(fields).issubset(allowed_fields):
            raise PaymentStoreError(
                "Invalid or empty transaction update"
            )

        if "status" in fields:
            if fields["status"] not in self.PAYMENT_STATUSES:
                raise PaymentStoreError("Invalid payment status")

        if "risk_decision" in fields:
            decision = fields["risk_decision"]

            if decision is not None and decision not in {
                "CAPTURE", "HOLD", "VOID"
            }:
                raise PaymentStoreError("Invalid risk decision")

        if "risk_score" in fields:
            score = fields["risk_score"]

            if score is not None:
                try:
                    score = float(score)
                except (TypeError, ValueError):
                    raise PaymentStoreError("Invalid risk score")

                if not 0 <= score <= 1:
                    raise PaymentStoreError(
                        "Risk score must be between 0 and 1"
                    )

                fields["risk_score"] = score

        for key in (
            "paypal_order_id",
            "authorization_id",
            "capture_id",
            "model_version",
            "last_error"
        ):
            if key in fields and fields[key] is not None:
                fields[key] = self._identifier(
                    fields[key],
                    key
                )

        assignments = [
            f"{field} = ?" for field in fields
        ]

        assignments.append(
            "updated_at = CURRENT_TIMESTAMP"
        )

        values = list(fields.values())
        values.append(transaction_id)

        with self.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE payment_transactions
                SET {", ".join(assignments)}
                WHERE transaction_id = ?
                """,
                values
            )

            if cursor.rowcount != 1:
                raise PaymentStoreError(
                    "Payment transaction not found"
                )

        return self.get_transaction(transaction_id)


    def claim_order_operation(self, transaction_id, operation):
        """Atomically claim CREATE_ORDER or AUTHORIZE before a PayPal call."""
        transaction_id = self._identifier(transaction_id, "transaction ID")
        operation = self._identifier(operation, "operation").upper()
        expected = {"CREATE_ORDER": "CREATED", "AUTHORIZE": "APPROVAL_PENDING"}
        claimed = {"CREATE_ORDER": "EXECUTING_CREATE_ORDER", "AUTHORIZE": "EXECUTING_AUTHORIZE"}
        if operation not in expected:
            raise PaymentStoreError("Only CREATE_ORDER and AUTHORIZE can be claimed here")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            transaction = connection.execute(
                "SELECT status FROM payment_transactions WHERE transaction_id = ?", (transaction_id,)
            ).fetchone()
            if transaction is None:
                raise PaymentStoreError("Payment transaction not found")
            if transaction["status"] != expected[operation]:
                raise PaymentStoreError("Transaction is not available for this PayPal operation")
            existing = connection.execute(
                "SELECT * FROM payment_operations WHERE transaction_id = ? AND operation = ?",
                (transaction_id, operation)
            ).fetchone()
            if existing is not None:
                raise PaymentStoreError("Operation already claimed; reconcile before retrying")
            operation_id, key = str(uuid.uuid4()), str(uuid.uuid4())
            connection.execute(
                "INSERT INTO payment_operations (operation_id, transaction_id, operation, idempotency_key, status) VALUES (?, ?, ?, ?, 'PREPARED')",
                (operation_id, transaction_id, operation, key)
            )
            cursor = connection.execute(
                "UPDATE payment_transactions SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE transaction_id = ? AND status = ?",
                (claimed[operation], transaction_id, expected[operation])
            )
            if cursor.rowcount != 1:
                raise PaymentStoreError("Operation claim was lost")
            row = connection.execute(
                "SELECT * FROM payment_operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            return dict(row)

    def claim_decision_operation(self, transaction_id, operation):
        """Atomically claim a persisted CAPTURE/VOID decision.

        SQLite BEGIN IMMEDIATE serializes competing writers. The transaction
        state transition and unique operation insert commit together, so only
        one worker can become the external-call owner. A crash after claiming
        is deliberately fail-closed: reconciliation is required, not retry.
        """
        transaction_id = self._identifier(transaction_id, "transaction ID")
        operation = self._identifier(operation, "operation").upper()
        if operation not in {"CAPTURE", "VOID"}:
            raise PaymentStoreError("Only CAPTURE and VOID can be claimed here")

        claimed_status = "EXECUTING_CAPTURE" if operation == "CAPTURE" else "EXECUTING_VOID"
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            transaction = connection.execute(
                "SELECT status FROM payment_transactions WHERE transaction_id = ?",
                (transaction_id,)
            ).fetchone()
            if transaction is None:
                raise PaymentStoreError("Payment transaction not found")
            if transaction["status"] != "RISK_PENDING":
                raise PaymentStoreError("Transaction is not available for a new payment operation")
            existing = connection.execute(
                "SELECT * FROM payment_operations WHERE transaction_id = ? AND operation = ?",
                (transaction_id, operation)
            ).fetchone()
            if existing is not None:
                raise PaymentStoreError("Payment operation has already been claimed; reconcile before retrying")

            operation_id = str(uuid.uuid4())
            idempotency_key = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO payment_operations (operation_id, transaction_id, operation, idempotency_key, status) VALUES (?, ?, ?, ?, 'PREPARED')",
                (operation_id, transaction_id, operation, idempotency_key)
            )
            cursor = connection.execute(
                "UPDATE payment_transactions SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE transaction_id = ? AND status = 'RISK_PENDING'",
                (claimed_status, transaction_id)
            )
            if cursor.rowcount != 1:
                raise PaymentStoreError("Payment operation claim was lost")
            row = connection.execute(
                "SELECT * FROM payment_operations WHERE operation_id = ?",
                (operation_id,)
            ).fetchone()
            return dict(row)

    def prepare_operation(
        self,
        transaction_id,
        operation
    ):
        transaction_id = self._identifier(
            transaction_id,
            "transaction ID"
        )

        operation = self._identifier(
            operation,
            "operation"
        ).upper()

        if operation not in self.OPERATIONS:
            raise PaymentStoreError("Unsupported payment operation")

        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            transaction = connection.execute("""
                SELECT transaction_id
                FROM payment_transactions
                WHERE transaction_id = ?
            """, (transaction_id,)).fetchone()

            if transaction is None:
                raise PaymentStoreError(
                    "Payment transaction not found"
                )

            existing = connection.execute("""
                SELECT *
                FROM payment_operations
                WHERE transaction_id = ?
                AND operation = ?
            """, (transaction_id, operation)).fetchone()

            if existing:
                return dict(existing)

            operation_id = str(uuid.uuid4())
            idempotency_key = str(uuid.uuid4())

            connection.execute("""
                INSERT INTO payment_operations (
                    operation_id,
                    transaction_id,
                    operation,
                    idempotency_key,
                    status
                )
                VALUES (?, ?, ?, ?, 'PREPARED')
            """, (
                operation_id,
                transaction_id,
                operation,
                idempotency_key
            ))

            row = connection.execute("""
                SELECT *
                FROM payment_operations
                WHERE operation_id = ?
            """, (operation_id,)).fetchone()

            return dict(row)

    def update_operation(
        self,
        transaction_id,
        operation,
        status,
        response=None,
        error_message=None
    ):
        transaction_id = self._identifier(
            transaction_id,
            "transaction ID"
        )

        operation = self._identifier(
            operation,
            "operation"
        ).upper()

        status = self._identifier(
            status,
            "operation status"
        ).upper()

        if operation not in self.OPERATIONS:
            raise PaymentStoreError("Unsupported payment operation")

        if status not in self.OPERATION_STATUSES:
            raise PaymentStoreError("Invalid operation status")

        response_json = (
            self._json(response)
            if response is not None
            else None
        )

        if error_message is not None:
            if not isinstance(error_message, str):
                raise PaymentStoreError("Invalid error message")

            error_message = error_message[:2000]

        with self.connect() as connection:
            cursor = connection.execute("""
                UPDATE payment_operations
                SET
                    status = ?,
                    response_json = ?,
                    error_message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE transaction_id = ?
                AND operation = ?
            """, (
                status,
                response_json,
                error_message,
                transaction_id,
                operation
            ))

            if cursor.rowcount != 1:
                raise PaymentStoreError(
                    "Payment operation not found"
                )

        return self.get_operation(transaction_id, operation)

    def get_operation(self, transaction_id, operation):
        transaction_id = self._identifier(
            transaction_id,
            "transaction ID"
        )

        operation = self._identifier(
            operation,
            "operation"
        ).upper()

        with self.connect() as connection:
            row = connection.execute("""
                SELECT *
                FROM payment_operations
                WHERE transaction_id = ?
                AND operation = ?
            """, (transaction_id, operation)).fetchone()

            if row is None:
                return None

            result = dict(row)

            if result["response_json"]:
                result["response"] = json.loads(
                    result["response_json"]
                )
            else:
                result["response"] = None

            return result

    def list_pending_operations(self):
        with self.connect() as connection:
            rows = connection.execute("""
                SELECT *
                FROM payment_operations
                WHERE status IN ('PREPARED', 'UNKNOWN')
                ORDER BY created_at
            """).fetchall()

            return [dict(row) for row in rows]

    def list_reconciliation_required(self):
        with self.connect() as connection:
            rows = connection.execute("""
                SELECT *
                FROM payment_transactions
                WHERE status = 'RECONCILIATION_REQUIRED'
                ORDER BY updated_at
            """).fetchall()

            return [dict(row) for row in rows]
