"""Commons dashboard API.

Demo endpoints are deterministic and never trigger PayPal operations.
PayPal execution remains in the separately tested payment services and must
only be enabled through an authenticated, operator-controlled workflow.
"""
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.demo_data import SCENARIOS, overview
from src.recovery_service import RecoveryService
from src.audit_service import AuditService
from src.paypal_integration import (
    CLIENT_ID, CLIENT_SECRET, BASE_URL, PAYPAL_WEBHOOK_ID
)
from src.risk_engine import RiskEngine, RiskEngineError

app = FastAPI(
    title="Commons API",
    version="1.1.0",
    description="Federated trust and recovery infrastructure for agentic commerce",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

recovery = RecoveryService()
audit = AuditService()


class AppealIn(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=8, max_length=4000)
    evidence: dict[str, Any] = Field(default_factory=dict)


class ReviewIn(BaseModel):
    outcome: str
    reviewer_note: str = Field(min_length=4, max_length=2000)


class RecourseIn(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=128)
    reason_codes: list[str]
    correction_options: list[dict[str, Any]]


class EvidenceIn(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=128)
    evidence: dict[str, Any]


def _audit(event_type: str, payload: dict[str, Any], transaction_id: str | None = None):
    try:
        return audit.record(event_type, payload, transaction_id)
    except Exception:
        # Audit failures must be visible to the caller, not silently ignored.
        raise HTTPException(status_code=500, detail="Audit event could not be persisted.")


@app.get("/health")
def health():
    return {"status": "ok", "service": "commons-api", "version": "1.1.0"}


@app.get("/api/runtime")
def runtime_status():
    """Configuration diagnostics; never returns credentials or secrets."""
    try:
        engine = RiskEngine()
        model = {"loaded": True, "active_version": engine.active_version,
                 "features": len(engine.features)}
    except (RiskEngineError, OSError, ValueError, KeyError) as exc:
        model = {"loaded": False, "error": str(exc)}
    sandbox = "sandbox" in BASE_URL.lower()
    return {
        "mode": "HYBRID_DEMO_WITH_LIVE_SANDBOX_WORKFLOW",
        "live_order_workflow": {"available": True, "steps": ["signed_mandate", "nonce_reservation", "paypal_checkout", "buyer_authorization", "live_model_inference", "operator_payment_decision"]},
        "paypal": {
            "credentials_configured": bool(CLIENT_ID and CLIENT_SECRET),
            "sandbox_endpoint": sandbox,
            "webhook_configured": bool(PAYPAL_WEBHOOK_ID),
            "ready_for_sandbox_test": bool(CLIENT_ID and CLIENT_SECRET and sandbox),
        },
        "agent_risk_model": model,
        "disclosure": "Dashboard scenario catalogue and merchant overview are synthetic. The /api/live/orders workflow performs real PayPal Sandbox checkout operations when configured. Runtime readiness does not prove a successful transaction.",
    }


@app.get("/api/overview")
def get_overview():
    return overview()


@app.get("/api/orders")
def orders():
    return {"mode": "SIMULATION", "items": SCENARIOS}


@app.get("/api/orders/{scenario_id}")
def order(scenario_id: str):
    item = next((x for x in SCENARIOS if x["id"] == scenario_id), None)
    if not item:
        raise HTTPException(404, "Scenario not found")
    return item


@app.get("/api/federation")
def federation():
    return {
        "mode": "SIMULATION", "algorithm": "FedAvg", "rounds": 5,
        "merchants": [
            {"id": "A", "name": "Merchant A", "local_records": "private local shard", "update": "validated parameter delta"},
            {"id": "B", "name": "Merchant B", "local_records": "private local shard", "update": "validated parameter delta"},
            {"id": "C", "name": "Merchant C", "local_records": "private local shard", "update": "validated parameter delta"},
        ],
        "privacy_note": "Three-merchant FedAvg simulation. No differential privacy or secure aggregation is claimed; raw order rows are not returned by this endpoint.",
    }


@app.get("/api/replay/scenarios")
def replay_scenarios():
    return {"mode": "SIMULATION", "scenarios": SCENARIOS}


@app.post("/api/replay/{scenario_id}")
def replay(scenario_id: str):
    item = next((x for x in SCENARIOS if x["id"] == scenario_id), None)
    if not item:
        raise HTTPException(404, "Scenario not found")
    result = {"mode": "SIMULATION", "scenario": item,
              "note": "Deterministic synthetic scenario; this endpoint does not invoke fresh model inference or PayPal."}
    _audit("DEMO_SCENARIO_REPLAYED", {"scenario_id": scenario_id, "decision": item["decision"]}, scenario_id)
    return result


@app.get("/api/recovery/analytics")
def recovery_analytics():
    return recovery.analytics()


@app.post("/api/recovery/recourse")
def create_recourse(body: RecourseIn):
    try:
        result = recovery.create_recourse(body.transaction_id, body.reason_codes, body.correction_options)
        _audit("RECOURSE_RECEIPT_CREATED", {"receipt_id": result["receipt_id"], "reason_codes": body.reason_codes}, body.transaction_id)
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/recovery/recourse/{receipt_id}")
def get_recourse(receipt_id: str):
    item = recovery.get_recourse(receipt_id)
    if not item:
        raise HTTPException(404, "Recourse receipt not found")
    return item


@app.post("/api/recovery/evidence")
def create_evidence(body: EvidenceIn):
    try:
        result = recovery.create_evidence(body.transaction_id, body.evidence)
        _audit("EVIDENCE_RECEIPT_CREATED", {"receipt_id": result["receipt_id"], "digest": result["payload_sha256"]}, body.transaction_id)
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/recovery/evidence/{receipt_id}")
def get_evidence(receipt_id: str):
    item = recovery.get_evidence(receipt_id)
    if not item:
        raise HTTPException(404, "Evidence receipt not found")
    return item


@app.post("/api/appeals")
def submit_appeal(body: AppealIn):
    try:
        result = recovery.submit_appeal(body.transaction_id, body.reason, body.evidence)
        _audit(
            "APPEAL_SUBMITTED",
            {
                "appeal_id": result["appeal_id"],
                "evidence_receipt_id": result["evidence"].get("evidence_receipt_id"),
            },
            body.transaction_id,
        )
        return result
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/appeals/{appeal_id}")
def get_appeal(appeal_id: str):
    item = recovery.get_appeal(appeal_id)
    if not item:
        raise HTTPException(404, "Appeal not found")
    return item


@app.post("/api/appeals/{appeal_id}/review")
def review_appeal(appeal_id: str, body: ReviewIn, authorization: str | None = Header(default=None)):
    _require_reviewer(authorization)
    try:
        result = recovery.review_appeal(appeal_id, body.outcome, body.reviewer_note)
        _audit("APPEAL_REVIEWED", {"appeal_id": appeal_id, "outcome": body.outcome}, result["transaction_id"])
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/audit/verify")
def verify_audit_chain():
    return {"valid": audit.verify_chain(), "events": len(audit.list_events(1000)),
            "scope": "Local tamper-evident hash chain; not an external immutable anchor."}


@app.get("/api/audit/events")
def audit_events(limit: int = Query(default=100, ge=1, le=1000)):
    return {"items": audit.list_events(limit)}


# ---------------------------------------------------------------------------
# Live transaction workflow. Demo scenario endpoints remain explicitly synthetic.
# ---------------------------------------------------------------------------
import hmac
import os
from src.order_service import OrderService, OrderServiceError
from src.payment_decision_service import PaymentDecisionService, PaymentDecisionError
from src.trusted_feature_provider import TrustedFeatureProvider
from src.payment_store import PaymentStore

_live_order_service = None
_live_decision_service = None
_live_feature_provider = None
_live_store = None

class LiveAgentOrderIn(BaseModel):
    order_id: str = Field(min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    merchant_id: str = Field(min_length=1, max_length=128)
    amount: str
    currency: str = Field(default="USD", min_length=3, max_length=3)
    category: str = Field(min_length=1, max_length=80)
    mandate: dict[str, Any]
    signature: str = Field(min_length=1)
    previous_address_hash: str | None = None
    current_address_hash: str | None = None

class AuthorizeLiveOrderIn(BaseModel):
    paypal_order_id: str = Field(min_length=1, max_length=128)

def _live_services():
    global _live_order_service, _live_decision_service, _live_feature_provider, _live_store
    if _live_order_service is None:
        _live_feature_provider = TrustedFeatureProvider()
        _live_order_service = OrderService(trusted_feature_provider=_live_feature_provider)
        _live_decision_service = PaymentDecisionService()
        _live_store = PaymentStore()
    return _live_order_service, _live_decision_service, _live_feature_provider, _live_store

def _require_reviewer(authorization: str | None):
    expected = os.getenv("COMMONS_REVIEWER_TOKEN")
    if not expected:
        raise HTTPException(503, "Reviewer actions are disabled: configure COMMONS_REVIEWER_TOKEN.")
    supplied = authorization or ""
    if not supplied.startswith("Bearer ") or not hmac.compare_digest(supplied[7:], expected):
        raise HTTPException(401, "Valid reviewer bearer token required.")

def _require_operator(authorization: str | None):
    expected = os.getenv("COMMONS_OPERATOR_TOKEN")
    if not expected:
        raise HTTPException(503, "Operator actions are disabled: configure COMMONS_OPERATOR_TOKEN.")
    supplied = (authorization or "")
    if not supplied.startswith("Bearer ") or not hmac.compare_digest(supplied[7:], expected):
        raise HTTPException(401, "Valid operator bearer token required.")

@app.post("/api/live/orders")
def create_live_agent_order(body: LiveAgentOrderIn):
    """Verify signed mandate, atomically reserve nonce/spend, then create a PayPal Sandbox checkout order."""
    order_service, _, feature_provider, _ = _live_services()
    payload = body.model_dump(exclude={"previous_address_hash", "current_address_hash"})
    try:
        result = order_service.create_agent_order(payload)
        feature_provider.record_order_context(
            transaction_id=result["transaction_id"],
            agent_id=body.agent_id,
            merchant_id=body.merchant_id,
            category=body.category,
            previous_address_hash=body.previous_address_hash,
            current_address_hash=body.current_address_hash,
        )
        _audit("LIVE_AGENT_ORDER_CREATED", {
            "agent_id": body.agent_id, "merchant_id": body.merchant_id,
            "paypal_order_id": result["paypal_order_id"],
            "mandate_status": result["mandate_status"]
        }, result["transaction_id"])
        return {"mode": "PAYPAL_SANDBOX", **result}
    except (OrderServiceError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc

@app.post("/api/live/orders/{transaction_id}/authorize")
def authorize_live_agent_order(transaction_id: str, body: AuthorizeLiveOrderIn):
    """Call after the buyer approves the PayPal checkout."""
    order_service, _, _, _ = _live_services()
    try:
        result = order_service.authorize_agent_order(transaction_id, body.paypal_order_id)
        _audit("LIVE_PAYPAL_AUTHORIZED", {
            "authorization_id": result.get("authorization_id"),
            "paypal_order_id": body.paypal_order_id
        }, transaction_id)
        return result
    except (OrderServiceError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc

@app.post("/api/live/orders/{transaction_id}/evaluate")
def evaluate_live_agent_order(transaction_id: str):
    """Build features only from persisted trusted context and verified mandate terms."""
    order_service, _, _, _ = _live_services()
    try:
        result = order_service.evaluate_authorized_order(transaction_id)
        _audit("LIVE_RISK_EVALUATED", {
            "decision": result["decision"],
            "risk_probability": result["risk_probability"],
            "model_version": result["model_version"],
            "reasons": result["reasons"]
        }, transaction_id)
        return result
    except (OrderServiceError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc

@app.post("/api/live/orders/{transaction_id}/execute")
def execute_live_agent_order(transaction_id: str, authorization: str | None = Header(default=None)):
    """Explicit operator-authorized CAPTURE/VOID; HOLD never moves money."""
    _require_operator(authorization)
    _, decision_service, _, _ = _live_services()
    try:
        result = decision_service.execute_decision(transaction_id)
        _audit("LIVE_PAYMENT_DECISION_EXECUTED", result, transaction_id)
        return result
    except (PaymentDecisionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc

@app.get("/api/live/orders/{transaction_id}")
def get_live_agent_order(transaction_id: str):
    _, _, _, store = _live_services()
    result = store.get_transaction(transaction_id)
    if not result:
        raise HTTPException(404, "Live transaction not found.")
    return result
