import unittest
from unittest.mock import Mock

from src.payment_decision_service import (
    PaymentDecisionService,
    PaymentDecisionError
)
from src.paypal_integration import PayPalError


class TestPaymentDecisionService(unittest.TestCase):

    def setUp(self):
        self.transaction_id = "txn_test_001"
        self.reservation_id = "reservation_test_001"
        self.authorization_id = "AUTH_TEST_001"

        self.transaction = {
            "transaction_id": self.transaction_id,
            "reservation_id": self.reservation_id,
            "authorization_id": self.authorization_id,
            "status": "RISK_PENDING",
            "risk_decision": "CAPTURE",
            "risk_score": 0.05,
            "model_version": "immune_v2"
        }

        self.payment_store = Mock()
        self.mandate_service = Mock()
        self.capture_fn = Mock()
        self.void_fn = Mock()

        # Return the shared dictionary so test mutations are visible.
        self.payment_store.get_transaction.return_value = (
            self.transaction
        )

        self.payment_store.get_operation.return_value = None

        self.payment_store.prepare_operation.return_value = {
            "operation_id": "operation_test_001",
            "idempotency_key": "stable_test_key_001"
        }

        self.service = PaymentDecisionService(
            payment_store=self.payment_store,
            mandate_service=self.mandate_service,
            capture_fn=self.capture_fn,
            void_fn=self.void_fn
        )

    def test_capture_decision_completes_payment(self):
        self.capture_fn.return_value = {
            "status": "COMPLETED",
            "capture_id": "CAPTURE_TEST_001"
        }

        result = self.service.execute_decision(
            self.transaction_id
        )

        self.capture_fn.assert_called_once_with(
            self.authorization_id,
            request_id="stable_test_key_001"
        )

        self.void_fn.assert_not_called()

        self.payment_store.update_operation.assert_called_once_with(
            self.transaction_id,
            "CAPTURE",
            status="SUCCEEDED",
            response={
                "status": "COMPLETED",
                "capture_id": "CAPTURE_TEST_001"
            }
        )

        self.payment_store.update_transaction.assert_called_once_with(
            self.transaction_id,
            status="CAPTURED",
            capture_id="CAPTURE_TEST_001",
            last_error=None
        )

        self.mandate_service.complete_reservation.assert_called_once_with(
            self.reservation_id
        )

        self.assertEqual(result["payment_status"], "CAPTURED")
        self.assertEqual(result["capture_id"], "CAPTURE_TEST_001")

    def test_hold_keeps_authorization_uncaptured(self):
        self.transaction["risk_decision"] = "HOLD"

        result = self.service.execute_decision(
            self.transaction_id
        )

        self.capture_fn.assert_not_called()
        self.void_fn.assert_not_called()

        self.payment_store.prepare_operation.assert_not_called()
        self.payment_store.update_operation.assert_not_called()

        self.payment_store.update_transaction.assert_called_once_with(
            self.transaction_id,
            status="AUTHORIZED_PENDING_REVIEW"
        )

        self.mandate_service.complete_reservation.assert_not_called()
        self.mandate_service.release_reservation.assert_not_called()

        self.assertEqual(
            result["payment_status"],
            "AUTHORIZED_PENDING_REVIEW"
        )

    def test_void_decision_completes_reservation(self):
        self.transaction["risk_decision"] = "VOID"

        self.void_fn.return_value = {
            "status": "VOIDED"
        }

        result = self.service.execute_decision(
            self.transaction_id
        )

        self.void_fn.assert_called_once_with(
            self.authorization_id,
            request_id="stable_test_key_001"
        )

        self.capture_fn.assert_not_called()

        self.payment_store.update_operation.assert_called_once_with(
            self.transaction_id,
            "VOID",
            status="SUCCEEDED",
            response={"status": "VOIDED"}
        )

        self.payment_store.update_transaction.assert_called_once_with(
            self.transaction_id,
            status="VOIDED",
            last_error=None
        )

        self.mandate_service.complete_reservation.assert_called_once_with(
            self.reservation_id
        )

        self.assertEqual(result["payment_status"], "VOIDED")

    def test_void_unconfirmed_status_requires_reconciliation(self):
        for response in (
            {"status": "CREATED"},
            {"status": "PENDING"},
            {},
            None,
        ):
            with self.subTest(response=response):
                self.payment_store.reset_mock()
                self.mandate_service.reset_mock()
                self.void_fn.reset_mock()
                self.payment_store.get_transaction.return_value = self.transaction
                self.payment_store.get_operation.return_value = None
                self.payment_store.prepare_operation.return_value = {
                    "operation_id": "operation_test_001",
                    "idempotency_key": "stable_test_key_001"
                }
                self.transaction["status"] = "RISK_PENDING"
                self.transaction["risk_decision"] = "VOID"
                self.void_fn.return_value = response

                with self.assertRaises(PaymentDecisionError):
                    self.service.execute_decision(self.transaction_id)

                self.payment_store.update_operation.assert_called_once_with(
                    self.transaction_id,
                    "VOID",
                    status="UNKNOWN",
                    response=response if isinstance(response, dict) else None,
                    error_message=(
                        "PayPal did not confirm that the authorization "
                        "was voided. Reconciliation is required."
                    )
                )

                self.payment_store.update_transaction.assert_called_once_with(
                    self.transaction_id,
                    status="RECONCILIATION_REQUIRED",
                    last_error=(
                        "PayPal did not confirm that the authorization "
                        "was voided. Reconciliation is required."
                    )
                )

                self.mandate_service.complete_reservation.assert_not_called()
                self.mandate_service.release_reservation.assert_not_called()

    def test_paypal_error_requires_reconciliation(self):
        self.capture_fn.side_effect = PayPalError(
            "Simulated PayPal failure"
        )

        with self.assertRaises(PaymentDecisionError):
            self.service.execute_decision(
                self.transaction_id
            )

        self.capture_fn.assert_called_once()

        self.payment_store.update_operation.assert_called_once_with(
            self.transaction_id,
            "CAPTURE",
            status="UNKNOWN",
            error_message="Simulated PayPal failure"
        )

        self.payment_store.update_transaction.assert_called_once_with(
            self.transaction_id,
            status="RECONCILIATION_REQUIRED",
            last_error="Simulated PayPal failure"
        )

        self.mandate_service.complete_reservation.assert_not_called()
        self.mandate_service.release_reservation.assert_not_called()

    def test_duplicate_operation_is_rejected(self):
        self.payment_store.get_operation.return_value = {
            "operation_id": "existing_operation",
            "status": "SUCCEEDED",
            "idempotency_key": "existing_key"
        }

        with self.assertRaises(PaymentDecisionError):
            self.service.execute_decision(
                self.transaction_id
            )

        self.capture_fn.assert_not_called()
        self.void_fn.assert_not_called()
        self.payment_store.prepare_operation.assert_not_called()

    def test_missing_transaction_is_rejected(self):
        self.payment_store.get_transaction.return_value = None

        with self.assertRaises(PaymentDecisionError):
            self.service.execute_decision(
                self.transaction_id
            )

        self.capture_fn.assert_not_called()
        self.void_fn.assert_not_called()

    def test_invalid_transaction_status_is_rejected(self):
        self.transaction["status"] = "CAPTURED"

        with self.assertRaises(PaymentDecisionError):
            self.service.execute_decision(
                self.transaction_id
            )

        self.capture_fn.assert_not_called()
        self.void_fn.assert_not_called()

    def test_missing_authorization_id_is_rejected(self):
        self.transaction["authorization_id"] = None

        with self.assertRaises(PaymentDecisionError):
            self.service.execute_decision(
                self.transaction_id
            )

        self.capture_fn.assert_not_called()
        self.void_fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
