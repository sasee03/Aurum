"""Generate Aurum demo CSVs from the Olist Brazilian e-commerce dataset.

Data source: Olist public dataset (see ``src/olist_ingest.py``). The Silver ETL
plants a price-threshold bug (``unit_price <= 20``) that wrongly drops valid
high-value line items — the detection story is the same shape as before but
grounded in real Olist order_items ``price`` values.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

try:
    from .olist_ingest import OLIST_DIR, build_raw_orders_from_olist, olist_summary
except ImportError:
    from olist_ingest import OLIST_DIR, build_raw_orders_from_olist, olist_summary

DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw"
HISTORICAL_DIR = DATA_DIR / "historical"


def build_historical_runs(bronze_count: int, expected_revenue: float) -> pd.DataFrame:
    """Bootstrap run history sized to the Olist bronze load (normal ~5% drop band)."""
    bronze_counts = [
        bronze_count,
        bronze_count - 100,
        bronze_count + 100,
        bronze_count - 50,
        bronze_count + 50,
        bronze_count,
        bronze_count - 150,
        bronze_count + 150,
        bronze_count,
        bronze_count - 80,
        bronze_count + 80,
        bronze_count,
        bronze_count - 30,
        bronze_count + 30,
        bronze_count,
    ]
    drop_pcts = [
        4.8, 5.2, 4.5, 5.5, 6.0, 4.9, 5.1, 5.8,
        4.7, 6.2, 5.0, 5.3, 4.6, 5.9, 5.4,
    ]
    gold_revenues = [expected_revenue] * len(bronze_counts)
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

    raw = build_raw_orders_from_olist(OLIST_DIR)
    stats = olist_summary(raw)
    historical = build_historical_runs(stats["raw_rows"], stats["expected_revenue"])

    raw.to_csv(RAW_DIR / "raw_orders.csv", index=False)
    historical.to_csv(HISTORICAL_DIR / "historical_runs.csv", index=False)

    print({**stats, "historical_runs": len(historical), "source": "olist"})


if __name__ == "__main__":
    generate()
