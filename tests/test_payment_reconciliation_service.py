import unittest
from unittest.mock import Mock

from src.payment_reconciliation_service import (
    PaymentReconciliationService,
    PaymentReconciliationError
)


class TestPaymentReconciliationService(unittest.TestCase):

    def setUp(self):
        self.transaction_id = "txn_reconcile_001"
        self.reservation_id = "reservation_reconcile_001"
        self.authorization_id = "AUTH_RECONCILE_001"

        self.transaction = {
            "transaction_id": self.transaction_id,
            "reservation_id": self.reservation_id,
            "authorization_id": self.authorization_id,
            "status": "RECONCILIATION_REQUIRED",
            "risk_decision": "CAPTURE"
        }

        self.operation = {
            "operation_id": "operation_reconcile_001",
            "status": "UNKNOWN",
            "idempotency_key": "reconcile_key_001"
        }

        self.payment_store = Mock()
        self.mandate_service = Mock()
        self.get_authorization_fn = Mock()

        self.payment_store.get_transaction.return_value = (
            self.transaction
        )
        self.payment_store.get_operation.return_value = (
            self.operation
        )

        self.service = PaymentReconciliationService(
            get_authorization_fn=self.get_authorization_fn,
            payment_store=self.payment_store,
            mandate_service=self.mandate_service
        )

    def test_confirmed_capture_is_finalized(self):
        self.get_authorization_fn.return_value = {
            "id": self.authorization_id,
            "status": "CAPTURED"
        }

        result = self.service.reconcile_transaction(
            self.transaction_id
        )

        self.payment_store.update_operation.assert_called_once_with(
            self.transaction_id,
            "CAPTURE",
            status="SUCCEEDED",
            response={
                "id": self.authorization_id,
                "status": "CAPTURED"
            }
        )

        self.payment_store.update_transaction.assert_called_once_with(
            self.transaction_id,
            status="CAPTURED",
            last_error=None
        )

        self.mandate_service.complete_reservation.assert_called_once_with(
            self.reservation_id
        )

        self.assertTrue(result["reconciled"])
        self.assertEqual(result["payment_status"], "CAPTURED")

    def test_confirmed_void_is_finalized(self):
        self.transaction["risk_decision"] = "VOID"

        self.get_authorization_fn.return_value = {
            "id": self.authorization_id,
            "status": "VOIDED"
        }

        result = self.service.reconcile_transaction(
            self.transaction_id
        )

        self.payment_store.update_operation.assert_called_once_with(
            self.transaction_id,
            "VOID",
            status="SUCCEEDED",
            response={
                "id": self.authorization_id,
                "status": "VOIDED"
            }
        )

        self.payment_store.update_transaction.assert_called_once_with(
            self.transaction_id,
            status="VOIDED",
            last_error=None
        )

        self.mandate_service.complete_reservation.assert_called_once_with(
            self.reservation_id
        )

        self.assertTrue(result["reconciled"])
        self.assertEqual(result["payment_status"], "VOIDED")

    def test_active_authorization_remains_unresolved(self):
        self.get_authorization_fn.return_value = {
            "id": self.authorization_id,
            "status": "CREATED"
        }

        result = self.service.reconcile_transaction(
            self.transaction_id
        )

        self.payment_store.update_operation.assert_not_called()
        self.payment_store.update_transaction.assert_not_called()
        self.mandate_service.complete_reservation.assert_not_called()

        self.assertFalse(result["reconciled"])
        self.assertEqual(
            result["payment_status"],
            "RECONCILIATION_REQUIRED"
        )

    def test_mismatched_authorization_id_is_rejected(self):
        self.get_authorization_fn.return_value = {
            "id": "AUTH_DIFFERENT",
            "status": "CAPTURED"
        }

        with self.assertRaises(PaymentReconciliationError):
            self.service.reconcile_transaction(
                self.transaction_id
            )

        self.payment_store.update_transaction.assert_not_called()
        self.mandate_service.complete_reservation.assert_not_called()

    def test_missing_transaction_is_rejected(self):
        self.payment_store.get_transaction.return_value = None

        with self.assertRaises(PaymentReconciliationError):
            self.service.reconcile_transaction(
                self.transaction_id
            )

        self.get_authorization_fn.assert_not_called()

    def test_wrong_transaction_status_is_rejected(self):
        self.transaction["status"] = "CAPTURED"

        with self.assertRaises(PaymentReconciliationError):
            self.service.reconcile_transaction(
                self.transaction_id
            )

        self.get_authorization_fn.assert_not_called()

    def test_missing_operation_is_rejected(self):
        self.payment_store.get_operation.return_value = None

        with self.assertRaises(PaymentReconciliationError):
            self.service.reconcile_transaction(
                self.transaction_id
            )

        self.get_authorization_fn.assert_not_called()

    def test_missing_authorization_is_rejected(self):
        self.transaction["authorization_id"] = None

        with self.assertRaises(PaymentReconciliationError):
            self.service.reconcile_transaction(
                self.transaction_id
            )

        self.get_authorization_fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
