import logging

from fastapi import FastAPI, HTTPException, Request

from src.paypal_integration import PAYPAL_WEBHOOK_ID

from src.paypal_webhook_service import (
    PayPalWebhookError,
    PayPalWebhookService,
    PayPalWebhookSignatureError,
    PayPalWebhookVerificationUnavailable,
    PayPalWebhookProcessingError,
)

from src.paypal_webhook_verifier import (
    PayPalWebhookVerifier,
)


logger = logging.getLogger("commons.paypal_webhook")

app = FastAPI(
    title="Commons PayPal Webhook API",
    version="1.0.0",
)

MAX_BODY_BYTES = 1_000_000


def handle_paypal_event(event):
    """Verified webhook is a signal; PayPal GET status remains authoritative."""
    from src.payment_store import PaymentStore
    from src.payment_reconciliation_service import PaymentReconciliationService
    from src.paypal_integration import get_authorization

    event_type = event.get("event_type", "")
    resource = event.get("resource") or {}
    related = (resource.get("supplementary_data") or {}).get("related_ids") or {}
    authorization_id = resource.get("id") if event_type.startswith("PAYMENT.AUTHORIZATION.") else related.get("authorization_id")

    logger.info(
        "Verified PayPal event: id=%s type=%s",
        event.get("id"), event_type
    )

    if event_type not in {
        "PAYMENT.AUTHORIZATION.CREATED",
        "PAYMENT.AUTHORIZATION.VOIDED",
        "PAYMENT.CAPTURE.COMPLETED",
        "PAYMENT.CAPTURE.DENIED",
        "PAYMENT.CAPTURE.PENDING",
    }:
        return {"handled": False, "reason": "EVENT_NOT_RELEVANT"}

    if not authorization_id:
        logger.info("Webhook has no related authorization ID; no local mutation.")
        return {"handled": False, "reason": "AUTHORIZATION_ID_MISSING"}

    store = PaymentStore()
    transaction = store.get_transaction_by_authorization(authorization_id)
    if not transaction:
        logger.info("No local transaction matches authorization %s", authorization_id)
        return {"handled": False, "reason": "TRANSACTION_NOT_FOUND"}

    if transaction.get("status") != "RECONCILIATION_REQUIRED":
        return {"handled": False, "reason": "RECONCILIATION_NOT_REQUIRED",
                "transaction_id": transaction.get("transaction_id")}

    reconciler = PaymentReconciliationService(
        get_authorization_fn=get_authorization,
        payment_store=store,
    )
    result = reconciler.reconcile_transaction(transaction["transaction_id"])
    return {"handled": True, "transaction_id": transaction["transaction_id"],
            "reconciliation": result}


webhook_service = None

if PAYPAL_WEBHOOK_ID:
    verifier = PayPalWebhookVerifier(
        webhook_id=PAYPAL_WEBHOOK_ID
    )

    webhook_service = PayPalWebhookService(
        verify_webhook_fn=verifier,
        event_handler=handle_paypal_event,
    )


@app.get("/health")
async def health():
    return {
        "status": "running",
        "service": "Commons PayPal Webhook API",
        "webhook_configured": webhook_service is not None,
    }


@app.post("/webhooks/paypal")
async def receive_paypal_webhook(request: Request):

    if webhook_service is None:
        raise HTTPException(
            status_code=503,
            detail="PayPal webhook is not configured.",
        )

    content_length = request.headers.get("content-length")

    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Webhook request body is too large.",
                )

        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid Content-Length header.",
            )

    raw_body = await request.body()

    if not raw_body:
        raise HTTPException(
            status_code=400,
            detail="Webhook request body is empty.",
        )

    if len(raw_body) > MAX_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Webhook request body is too large.",
        )

    try:
        result = webhook_service.receive(
            headers=dict(request.headers),
            raw_body=raw_body,
        )

        return result

    except PayPalWebhookSignatureError as error:
        logger.warning(
            "PayPal webhook signature rejected: %s",
            error,
        )

        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except PayPalWebhookVerificationUnavailable as error:
        logger.warning(
            "PayPal webhook verification temporarily unavailable."
        )

        raise HTTPException(
            status_code=503,
            detail=str(error),
        ) from error

    except PayPalWebhookProcessingError as error:
        logger.exception(
            "PayPal webhook event processing failed."
        )

        raise HTTPException(
            status_code=500,
            detail=str(error),
        ) from error

    except PayPalWebhookError as error:
        logger.warning(
            "PayPal webhook request rejected: %s",
            error,
        )

        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except Exception:
        logger.exception(
            "Unexpected error while processing PayPal webhook."
        )

        raise HTTPException(
            status_code=500,
            detail="Internal webhook processing error.",
        )
