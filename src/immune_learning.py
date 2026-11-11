from pathlib import Path
import json
import joblib
import numpy as np
import pandas as pd

from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix
)

ROOT = Path(__file__).resolve().parent.parent

DATA_PATH = ROOT / "data" / "processed" / "synthetic_agent_orders.csv"
MODEL_PATH = ROOT / "models" / "federated_risk_model.joblib"
OUTPUT_DIR = ROOT / "data" / "processed"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

RANDOM_STATE = 42
ADAPTATION_PER_FAMILY = 100
HOLDOUT_PER_FAMILY = 50

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

rng = np.random.default_rng(RANDOM_STATE)

df = pd.read_csv(DATA_PATH)
saved = joblib.load(MODEL_PATH)

required = FEATURES + [
    TARGET,
    GROUP,
    MERCHANT,
    "order_id"
]

missing = [
    column for column in required
    if column not in df.columns
]

if missing:
    raise ValueError(f"Missing required columns: {missing}")

if list(saved["features"]) != FEATURES:
    raise ValueError("Model feature order does not match the dataset.")

splitter = GroupShuffleSplit(
    n_splits=1,
    test_size=0.20,
    random_state=RANDOM_STATE
)

train_idx, test_idx = next(
    splitter.split(
        df,
        df[TARGET],
        groups=df[GROUP]
    )
)

train_df = df.iloc[train_idx].copy()
test_df = df.iloc[test_idx].copy()

if set(train_df[GROUP]).intersection(set(test_df[GROUP])):
    raise RuntimeError("Agent leakage detected.")

train_legitimate = train_df[
    train_df[TARGET] == 0
].copy()

test_legitimate = test_df[
    test_df[TARGET] == 0
].copy()

if len(train_legitimate) < ADAPTATION_PER_FAMILY * 3:
    raise ValueError("Not enough legitimate training records.")

if len(test_legitimate) < HOLDOUT_PER_FAMILY * 3:
    raise ValueError("Not enough legitimate testing records.")

def create_attack(source, family, sequence):
    row = source.copy()

    if family == "emerging_retry_burst":
        row["orders_per_hour"] = max(
            float(row["orders_per_hour"]),
            12.0
        ) + float(rng.uniform(3, 8))

        row["payment_retries"] = max(
            int(row["payment_retries"]),
            3
        ) + int(rng.integers(1, 4))

        row["shared_agent_flag_count"] = (
            float(row["shared_agent_flag_count"])
            + float(rng.uniform(1, 3))
        )

    elif family == "emerging_mandate_drift":
        row["category_allowed"] = 0

        row["amount"] = max(
            float(row["amount"]),
            float(row["mandate_cap"]) * 1.2
        )

        row["amount_vs_merchant_norm"] = max(
            float(row["amount_vs_merchant_norm"]),
            1.8
        )

        row["address_changed"] = 1

    elif family == "emerging_coordinated_orders":
        row["orders_per_hour"] = max(
            float(row["orders_per_hour"]),
            15.0
        )

        row["payment_retries"] = max(
            int(row["payment_retries"]),
            2
        )

        row["shared_agent_flag_count"] = (
            float(row["shared_agent_flag_count"])
            + float(rng.uniform(2, 5))
        )

        row["address_changed"] = 1

    else:
        raise ValueError(f"Unknown attack family: {family}")

    row[TARGET] = 1
    row["attack_family"] = family
    row["order_id"] = f"EMERGING-{family}-{sequence}"

    return row

families = [
    "emerging_retry_burst",
    "emerging_mandate_drift",
    "emerging_coordinated_orders"
]

def generate_dataset(source, samples_per_family, prefix):
    generated = []

    for family in families:
        selected = source.sample(
            n=samples_per_family,
            random_state=RANDOM_STATE + len(generated)
        )

        for index, (_, original) in enumerate(selected.iterrows()):
            generated.append(
                create_attack(
                    original.copy(),
                    family,
                    f"{prefix}-{family}-{index:04d}"
                )
            )

    return pd.DataFrame(generated)

adaptation_attacks = generate_dataset(
    train_legitimate,
    ADAPTATION_PER_FAMILY,
    "ADAPT"
)

holdout_attacks = generate_dataset(
    test_legitimate,
    HOLDOUT_PER_FAMILY,
    "HOLDOUT"
)

adaptation_path = OUTPUT_DIR / "emerging_attack_adaptation.csv"
holdout_path = OUTPUT_DIR / "emerging_attack_holdout.csv"
report_path = OUTPUT_DIR / "immune_baseline_report.json"

adaptation_attacks.to_csv(
    adaptation_path,
    index=False
)

clean_holdout = test_legitimate.sample(
    n=len(holdout_attacks),
    random_state=RANDOM_STATE
).copy()

clean_holdout["attack_family"] = "legitimate"

evaluation_data = pd.concat(
    [
        clean_holdout,
        holdout_attacks
    ],
    ignore_index=True
)

evaluation_data = evaluation_data.sample(
    frac=1,
    random_state=RANDOM_STATE
).reset_index(drop=True)

# Persist the complete independent evaluation set, including clean negatives.
# The evaluator needs both legitimate and attack examples to measure FPR and recall.
evaluation_data.to_csv(holdout_path, index=False)

model = saved["model"]
scaler = saved["scaler"]

X_holdout = evaluation_data[FEATURES].astype(float)
X_holdout_scaled = scaler.transform(X_holdout)

holdout_probabilities = model.predict_proba(
    X_holdout_scaled
)[:, 1]

holdout_predictions = (
    holdout_probabilities >= 0.5
).astype(int)

y_holdout = evaluation_data[TARGET].astype(int)

tn, fp, fn, tp = confusion_matrix(
    y_holdout,
    holdout_predictions,
    labels=[0, 1]
).ravel()

baseline_metrics = {
    "evaluation_records": int(len(evaluation_data)),
    "legitimate_records": int((y_holdout == 0).sum()),
    "attack_records": int((y_holdout == 1).sum()),
    "attack_families": families,
    "accuracy": float(
        accuracy_score(y_holdout, holdout_predictions)
    ),
    "precision": float(
        precision_score(
            y_holdout,
            holdout_predictions,
            zero_division=0
        )
    ),
    "recall": float(
        recall_score(
            y_holdout,
            holdout_predictions,
            zero_division=0
        )
    ),
    "f1_score": float(
        f1_score(
            y_holdout,
            holdout_predictions,
            zero_division=0
        )
    ),
    "false_positive_rate": float(
        fp / (fp + tn)
    ) if (fp + tn) else 0.0,
    "true_negatives": int(tn),
    "false_positives": int(fp),
    "false_negatives": int(fn),
    "true_positives": int(tp)
}

with open(report_path, "w", encoding="utf-8") as file:
    json.dump(baseline_metrics, file, indent=4)

print("\n========== COMMONS IMMUNE LEARNING ==========")

print("\nEmerging attack scenarios:")

for family in families:
    print(
        f"{family}: "
        f"{int((evaluation_data['attack_family'] == family).sum())} "
        "holdout attacks"
    )

print("\nDataset generation:")
print(f"Adaptation attacks: {len(adaptation_attacks)}")
print(f"Holdout evaluation records: {len(evaluation_data)}")
print(f"Legitimate evaluation records: {len(clean_holdout)}")

print("\nExisting model baseline performance:")

for name, value in baseline_metrics.items():
    if isinstance(value, float):
        print(f"{name}: {value:.4f}")
    else:
        print(f"{name}: {value}")

print("\nSaved files:")
print(adaptation_path)
print(holdout_path)
print(report_path)

print("\nEmerging attack baseline evaluation completed.")
