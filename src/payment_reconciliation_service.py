from src.payment_store import PaymentStore, PaymentStoreError
from src.mandate_service import MandateService, MandateServiceError
from src.paypal_integration import PayPalError, PayPalTransportError


class PaymentReconciliationError(Exception):
    pass


class PaymentReconciliationService:

    def __init__(
        self,
        get_authorization_fn,
        payment_store=None,
        mandate_service=None
    ):
        if not callable(get_authorization_fn):
            raise ValueError(
                "A valid PayPal authorization retrieval function is required."
            )

        self.payment_store = payment_store or PaymentStore()
        self.mandate_service = mandate_service or MandateService()
        self.get_authorization_fn = get_authorization_fn

    def reconcile_transaction(self, transaction_id):
        if not isinstance(transaction_id, str) or not transaction_id.strip():
            raise PaymentReconciliationError(
                "A valid transaction ID is required."
            )

        transaction = self.payment_store.get_transaction(transaction_id)

        if not transaction:
            raise PaymentReconciliationError(
                "Payment transaction was not found."
            )

        if transaction.get("status") != "RECONCILIATION_REQUIRED":
            raise PaymentReconciliationError(
                "Only transactions requiring reconciliation can be processed."
            )

        authorization_id = transaction.get("authorization_id")
        reservation_id = transaction.get("reservation_id")

        if not authorization_id or not reservation_id:
            raise PaymentReconciliationError(
                "Authorization or mandate reservation information is missing."
            )

        operation_name = transaction.get("risk_decision")

        if operation_name not in ("CAPTURE", "VOID"):
            raise PaymentReconciliationError(
                "The transaction does not have a reconcilable payment decision."
            )

        operation = self.payment_store.get_operation(
            transaction_id,
            operation_name
        )

        if not operation:
            raise PaymentReconciliationError(
                "The original payment operation could not be found."
            )

        if operation.get("status") not in ("UNKNOWN", "PREPARED"):
            raise PaymentReconciliationError(
                "The payment operation is not awaiting reconciliation."
            )

        try:
            remote = self.get_authorization_fn(authorization_id)
        except (PayPalTransportError, PayPalError) as exc:
            raise PaymentReconciliationError(
                "PayPal authorization status could not be retrieved. "
                "The transaction remains unresolved."
            ) from exc
        except Exception as exc:
            raise PaymentReconciliationError(
                "Unexpected error while retrieving PayPal authorization."
            ) from exc

        if not isinstance(remote, dict):
            raise PaymentReconciliationError(
                "PayPal returned an invalid authorization response."
            )

        remote_id = remote.get("id")
        remote_status = remote.get("status")

        if remote_id and remote_id != authorization_id:
            raise PaymentReconciliationError(
                "PayPal returned an authorization with a mismatched ID."
            )

        if not isinstance(remote_status, str):
            raise PaymentReconciliationError(
                "PayPal authorization response has no valid status."
            )

        remote_status = remote_status.upper()

        if operation_name == "CAPTURE":
            if remote_status == "CAPTURED":
                return self._finalize(
                    transaction_id,
                    reservation_id,
                    operation_name,
                    "CAPTURED",
                    remote
                )

            if remote_status == "CREATED":
                return self._unresolved(
                    transaction_id,
                    remote_status,
                    "Authorization remains active and uncaptured. "
                    "The capture outcome is not confirmed."
                )

        if operation_name == "VOID":
            if remote_status == "VOIDED":
                return self._finalize(
                    transaction_id,
                    reservation_id,
                    operation_name,
                    "VOIDED",
                    remote
                )

            if remote_status == "CREATED":
                return self._unresolved(
                    transaction_id,
                    remote_status,
                    "Authorization remains active. "
                    "The void outcome is not confirmed."
                )

        return self._unresolved(
            transaction_id,
            remote_status,
            "PayPal's authorization status does not establish "
            "a confirmed terminal outcome for this operation."
        )

    def _finalize(
        self,
        transaction_id,
        reservation_id,
        operation_name,
        final_status,
        remote_response
    ):
        try:
            self.payment_store.update_operation(
                transaction_id,
                operation_name,
                status="SUCCEEDED",
                response=remote_response
            )

            transaction_updates = {
                "status": final_status,
                "last_error": None
            }

            if operation_name == "CAPTURE":
                purchase_units = remote_response.get("purchase_units", [])
                capture_id = None

                for unit in purchase_units:
                    for capture in unit.get("payments", {}).get("captures", []):
                        if capture.get("status") == "COMPLETED":
                            capture_id = capture.get("id")
                            break

                    if capture_id:
                        break

                if capture_id:
                    transaction_updates["capture_id"] = capture_id

            self.payment_store.update_transaction(
                transaction_id,
                **transaction_updates
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
                        "PayPal's terminal status was confirmed, "
                        "but local finalization failed."
                    )
                )
            except Exception:
                pass

            raise PaymentReconciliationError(
                "PayPal's terminal outcome was confirmed, but Commons "
                "could not finalize its local records."
            ) from exc

        return {
            "transaction_id": transaction_id,
            "operation": operation_name,
            "paypal_authorization_status": final_status,
            "payment_status": final_status,
            "reconciled": True,
            "message": (
                "PayPal's terminal status was confirmed and local "
                "records were updated."
            )
        }

    def _unresolved(
        self,
        transaction_id,
        remote_status,
        message
    ):
        return {
            "transaction_id": transaction_id,
            "paypal_authorization_status": remote_status,
            "payment_status": "RECONCILIATION_REQUIRED",
            "reconciled": False,
            "message": message
        }
