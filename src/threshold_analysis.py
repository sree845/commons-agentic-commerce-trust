from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "processed" / "risk_model_predictions.csv"

df = pd.read_csv(DATA_PATH)

print("\n========== COMMONS THRESHOLD ANALYSIS ==========")

for capture_limit, void_limit in [
    (10, 70),
    (15, 70),
    (20, 70),
    (25, 70),
    (30, 70),
    (20, 60),
    (20, 50),
    (30, 60)
]:
    decisions = pd.Series("HOLD", index=df.index)
    decisions[df["risk_score"] < capture_limit] = "CAPTURE"
    decisions[df["risk_score"] >= void_limit] = "VOID"

    capture = df[decisions == "CAPTURE"]
    hold = df[decisions == "HOLD"]
    void = df[decisions == "VOID"]

    captured_attacks = int(capture["is_attack"].sum())
    voided_legitimate = int((void["is_attack"] == 0).sum())

    print(f"\nThresholds: CAPTURE < {capture_limit}, VOID >= {void_limit}")
    print(f"Capture: {len(capture)} orders, {captured_attacks} attacks")
    print(f"Hold: {len(hold)} orders")
    print(f"Void: {len(void)} orders, {voided_legitimate} legitimate")
    print(f"Attacks captured: {captured_attacks}")
    print(f"Legitimate orders voided: {voided_legitimate}")

print("\nThreshold analysis completed.")
