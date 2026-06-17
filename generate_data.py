"""Generate deterministic Aurum demo CSVs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


DATA_DIR = Path("data")


def build_bronze_orders() -> pd.DataFrame:
    order_ids = range(1, 100_001)
    rows = []

    for order_id in order_ids:
        is_invalid = order_id > 96_000
        is_discounted = 72_000 < order_id <= 96_000

        if is_invalid:
            net_amount = 100
        elif is_discounted:
            net_amount = 200
        else:
            net_amount = 1_348 if order_id <= 16_000 else 1_347

        rows.append(
            {
                "order_id": order_id,
                "customer_id": (order_id % 10_000) + 1,
                "status": "INVALID" if is_invalid else "VALID",
                "has_discount": is_discounted,
                "net_amount": net_amount,
                "order_date": "2026-06-17",
            }
        )

    return pd.DataFrame(rows)


def build_historical_runs() -> pd.DataFrame:
    drop_pcts = [
        3.77,
        3.85,
        3.77,
        3.85,
        3.77,
        3.85,
        3.77,
        3.85,
        3.79,
        3.83,
        3.78,
        3.84,
        3.81,
        3.81,
        3.81,
    ]
    return pd.DataFrame(
        {
            "run_id": [f"history_{idx:02d}" for idx in range(1, 16)],
            "bronze_count": [100_000] * 15,
            "silver_count": [round(100_000 * (1 - pct / 100)) for pct in drop_pcts],
            "drop_pct": drop_pcts,
        }
    )


def generate() -> None:
    DATA_DIR.mkdir(exist_ok=True)

    bronze = build_bronze_orders()
    correct_silver = bronze[bronze["status"] == "VALID"].copy()
    buggy_silver = correct_silver[~correct_silver["has_discount"]].copy()

    bronze.to_csv(DATA_DIR / "bronze_orders.csv", index=False)
    correct_silver.to_csv(DATA_DIR / "silver_orders_correct.csv", index=False)
    buggy_silver.to_csv(DATA_DIR / "silver_orders_buggy.csv", index=False)
    build_historical_runs().to_csv(DATA_DIR / "historical_runs.csv", index=False)

    expected_revenue_cr = correct_silver["net_amount"].sum() / 10_000_000
    actual_revenue_cr = buggy_silver["net_amount"].sum() / 10_000_000
    print(
        {
            "bronze_count": len(bronze),
            "silver_buggy_count": len(buggy_silver),
            "drop_pct": round((len(bronze) - len(buggy_silver)) / len(bronze) * 100, 2),
            "expected_revenue_cr": round(expected_revenue_cr, 2),
            "actual_revenue_cr": round(actual_revenue_cr, 2),
            "impact_cr": round(expected_revenue_cr - actual_revenue_cr, 2),
        }
    )


if __name__ == "__main__":
    generate()
