"""Generate a deterministic synthetic retail dataset for the Aurum demo.

The raw dataset is Online-Retail shaped. It is engineered so that a *planted
bug* in the Silver transformation (dropping valid high-quantity orders) produces
the demo storyline:

    Bronze 100,000  ->  Silver 72,000  (28% drop)
    Expected revenue Rs 10.18 Cr  ->  Actual revenue Rs 9.70 Cr  (Rs 0.48 Cr loss)

All numbers fall out of the data; nothing downstream is hardcoded.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw"
HISTORICAL_DIR = DATA_DIR / "historical"

RUN_DATE = "2026-06-17"
COUNTRIES = ["United Kingdom", "Germany", "France", "EIRE", "Spain"]

# Each group: (count, quantity, unit_price, stock_code, description, valid, cancelled)
# Revenue per row = quantity * unit_price.
#   A: 16,000 * (4 * 337)  = 21,568,000
#   B: 56,000 * (3 * 449)  = 75,432,000
#   C: 24,000 * (25 * 8)   =  4,800,000   <- valid high-quantity (wrongly dropped)
#   D:  4,000 empty order lines (quantity 0) -> legitimately removed in Silver
GROUPS = [
    {"count": 16_000, "quantity": 4, "unit_price": 337.0, "stock_code": "85123A",
     "description": "WHITE HANGING HEART T-LIGHT HOLDER"},
    {"count": 56_000, "quantity": 3, "unit_price": 449.0, "stock_code": "71053",
     "description": "WHITE METAL LANTERN"},
    {"count": 24_000, "quantity": 25, "unit_price": 8.0, "stock_code": "22423",
     "description": "REGENCY CAKESTAND 3 TIER (WHOLESALE)"},
    {"count": 4_000, "quantity": 0, "unit_price": 5.0, "stock_code": "84029E",
     "description": "INVALID / EMPTY ORDER LINE"},
]


def build_raw_orders() -> pd.DataFrame:
    rows = []
    order_id = 0
    for group in GROUPS:
        for _ in range(group["count"]):
            order_id += 1
            rows.append(
                {
                    "invoice_no": f"INV{order_id:06d}",
                    "stock_code": group["stock_code"],
                    "description": group["description"],
                    "quantity": group["quantity"],
                    "invoice_date": RUN_DATE,
                    "unit_price": group["unit_price"],
                    "customer_id": (order_id % 5_000) + 1,
                    "country": COUNTRIES[order_id % len(COUNTRIES)],
                }
            )
    return pd.DataFrame(rows)


def build_historical_runs() -> pd.DataFrame:
    bronze_counts = [
        100000, 99900, 100100, 99950, 100050, 100000, 99850, 100150,
        100000, 99920, 100080, 100000, 99970, 100030, 100000,
    ]
    drop_pcts = [
        4.8, 5.2, 4.5, 5.5, 6.0, 4.9, 5.1, 5.8,
        4.7, 6.2, 5.0, 5.3, 4.6, 5.9, 5.4,
    ]
    gold_revenues = [
        101800000, 101600000, 102000000, 101700000, 101900000,
        101800000, 101500000, 102100000, 101800000, 101650000,
        101950000, 101800000, 101750000, 101850000, 101800000,
    ]
    rows = []
    for i, (bronze, drop, revenue) in enumerate(
        zip(bronze_counts, drop_pcts, gold_revenues), start=1
    ):
        silver = round(bronze * (1 - drop / 100))
        rows.append(
            {
                "run_id": f"history_{i:02d}",
                "bronze_count": bronze,
                "silver_count": silver,
                "drop_pct": round((bronze - silver) / bronze * 100, 2),
                "gold_revenue": revenue,
            }
        )
    return pd.DataFrame(rows)


def generate() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    HISTORICAL_DIR.mkdir(parents=True, exist_ok=True)

    raw = build_raw_orders()
    historical = build_historical_runs()

    raw.to_csv(RAW_DIR / "raw_orders.csv", index=False)
    historical.to_csv(HISTORICAL_DIR / "historical_runs.csv", index=False)

    valid = raw[(raw["quantity"] > 0) & (raw["unit_price"] > 0)]
    expected_revenue = float((valid["quantity"] * valid["unit_price"]).sum())
    print(
        {
            "raw_rows": len(raw),
            "valid_rows": len(valid),
            "expected_revenue": expected_revenue,
            "historical_runs": len(historical),
        }
    )


if __name__ == "__main__":
    generate()
