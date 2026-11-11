import json
import joblib
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
    roc_auc_score,
    average_precision_score
)
from sklearn.model_selection import GroupShuffleSplit

ROOT = Path(__file__).resolve().parents[1]

DATA_PATH = ROOT / "data/processed/synthetic_agent_orders.csv"
ADAPTATION_PATH = ROOT / "data/processed/emerging_attack_adaptation.csv"
HOLDOUT_PATH = ROOT / "data/processed/emerging_attack_holdout.csv"
MODEL_PATH = ROOT / "models/federated_risk_model.joblib"

CANDIDATE_PATH = ROOT / "models/immune_candidate_model.joblib"
REPORT_PATH = ROOT / "data/processed/immune_evaluation_report.json"
VERSION_PATH = ROOT / "models/immune_model_versions.json"

RANDOM_STATE = 42
VALIDATION_SIZE = 0.25
LOCAL_EPOCHS = 30
LEARNING_RATE = 0.03
L2 = 0.001
MAX_FPR_INCREASE = 0.02


def calculate_metrics(y_true, probabilities):
    predictions = (probabilities >= 0.5).astype(int)

    tn, fp, fn, tp = confusion_matrix(
        y_true,
        predictions,
        labels=[0, 1]
    ).ravel()

    return {
        "accuracy": round(float(accuracy_score(y_true, predictions)), 4),
        "precision": round(float(precision_score(
            y_true, predictions, zero_division=0
        )), 4),
        "recall": round(float(recall_score(
            y_true, predictions, zero_division=0
        )), 4),
        "f1": round(float(f1_score(
            y_true, predictions, zero_division=0
        )), 4),
        "roc_auc": round(float(roc_auc_score(
            y_true, probabilities
        )), 4),
        "pr_auc": round(float(average_precision_score(
            y_true, probabilities
        )), 4),
        "fpr": round(float(fp / (fp + tn)) if (fp + tn) else 0.0, 4),
        "confusion_matrix": {
            "tn": int(tn),
            "fp": int(fp),
            "fn": int(fn),
            "tp": int(tp)
        },
        "samples": int(len(y_true))
    }


def load_data():
    data = pd.read_csv(DATA_PATH)
    adaptation = pd.read_csv(ADAPTATION_PATH)
    holdout = pd.read_csv(HOLDOUT_PATH)

    required = {
        "agent_id",
        "is_attack"
    }

    for name, frame in [
        ("main dataset", data),
        ("adaptation dataset", adaptation),
        ("holdout dataset", holdout)
    ]:
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(
                f"{name} is missing columns: {sorted(missing)}"
            )

    return data, adaptation, holdout


def build_validation_split(data, adaptation):
    train_legitimate = data[data["is_attack"] == 0].copy()

    if len(adaptation) == 0:
        raise ValueError("Adaptation dataset is empty.")

    # Validation and adaptation groups must not overlap.
    splitter = GroupShuffleSplit(
        n_splits=1,
        test_size=VALIDATION_SIZE,
        random_state=RANDOM_STATE
    )

    train_idx, validation_idx = next(
        splitter.split(
            adaptation,
            groups=adaptation["agent_id"]
        )
    )

    adaptation_train_attacks = adaptation.iloc[train_idx].copy()
    adaptation_validation_attacks = adaptation.iloc[
        validation_idx
    ].copy()

    validation_agents = set(
        adaptation_validation_attacks["agent_id"]
    )

    legitimate_train = train_legitimate[
        ~train_legitimate["agent_id"].isin(validation_agents)
    ].copy()

    legitimate_validation = train_legitimate[
        train_legitimate["agent_id"].isin(validation_agents)
    ].copy()

    if len(legitimate_train) == 0 or len(legitimate_validation) == 0:
        raise ValueError(
            "Unable to create legitimate adaptation and validation groups."
        )

    # Keep the adaptation training data balanced.
    legitimate_train = legitimate_train.sample(
        n=min(len(legitimate_train), len(adaptation_train_attacks)),
        random_state=RANDOM_STATE
    )

    # Keep validation data balanced.
    legitimate_validation = legitimate_validation.sample(
        n=min(
            len(legitimate_validation),
            len(adaptation_validation_attacks)
        ),
        random_state=RANDOM_STATE
    )

    adaptation_train = pd.concat(
        [legitimate_train, adaptation_train_attacks],
        ignore_index=True
    ).sample(frac=1, random_state=RANDOM_STATE)

    validation = pd.concat(
        [legitimate_validation, adaptation_validation_attacks],
        ignore_index=True
    ).sample(frac=1, random_state=RANDOM_STATE)

    return adaptation_train, validation


def continued_training(model_package, adaptation_train):
    model = model_package["model"]
    scaler = model_package["scaler"]
    features = model_package["features"]

    X = adaptation_train[features].astype(float)
    y = adaptation_train["is_attack"].astype(int).to_numpy()

    X_scaled = scaler.transform(X)

    weights = model.coef_.astype(float).copy()
    bias = model.intercept_.astype(float).copy()

    positive_count = max(int(y.sum()), 1)
    negative_count = max(int(len(y) - y.sum()), 1)

    class_weights = np.where(
        y == 1,
        len(y) / (2 * positive_count),
        len(y) / (2 * negative_count)
    )

    for _ in range(LOCAL_EPOCHS):
        logits = np.clip(
            X_scaled @ weights.T + bias,
            -30,
            30
        ).ravel()

        probabilities = 1 / (1 + np.exp(-logits))

        errors = (probabilities - y) * class_weights

        weight_gradient = (
            errors @ X_scaled / len(y)
        ).reshape(weights.shape)

        bias_gradient = np.array([
            errors.mean()
        ])

        weights -= LEARNING_RATE * (
            weight_gradient + L2 * weights
        )

        bias -= LEARNING_RATE * bias_gradient

    candidate = joblib.load(MODEL_PATH)

    candidate_model = candidate["model"]
    candidate_model.coef_ = weights
    candidate_model.intercept_ = bias

    return candidate


def predict(model_package, frame):
    features = model_package["features"]
    model = model_package["model"]
    scaler = model_package["scaler"]

    X = frame[features].astype(float)
    X_scaled = scaler.transform(X)

    return model.predict_proba(X_scaled)[:, 1]


def main():
    print("\nCOMMONS IMMUNE LEARNING EVALUATION")
    print("=" * 50)

    data, adaptation, holdout = load_data()
    original_package = joblib.load(MODEL_PATH)

    features = original_package["features"]

    for name, frame in [
        ("adaptation", adaptation),
        ("holdout", holdout)
    ]:
        missing = set(features + ["is_attack"]) - set(frame.columns)
        if missing:
            raise ValueError(
                f"{name} dataset is missing columns: {sorted(missing)}"
            )

    if adaptation["is_attack"].nunique() != 1:
        raise ValueError(
            "Expected the adaptation file to contain emerging attacks only."
        )

    if holdout["is_attack"].nunique() != 2:
        raise ValueError(
            "Holdout must contain both legitimate and attack records."
        )

    adaptation_train, validation = build_validation_split(
        data,
        adaptation
    )

    print("\nDataset preparation")
    print("-" * 50)
    print("Adaptation training records:", len(adaptation_train))
    print("Validation records:", len(validation))
    print("Final holdout records:", len(holdout))

    train_groups = set(adaptation_train["agent_id"])
    validation_groups = set(validation["agent_id"])

    if train_groups & validation_groups:
        raise ValueError("Agent leakage detected between training and validation.")

    print("Agent-group separation: PASSED")

    # Evaluate the original model on validation.
    baseline_validation_probabilities = predict(
        original_package,
        validation
    )

    baseline_validation = calculate_metrics(
        validation["is_attack"].to_numpy(),
        baseline_validation_probabilities
    )

    # Continue training from the existing federated parameters.
    candidate_package = continued_training(
        original_package,
        adaptation_train
    )

    candidate_validation_probabilities = predict(
        candidate_package,
        validation
    )

    candidate_validation = calculate_metrics(
        validation["is_attack"].to_numpy(),
        candidate_validation_probabilities
    )

    # Safety gate: no material increase in false-positive rate,
    # and no reduction in validation recall.
    fpr_change = (
        candidate_validation["fpr"] -
        baseline_validation["fpr"]
    )

    recall_change = (
        candidate_validation["recall"] -
        baseline_validation["recall"]
    )

    accepted = (
        fpr_change <= MAX_FPR_INCREASE
        and recall_change >= 0
    )

    selected_package = (
        candidate_package if accepted else original_package
    )

    selected_version = (
        "immune_v2" if accepted else "federated_v1"
    )

    if accepted:
        joblib.dump(candidate_package, CANDIDATE_PATH)
        print("\nCandidate model accepted by validation safety gate.")
    else:
        print("\nCandidate rejected. Original federated model retained.")

    # Final comparison: evaluate both models on the same reserved holdout.
    # Do not use these results to change the acceptance decision.
    baseline_holdout = calculate_metrics(
        holdout["is_attack"].to_numpy(),
        predict(original_package, holdout)
    )

    candidate_holdout = calculate_metrics(
        holdout["is_attack"].to_numpy(),
        predict(candidate_package, holdout)
    )

    selected_holdout = calculate_metrics(
        holdout["is_attack"].to_numpy(),
        predict(selected_package, holdout)
    )

    report = {
        "experiment": "Commons immune learning adaptation",
        "random_state": RANDOM_STATE,
        "adaptation_training_records": int(len(adaptation_train)),
        "validation_records": int(len(validation)),
        "final_holdout_records": int(len(holdout)),
        "agent_group_separation": True,
        "validation": {
            "baseline": baseline_validation,
            "candidate": candidate_validation,
            "fpr_change": round(float(fpr_change), 4),
            "recall_change": round(float(recall_change), 4),
            "safety_gate_passed": bool(accepted)
        },
        "final_holdout": {
            "baseline_federated_model": baseline_holdout,
            "adapted_candidate_model": candidate_holdout,
            "selected_model": selected_holdout
        },
        "deployment_decision": {
            "accepted": bool(accepted),
            "selected_version": selected_version,
            "rollback_action": (
                "Retain original federated model"
                if not accepted
                else "Candidate passed validation safety gate"
            )
        },
        "limitations": [
            "Emerging attacks are synthetically generated.",
            "Adaptation records originate from the existing training population.",
            "The final holdout is reused for before-and-after comparison.",
            "Training and evaluation use synthetic emerging-attack examples; external merchant incident data is not yet connected.",
            "The safety gate is a validation policy, not proof of production safety."
        ]
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(REPORT_PATH, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=4)

    # Evaluation never silently changes the live model. Promotion is a separate,
    # named-human approval operation implemented by immune_governance.py.
    pending = {
        "candidate_version": "immune_candidate_pending",
        "candidate_path": str(CANDIDATE_PATH.relative_to(ROOT)) if accepted else None,
        "safety_gate_passed": bool(accepted),
        "status": "PENDING_HUMAN_APPROVAL" if accepted else "REJECTED",
        "created_at": int(__import__("time").time()),
        "validation": report["validation"],
        "limitations": ["Attack examples are synthetically generated; external incident data is not represented."]
    }
    with open(ROOT / "models" / "immune_candidate_review.json", "w", encoding="utf-8") as file:
        json.dump(pending, file, indent=4)

    print("\nVALIDATION RESULTS")
    print("-" * 50)
    print("Baseline FPR:", baseline_validation["fpr"])
    print("Candidate FPR:", candidate_validation["fpr"])
    print("Baseline recall:", baseline_validation["recall"])
    print("Candidate recall:", candidate_validation["recall"])
    print("Safety gate:", "PASSED" if accepted else "REJECTED")

    print("\nFINAL HOLDOUT COMPARISON")
    print("-" * 50)
    print("Baseline:", baseline_holdout)
    print("Candidate:", candidate_holdout)
    print("Selected:", selected_holdout)

    print("\nCandidate state:", "PENDING HUMAN APPROVAL" if accepted else "REJECTED")
    print("Evaluation report:", REPORT_PATH)
    print("Version history:", VERSION_PATH)
    print("\nIMMUNE LEARNING EVALUATION COMPLETE")


if __name__ == "__main__":
    main()
