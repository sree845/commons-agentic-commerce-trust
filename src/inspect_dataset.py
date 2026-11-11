import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data" / "raw"

file = DATA / "train_transaction.csv"

total = 0
fraud = 0
legitimate = 0
missing = None

for chunk in pd.read_csv(file, chunksize=50000):
    total += len(chunk)
    fraud += int(chunk["isFraud"].sum())
    legitimate += int((chunk["isFraud"] == 0).sum())

    current_missing = chunk.isnull().sum()
    if missing is None:
        missing = current_missing
    else:
        missing += current_missing

print("\n========== FULL DATASET RESULTS ==========")
print("Total transactions:", total)
print("Legitimate:", legitimate)
print("Fraudulent:", fraud)
print("Fraud percentage:", round(fraud / total * 100, 3))
print("\nTop 20 missing-value columns:")
print((missing / total * 100).sort_values(ascending=False).head(20).round(2))
