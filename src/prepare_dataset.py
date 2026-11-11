import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
RAW = BASE / "data" / "raw"
PROCESSED = BASE / "data" / "processed"
PROCESSED.mkdir(parents=True, exist_ok=True)

transaction_features = [
    "TransactionID", "TransactionDT", "isFraud",
    "TransactionAmt", "ProductCD",
    "card1", "card2", "card3", "card4", "card5", "card6",
    "addr1", "dist1", "P_emaildomain",
    "C1", "C2", "C5", "C6", "C7", "C8",
    "C9", "C10", "C11", "C12", "C13", "C14",
    "D1", "D2", "D3", "D4", "D10", "D15",
    "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9"
]

identity_features = [
    "TransactionID", "id_01", "id_02", "id_05",
    "id_06", "id_11", "id_12", "id_13", "id_15",
    "id_17", "id_19", "id_20", "DeviceType"
]

print("Loading transaction data...")

transactions = pd.read_csv(
    RAW / "train_transaction.csv",
    usecols=transaction_features
)

print("Loading identity data...")

identity = pd.read_csv(
    RAW / "train_identity.csv",
    usecols=identity_features
)

print("Merging datasets...")

data = transactions.merge(
    identity,
    on="TransactionID",
    how="left",
    validate="one_to_one"
)

data = data.sort_values("TransactionDT").reset_index(drop=True)

split_index = int(len(data) * 0.8)
data["dataset_split"] = "test"
data.loc[:split_index - 1, "dataset_split"] = "train"

data["dataset_source"] = "IEEE-CIS"

output = PROCESSED / "ieee_cis_prepared.csv"
data.to_csv(output, index=False)

print("\n========== PREPARATION COMPLETE ==========")
print("Total records:", len(data))
print("Total features:", len(data.columns))
print("Training records:", (data["dataset_split"] == "train").sum())
print("Testing records:", (data["dataset_split"] == "test").sum())
print("Fraudulent records:", int(data["isFraud"].sum()))
print("Legitimate records:", int((data["isFraud"] == 0).sum()))
print("Output:", output)
print("\nDataset preparation completed successfully.")
