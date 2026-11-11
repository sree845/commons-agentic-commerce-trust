import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
file = BASE / "data" / "processed" / "ieee_cis_prepared.csv"

df = pd.read_csv(file, usecols=["isFraud", "dataset_split"])

for split in ["train", "test"]:
    part = df[df["dataset_split"] == split]
    fraud = int(part["isFraud"].sum())
    total = len(part)

    print(f"\n{split.upper()} SET")
    print("Total:", total)
    print("Fraud:", fraud)
    print("Legitimate:", total - fraud)
    print("Fraud rate:", round(fraud / total * 100, 3), "%")

print("\nVerification completed.")
