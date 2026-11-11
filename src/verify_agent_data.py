import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
file = BASE / "data" / "processed" / "synthetic_agent_orders.csv"

df = pd.read_csv(file)

features = [
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

print("Rows:", len(df))
print("Duplicate order IDs:", df["order_id"].duplicated().sum())
print("Missing feature values:", df[features].isnull().sum().sum())
print("Invalid attack labels:", (~df["is_attack"].isin([0, 1])).sum())

print("\nMerchant counts:")
print(df["merchant_id"].value_counts())

print("\nAttack labels:")
print(df["is_attack"].value_counts())

print("\nFeature correlation with attack label:")
print(df[features + ["is_attack"]].corr(numeric_only=True)["is_attack"].sort_values(ascending=False))

assert len(df) == 6000
assert df["order_id"].is_unique
assert df[features].notnull().all().all()
assert df["is_attack"].isin([0, 1]).all()

print("\nAll dataset integrity checks passed.")
