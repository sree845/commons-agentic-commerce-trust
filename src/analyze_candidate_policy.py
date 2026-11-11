import pandas as pd

data = pd.read_csv(
    "data/processed/synthetic_agent_orders.csv"
)

overruns = data[
    (data["is_attack"] == 1)
    & (data["attack_family"] == "mandate_overrun")
].copy()

overruns["exceeds_cap"] = (
    overruns["amount"] > overruns["mandate_cap"]
)

print("TOTAL MANDATE-OVERRUN ATTACKS:", len(overruns))
print("\nAMOUNT EXCEEDS CAP:")
print(overruns["exceeds_cap"].value_counts().to_string())

print("\nATTACKS THAT ML WOULD CAPTURE:")
captured = overruns[
    (overruns["merchant_id"] == "merchant_C")
]

print(
    captured[
        [
            "order_id",
            "merchant_id",
            "amount",
            "mandate_cap",
            "amount_vs_merchant_norm",
            "exceeds_cap"
        ]
    ].to_string(index=False)
)
