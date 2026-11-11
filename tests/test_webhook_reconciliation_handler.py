def test_verified_authorization_webhook_reconciles_only_matching_pending_transaction(monkeypatch):
    from src import paypal_webhook_api as webhook_api
    from src import payment_store as payment_store_module
    from src import payment_reconciliation_service as reconciliation_module

    class FakeStore:
        def get_transaction_by_authorization(self, authorization_id):
            assert authorization_id == "AUTH-1"
            return {"transaction_id": "TX-1", "status": "RECONCILIATION_REQUIRED"}

    calls = []
    class FakeReconciler:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))
        def reconcile_transaction(self, transaction_id):
            calls.append(("reconcile", transaction_id))
            return {"payment_status": "CAPTURED"}

    monkeypatch.setattr(payment_store_module, "PaymentStore", FakeStore)
    monkeypatch.setattr(reconciliation_module, "PaymentReconciliationService", FakeReconciler)

    result = webhook_api.handle_paypal_event({
        "id": "WH-1",
        "event_type": "PAYMENT.AUTHORIZATION.CREATED",
        "resource": {"id": "AUTH-1"}
    })

    assert result["handled"] is True
    assert result["transaction_id"] == "TX-1"
    assert calls[-1] == ("reconcile", "TX-1")


def test_unmatched_webhook_does_not_attempt_reconciliation(monkeypatch):
    from src import paypal_webhook_api as webhook_api
    from src import payment_store as payment_store_module

    class FakeStore:
        def get_transaction_by_authorization(self, authorization_id):
            return None

    monkeypatch.setattr(payment_store_module, "PaymentStore", FakeStore)
    result = webhook_api.handle_paypal_event({
        "id": "WH-2",
        "event_type": "PAYMENT.AUTHORIZATION.CREATED",
        "resource": {"id": "AUTH-NOT-LOCAL"}
    })
    assert result == {"handled": False, "reason": "TRANSACTION_NOT_FOUND"}
