import unittest

from src.paypal_webhook_verifier import (
    PayPalWebhookVerifier,
    PayPalWebhookVerificationError,
    VERIFY_ENDPOINT,
)


class TestPayPalWebhookVerifier(unittest.TestCase):
    def setUp(self):
        self.webhook_id = "TEST-WEBHOOK-ID"

        self.headers = {
            "paypal-transmission-id": "transmission-123",
            "paypal-transmission-time": "2026-11-08T10:00:00Z",
            "paypal-cert-url": "https://api.paypal.com/cert/test",
            "paypal-auth-algo": "SHA256withRSA",
            "paypal-transmission-sig": "test-signature",
        }

        self.event = {
            "id": "WH-EVENT-123",
            "event_type": "PAYMENT.AUTHORIZATION.CREATED",
            "resource": {
                "id": "AUTH-123",
                "status": "CREATED",
            },
        }

        self.token_calls = []

        def token_provider():
            self.token_calls.append(True)
            return "test-access-token"

        self.token_provider = token_provider

        self.responses = []

        def request_fn(method, endpoint, token, payload):
            self.responses.append({
                "method": method,
                "endpoint": endpoint,
                "token": token,
                "payload": payload,
            })
            return self.api_response

        self.request_fn = request_fn
        self.api_response = {
            "verification_status": "SUCCESS"
        }

        self.verifier = PayPalWebhookVerifier(
            webhook_id=self.webhook_id,
            token_provider=self.token_provider,
            request_fn=self.request_fn,
        )

    def test_successful_verification(self):
        result = self.verifier.verify(
            self.headers,
            self.event,
        )

        self.assertTrue(result)
        self.assertEqual(len(self.token_calls), 1)
        self.assertEqual(len(self.responses), 1)

    def test_verification_request_uses_correct_endpoint(self):
        self.verifier.verify(self.headers, self.event)

        request = self.responses[0]

        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["endpoint"], VERIFY_ENDPOINT)
        self.assertEqual(request["token"], "test-access-token")

    def test_verification_payload_contains_webhook_id(self):
        self.verifier.verify(self.headers, self.event)

        payload = self.responses[0]["payload"]

        self.assertEqual(payload["webhook_id"], self.webhook_id)
        self.assertEqual(payload["webhook_event"], self.event)

    def test_verification_payload_contains_transmission_headers(self):
        self.verifier.verify(self.headers, self.event)

        payload = self.responses[0]["payload"]

        self.assertEqual(
            payload["transmission_id"],
            self.headers["paypal-transmission-id"],
        )
        self.assertEqual(
            payload["transmission_time"],
            self.headers["paypal-transmission-time"],
        )
        self.assertEqual(
            payload["cert_url"],
            self.headers["paypal-cert-url"],
        )
        self.assertEqual(
            payload["auth_algo"],
            self.headers["paypal-auth-algo"],
        )
        self.assertEqual(
            payload["transmission_sig"],
            self.headers["paypal-transmission-sig"],
        )

    def test_invalid_signature_returns_false(self):
        self.api_response = {
            "verification_status": "FAILURE"
        }

        result = self.verifier.verify(
            self.headers,
            self.event,
        )

        self.assertFalse(result)

    def test_missing_header_returns_false(self):
        headers = dict(self.headers)
        del headers["paypal-transmission-sig"]

        result = self.verifier.verify(
            headers,
            self.event,
        )

        self.assertFalse(result)
        self.assertEqual(len(self.token_calls), 0)
        self.assertEqual(len(self.responses), 0)

    def test_empty_header_returns_false(self):
        headers = dict(self.headers)
        headers["paypal-transmission-id"] = " "

        result = self.verifier.verify(
            headers,
            self.event,
        )

        self.assertFalse(result)
        self.assertEqual(len(self.responses), 0)

    def test_invalid_event_returns_false(self):
        result = self.verifier.verify(
            self.headers,
            None,
        )

        self.assertFalse(result)
        self.assertEqual(len(self.responses), 0)

    def test_invalid_headers_type_returns_false(self):
        result = self.verifier.verify(
            None,
            self.event,
        )

        self.assertFalse(result)
        self.assertEqual(len(self.responses), 0)

    def test_unexpected_paypal_response_is_rejected(self):
        self.api_response = {
            "verification_status": "PENDING"
        }

        with self.assertRaises(PayPalWebhookVerificationError):
            self.verifier.verify(self.headers, self.event)

    def test_invalid_api_response_is_rejected(self):
        self.api_response = None

        with self.assertRaises(PayPalWebhookVerificationError):
            self.verifier.verify(self.headers, self.event)

    def test_api_exception_is_wrapped(self):
        def failing_request(*args, **kwargs):
            raise RuntimeError("Simulated API failure")

        verifier = PayPalWebhookVerifier(
            webhook_id=self.webhook_id,
            token_provider=self.token_provider,
            request_fn=failing_request,
        )

        with self.assertRaises(PayPalWebhookVerificationError):
            verifier.verify(self.headers, self.event)

    def test_empty_webhook_id_is_rejected(self):
        with self.assertRaises(ValueError):
            PayPalWebhookVerifier(
                webhook_id=" ",
                token_provider=self.token_provider,
                request_fn=self.request_fn,
            )

    def test_header_names_are_case_insensitive(self):
        headers = {
            key.title(): value
            for key, value in self.headers.items()
        }

        result = self.verifier.verify(headers, self.event)

        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
