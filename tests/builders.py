"""Tiny in-memory dataset builders for unit tests.

Tests construct exactly the scenario they need (a handful of rows) and load them
into a DuckDB-backed DataLoader via `DataLoader.from_frames`, bypassing the demo
ETL so each check can be exercised in isolation.
"""

from __future__ import annotations

import pandas as pd

from src.data_loader import DataLoader

_BASE_ROW = {
    "invoice_no": "INV000001",
    "stock_code": "A1",
    "description": "ITEM",
    "quantity": 1,
    "invoice_date": "2026-06-17",
    "unit_price": 10.0,
    "customer_id": 1,
    "country": "United Kingdom",
}


def make_rows(n: int, start: int = 1, **overrides) -> list[dict]:
    rows = []
    for i in range(n):
        row = dict(_BASE_ROW)
        row.update(overrides)
        row["invoice_no"] = f"INV{start + i:06d}"
        row["customer_id"] = (start + i) % 100 + 1
        rows.append(row)
    return rows


def to_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=list(_BASE_ROW.keys()))
    return pd.DataFrame(rows)


def to_silver(rows: list[dict]) -> pd.DataFrame:
    out = []
    for r in rows:
        row = dict(r)
        row["net_revenue"] = row["quantity"] * row["unit_price"]
        out.append(row)
    return pd.DataFrame(out)


def gold_from_silver(silver: pd.DataFrame) -> pd.DataFrame:
    total_revenue = float(silver["net_revenue"].sum())
    total_orders = int(silver["invoice_no"].nunique())
    total_customers = int(silver["customer_id"].nunique())
    aov = total_revenue / total_orders if total_orders else 0.0
    return pd.DataFrame(
        [
            {
                "total_revenue": total_revenue,
                "total_orders": total_orders,
                "total_customers": total_customers,
                "average_order_value": aov,
            }
        ]
    )


def historical_df(bronze_counts, drop_pcts, gold_revenues) -> pd.DataFrame:
    rows = []
    for i, (b, d, g) in enumerate(zip(bronze_counts, drop_pcts, gold_revenues), 1):
        rows.append(
            {
                "run_id": f"history_{i:02d}",
                "bronze_count": b,
                "silver_count": round(b * (1 - d / 100)),
                "drop_pct": d,
                "gold_revenue": g,
            }
        )
    return pd.DataFrame(rows)


def loader_from(**frames) -> DataLoader:
    return DataLoader.from_frames(frames)
