"""Networked, merchant-isolated FedAvg coordinator for Commons.

Only model parameters and sample counts cross the wire; order/customer rows stay local.
Use TLS at the reverse proxy and distinct 256-bit secrets per merchant.
"""
from __future__ import annotations
import hashlib, hmac, json, os, time, uuid
from pathlib import Path
from threading import RLock
from typing import Any
import joblib
import numpy as np
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "models"
STATE_DIR = ROOT / "data" / "federation_network"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = STATE_DIR / "coordinator_state.json"
MODEL_FILE = MODEL_DIR / "federated_risk_model.joblib"
FEATURES = ["amount", "mandate_cap", "category_allowed", "mandate_age_days", "orders_per_hour", "address_changed", "payment_retries", "amount_vs_merchant_norm", "shared_agent_flag_count"]
LOCK = RLock()
app = FastAPI(title="Commons Federated Coordinator", version="1.0.0")


def merchant_secrets() -> dict[str, str]:
    raw = os.getenv("COMMONS_MERCHANT_SECRETS", "")
    try: values = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc: raise RuntimeError("COMMONS_MERCHANT_SECRETS must be JSON") from exc
    return {str(k): str(v) for k, v in values.items()}


def read_state() -> dict[str, Any]:
    if STATE_FILE.exists(): return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"rounds": {}, "accepted_updates": []}


def write_state(state: dict[str, Any]) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def authenticate(merchant_id: str, payload: dict, signature: str) -> None:
    secret = merchant_secrets().get(merchant_id)
    if not secret or len(secret.encode()) < 32:
        raise HTTPException(401, "Unknown merchant or merchant secret is not configured (minimum 32 bytes).")
    expected = hmac.new(secret.encode(), canonical(payload), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature): raise HTTPException(401, "Invalid merchant update signature.")


class RoundRequest(BaseModel):
    round_id: str = Field(min_length=8, max_length=80)
    expected_merchants: list[str] = Field(min_length=2, max_length=20)
    feature_schema: list[str]
    base_model_version: str


class UpdateRequest(BaseModel):
    round_id: str
    merchant_id: str
    sample_count: int = Field(gt=0, le=10_000_000)
    feature_schema: list[str]
    base_model_version: str
    coefficients: list[list[float]]
    intercept: list[float]
    nonce: str = Field(min_length=16, max_length=128)
    created_at: int


@app.get("/health")
def health(): return {"service": "commons-federation-coordinator", "status": "ok", "protocol": "signed-fedavg-v1"}

@app.post("/v1/rounds")
def open_round(req: RoundRequest):
    if req.feature_schema != FEATURES: raise HTTPException(422, "Feature schema mismatch.")
    if len(set(req.expected_merchants)) != len(req.expected_merchants): raise HTTPException(422, "Duplicate merchant IDs.")
    secrets = merchant_secrets()
    if not set(req.expected_merchants).issubset(secrets): raise HTTPException(422, "Every participant must have a configured merchant credential.")
    with LOCK:
        state = read_state()
        if req.round_id in state["rounds"]: raise HTTPException(409, "Round already exists.")
        state["rounds"][req.round_id] = {"expected": sorted(req.expected_merchants), "feature_schema": req.feature_schema, "base_model_version": req.base_model_version, "updates": {}, "status": "collecting", "created_at": int(time.time())}
        write_state(state)
    return {"round_id": req.round_id, "status": "collecting", "participants": len(req.expected_merchants)}

@app.post("/v1/updates")
async def submit_update(req: UpdateRequest, request: Request, x_commons_signature: str = Header(default="")):
    raw_payload = json.loads((await request.body()).decode("utf-8"))
    authenticate(req.merchant_id, raw_payload, x_commons_signature)
    if abs(int(time.time()) - req.created_at) > 300: raise HTTPException(401, "Update timestamp outside five-minute window.")
    coef = np.asarray(req.coefficients, dtype=float); intercept = np.asarray(req.intercept, dtype=float)
    if coef.shape != (1, len(FEATURES)) or intercept.shape != (1,) or not np.isfinite(coef).all() or not np.isfinite(intercept).all(): raise HTTPException(422, "Invalid parameter dimensions or non-finite values.")
    with LOCK:
        state = read_state(); rnd = state["rounds"].get(req.round_id)
        if not rnd: raise HTTPException(404, "Round not found.")
        if rnd["status"] != "collecting": raise HTTPException(409, "Round is not accepting updates.")
        if req.merchant_id not in rnd["expected"]: raise HTTPException(403, "Merchant is not a participant in this round.")
        if req.feature_schema != rnd["feature_schema"] or req.base_model_version != rnd["base_model_version"]: raise HTTPException(409, "Schema or base model version mismatch.")
        if req.merchant_id in rnd["updates"]: raise HTTPException(409, "One update per merchant per round; duplicate/replay rejected.")
        if any(x["nonce"] == req.nonce for x in state["accepted_updates"]): raise HTTPException(409, "Nonce replay rejected.")
        rnd["updates"][req.merchant_id] = {"sample_count": req.sample_count, "coefficients": coef.tolist(), "intercept": intercept.tolist(), "nonce": req.nonce, "received_at": int(time.time())}
        state["accepted_updates"].append({"merchant_id": req.merchant_id, "nonce": req.nonce})
        if set(rnd["updates"]) == set(rnd["expected"]):
            total = sum(x["sample_count"] for x in rnd["updates"].values())
            avg_coef = sum(np.asarray(x["coefficients"]) * x["sample_count"] for x in rnd["updates"].values()) / total
            avg_intercept = sum(np.asarray(x["intercept"]) * x["sample_count"] for x in rnd["updates"].values()) / total
            package = joblib.load(MODEL_FILE)
            if list(package["features"]) != FEATURES: raise HTTPException(500, "Coordinator model schema mismatch.")
            package["model"].coef_ = avg_coef; package["model"].intercept_ = avg_intercept
            version = f"fednet_{req.round_id}"
            package["federation"] = {"version": version, "round_id": req.round_id, "participants": rnd["expected"], "sample_count": total, "aggregation": "sample-weighted FedAvg", "created_at": int(time.time())}
            target = MODEL_DIR / f"{version}.joblib"; joblib.dump(package, target)
            rnd.update({"status": "aggregated", "model_version": version, "model_path": str(target.relative_to(MODEL_DIR.parent)) if MODEL_DIR.parent in target.parents else target.name, "total_samples": total, "completed_at": int(time.time())})
        write_state(state)
        return {"round_id": req.round_id, "status": rnd["status"], "received": len(rnd["updates"]), "expected": len(rnd["expected"]), "model_version": rnd.get("model_version")}

@app.get("/v1/rounds/{round_id}")
def round_status(round_id: str):
    rnd = read_state()["rounds"].get(round_id)
    if not rnd: raise HTTPException(404, "Round not found.")
    return {"round_id": round_id, "status": rnd["status"], "participants_expected": rnd["expected"], "participants_received": sorted(rnd["updates"]), "model_version": rnd.get("model_version"), "total_samples": rnd.get("total_samples")}
