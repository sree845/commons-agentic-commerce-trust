from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "processed" / "risk_model_predictions.csv"

df = pd.read_csv(DATA_PATH)

required = ["risk_score", "is_attack"]
missing = [column for column in required if column not in df.columns]

if missing:
    raise ValueError(f"Missing columns: {missing}")

def assign_decision(score):
    if score < 10:
        return "CAPTURE"
    elif score < 70:
        return "HOLD"
    return "VOID"

df["decision"] = df["risk_score"].apply(assign_decision)

print("\n========== COMMONS RISK DECISION EVALUATION ==========")

print("\nDecision Distribution:")
print(df["decision"].value_counts().reindex(
    ["CAPTURE", "HOLD", "VOID"], fill_value=0
))

print("\nDecision Breakdown:")
breakdown = pd.crosstab(
    df["decision"],
    df["is_attack"],
    rownames=["Decision"],
    colnames=["Actual Label"],
    margins=True
)

breakdown = breakdown.rename(columns={
    0: "Legitimate",
    1: "Attack"
})

print(breakdown)

print("\nDecision Quality:")

for decision in ["CAPTURE", "HOLD", "VOID"]:
    subset = df[df["decision"] == decision]

    if len(subset) == 0:
        print(f"{decision}: No orders")
        continue

    attacks = int(subset["is_attack"].sum())
    legitimate = len(subset) - attacks

    print(f"\n{decision}")
    print(f"Total orders: {len(subset)}")
    print(f"Actual attacks: {attacks}")
    print(f"Legitimate orders: {legitimate}")
    print(f"Attack proportion: {attacks / len(subset) * 100:.2f}%")

output_path = ROOT / "data" / "processed" / "risk_decision_evaluation.csv"
df.to_csv(output_path, index=False)

print("\nSaved evaluation:")
print(output_path)
print("\nRisk threshold evaluation completed.")
