import uuid
from decimal import Decimal, InvalidOperation
from src.mandate_service_integration import persist_verified_terms
from src.mandate_service import (
    MandateService,
    MandateServiceError
)
from src.payment_store import (
    PaymentStore,
    PaymentStoreError
)
from src.paypal_integration import (
    create_order as paypal_create_order,
    authorize_order as paypal_authorize_order,
    PayPalError,
    PayPalTransportError
)
from src.risk_engine import (
    RiskEngine,
    RiskEngineError,
    REQUIRED_FEATURES
)


class OrderServiceError(Exception):
    pass


class OrderService:

    def __init__(
        self,
        mandate_service=None,
        payment_store=None,
        paypal_create_order_fn=None,
        paypal_authorize_order_fn=None,
        risk_engine=None,
        trusted_feature_provider=None
    ):
        self.mandate_service = mandate_service or MandateService()
        self.payment_store = payment_store or PaymentStore()

        self.paypal_create_order = (
            paypal_create_order_fn or paypal_create_order
        )

        self.paypal_authorize_order = (
            paypal_authorize_order_fn or paypal_authorize_order
        )

        self.risk_engine = risk_engine or RiskEngine()
        self.trusted_feature_provider = trusted_feature_provider

    @staticmethod
    def _validate_order(order):
        if not isinstance(order, dict):
            raise OrderServiceError(
                "Order must be a JSON object."
            )

        required = (
            "order_id",
            "agent_id",
            "merchant_id",
            "amount",
            "currency",
            "category",
            "mandate",
            "signature"
        )

        missing = [
            field for field in required
            if field not in order
        ]

        if missing:
            raise OrderServiceError(
                f"Missing required order fields: {missing}"
            )

        for field in (
            "order_id",
            "agent_id",
            "merchant_id",
            "category"
        ):
            value = order[field]

            if not isinstance(value, str) or not value.strip():
                raise OrderServiceError(
                    f"'{field}' must be a non-empty string."
                )

        try:
            amount = Decimal(str(order["amount"]))
        except (InvalidOperation, ValueError):
            raise OrderServiceError(
                "Order amount must be a valid decimal number."
            )

        if (
            not amount.is_finite()
            or amount <= 0
            or amount != amount.quantize(Decimal("0.01"))
        ):
            raise OrderServiceError(
                "Order amount must be positive and have at most "
                "two decimal places."
            )

        currency = order["currency"]

        if (
            not isinstance(currency, str)
            or len(currency) != 3
            or not currency.isalpha()
        ):
            raise OrderServiceError(
                "Currency must be a three-letter alphabetic code."
            )

        if not isinstance(order["mandate"], dict):
            raise OrderServiceError(
                "Mandate must be a JSON object."
            )

        if (
            not isinstance(order["signature"], str)
            or not order["signature"].strip()
        ):
            raise OrderServiceError(
                "A signed mandate is required."
            )

        if order["mandate"].get("agent_id") != order["agent_id"]:
            raise OrderServiceError(
                "Order agent does not match the mandate agent."
            )

        return format(amount, ".2f"), currency.upper()

    def create_agent_order(self, order):
        amount, currency = self._validate_order(order)

        mandate_order = {
            "amount": amount,
            "order_id": order["order_id"],
            "merchant_id": order["merchant_id"],
            "category": order["category"]
        }

        try:
            reservation = self.mandate_service.reserve_order(
                mandate=order["mandate"],
                signature=order["signature"],
                order=mandate_order
            )
        except MandateServiceError as exc:
            raise OrderServiceError(
                f"Mandate verification failed: {exc}"
            ) from exc

        try:
            persist_verified_terms(order["mandate"])
        except Exception as exc:
            try:
                self.mandate_service.release_reservation(
                    reservation["reservation_id"]
                )
            except MandateServiceError:
                pass
            raise OrderServiceError(
                f"Could not persist verified mandate terms: {exc}"
            ) from exc

        reservation_id = reservation["reservation_id"]
        transaction_id = str(uuid.uuid4())

        try:
            self.payment_store.create_transaction(
                reservation_id=reservation_id,
                amount=amount,
                currency=currency,
                transaction_id=transaction_id
            )
        except PaymentStoreError as exc:
            try:
                self.mandate_service.release_reservation(
                    reservation_id
                )
            except MandateServiceError:
                pass

            raise OrderServiceError(
                f"Could not create payment transaction: {exc}"
            ) from exc

        try:
            claim = getattr(self.payment_store, "claim_order_operation", None)
            operation = (
                claim(transaction_id, "CREATE_ORDER")
                if callable(claim)
                else self.payment_store.prepare_operation(transaction_id, "CREATE_ORDER")
            )
        except PaymentStoreError as exc:
            self.payment_store.update_transaction(
                transaction_id,
                status="RECONCILIATION_REQUIRED",
                last_error=str(exc)
            )

            raise OrderServiceError(
                f"Could not prepare PayPal operation: {exc}"
            ) from exc

        try:
            result = self.paypal_create_order(
                amount=amount,
                currency=currency,
                description="Commons AI-agent order",
                custom_id=transaction_id,
                request_id=operation["idempotency_key"]
            )

        except PayPalTransportError as exc:
            self.payment_store.update_operation(
                transaction_id,
                "CREATE_ORDER",
                status="UNKNOWN",
                error_message=str(exc)
            )

            self.payment_store.update_transaction(
                transaction_id,
                status="RECONCILIATION_REQUIRED",
                last_error=str(exc)
            )

            raise OrderServiceError(
                "PayPal order creation outcome is unknown. "
                "The mandate reservation has been retained. "
                "Reconcile with PayPal before retrying."
            ) from exc

        except PayPalError as exc:
            self.payment_store.update_operation(
                transaction_id,
                "CREATE_ORDER",
                status="FAILED",
                error_message=str(exc)
            )

            self.payment_store.update_transaction(
                transaction_id,
                status="FAILED",
                last_error=str(exc)
            )

            try:
                self.mandate_service.release_reservation(
                    reservation_id
                )
            except MandateServiceError:
                pass

            raise OrderServiceError(
                f"PayPal order creation failed: {exc}"
            ) from exc

        except Exception as exc:
            self.payment_store.update_operation(
                transaction_id,
                "CREATE_ORDER",
                status="UNKNOWN",
                error_message=str(exc)
            )

            self.payment_store.update_transaction(
                transaction_id,
                status="RECONCILIATION_REQUIRED",
                last_error=str(exc)
            )

            raise OrderServiceError(
                "Unexpected error during PayPal order creation. "
                "The result must be reconciled before retrying."
            ) from exc

        paypal_order_id = result.get("order_id")

        if not paypal_order_id:
            message = (
                "PayPal response did not contain an order ID. "
                "Reconciliation is required."
            )

            self.payment_store.update_operation(
                transaction_id,
                "CREATE_ORDER",
                status="UNKNOWN",
                response=result,
                error_message=message
            )

            self.payment_store.update_transaction(
                transaction_id,
                status="RECONCILIATION_REQUIRED",
                last_error=message
            )

            raise OrderServiceError(message)

        try:
            self.payment_store.update_operation(
                transaction_id,
                "CREATE_ORDER",
                status="SUCCEEDED",
                response=result
            )

            self.payment_store.update_transaction(
                transaction_id,
                status="APPROVAL_PENDING",
                paypal_order_id=paypal_order_id
            )

        except PaymentStoreError as exc:
            message = (
                "PayPal created the order, but Commons could not "
                "persist the result. Reconciliation is required."
            )

            try:
                self.payment_store.update_transaction(
                    transaction_id,
                    status="RECONCILIATION_REQUIRED",
                    last_error=message
                )
            except PaymentStoreError:
                pass

            raise OrderServiceError(message) from exc

        return {
            "transaction_id": transaction_id,
            "agent_order_id": order["order_id"],
            "merchant_id": order["merchant_id"],
            "agent_id": order["agent_id"],
            "reservation_id": reservation_id,
            "paypal_order_id": paypal_order_id,
            "paypal_status": result.get("status"),
            "approval_url": result.get("approval_url"),
            "payment_status": "APPROVAL_PENDING",
            "mandate_status": reservation["status"],
            "message": (
                "Mandate verified and spending reserved. "
                "PayPal checkout order created. "
                "No payment has been authorized or captured yet."
            )
        }

    def authorize_agent_order(
        self,
        transaction_id,
        paypal_order_id
    ):
        if (
            not isinstance(transaction_id, str)
            or not transaction_id.strip()
        ):
            raise OrderServiceError(
                "Transaction ID is required."
            )

        if (
            not isinstance(paypal_order_id, str)
            or not paypal_order_id.strip()
        ):
            raise OrderServiceError(
                "PayPal order ID is required."
            )

        transaction = self.payment_store.get_transaction(
            transaction_id
        )

        if not transaction:
            raise OrderServiceError(
                "Payment transaction was not found."
            )

        if transaction.get("paypal_order_id") != paypal_order_id:
            raise OrderServiceError(
                "PayPal order ID does not match the stored transaction."
            )

        if transaction.get("status") == "RISK_PENDING":
            return {
                "transaction_id": transaction_id,
                "paypal_order_id": paypal_order_id,
                "authorization_id": transaction.get(
                    "authorization_id"
                ),
                "payment_status": "RISK_PENDING",
                "message": (
                    "Payment is already authorized and awaiting "
                    "risk evaluation."
                )
            }

        if transaction.get("status") != "APPROVAL_PENDING":
            raise OrderServiceError(
                "Transaction is not awaiting buyer approval."
            )

        if self.payment_store.get_operation(
            transaction_id,
            "AUTHORIZE"
        ) is not None:
            raise OrderServiceError(
                "An authorization operation already exists. "
                "Reconcile its PayPal status before attempting "
                "another authorization."
            )

        try:
            claim = getattr(self.payment_store, "claim_order_operation", None)
            operation = (
                claim(transaction_id, "AUTHORIZE")
                if callable(claim)
                else self.payment_store.prepare_operation(transaction_id, "AUTHORIZE")
            )
        except PaymentStoreError as exc:
            self.payment_store.update_transaction(
                transaction_id,
                status="RECONCILIATION_REQUIRED",
                last_error=str(exc)
            )

            raise OrderServiceError(
                f"Could not prepare authorization operation: {exc}"
            ) from exc

        try:
            result = self.paypal_authorize_order(
                paypal_order_id,
                request_id=operation["idempotency_key"]
            )

        except PayPalTransportError as exc:
            self.payment_store.update_operation(
                transaction_id,
                "AUTHORIZE",
                status="UNKNOWN",
                error_message=str(exc)
            )

            self.payment_store.update_transaction(
                transaction_id,
                status="RECONCILIATION_REQUIRED",
                last_error=str(exc)
            )

            raise OrderServiceError(
                "Authorization outcome is unknown. "
                "Do not retry until PayPal has been reconciled."
            ) from exc

        except PayPalError as exc:
            self.payment_store.update_operation(
                transaction_id,
                "AUTHORIZE",
                status="FAILED",
                error_message=str(exc)
            )

            self.payment_store.update_transaction(
                transaction_id,
                status="RECONCILIATION_REQUIRED",
                last_error=str(exc)
            )

            raise OrderServiceError(
                "PayPal authorization failed. "
                "Reconciliation is required before further action."
            ) from exc

        except Exception as exc:
            self.payment_store.update_operation(
                transaction_id,
                "AUTHORIZE",
                status="UNKNOWN",
                error_message=str(exc)
            )

            self.payment_store.update_transaction(
                transaction_id,
                status="RECONCILIATION_REQUIRED",
                last_error=str(exc)
            )

            raise OrderServiceError(
                "Unexpected authorization error. "
                "The transaction requires reconciliation."
            ) from exc

        authorization_id = result.get("authorization_id")

        if not authorization_id:
            message = (
                "PayPal authorization response did not contain "
                "an authorization ID. Reconciliation is required."
            )

            self.payment_store.update_operation(
                transaction_id,
                "AUTHORIZE",
                status="UNKNOWN",
                response=result,
                error_message=message
            )

            self.payment_store.update_transaction(
                transaction_id,
                status="RECONCILIATION_REQUIRED",
                last_error=message
            )

            raise OrderServiceError(message)

        try:
            self.payment_store.update_operation(
                transaction_id,
                "AUTHORIZE",
                status="SUCCEEDED",
                response=result
            )

            self.payment_store.update_transaction(
                transaction_id,
                status="RISK_PENDING",
                authorization_id=authorization_id,
                last_error=None
            )

        except PaymentStoreError as exc:
            message = (
                "PayPal authorization succeeded, but Commons could "
                "not persist the result. Reconciliation is required."
            )

            try:
                self.payment_store.update_transaction(
                    transaction_id,
                    status="RECONCILIATION_REQUIRED",
                    last_error=message
                )
            except PaymentStoreError:
                pass

            raise OrderServiceError(message) from exc

        return {
            "transaction_id": transaction_id,
            "paypal_order_id": paypal_order_id,
            "authorization_id": authorization_id,
            "paypal_status": result.get("status"),
            "payment_status": "RISK_PENDING",
            "message": (
                "Buyer-approved PayPal order successfully authorized. "
                "Funds have not been captured. "
                "The order is ready for risk evaluation."
            )
        }

    def evaluate_authorized_order(self, transaction_id):
        if (
            not isinstance(transaction_id, str)
            or not transaction_id.strip()
        ):
            raise OrderServiceError(
                "Transaction ID is required."
            )

        transaction = self.payment_store.get_transaction(
            transaction_id
        )

        if not transaction:
            raise OrderServiceError(
                "Payment transaction was not found."
            )

        if transaction.get("status") != "RISK_PENDING":
            raise OrderServiceError(
                "Only authorized transactions awaiting risk "
                "evaluation can be scored."
            )

        if not transaction.get("authorization_id"):
            raise OrderServiceError(
                "Stored PayPal authorization ID is missing."
            )

        if self.trusted_feature_provider is None:
            raise OrderServiceError(
                "Trusted feature provider is not configured. "
                "Risk evaluation is blocked rather than using "
                "unverified or fabricated feature values."
            )

        try:
            features = self.trusted_feature_provider(transaction)
        except Exception as exc:
            raise OrderServiceError(
                f"Trusted feature construction failed: {exc}"
            ) from exc

        if not isinstance(features, dict):
            raise OrderServiceError(
                "Trusted feature provider must return a dictionary."
            )

        missing = [
            feature for feature in REQUIRED_FEATURES
            if feature not in features
        ]

        unexpected = [
            feature for feature in features
            if feature not in REQUIRED_FEATURES
        ]

        if missing:
            raise OrderServiceError(
                f"Trusted feature provider omitted features: {missing}"
            )

        if unexpected:
            raise OrderServiceError(
                f"Unexpected features supplied: {unexpected}"
            )

        try:
            result = self.risk_engine.score_order(features)
        except (ValueError, RiskEngineError, KeyError) as exc:
            raise OrderServiceError(
                f"Risk evaluation failed: {exc}"
            ) from exc

        try:
            self.payment_store.update_transaction(
                transaction_id,
                risk_decision=result["decision"],
                risk_score=result["risk_probability"],
                model_version=result["model_version"]
            )
        except PaymentStoreError as exc:
            raise OrderServiceError(
                "Risk evaluation completed, but its result could "
                "not be persisted. Do not apply a payment decision "
                "until the result has been reconciled."
            ) from exc

        return {
            "transaction_id": transaction_id,
            "authorization_id": transaction["authorization_id"],
            "payment_status": "RISK_PENDING",
            "decision": result["decision"],
            "risk_probability": result["risk_probability"],
            "risk_percentage": result["risk_percentage"],
            "model_version": result["model_version"],
            "thresholds": result["thresholds"],
            "reasons": result["reasons"],
            "features": result["features"],
            "message": (
                "Risk evaluation completed and decision persisted. "
                "No capture or void request has been sent yet."
            )
        }
