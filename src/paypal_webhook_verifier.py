import logging

from src.paypal_integration import (
    PayPalError,
    get_access_token,
    paypal_request,
)


logger = logging.getLogger(__name__)

VERIFY_ENDPOINT = "/v1/notifications/verify-webhook-signature"

REQUIRED_HEADERS = (
    "paypal-transmission-id",
    "paypal-transmission-time",
    "paypal-cert-url",
    "paypal-auth-algo",
    "paypal-transmission-sig",
)


class PayPalWebhookVerificationError(PayPalError):
    """Raised when PayPal webhook verification cannot be completed."""


class PayPalWebhookVerifier:
    def __init__(
        self,
        webhook_id,
        token_provider=None,
        request_fn=None,
    ):
        if not isinstance(webhook_id, str) or not webhook_id.strip():
            raise ValueError("A valid PayPal Webhook ID is required.")

        self.webhook_id = webhook_id.strip()
        self.token_provider = token_provider or get_access_token
        self.request_fn = request_fn or paypal_request

    def __call__(self, headers, event):
        return self.verify(headers, event)

    def verify(self, headers, event):
        if not isinstance(headers, dict):
            return False

        if not isinstance(event, dict):
            return False

        normalized_headers = {
            str(key).lower(): value
            for key, value in headers.items()
        }

        if any(
            not isinstance(normalized_headers.get(name), str)
            or not normalized_headers[name].strip()
            for name in REQUIRED_HEADERS
        ):
            return False

        payload = {
            "transmission_id": normalized_headers[
                "paypal-transmission-id"
            ],
            "transmission_time": normalized_headers[
                "paypal-transmission-time"
            ],
            "cert_url": normalized_headers[
                "paypal-cert-url"
            ],
            "auth_algo": normalized_headers[
                "paypal-auth-algo"
            ],
            "transmission_sig": normalized_headers[
                "paypal-transmission-sig"
            ],
            "webhook_id": self.webhook_id,
            "webhook_event": event,
        }

        try:
            access_token = self.token_provider()

            if not isinstance(access_token, str) or not access_token.strip():
                raise PayPalWebhookVerificationError(
                    "PayPal did not provide a valid access token."
                )

            result = self.request_fn(
                "POST",
                VERIFY_ENDPOINT,
                access_token,
                payload,
            )

        except Exception as error:
            logger.exception("PayPal webhook verification request failed.")
            raise PayPalWebhookVerificationError(
                "Could not complete PayPal webhook verification."
            ) from error

        if not isinstance(result, dict):
            raise PayPalWebhookVerificationError(
                "PayPal returned an invalid verification response."
            )

        verification_status = result.get("verification_status")

        if verification_status == "SUCCESS":
            return True

        if verification_status == "FAILURE":
            return False

        raise PayPalWebhookVerificationError(
            "PayPal returned an unexpected webhook verification status."
        )
