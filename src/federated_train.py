from pathlib import Path
import json
import joblib
import numpy as np
import pandas as pd

from sklearn.model_selection import GroupShuffleSplit
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
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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
MERCHANT = "merchant_id"

RANDOM_STATE = 42
FEDERATED_ROUNDS = 5
LOCAL_EPOCHS = 5
LEARNING_RATE = 0.1
L2_STRENGTH = 0.001
C = 1.0

def sigmoid(z):
    z = np.clip(z, -30, 30)
    return 1.0 / (1.0 + np.exp(-z))

def local_train(X, y, initial_coef, initial_intercept,
                class_weights):
    coef = initial_coef.copy()
    intercept = initial_intercept.copy()

    sample_weights = np.where(
        y == 1,
        class_weights[1],
        class_weights[0]
    )

    weight_sum = sample_weights.sum()

    for _ in range(LOCAL_EPOCHS):
        probabilities = sigmoid(
            X @ coef.T + intercept
        ).ravel()

        errors = sample_weights * (probabilities - y)

        grad_coef = (
            errors @ X / weight_sum
            + L2_STRENGTH * coef.ravel()
        )

        grad_intercept = np.array([
            errors.sum() / weight_sum
        ])

        coef -= LEARNING_RATE * grad_coef.reshape(1, -1)
        intercept -= LEARNING_RATE * grad_intercept

    return coef, intercept

def calculate_metrics(y_true, probabilities):
    predictions = (probabilities >= 0.5).astype(int)

    tn, fp, fn, tp = confusion_matrix(
        y_true,
        predictions,
        labels=[0, 1]
    ).ravel()

    return {
        "accuracy": float(accuracy_score(y_true, predictions)),
        "precision": float(
            precision_score(y_true, predictions, zero_division=0)
        ),
        "recall": float(
            recall_score(y_true, predictions, zero_division=0)
        ),
        "f1_score": float(
            f1_score(y_true, predictions, zero_division=0)
        ),
        "roc_auc": float(roc_auc_score(y_true, probabilities)),
        "pr_auc": float(average_precision_score(y_true, probabilities)),
        "false_positive_rate": float(
            fp / (fp + tn)
        ) if (fp + tn) else 0.0,
        "true_negatives": int(tn),
        "false_positives": int(fp),
        "false_negatives": int(fn),
        "true_positives": int(tp)
    }

df = pd.read_csv(DATA_PATH)

required = FEATURES + [TARGET, GROUP, MERCHANT]
missing = [column for column in required if column not in df.columns]

if missing:
    raise ValueError(f"Missing required columns: {missing}")

if df[required].isnull().any().any():
    raise ValueError("Missing values found in model data.")

if set(df[TARGET].unique()) != {0, 1}:
    raise ValueError("Target must contain both classes.")

merchants = sorted(df[MERCHANT].unique())

if len(merchants) != 3:
    raise ValueError(
        f"Expected exactly three merchants, found {len(merchants)}."
    )

splitter = GroupShuffleSplit(
    n_splits=1,
    test_size=0.20,
    random_state=RANDOM_STATE
)

train_idx, test_idx = next(
    splitter.split(df, df[TARGET], groups=df[GROUP])
)

train_df = df.iloc[train_idx].copy()
test_df = df.iloc[test_idx].copy()

if set(train_df[GROUP]).intersection(set(test_df[GROUP])):
    raise RuntimeError("Agent leakage detected.")

X_train = train_df[FEATURES].astype(float)
y_train = train_df[TARGET].astype(int).to_numpy()

X_test = test_df[FEATURES].astype(float)
y_test = test_df[TARGET].astype(int).to_numpy()

if len(np.unique(y_train)) != 2 or len(np.unique(y_test)) != 2:
    raise ValueError("Training and testing sets must contain both classes.")

scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

class_counts = np.bincount(y_train, minlength=2)

class_weights = {
    0: len(y_train) / (2.0 * class_counts[0]),
    1: len(y_train) / (2.0 * class_counts[1])
}

merchant_data = {}

print("\n========== COMMONS FEDERATED LEARNING ==========")
print("Training method: Iterative Federated Averaging")
print(f"Federated rounds: {FEDERATED_ROUNDS}")
print(f"Local epochs per round: {LOCAL_EPOCHS}")

for merchant in merchants:
    local_indices = np.where(
        train_df[MERCHANT].to_numpy() == merchant
    )[0]

    local_X = X_train_scaled[local_indices]
    local_y = y_train[local_indices]

    if len(np.unique(local_y)) != 2:
        raise ValueError(
            f"{merchant} local training data must contain both classes."
        )

    merchant_data[merchant] = {
        "X": local_X,
        "y": local_y,
        "samples": len(local_y)
    }

    print(
        f"{merchant}: {len(local_y)} local training records, "
        f"{int(local_y.sum())} attacks"
    )

n_features = len(FEATURES)

global_coef = np.zeros((1, n_features), dtype=float)
global_intercept = np.zeros(1, dtype=float)

history = []

for round_number in range(1, FEDERATED_ROUNDS + 1):
    local_updates = []
    total_samples = sum(
        merchant_data[m]["samples"] for m in merchants
    )

    print(f"\nFederated Round {round_number}")

    for merchant in merchants:
        local = merchant_data[merchant]

        local_coef, local_intercept = local_train(
            local["X"],
            local["y"],
            global_coef,
            global_intercept,
            class_weights
        )

        if not np.isfinite(local_coef).all():
            raise ValueError(
                f"Invalid coefficients from {merchant}."
            )

        if not np.isfinite(local_intercept).all():
            raise ValueError(
                f"Invalid intercept from {merchant}."
            )

        local_updates.append({
            "merchant": merchant,
            "samples": local["samples"],
            "coef": local_coef,
            "intercept": local_intercept
        })

    aggregated_coef = np.zeros_like(global_coef)
    aggregated_intercept = np.zeros_like(global_intercept)

    for update in local_updates:
        weight = update["samples"] / total_samples

        aggregated_coef += weight * update["coef"]
        aggregated_intercept += weight * update["intercept"]

    if not np.isfinite(aggregated_coef).all():
        raise ValueError("Aggregated coefficients are invalid.")

    if not np.isfinite(aggregated_intercept).all():
        raise ValueError("Aggregated intercept is invalid.")

    previous_coef = global_coef.copy()

    global_coef = aggregated_coef
    global_intercept = aggregated_intercept

    coefficient_norm = float(np.linalg.norm(global_coef))
    update_norm = float(np.linalg.norm(global_coef - previous_coef))

    history.append({
        "round": round_number,
        "participating_merchants": len(local_updates),
        "training_samples": total_samples,
        "coefficient_norm": coefficient_norm,
        "global_update_norm": update_norm
    })

    print(
        f"Participating merchants: {len(local_updates)} | "
        f"Training records: {total_samples} | "
        f"Coefficient norm: {coefficient_norm:.6f} | "
        f"Global update: {update_norm:.6f}"
    )

federated_model = LogisticRegression(
    class_weight="balanced",
    max_iter=2000,
    random_state=RANDOM_STATE,
    C=C
)

federated_model.classes_ = np.array([0, 1])
federated_model.coef_ = global_coef.copy()
federated_model.intercept_ = global_intercept.copy()
federated_model.n_features_in_ = n_features
federated_model.n_iter_ = np.array([FEDERATED_ROUNDS])

federated_probabilities = federated_model.predict_proba(
    X_test_scaled
)[:, 1]

federated_metrics = calculate_metrics(
    y_test,
    federated_probabilities
)

federated_metrics.update({
    "training_records": int(len(X_train)),
    "testing_records": int(len(X_test)),
    "participating_merchants": len(merchants),
    "federated_rounds": FEDERATED_ROUNDS,
    "local_epochs_per_round": LOCAL_EPOCHS
})

central_model = LogisticRegression(
    class_weight="balanced",
    max_iter=2000,
    random_state=RANDOM_STATE,
    C=C
)

central_model.fit(X_train_scaled, y_train)

central_probabilities = central_model.predict_proba(
    X_test_scaled
)[:, 1]

central_metrics = calculate_metrics(
    y_test,
    central_probabilities
)

comparison = {
    "centralized": central_metrics,
    "federated": federated_metrics
}

comparison_path = OUTPUT_DIR / "federated_model_comparison.json"
metrics_path = MODEL_DIR / "federated_model_metrics.json"
history_path = OUTPUT_DIR / "federated_training_history.json"
model_path = MODEL_DIR / "federated_risk_model.joblib"
predictions_path = OUTPUT_DIR / "federated_predictions.csv"

with open(comparison_path, "w", encoding="utf-8") as file:
    json.dump(comparison, file, indent=4)

with open(metrics_path, "w", encoding="utf-8") as file:
    json.dump(federated_metrics, file, indent=4)

with open(history_path, "w", encoding="utf-8") as file:
    json.dump(history, file, indent=4)

joblib.dump({
    "model": federated_model,
    "scaler": scaler,
    "features": FEATURES,
    "thresholds": {
        "capture_below": 0.10,
        "void_at_or_above": 0.70
    },
    "merchant_ids": [str(m) for m in merchants],
    "federated_rounds": FEDERATED_ROUNDS,
    "local_epochs_per_round": LOCAL_EPOCHS,
    "training_method": "Iterative FedAvg",
    "preprocessing_note": (
        "Shared scaler fitted on pooled training features "
        "in this three-merchant simulation."
    )
}, model_path)

prediction_output = test_df[
    ["order_id", MERCHANT, GROUP, TARGET]
].copy()

prediction_output["risk_probability"] = np.round(
    federated_probabilities, 6
)

prediction_output["risk_score_percent"] = np.round(
    federated_probabilities * 100, 2
)

prediction_output["decision"] = np.select(
    [
        federated_probabilities < 0.10,
        federated_probabilities < 0.70
    ],
    [
        "CAPTURE",
        "HOLD"
    ],
    default="VOID"
)

prediction_output.to_csv(predictions_path, index=False)

print("\n========== FEDERATED MODEL RESULTS ==========")

print("\nFederated Metrics:")
for name, value in federated_metrics.items():
    if isinstance(value, float):
        print(f"{name}: {value:.4f}")
    else:
        print(f"{name}: {value}")

print("\nCentralized vs Federated Comparison:")
for metric in central_metrics:
    print(
        f"{metric}: "
        f"Centralized={central_metrics[metric]:.4f} | "
        f"Federated={federated_metrics[metric]:.4f}"
    )

print("\nFederated Confusion Matrix:")
print(
    f"TN: {federated_metrics['true_negatives']} | "
    f"FP: {federated_metrics['false_positives']} | "
    f"FN: {federated_metrics['false_negatives']} | "
    f"TP: {federated_metrics['true_positives']}"
)

print("\nSaved files:")
print(model_path)
print(metrics_path)
print(comparison_path)
print(history_path)
print(predictions_path)

print("\nIterative federated learning completed successfully.")
