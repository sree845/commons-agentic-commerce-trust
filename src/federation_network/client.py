"""Merchant-local training and signed update submission. Raw rows never leave this process."""
import argparse, hashlib, hmac, json, os, secrets, time
import joblib, numpy as np, pandas as pd, requests
from pathlib import Path
FEATURES = ["amount", "mandate_cap", "category_allowed", "mandate_age_days", "orders_per_hour", "address_changed", "payment_retries", "amount_vs_merchant_norm", "shared_agent_flag_count"]

def train_local(csv_path: str, model_path: str, merchant_id: str, epochs: int = 20, lr: float = 0.02):
    frame = pd.read_csv(csv_path)
    required = FEATURES + ["is_attack", "merchant_id"]
    missing = sorted(set(required) - set(frame.columns))
    if missing: raise ValueError(f"Missing local columns: {missing}")
    frame = frame[frame.merchant_id.astype(str) == merchant_id]
    if len(frame) < 20 or frame.is_attack.nunique() != 2: raise ValueError("Local merchant dataset needs at least 20 rows and both classes.")
    package = joblib.load(model_path)
    if list(package["features"]) != FEATURES: raise ValueError("Model feature order mismatch.")
    x = package["scaler"].transform(frame[FEATURES].astype(float)); y = frame.is_attack.astype(int).to_numpy()
    model = package["model"]; w = model.coef_.astype(float).copy(); b = model.intercept_.astype(float).copy()
    weights = np.where(y == 1, len(y) / (2 * max(y.sum(), 1)), len(y) / (2 * max((y == 0).sum(), 1)))
    for _ in range(epochs):
        p = 1 / (1 + np.exp(-np.clip((x @ w.T + b).ravel(), -30, 30)))
        err = (p-y)*weights
        w -= lr * ((err @ x / len(y)).reshape(w.shape) + 0.001*w)
        b -= lr * np.array([err.mean()])
    return {"merchant_id": merchant_id, "sample_count": len(y), "feature_schema": FEATURES, "base_model_version": package.get("version", "federated_v1"), "coefficients": w.tolist(), "intercept": b.tolist(), "nonce": secrets.token_hex(16), "created_at": int(time.time())}

def submit_update(update: dict, coordinator: str, secret: str):
    if len(secret.encode()) < 32: raise ValueError("Merchant HMAC secret must be at least 32 bytes.")
    body = json.dumps(update, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    response = requests.post(coordinator.rstrip("/")+"/v1/updates", data=body, headers={"Content-Type":"application/json", "X-Commons-Signature":signature}, timeout=30)
    response.raise_for_status(); return response.json()

if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("--csv",required=True); p.add_argument("--model",required=True); p.add_argument("--merchant",required=True); p.add_argument("--coordinator",required=True); p.add_argument("--secret-env",default="COMMONS_MERCHANT_SECRET"); p.add_argument("--round",required=True); a=p.parse_args()
    update=train_local(a.csv,a.model,a.merchant); update["round_id"]=a.round
    print(json.dumps(submit_update(update,a.coordinator,os.environ[a.secret_env]),indent=2))
