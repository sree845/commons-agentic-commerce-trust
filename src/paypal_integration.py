import os
import uuid
from pathlib import Path
from decimal import Decimal, InvalidOperation

import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET")
BASE_URL = os.getenv(
    "PAYPAL_BASE_URL",
    "https://api-m.sandbox.paypal.com"
).rstrip("/")
PAYPAL_WEBHOOK_ID = os.getenv("PAYPAL_WEBHOOK_ID")

TIMEOUT = 30


class PayPalError(Exception):
    pass


class PayPalTransportError(PayPalError):
    """The request outcome may be unknown because communication failed."""
    pass


def validate_configuration():
    if not CLIENT_ID or not CLIENT_SECRET:
        raise PayPalError(
            "PayPal credentials are missing. Check your project-root .env file."
        )

    if "sandbox" not in BASE_URL.lower():
        raise PayPalError(
            "This project must use the PayPal Sandbox endpoint during development."
        )


def validate_amount(amount):
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        raise ValueError("Amount must be a valid decimal number.")

    if not value.is_finite() or value <= 0:
        raise ValueError("Amount must be greater than zero.")

    if value != value.quantize(Decimal("0.01")):
        raise ValueError("Amount cannot have more than two decimal places.")

    return format(value, ".2f")


def validate_request_id(request_id):
    if request_id is None:
        return str(uuid.uuid4())

    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("Request ID must be a non-empty string.")

    if len(request_id) > 108:
        raise ValueError("Request ID exceeds the supported length.")

    return request_id.strip()


def paypal_request(method, endpoint, token, payload=None, request_id=None):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    if request_id:
        headers["PayPal-Request-Id"] = validate_request_id(request_id)

    try:
        response = requests.request(
            method=method,
            url=f"{BASE_URL}{endpoint}",
            headers=headers,
            json=payload,
            timeout=TIMEOUT
        )
    except requests.RequestException as error:
        raise PayPalTransportError(
            f"Could not confirm the PayPal request outcome: {error}"
        ) from error

    if not response.ok:
        try:
            error_data = response.json()
        except ValueError:
            error_data = response.text[:1000]

        raise PayPalError(
            f"PayPal API error ({response.status_code}): {error_data}"
        )

    if not response.content:
        return {}

    try:
        return response.json()
    except ValueError as error:
        raise PayPalError(
            "PayPal returned an invalid JSON response."
        ) from error


def get_access_token():
    validate_configuration()

    try:
        response = requests.post(
            f"{BASE_URL}/v1/oauth2/token",
            auth=HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET),
            headers={
                "Accept": "application/json",
                "Accept-Language": "en_US"
            },
            data={"grant_type": "client_credentials"},
            timeout=TIMEOUT
        )
    except requests.RequestException as error:
        raise PayPalTransportError(
            f"PayPal OAuth request failed: {error}"
        ) from error

    if not response.ok:
        raise PayPalError(
            f"PayPal OAuth failed ({response.status_code}): "
            f"{response.text[:1000]}"
        )

    try:
        token_data = response.json()
    except ValueError as error:
        raise PayPalError(
            "PayPal returned invalid OAuth JSON."
        ) from error

    access_token = token_data.get("access_token")

    if not access_token:
        raise PayPalError("PayPal did not return an access token.")

    return access_token


def create_order(
    amount,
    currency="USD",
    return_url="http://localhost:5173/paypal/success",
    cancel_url="http://localhost:5173/paypal/cancel",
    description="Commons AI-agent order",
    custom_id=None,
    request_id=None
):
    amount = validate_amount(amount)

    if (
        not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isalpha()
    ):
        raise ValueError(
            "Currency must be a three-letter alphabetic currency code."
        )

    if not return_url.startswith("https://") and not return_url.startswith(
        "http://localhost"
    ):
        raise ValueError("Return URL must use HTTPS or localhost.")

    if not cancel_url.startswith("https://") and not cancel_url.startswith(
        "http://localhost"
    ):
        raise ValueError("Cancel URL must use HTTPS or localhost.")

    token = get_access_token()

    payload = {
        "intent": "AUTHORIZE",
        "purchase_units": [
            {
                "amount": {
                    "currency_code": currency.upper(),
                    "value": amount
                },
                "description": description
            }
        ],
        "application_context": {
            "return_url": return_url,
            "cancel_url": cancel_url,
            "user_action": "PAY_NOW"
        }
    }

    if custom_id:
        payload["purchase_units"][0]["custom_id"] = str(custom_id)

    result = paypal_request(
        "POST",
        "/v2/checkout/orders",
        token,
        payload,
        request_id=validate_request_id(request_id)
    )

    approval_url = next(
        (
            link["href"]
            for link in result.get("links", [])
            if link.get("rel") in ("approve", "payer-action")
        ),
        None
    )

    return {
        "order_id": result.get("id"),
        "status": result.get("status"),
        "intent": result.get("intent"),
        "approval_url": approval_url,
        "response": result
    }


def authorize_order(order_id, request_id=None):
    if not order_id:
        raise ValueError("PayPal order ID is required.")

    token = get_access_token()

    result = paypal_request(
        "POST",
        f"/v2/checkout/orders/{order_id}/authorize",
        token,
        payload={},
        request_id=validate_request_id(request_id)
    )

    authorizations = []

    for unit in result.get("purchase_units", []):
        payments = unit.get("payments", {})
        authorizations.extend(
            payments.get("authorizations", [])
        )

    if not authorizations:
        raise PayPalError(
            "Authorization response did not contain an authorization ID."
        )

    authorization = authorizations[0]

    return {
        "order_id": result.get("id"),
        "authorization_id": authorization.get("id"),
        "status": authorization.get("status"),
        "amount": authorization.get("amount"),
        "response": result
    }


def capture_authorization(authorization_id, request_id=None):
    if not authorization_id:
        raise ValueError("Authorization ID is required.")

    token = get_access_token()

    result = paypal_request(
        "POST",
        f"/v2/payments/authorizations/{authorization_id}/capture",
        token,
        payload={
            "final_capture": True
        },
        request_id=validate_request_id(request_id)
    )

    return {
        "authorization_id": authorization_id,
        "capture_id": result.get("id"),
        "status": result.get("status"),
        "amount": result.get("amount"),
        "response": result
    }


def void_authorization(authorization_id, request_id=None):
    if not authorization_id:
        raise ValueError("Authorization ID is required.")

    token = get_access_token()

    result = paypal_request(
        "POST",
        f"/v2/payments/authorizations/{authorization_id}/void",
        token,
        payload={},
        request_id=validate_request_id(request_id)
    )

    return {
        "authorization_id": authorization_id,
        "status": result.get("status"),
        "response": result
    }


def apply_risk_decision(
    authorization_id,
    decision,
    request_id=None
):
    decision = str(decision).upper()

    if decision == "HOLD":
        return {
            "decision": "HOLD",
            "status": "AUTHORIZED_PENDING_REVIEW",
            "authorization_id": authorization_id,
            "message": (
                "Authorization remains uncaptured. "
                "No capture or void request was sent."
            )
        }

    if decision == "CAPTURE":
        result = capture_authorization(
            authorization_id,
            request_id=request_id
        )

        return {
            "decision": "CAPTURE",
            "status": result["status"],
            "payment": result
        }

    if decision == "VOID":
        result = void_authorization(
            authorization_id,
            request_id=request_id
        )

        return {
            "decision": "VOID",
            "status": result["status"],
            "payment": result
        }

    raise ValueError(
        "Invalid risk decision. Use CAPTURE, HOLD or VOID."
    )


def get_authorization(authorization_id):
    if not authorization_id:
        raise ValueError("Authorization ID is required.")

    token = get_access_token()

    return paypal_request(
        "GET",
        f"/v2/payments/authorizations/{authorization_id}",
        token
    )


if __name__ == "__main__":
    try:
        token = get_access_token()

        print("PayPal Sandbox connection successful.")
        print("OAuth authentication: PASSED")
        print("Base URL:", BASE_URL)
        print("Payment operations are ready.")

    except (PayPalError, ValueError) as error:
        print("PayPal integration error:", error)
        raise SystemExit(1)
