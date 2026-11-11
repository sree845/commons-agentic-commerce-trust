from pathlib import Path
import json
import joblib
import numpy as np
import pandas as pd

from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    average_precision_score,
    confusion_matrix
)

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "processed" / "synthetic_agent_orders.csv"
MODEL_DIR = ROOT / "models"
OUTPUT_DIR = ROOT / "data" / "processed"

MODEL_DIR.mkdir(parents=True, exist_ok=True)

FEATURES = [
    "amount",
    "mandate_cap",
    "category_allowed",
    "mandate_age_days",
    "orders_per_hour",
    "address_changed",
    "payment_retries",
    "amount_vs_merchant_norm",
    "shared_agent_flag_count"
]

TARGET = "is_attack"
GROUP = "agent_id"

df = pd.read_csv(DATA_PATH)

required = FEATURES + [TARGET, GROUP]
missing = [column for column in required if column not in df.columns]

if missing:
    raise ValueError(f"Missing required columns: {missing}")

if df[required].isnull().any().any():
    raise ValueError("Missing values found in model data.")

X = df[FEATURES].astype(float)
y = df[TARGET].astype(int)
groups = df[GROUP]

if set(y.unique()) != {0, 1}:
    raise ValueError("Target must contain both classes: 0 and 1.")

splitter = GroupShuffleSplit(
    n_splits=1,
    test_size=0.20,
    random_state=42
)

train_idx, test_idx = next(splitter.split(X, y, groups))

X_train = X.iloc[train_idx]
X_test = X.iloc[test_idx]
y_train = y.iloc[train_idx]
y_test = y.iloc[test_idx]

train_agents = set(groups.iloc[train_idx])
test_agents = set(groups.iloc[test_idx])

if train_agents.intersection(test_agents):
    raise RuntimeError("Agent leakage detected between train and test sets.")

model = Pipeline([
    ("scaler", StandardScaler()),
    ("classifier", LogisticRegression(
        class_weight="balanced",
        max_iter=2000,
        random_state=42
    ))
])

model.fit(X_train, y_train)

probabilities = model.predict_proba(X_test)[:, 1]
predictions = (probabilities >= 0.5).astype(int)

tn, fp, fn, tp = confusion_matrix(
    y_test,
    predictions,
    labels=[0, 1]
).ravel()

false_positive_rate = fp / (fp + tn) if (fp + tn) else 0.0

metrics = {
    "training_records": int(len(X_train)),
    "testing_records": int(len(X_test)),
    "training_agents": int(len(train_agents)),
    "testing_agents": int(len(test_agents)),
    "accuracy": float(accuracy_score(y_test, predictions)),
    "precision": float(precision_score(y_test, predictions, zero_division=0)),
    "recall": float(recall_score(y_test, predictions, zero_division=0)),
    "f1_score": float(f1_score(y_test, predictions, zero_division=0)),
    "roc_auc": float(roc_auc_score(y_test, probabilities)),
    "pr_auc": float(average_precision_score(y_test, probabilities)),
    "false_positive_rate": float(false_positive_rate),
    "true_negatives": int(tn),
    "false_positives": int(fp),
    "false_negatives": int(fn),
    "true_positives": int(tp)
}

classifier = model.named_steps["classifier"]
coefficients = classifier.coef_[0]

contributions = (
    X_test
    .pipe(model.named_steps["scaler"].transform)
    * coefficients
)

prediction_output = df.iloc[test_idx][
    ["order_id", "merchant_id", "agent_id", TARGET]
].copy()

prediction_output["risk_score"] = np.round(probabilities * 100, 2)
prediction_output["confidence"] = np.round(
    np.maximum(probabilities, 1 - probabilities) * 100,
    2
)
prediction_output["predicted_attack"] = predictions

explanations = []

for row in contributions:
    top_indices = np.argsort(np.abs(row))[::-1][:3]
    reasons = []

    for index in top_indices:
        if row[index] > 0:
            direction = "increased risk"
        else:
            direction = "reduced risk"

        reasons.append(
            f"{FEATURES[index]} ({direction})"
        )

    explanations.append("; ".join(reasons))

prediction_output["explanation"] = explanations

model_path = MODEL_DIR / "risk_model.joblib"
metrics_path = MODEL_DIR / "risk_model_metrics.json"
predictions_path = OUTPUT_DIR / "risk_model_predictions.csv"

# Persist the exact inference contract consumed by RiskEngine. The scaler and
# classifier are separated so the live feature validator can scale once and
# obtain calibrated 0..1 probabilities from predict_proba.
joblib.dump({
    "model": model.named_steps["classifier"],
    "scaler": model.named_steps["scaler"],
    "features": FEATURES,
    "thresholds": {
        "capture_below": 0.10,
        "void_at_or_above": 0.70
    },
    "training_method": "centralized LogisticRegression",
    "dataset": "synthetic_agent_orders"
}, model_path)

with open(metrics_path, "w", encoding="utf-8") as file:
    json.dump(metrics, file, indent=4)

prediction_output.to_csv(predictions_path, index=False)

print("\n========== COMMONS AI RISK ENGINE ==========")
print("\nDataset:")
print(f"Total records: {len(df)}")
print(f"Training records: {len(X_train)}")
print(f"Testing records: {len(X_test)}")
print(f"Training agents: {len(train_agents)}")
print(f"Testing agents: {len(test_agents)}")

print("\nEvaluation Metrics:")
for name, value in metrics.items():
    if isinstance(value, float):
        print(f"{name}: {value:.4f}")
    else:
        print(f"{name}: {value}")

print("\nConfusion Matrix:")
print(f"True Negatives: {tn}")
print(f"False Positives: {fp}")
print(f"False Negatives: {fn}")
print(f"True Positives: {tp}")

print("\nSaved files:")
print(model_path)
print(metrics_path)
print(predictions_path)

print("\nRisk engine training completed successfully.")
