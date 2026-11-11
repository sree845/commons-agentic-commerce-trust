import pandas as pd
from src.risk_engine import RiskEngine

engine = RiskEngine()

data = pd.read_csv(
    "data/processed/emerging_attack_holdout.csv"
)

data["risk"] = engine.model.predict_proba(
    engine.scaler.transform(data[engine.features])
)[:, 1]

print("HOLDOUT SIZE:", len(data))
print("\nLABEL COUNTS:")
print(data["is_attack"].value_counts())

for capture_threshold, void_threshold in [
    (0.30, 0.70),
    (0.35, 0.70),
    (0.40, 0.70)
]:
    def decide(score):
        if score < capture_threshold:
            return "CAPTURE"
        elif score >= void_threshold:
            return "VOID"
        return "HOLD"

    data["decision"] = data["risk"].apply(decide)

    print(
        f"\nPOLICY: CAPTURE < {capture_threshold}, "
        f"VOID >= {void_threshold}"
    )

    table = pd.crosstab(
        data["is_attack"].map({
            0: "Legitimate",
            1: "Attack"
        }),
        data["decision"]
    )

    table = table.reindex(
        index=["Legitimate", "Attack"],
        columns=["CAPTURE", "HOLD", "VOID"],
        fill_value=0
    )

    print(table.to_string())
