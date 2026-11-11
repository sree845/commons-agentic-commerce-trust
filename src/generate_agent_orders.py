import pandas as pd
import numpy as np
from pathlib import Path

SEED = 42
rng = np.random.default_rng(SEED)

BASE = Path(__file__).resolve().parent.parent
OUTPUT = BASE / "data" / "processed"
OUTPUT.mkdir(parents=True, exist_ok=True)

MERCHANTS = {
    "merchant_A": "address_swap",
    "merchant_B": "rapid_retries",
    "merchant_C": "mandate_overrun"
}

ATTACKS = [
    "mandate_overrun",
    "category_violation",
    "address_swap",
    "rapid_retries",
    "payment_retry_abuse"
]

def generate_order(merchant, index):
    attack = rng.random() < 0.20

    if attack:
        if rng.random() < 0.65:
            family = MERCHANTS[merchant]
        else:
            family = rng.choice(ATTACKS)
    else:
        family = "legitimate"

    is_attack = int(attack)

    mandate_cap = float(rng.choice([50, 100, 200, 500]))
    amount = float(rng.uniform(10, min(mandate_cap, 150)))

    allowed_category = 1
    mandate_age_days = int(rng.integers(5, 180))
    orders_per_hour = int(rng.integers(1, 4))
    address_changed = 0
    payment_retries = int(rng.integers(0, 2))
    shared_agent_flag_count = int(rng.integers(0, 2))

    if family == "mandate_overrun":
        amount = mandate_cap * float(rng.uniform(1.2, 2.5))

    elif family == "category_violation":
        allowed_category = 0

    elif family == "address_swap":
        address_changed = 1

    elif family == "rapid_retries":
        orders_per_hour = int(rng.integers(8, 25))

    elif family == "payment_retry_abuse":
        payment_retries = int(rng.integers(4, 12))

    

    return {
        "order_id": f"{merchant}_{index:05d}",
        "merchant_id": merchant,
        "agent_id": f"agent_{rng.integers(1, 501):04d}",
        "amount": round(amount, 2),
        "mandate_cap": mandate_cap,
        "category_allowed": allowed_category,
        "mandate_age_days": mandate_age_days,
        "orders_per_hour": orders_per_hour,
        "address_changed": address_changed,
        "payment_retries": payment_retries,
        "amount_vs_merchant_norm": round(
            amount / 75.0, 3
        ),
        "shared_agent_flag_count": shared_agent_flag_count,
        "attack_family": family,
        "is_attack": is_attack
    }

records = []

orders_per_merchant = 2000

for merchant in MERCHANTS:
    for index in range(orders_per_merchant):
        records.append(
            generate_order(merchant, index + 1)
        )

df = pd.DataFrame(records)

df = df.sample(frac=1, random_state=SEED).reset_index(drop=True)

output_file = OUTPUT / "synthetic_agent_orders.csv"
df.to_csv(output_file, index=False)

print("\n========== COMMONS AGENT DATASET ==========")
print("Total orders:", len(df))
print("Legitimate orders:", int((df["is_attack"] == 0).sum()))
print("Attack orders:", int(df["is_attack"].sum()))

print("\nMerchant distribution:")
print(df["merchant_id"].value_counts())

print("\nAttack family distribution:")
print(df["attack_family"].value_counts())

print("\nMerchant and attack distribution:")
print(pd.crosstab(
    df["merchant_id"],
    df["attack_family"]
))

print("\nOutput:", output_file)
print("\nDataset generation completed.")
