from src.payment_store import (
    PaymentStore,
    PaymentStoreError
)
from src.mandate_service import (
    MandateService,
    MandateServiceError
)
from src.paypal_integration import (
    capture_authorization,
    void_authorization,
    PayPalError,
    PayPalTransportError
)


class PaymentDecisionError(Exception):
    pass


class PaymentDecisionService:

    def __init__(
        self,
        payment_store=None,
        mandate_service=None,
        capture_fn=None,
        void_fn=None
    ):
        self.payment_store = payment_store or PaymentStore()
        self.mandate_service = mandate_service or MandateService()

        self.capture_fn = capture_fn or capture_authorization
        self.void_fn = void_fn or void_authorization

    def execute_decision(self, transaction_id):
        if (
            not isinstance(transaction_id, str)
            or not transaction_id.strip()
        ):
            raise PaymentDecisionError(
                "Transaction ID is required."
            )

        transaction = self.payment_store.get_transaction(
            transaction_id
        )

        if not transaction:
            raise PaymentDecisionError(
                "Payment transaction was not found."
            )

        if transaction.get("status") != "RISK_PENDING":
            raise PaymentDecisionError(
                "Only transactions awaiting risk evaluation "
                "can have a payment decision executed."
            )

        decision = transaction.get("risk_decision")
        authorization_id = transaction.get("authorization_id")
        reservation_id = transaction.get("reservation_id")

        if decision not in ("CAPTURE", "HOLD", "VOID"):
            raise PaymentDecisionError(
                "Transaction does not contain a valid persisted "
                "risk decision."
            )

        if not authorization_id:
            raise PaymentDecisionError(
                "PayPal authorization ID is missing."
            )

        if not reservation_id:
            raise PaymentDecisionError(
                "Mandate reservation ID is missing."
            )

        if decision == "HOLD":
            self.payment_store.update_transaction(
                transaction_id,
                status="AUTHORIZED_PENDING_REVIEW"
            )

            return {
                "transaction_id": transaction_id,
                "authorization_id": authorization_id,
                "decision": "HOLD",
                "payment_status": "AUTHORIZED_PENDING_REVIEW",
                "message": (
                    "Payment remains authorized but uncaptured. "
                    "The mandate reservation remains active for review."
                )
            }

        operation_name = decision

        # Fast rejection for an already-recorded operation. The atomic claim
        # below remains the authoritative race-safe guard.
        existing_operation = self.payment_store.get_operation(
            transaction_id, operation_name
        )
        if existing_operation is not None:
            raise PaymentDecisionError(
                f"A {operation_name} operation already exists. "
                "Reconcile its PayPal status before attempting another operation."
            )

        try:
            # Claim the operation and move the transaction out of RISK_PENDING
            # in one SQLite write transaction. Concurrent callers cannot both
            # reach PayPal. An interrupted claim is reconciled, never replayed.
            operation = self.payment_store.claim_decision_operation(
                transaction_id, operation_name
            )
            # Test doubles and legacy injected stores may not implement the
            # new claim contract. The production PaymentStore always returns
            # a persisted operation mapping; reject malformed production data.
            if not isinstance(operation, dict) or not operation.get("idempotency_key"):
                if type(self.payment_store) is PaymentStore:
                    raise PaymentStoreError("Atomic operation claim returned an invalid record")
                operation = self.payment_store.prepare_operation(
                    transaction_id, operation_name
                )
        except PaymentStoreError as exc:
            raise PaymentDecisionError(
                f"Could not claim {operation_name} operation: {exc}"
            ) from exc

        try:
            if decision == "CAPTURE":
                result = self.capture_fn(
                    authorization_id,
                    request_id=operation["idempotency_key"]
                )
            else:
                result = self.void_fn(
                    authorization_id,
                    request_id=operation["idempotency_key"]
                )

        except (PayPalTransportError, PayPalError) as exc:
            self.payment_store.update_operation(
                transaction_id,
                operation_name,
                status="UNKNOWN",
                error_message=str(exc)
            )

            self.payment_store.update_transaction(
                transaction_id,
                status="RECONCILIATION_REQUIRED",
                last_error=str(exc)
            )

            raise PaymentDecisionError(
                f"PayPal {operation_name.lower()} outcome is uncertain. "
                "The mandate reservation has been retained. "
                "Reconcile with PayPal before retrying."
            ) from exc

        except Exception as exc:
            self.payment_store.update_operation(
                transaction_id,
                operation_name,
                status="UNKNOWN",
                error_message=str(exc)
            )

            self.payment_store.update_transaction(
                transaction_id,
                status="RECONCILIATION_REQUIRED",
                last_error=str(exc)
            )

            raise PaymentDecisionError(
                f"Unexpected error during {operation_name.lower()}. "
                "Reconciliation is required."
            ) from exc

        # A VOID is final only when PayPal explicitly confirms VOIDED.
        # Any other response is uncertain and must be reconciled.
        if decision == "VOID":
            paypal_status = (
                result.get("status")
                if isinstance(result, dict)
                else None
            )

            if (
                not isinstance(paypal_status, str)
                or paypal_status.strip().upper() != "VOIDED"
            ):
                message = (
                    "PayPal did not confirm that the authorization "
                    "was voided. Reconciliation is required."
                )

                self.payment_store.update_operation(
                    transaction_id,
                    operation_name,
                    status="UNKNOWN",
                    response=result if isinstance(result, dict) else None,
                    error_message=message
                )

                self.payment_store.update_transaction(
                    transaction_id,
                    status="RECONCILIATION_REQUIRED",
                    last_error=message
                )

                raise PaymentDecisionError(message)

        try:
            self.payment_store.update_operation(
                transaction_id,
                operation_name,
                status="SUCCEEDED",
                response=result
            )
        except PaymentStoreError as exc:
            self.payment_store.update_transaction(
                transaction_id,
                status="RECONCILIATION_REQUIRED",
                last_error=(
                    f"PayPal {operation_name.lower()} succeeded, "
                    "but its result could not be persisted."
                )
            )

            raise PaymentDecisionError(
                "PayPal operation succeeded, but Commons could not "
                "persist its result. Reconciliation is required."
            ) from exc

        if decision == "CAPTURE":
            return self._complete_capture(
                transaction_id,
                reservation_id,
                result
            )

        return self._complete_void(
            transaction_id,
            reservation_id,
            result
        )

    def _complete_capture(
        self,
        transaction_id,
        reservation_id,
        result
    ):
        capture_status = result.get("status")
        capture_id = result.get("capture_id")

        if capture_status == "COMPLETED":
            try:
                self.payment_store.update_transaction(
                    transaction_id,
                    status="CAPTURED",
                    capture_id=capture_id,
                    last_error=None
                )

                self.mandate_service.complete_reservation(
                    reservation_id
                )

            except (PaymentStoreError, MandateServiceError) as exc:
                try:
                    self.payment_store.update_transaction(
                        transaction_id,
                        status="RECONCILIATION_REQUIRED",
                        last_error=(
                            "PayPal capture completed, but Commons "
                            "could not finalize its local records."
                        )
                    )
                except PaymentStoreError:
                    pass

                raise PaymentDecisionError(
                    "PayPal capture completed, but local payment "
                    "or mandate records require reconciliation."
                ) from exc

            return {
                "transaction_id": transaction_id,
                "capture_id": capture_id,
                "decision": "CAPTURE",
                "payment_status": "CAPTURED",
                "paypal_status": capture_status,
                "message": (
                    "Payment successfully captured and mandate "
                    "reservation completed."
                )
            }

        if capture_status == "PENDING":
            self.payment_store.update_transaction(
                transaction_id,
                status="CAPTURE_PENDING",
                capture_id=capture_id,
                last_error=(
                    "PayPal accepted the capture, but it is still pending."
                )
            )

            return {
                "transaction_id": transaction_id,
                "capture_id": capture_id,
                "decision": "CAPTURE",
                "payment_status": "CAPTURE_PENDING",
                "paypal_status": capture_status,
                "message": (
                    "PayPal capture is pending. The mandate reservation "
                    "is retained until the final outcome is confirmed."
                )
            }

        message = (
            "PayPal returned an unexpected capture status. "
            "Reconciliation is required."
        )

        self.payment_store.update_transaction(
            transaction_id,
            status="RECONCILIATION_REQUIRED",
            capture_id=capture_id,
            last_error=message
        )

        raise PaymentDecisionError(message)

    def _complete_void(
        self,
        transaction_id,
        reservation_id,
        result
    ):
        try:
            self.payment_store.update_transaction(
                transaction_id,
                status="VOIDED",
                last_error=None
            )

            self.mandate_service.complete_reservation(
                reservation_id
            )

        except (PaymentStoreError, MandateServiceError) as exc:
            try:
                self.payment_store.update_transaction(
                    transaction_id,
                    status="RECONCILIATION_REQUIRED",
                    last_error=(
                        "PayPal void succeeded, but Commons could "
                        "not finalize its local records."
                    )
                )
            except PaymentStoreError:
                pass

            raise PaymentDecisionError(
                "PayPal void succeeded, but local payment or mandate "
                "records require reconciliation."
            ) from exc

        return {
            "transaction_id": transaction_id,
            "decision": "VOID",
            "payment_status": "VOIDED",
            "paypal_status": result.get("status"),
            "message": (
                "Authorization successfully voided and mandate "
                "reservation completed."
            )
        }
