
"""Train and evaluate the IEEE-CIS fraud model with chronological validation.

Run from project root:
    python -m src.train_ieee_cis_model

The IEEE-CIS model is separate from Commons' agent-risk and mandate layers.
The validation set selects an operating threshold. The final test set is
used only for the final evaluation.
"""

from pathlib import Path
import json

import joblib
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "processed" / "ieee_cis_prepared.csv"
MODELS = ROOT / "models"
OUTPUT = ROOT / "data" / "processed"

RANDOM_STATE = 42
VALIDATION_FRACTION = 0.20
MAX_VALIDATION_FPR = 0.02

NUMERIC = [
    "TransactionAmt", "card2", "card3", "card5", "addr1",
    "dist1", "C1", "C2", "C5", "C6", "C7", "C8",
    "C9", "C10", "C11", "C12", "C13", "C14",
    "D1", "D2", "D3", "D4", "D10", "D15",
    "id_01", "id_02", "id_05", "id_06", "id_11",
    "id_13", "id_17", "id_19", "id_20"
]

CATEGORICAL = [
    "ProductCD", "card4", "card6", "P_emaildomain",
    "DeviceType", "id_12", "id_15"
]

TARGET = "isFraud"


def calculate_metrics(y_true, probabilities, threshold):
    predictions = (probabilities >= threshold).astype(int)

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
        "f1": float(
            f1_score(y_true, predictions, zero_division=0)
        ),
        "roc_auc": float(roc_auc_score(y_true, probabilities)),
        "pr_auc": float(
            average_precision_score(y_true, probabilities)
        ),
        "false_positive_rate": float(
            fp / (fp + tn)
        ) if (tn + fp) else 0.0,
        "true_negative": int(tn),
        "false_positive": int(fp),
        "false_negative": int(fn),
        "true_positive": int(tp),
        "threshold": float(threshold)
    }


def select_threshold(y_true, probabilities, max_fpr):
    """Maximize validation recall subject to a maximum validation FPR."""

    fpr, tpr, thresholds = roc_curve(
        y_true,
        probabilities
    )

    valid = np.isfinite(thresholds) & (fpr <= max_fpr)

    if not np.any(valid):
        raise RuntimeError(
            "No finite threshold satisfies the validation FPR constraint."
        )

    best_recall = np.max(tpr[valid])

    candidates = np.where(
        valid & np.isclose(tpr, best_recall)
    )[0]

    # Prefer the highest threshold when recall is tied.
    best_index = candidates[
        np.argmax(thresholds[candidates])
    ]

    return float(thresholds[best_index]), {
        "maximum_allowed_fpr": float(max_fpr),
        "validation_fpr": float(fpr[best_index]),
        "validation_recall": float(tpr[best_index])
    }


def main():
    if not DATA.exists():
        raise FileNotFoundError(
            f"{DATA} not found. Run python -m src.prepare_dataset first."
        )

    print("Loading prepared IEEE-CIS dataset...")

    df = pd.read_csv(DATA, low_memory=False)

    required = (
        NUMERIC
        + CATEGORICAL
        + [TARGET, "dataset_split", "TransactionDT"]
    )

    missing = [column for column in required if column not in df.columns]

    if missing:
        raise ValueError(
            f"Prepared dataset is missing columns: {missing}"
        )

    df = df.loc[
        df["dataset_split"].isin(["train", "test"])
    ].copy()

    df = df.sort_values(
        "TransactionDT",
        kind="stable"
    ).reset_index(drop=True)

    # Preserve the original chronological final test partition.
    train_pool = df[
        df["dataset_split"] == "train"
    ].copy()

    test = df[
        df["dataset_split"] == "test"
    ].copy()

    if train_pool.empty or test.empty:
        raise ValueError("Training or final test partition is empty.")

    # Reserve the latest 20% of the original training partition
    # for threshold selection.
    validation_size = max(
        1,
        int(len(train_pool) * VALIDATION_FRACTION)
    )

    train = train_pool.iloc[:-validation_size].copy()
    validation = train_pool.iloc[-validation_size:].copy()

    for name, partition in [
        ("training", train),
        ("validation", validation),
        ("final test", test)
    ]:
        if partition.empty or partition[TARGET].nunique() != 2:
            raise ValueError(
                f"{name} partition must contain both classes."
            )

    feature_columns = NUMERIC + CATEGORICAL

    X_train = train[feature_columns]
    X_validation = validation[feature_columns]
    X_test = test[feature_columns]

    y_train = train[TARGET].astype(int)
    y_validation = validation[TARGET].astype(int)
    y_test = test[TARGET].astype(int)

    print(f"Training records: {len(train)}")
    print(f"Validation records: {len(validation)}")
    print(f"Final test records: {len(test)}")

    numeric_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scale", StandardScaler())
    ])

    categorical_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(
            handle_unknown="ignore",
            min_frequency=10
        ))
    ])

    prep = ColumnTransformer([
        ("num", numeric_pipe, NUMERIC),
        ("cat", categorical_pipe, CATEGORICAL)
    ])

    model = Pipeline([
        ("prep", prep),
        ("classifier", LogisticRegression(
            class_weight="balanced",
            max_iter=1500,
            solver="liblinear",
            random_state=RANDOM_STATE
        ))
    ])

    print("\nTraining IEEE-CIS model...")

    model.fit(X_train, y_train)

    print("Evaluating validation probabilities...")

    validation_probabilities = model.predict_proba(
        X_validation
    )[:, 1]

    threshold, threshold_info = select_threshold(
        y_validation,
        validation_probabilities,
        MAX_VALIDATION_FPR
    )

    validation_metrics = calculate_metrics(
        y_validation,
        validation_probabilities,
        threshold
    )

    print(f"\nSelected threshold: {threshold:.6f}")
    print(
        "Validation FPR: "
        f"{threshold_info['validation_fpr']:.4f}"
    )
    print(
        "Validation recall: "
        f"{threshold_info['validation_recall']:.4f}"
    )

    print("\nEvaluating untouched final test set...")

    test_probabilities = model.predict_proba(
        X_test
    )[:, 1]

    test_metrics = calculate_metrics(
        y_test,
        test_probabilities,
        threshold
    )

    result = {
        "dataset": "IEEE-CIS Fraud Detection",
        "split_method": (
            "Chronological 64/16/20 training/validation/final-test "
            "within the prepared chronological 80/20 partition"
        ),
        "threshold_selection": threshold_info,
        "training_records": int(len(train)),
        "validation_records": int(len(validation)),
        "testing_records": int(len(test)),
        "training_fraud_rate": float(y_train.mean()),
        "validation_fraud_rate": float(y_validation.mean()),
        "testing_fraud_rate": float(y_test.mean()),
        "validation_metrics": validation_metrics,
        "test_metrics": test_metrics,
        "features_numeric": NUMERIC,
        "features_categorical": CATEGORICAL,
        "excluded_columns": [
            "TransactionID",
            "isFraud from features",
            "dataset_split",
            "dataset_source",
            "TransactionDT from features"
        ]
    }

    MODELS.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    artifact = {
        "model": model,
        "numeric_features": NUMERIC,
        "categorical_features": CATEGORICAL,
        "target": TARGET,
        "dataset": "IEEE-CIS",
        "threshold": threshold,
        "threshold_selection": threshold_info,
        "split_method": result["split_method"]
    }

    joblib.dump(
        artifact,
        MODELS / "ieee_cis_fraud_model.joblib"
    )

    (MODELS / "ieee_cis_metrics.json").write_text(
        json.dumps(result, indent=2),
        encoding="utf-8"
    )

    predictions = test[
        ["TransactionID", "TransactionDT", TARGET]
    ].copy()

    predictions["fraud_probability"] = test_probabilities
    predictions["selected_threshold"] = threshold
    predictions["predicted_fraud"] = (
        test_probabilities >= threshold
    ).astype(int)

    predictions.to_csv(
        OUTPUT / "ieee_cis_predictions.csv",
        index=False
    )

    print("\n========== IEEE-CIS FINAL TEST RESULTS ==========")

    for name, value in test_metrics.items():
        if isinstance(value, float):
            print(f"{name}: {value:.6f}")
        else:
            print(f"{name}: {value}")

    print("\nSaved:")
    print(MODELS / "ieee_cis_fraud_model.joblib")
    print(MODELS / "ieee_cis_metrics.json")
    print(OUTPUT / "ieee_cis_predictions.csv")


if __name__ == "__main__":
    main()
