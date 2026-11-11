import pandas as pd
from src.risk_engine import RiskEngine

engine = RiskEngine()

data = pd.read_csv(
    "data/processed/synthetic_agent_orders.csv"
)

probabilities = engine.model.predict_proba(
    engine.scaler.transform(data[engine.features])
)[:, 1]

data["risk"] = probabilities

policies = [
    (0.10, 0.70),
    (0.25, 0.70),
    (0.30, 0.70),
    (0.35, 0.70),
    (0.40, 0.70),
    (0.45, 0.70),
    (0.30, 0.65),
    (0.35, 0.65),
    (0.40, 0.65)
]

for capture_threshold, void_threshold in policies:
    if capture_threshold >= void_threshold:
        continue

    def decide(score):
        if score < capture_threshold:
            return "CAPTURE"
        if score >= void_threshold:
            return "VOID"
        return "HOLD"

    data["decision"] = data["risk"].apply(decide)

    print(
        f"\nPolicy: CAPTURE < {capture_threshold:.2f}, "
        f"VOID >= {void_threshold:.2f}"
    )

    table = pd.crosstab(
        data["is_attack"].map({
            0: "Legitimate",
            1: "Attack"
        }),
        data["decision"]
    ).reindex(
        index=["Legitimate", "Attack"],
        columns=["CAPTURE", "HOLD", "VOID"],
        fill_value=0
    )

    print(table)

    legitimate = data[data["is_attack"] == 0]
    attacks = data[data["is_attack"] == 1]

    print(
        "Legitimate capture rate:",
        round((legitimate["decision"] == "CAPTURE").mean() * 100, 2),
        "%"
    )

    print(
        "Attack capture rate:",
        round((attacks["decision"] == "CAPTURE").mean() * 100, 2),
        "%"
    )

    print(
        "Legitimate void rate:",
        round((legitimate["decision"] == "VOID").mean() * 100, 2),
        "%"
    )
