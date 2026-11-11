from fastapi.testclient import TestClient

import src.paypal_webhook_api as api

from src.paypal_webhook_service import (
    PayPalWebhookService,
)


HEADERS = {
    "paypal-transmission-id": "TEST-TRANSMISSION-001",
    "paypal-transmission-time": "2026-11-08T12:00:00Z",
    "paypal-cert-url": "https://api.sandbox.paypal.com/cert",
    "paypal-auth-algo": "SHA256withRSA",
    "paypal-transmission-sig": "mock-signature",
}


def sample_event():
    return {
        "id": "WH-TEST-001",
        "event_type": "PAYMENT.AUTHORIZATION.CREATED",
        "resource": {
            "id": "AUTH-TEST-001"
        }
    }


def configure_test_service(
    monkeypatch,
    tmp_path,
    verifier,
    handler=None
):
    if handler is None:
        handler = lambda event: None

    service = PayPalWebhookService(
        verify_webhook_fn=verifier,
        event_handler=handler,
        db_path=str(tmp_path / "webhook_test.db")
    )

    monkeypatch.setattr(
        api,
        "webhook_service",
        service
    )

    return service


def test_missing_headers_are_rejected(monkeypatch, tmp_path):
    configure_test_service(
        monkeypatch,
        tmp_path,
        verifier=lambda headers, event: True
    )

    client = TestClient(api.app)

    response = client.post(
        "/webhooks/paypal",
        json=sample_event()
    )

    assert response.status_code == 400
    assert "Missing required" in response.json()["detail"]


def test_invalid_signature_is_rejected(monkeypatch, tmp_path):
    verifier_calls = []

    def verifier(headers, event):
        verifier_calls.append(event["id"])
        return False

    configure_test_service(
        monkeypatch,
        tmp_path,
        verifier=verifier
    )

    client = TestClient(api.app)

    response = client.post(
        "/webhooks/paypal",
        headers=HEADERS,
        json=sample_event()
    )

    assert response.status_code == 400

    assert (
        "signature verification failed"
        in response.json()["detail"]
    )

    assert verifier_calls == ["WH-TEST-001"]


def test_valid_signature_processes_event(monkeypatch, tmp_path):
    processed_events = []

    service = configure_test_service(
        monkeypatch,
        tmp_path,
        verifier=lambda headers, event: True,
        handler=lambda event: processed_events.append(
            event["id"]
        )
    )

    client = TestClient(api.app)

    response = client.post(
        "/webhooks/paypal",
        headers=HEADERS,
        json=sample_event()
    )

    assert response.status_code == 200
    assert response.json()["status"] == "PROCESSED"
    assert response.json()["processed"] is True

    assert processed_events == ["WH-TEST-001"]

    stored_event = service.get_event("WH-TEST-001")

    assert stored_event is not None
    assert stored_event["status"] == "PROCESSED"


def test_duplicate_event_is_not_processed_twice(
    monkeypatch,
    tmp_path
):
    processed_events = []

    configure_test_service(
        monkeypatch,
        tmp_path,
        verifier=lambda headers, event: True,
        handler=lambda event: processed_events.append(
            event["id"]
        )
    )

    client = TestClient(api.app)

    first_response = client.post(
        "/webhooks/paypal",
        headers=HEADERS,
        json=sample_event()
    )

    second_response = client.post(
        "/webhooks/paypal",
        headers=HEADERS,
        json=sample_event()
    )

    assert first_response.status_code == 200
    assert first_response.json()["status"] == "PROCESSED"

    assert second_response.status_code == 200
    assert second_response.json()["status"] == "DUPLICATE"

    assert processed_events == ["WH-TEST-001"]


def test_verification_service_failure_returns_503(
    monkeypatch,
    tmp_path
):
    def verifier(headers, event):
        raise RuntimeError("Simulated PayPal outage")

    configure_test_service(
        monkeypatch,
        tmp_path,
        verifier=verifier
    )

    client = TestClient(api.app)

    response = client.post(
        "/webhooks/paypal",
        headers=HEADERS,
        json=sample_event()
    )

    assert response.status_code == 503


def test_handler_failure_returns_500_and_records_failure(
    monkeypatch,
    tmp_path
):
    def handler(event):
        raise RuntimeError(
            "Simulated processing failure"
        )

    service = configure_test_service(
        monkeypatch,
        tmp_path,
        verifier=lambda headers, event: True,
        handler=handler
    )

    client = TestClient(api.app)

    response = client.post(
        "/webhooks/paypal",
        headers=HEADERS,
        json=sample_event()
    )

    assert response.status_code == 500

    stored_event = service.get_event("WH-TEST-001")

    assert stored_event is not None
    assert stored_event["status"] == "FAILED"

    assert (
        "Simulated processing failure"
        in stored_event["last_error"]
    )
