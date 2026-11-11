import json
import sqlite3
import uuid

from datetime import datetime, timezone, timedelta
from pathlib import Path
from contextlib import contextmanager


class PayPalWebhookError(Exception):
    pass


class PayPalWebhookSignatureError(PayPalWebhookError):
    pass


class PayPalWebhookVerificationUnavailable(PayPalWebhookError):
    pass


class PayPalWebhookProcessingError(PayPalWebhookError):
    pass


class PayPalWebhookService:

    REQUIRED_HEADERS = (
        "paypal-transmission-id",
        "paypal-transmission-time",
        "paypal-cert-url",
        "paypal-auth-algo",
        "paypal-transmission-sig"
    )

    def __init__(
        self,
        verify_webhook_fn,
        event_handler,
        db_path="data/commons_state.db",
        processing_lease_seconds=300
    ):
        if not callable(verify_webhook_fn):
            raise ValueError(
                "A webhook verification function is required."
            )

        if not callable(event_handler):
            raise ValueError(
                "A webhook event handler is required."
            )

        if (
            not isinstance(processing_lease_seconds, int)
            or isinstance(processing_lease_seconds, bool)
            or processing_lease_seconds < 1
        ):
            raise ValueError(
                "Processing lease must be a positive integer."
            )

        self.verify_webhook_fn = verify_webhook_fn
        self.event_handler = event_handler
        self.processing_lease_seconds = processing_lease_seconds
        self.db_path = str(db_path)

        Path(self.db_path).parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self._initialize_database()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(
            self.db_path,
            timeout=30
        )

        connection.row_factory = sqlite3.Row

        try:
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
            connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def _initialize_database(self):
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS paypal_webhook_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    resource_id TEXT,
                    raw_body TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN (
                            'RECEIVED',
                            'PROCESSING',
                            'PROCESSED',
                            'FAILED'
                        )
                    ),
                    received_at TEXT NOT NULL,
                    processed_at TEXT,
                    last_error TEXT,
                    processing_started_at TEXT,
                    claim_token TEXT
                )
            """)

            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(paypal_webhook_events)"
                ).fetchall()
            }

            if "processing_started_at" not in columns:
                connection.execute(
                    "ALTER TABLE paypal_webhook_events "
                    "ADD COLUMN processing_started_at TEXT"
                )

            if "claim_token" not in columns:
                connection.execute(
                    "ALTER TABLE paypal_webhook_events "
                    "ADD COLUMN claim_token TEXT"
                )

    @staticmethod
    def _normalize_headers(headers):
        if not isinstance(headers, dict):
            raise PayPalWebhookError(
                "Webhook headers must be a dictionary."
            )

        return {
            str(key).lower(): str(value).strip()
            for key, value in headers.items()
        }

    @staticmethod
    def _parse_body(raw_body):
        if isinstance(raw_body, bytes):
            try:
                raw_body = raw_body.decode("utf-8")

            except UnicodeDecodeError as exc:
                raise PayPalWebhookError(
                    "Webhook body is not valid UTF-8."
                ) from exc

        if not isinstance(raw_body, str) or not raw_body:
            raise PayPalWebhookError(
                "Original webhook body is required."
            )

        try:
            event = json.loads(raw_body)

        except json.JSONDecodeError as exc:
            raise PayPalWebhookError(
                "Webhook body is not valid JSON."
            ) from exc

        if not isinstance(event, dict):
            raise PayPalWebhookError(
                "Webhook event must be a JSON object."
            )

        return raw_body, event

    def receive(self, headers, raw_body):
        normalized_headers = self._normalize_headers(headers)

        missing_headers = [
            name
            for name in self.REQUIRED_HEADERS
            if not normalized_headers.get(name)
        ]

        if missing_headers:
            raise PayPalWebhookError(
                "Missing required PayPal transmission headers: "
                + ", ".join(missing_headers)
            )

        raw_body, event = self._parse_body(raw_body)

        event_id = event.get("id")
        event_type = event.get("event_type")
        resource = event.get("resource", {})

        if not isinstance(event_id, str) or not event_id.strip():
            raise PayPalWebhookError(
                "PayPal event ID is missing."
            )

        if not isinstance(event_type, str) or not event_type.strip():
            raise PayPalWebhookError(
                "PayPal event type is missing."
            )

        if not isinstance(resource, dict):
            raise PayPalWebhookError(
                "PayPal event resource must be an object."
            )

        try:
            verified = self.verify_webhook_fn(
                normalized_headers,
                event
            )

        except Exception as exc:
            raise PayPalWebhookVerificationUnavailable(
                "PayPal webhook verification is temporarily unavailable."
            ) from exc

        if verified is not True:
            raise PayPalWebhookSignatureError(
                "PayPal webhook signature verification failed."
            )

        resource_id = resource.get("id")

        received_at = datetime.now(
            timezone.utc
        ).isoformat()

        claim_token = self._claim_event(
            event_id=event_id,
            event_type=event_type,
            resource_id=resource_id,
            raw_body=raw_body,
            received_at=received_at
        )

        if claim_token is None:
            return {
                "event_id": event_id,
                "event_type": event_type,
                "status": "DUPLICATE",
                "processed": False,
                "message": (
                    "This event has already been processed or "
                    "is currently being processed."
                )
            }

        try:
            self.event_handler(event)

        except Exception as exc:
            self._mark_failed(event_id, claim_token, str(exc))

            raise PayPalWebhookProcessingError(
                "Webhook event processing failed. "
                "The event is retained for controlled retry."
            ) from exc

        self._mark_processed(event_id, claim_token)

        return {
            "event_id": event_id,
            "event_type": event_type,
            "status": "PROCESSED",
            "processed": True,
            "message": "Verified PayPal webhook event processed."
        }

    def _claim_event(
        self,
        event_id,
        event_type,
        resource_id,
        raw_body,
        received_at
    ):
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        new_token = uuid.uuid4().hex

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            existing = connection.execute(
                '''
                SELECT status, processing_started_at
                FROM paypal_webhook_events
                WHERE event_id = ?
                ''',
                (event_id,)
            ).fetchone()

            if existing:
                status = existing["status"]

                if status == "PROCESSED":
                    return None

                if status == "FAILED":
                    cursor = connection.execute(
                        '''
                        UPDATE paypal_webhook_events
                        SET status = 'PROCESSING',
                            processing_started_at = ?,
                            claim_token = ?,
                            last_error = NULL
                        WHERE event_id = ?
                          AND status = 'FAILED'
                        ''',
                        (now_text, new_token, event_id)
                    )
                    return new_token if cursor.rowcount == 1 else None

                if status == "PROCESSING":
                    started_text = existing["processing_started_at"]

                    # Legacy or malformed leases are not reclaimed
                    # automatically because their age is unknown.
                    if not started_text:
                        return None

                    try:
                        started = datetime.fromisoformat(
                            started_text.replace("Z", "+00:00")
                        )
                        if started.tzinfo is None:
                            return None
                    except (TypeError, ValueError):
                        return None

                    age = (now - started).total_seconds()
                    if age < self.processing_lease_seconds:
                        return None

                    cursor = connection.execute(
                        '''
                        UPDATE paypal_webhook_events
                        SET processing_started_at = ?,
                            claim_token = ?,
                            last_error = NULL
                        WHERE event_id = ?
                          AND status = 'PROCESSING'
                          AND processing_started_at = ?
                        ''',
                        (now_text, new_token, event_id, started_text)
                    )
                    return new_token if cursor.rowcount == 1 else None

                return None

            connection.execute(
                '''
                INSERT INTO paypal_webhook_events (
                    event_id,
                    event_type,
                    resource_id,
                    raw_body,
                    status,
                    received_at,
                    processing_started_at,
                    claim_token
                )
                VALUES (?, ?, ?, ?, 'PROCESSING', ?, ?, ?)
                ''',
                (
                    event_id,
                    event_type,
                    resource_id,
                    raw_body,
                    received_at,
                    now_text,
                    new_token
                )
            )

            return new_token

    def _mark_processed(self, event_id, claim_token):
        with self._connect() as connection:
            cursor = connection.execute(
                '''
                UPDATE paypal_webhook_events
                SET status = 'PROCESSED',
                    processed_at = ?,
                    processing_started_at = NULL,
                    claim_token = NULL,
                    last_error = NULL
                WHERE event_id = ?
                  AND status = 'PROCESSING'
                  AND claim_token = ?
                ''',
                (
                    datetime.now(timezone.utc).isoformat(),
                    event_id,
                    claim_token
                )
            )

            if cursor.rowcount != 1:
                raise PayPalWebhookError(
                    "Webhook processing claim was lost before completion."
                )

    def _mark_failed(self, event_id, claim_token, error):
        with self._connect() as connection:
            cursor = connection.execute(
                '''
                UPDATE paypal_webhook_events
                SET status = 'FAILED',
                    processing_started_at = NULL,
                    claim_token = NULL,
                    last_error = ?
                WHERE event_id = ?
                  AND status = 'PROCESSING'
                  AND claim_token = ?
                ''',
                (
                    str(error)[:2000],
                    event_id,
                    claim_token
                )
            )

            return cursor.rowcount == 1

    def get_event(self, event_id):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM paypal_webhook_events
                WHERE event_id = ?
                """,
                (event_id,)
            ).fetchone()

            return dict(row) if row else None

    def list_failed_events(self, limit=100):
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError(
                "Limit must be between 1 and 1000."
            )

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, event_type, resource_id,
                       received_at, last_error
                FROM paypal_webhook_events
                WHERE status = 'FAILED'
                ORDER BY received_at ASC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()

            return [dict(row) for row in rows]
