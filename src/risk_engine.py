import json
import joblib
import numpy as np
import pandas as pd
from pathlib import Path, PureWindowsPath


ROOT = Path(__file__).resolve().parents[1]

VERSION_PATH = ROOT / "models" / "immune_model_versions.json"

REQUIRED_FEATURES = [
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


class RiskEngineError(Exception):
    pass


class RiskEngine:
    def __init__(self):
        self.model = None
        self.scaler = None
        self.features = None
        self.thresholds = None
        self.active_version = None
        self.load_active_model()

    def load_active_model(self):
        if not VERSION_PATH.exists():
            raise RiskEngineError("Model version registry not found.")

        with open(VERSION_PATH, "r", encoding="utf-8") as file:
            registry = json.load(file)

        active_version = registry.get("active_version")
        versions = registry.get("versions", {})

        if active_version not in versions:
            raise RiskEngineError("Active model version is not registered.")

        model_info = versions[active_version]

        if model_info.get("status") != "active":
            raise RiskEngineError("Registered model is not marked active.")

        # Registry files may have been created on Windows and deployed on Linux.
        relative_model_path = str(model_info["path"]).replace("\\", "/")
        model_path = ROOT.joinpath(*PureWindowsPath(relative_model_path).parts)

        if not model_path.exists():
            raise RiskEngineError("Active model file does not exist.")

        package = joblib.load(model_path)

        if not isinstance(package, dict):
            raise RiskEngineError("Invalid model package.")

        required_keys = {"model", "scaler", "features", "thresholds"}

        if not required_keys.issubset(package):
            raise RiskEngineError("Model package is incomplete.")

        if package["features"] != REQUIRED_FEATURES:
            raise RiskEngineError("Model feature order does not match.")

        thresholds = package["thresholds"]

        if not (
            0 <= thresholds["capture_below"]
            < thresholds["void_at_or_above"] <= 1
        ):
            raise RiskEngineError("Invalid model decision thresholds.")

        self.model = package["model"]
        self.scaler = package["scaler"]
        self.features = package["features"]
        self.thresholds = thresholds
        self.active_version = active_version

    def score_order(self, order):
        missing = [
            feature for feature in self.features
            if feature not in order
        ]

        if missing:
            raise ValueError(
                f"Missing model features: {missing}"
            )

        values = {}

        for feature in self.features:
            value = order[feature]

            if isinstance(value, bool) or not isinstance(
                value, (int, float, np.integer, np.floating)
            ):
                raise ValueError(
                    f"Feature '{feature}' must be numeric."
                )

            if not np.isfinite(value):
                raise ValueError(
                    f"Feature '{feature}' must be finite."
                )

            values[feature] = float(value)

        if values["amount"] <= 0:
            raise ValueError("Order amount must be positive.")

        if values["mandate_cap"] <= 0:
            raise ValueError("Mandate cap must be positive.")

        if values["category_allowed"] not in (0, 1):
            raise ValueError("category_allowed must be 0 or 1.")

        if values["address_changed"] not in (0, 1):
            raise ValueError("address_changed must be 0 or 1.")

        if values["mandate_age_days"] < 0:
            raise ValueError("Mandate age cannot be negative.")

        if values["orders_per_hour"] < 0:
            raise ValueError("Orders per hour cannot be negative.")

        if values["payment_retries"] < 0:
            raise ValueError("Payment retries cannot be negative.")

        if values["shared_agent_flag_count"] < 0:
            raise ValueError("Shared agent flags cannot be negative.")

        input_frame = pd.DataFrame(
            [[values[feature] for feature in self.features]],
            columns=self.features
        )

        scaled = self.scaler.transform(input_frame)

        probability = float(
            self.model.predict_proba(scaled)[0][1]
        )

        capture_threshold = self.thresholds["capture_below"]
        void_threshold = self.thresholds["void_at_or_above"]

        if probability < capture_threshold:
            decision = "CAPTURE"
        elif probability >= void_threshold:
            decision = "VOID"
        else:
            decision = "HOLD"

        reasons = []

        if values["amount"] > values["mandate_cap"]:
            reasons.append("Order amount exceeds mandate cap.")

        if values["category_allowed"] == 0:
            reasons.append("Order category is not permitted.")

        if values["address_changed"] == 1:
            reasons.append("Delivery address has changed.")

        if values["orders_per_hour"] >= 8:
            reasons.append("Unusually high order frequency.")

        if values["payment_retries"] >= 4:
            reasons.append("Unusually high payment retries.")

        if values["shared_agent_flag_count"] > 0:
            reasons.append("Agent has existing network risk flags.")

        if not reasons:
            reasons.append(
                "No configured behavioural warning indicators detected."
            )

        return {
            "decision": decision,
            "risk_probability": round(probability, 6),
            "risk_percentage": round(probability * 100, 2),
            "model_version": self.active_version,
            "thresholds": self.thresholds,
            "reasons": reasons,
            "features": values
        }


if __name__ == "__main__":
    try:
        engine = RiskEngine()

        test_order = {
            "amount": 45.00,
            "mandate_cap": 100.00,
            "category_allowed": 1,
            "mandate_age_days": 60,
            "orders_per_hour": 2,
            "address_changed": 0,
            "payment_retries": 0,
            "amount_vs_merchant_norm": 45.00 / 75.0,
            "shared_agent_flag_count": 0
        }

        result = engine.score_order(test_order)

        print("\n========== COMMONS RISK ENGINE ==========")
        print("Model version:", engine.active_version)
        print("Risk probability:", result["risk_probability"])
        print("Risk percentage:", result["risk_percentage"], "%")
        print("Decision:", result["decision"])
        print("Reasons:")

        for reason in result["reasons"]:
            print("-", reason)

        print("\nRisk engine test completed.")

    except (RiskEngineError, ValueError, KeyError) as error:
        print("Risk engine error:", error)
        raise SystemExit(1)
