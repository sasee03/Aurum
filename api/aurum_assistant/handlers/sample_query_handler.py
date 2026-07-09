"""Sample revenue query handler using local demo data."""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from typing import Any, Optional

from api.aurum_assistant.context import format_response, load_sample_orders
from src.config_loader import AurumDatasetConfig, load_dataset_config


def _build_sql_template(cfg: AurumDatasetConfig) -> str:
    geo = cfg.columns.geography
    label = cfg.metrics.top_revenue_label
    formula = cfg.metrics.revenue_formula
    silver = cfg.tables.silver
    return f"""SELECT
  {geo} AS {label},
  ROUND(SUM({formula}), 2) AS revenue
FROM {silver}
GROUP BY {geo}
ORDER BY revenue DESC
LIMIT 5;"""


@lru_cache(maxsize=1)
def _dataset_config() -> AurumDatasetConfig:
    return load_dataset_config()


def _compute_top_states(
    orders: list[dict], cfg: AurumDatasetConfig, limit: int = 5
) -> list[dict]:
    geo_col = cfg.columns.geography
    label = cfg.metrics.top_revenue_label
    qty_col = cfg.columns.quantity
    price_col = cfg.columns.unit_price
    totals: dict[str, float] = defaultdict(float)
    for row in orders:
        state = row.get(label) or row.get(geo_col, "Unknown")
        qty = float(row.get(qty_col, 0))
        price = float(row.get(price_col, 0))
        totals[state] += qty * price
    ranked = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [{label: code, "revenue": round(r, 2)} for code, r in ranked]


def handle(
    question: str,
    page: str = "query",
    layer: Optional[str] = None,
    context: Optional[dict] = None,
) -> dict:
    cfg = _dataset_config()
    sql_template = _build_sql_template(cfg)

    orders = load_sample_orders()
    if not orders:
        return format_response(
            "sample_revenue_query",
            "Sample order data is not available. Add data/sample/sample_orders.json to enable preview queries.",
            data={"sql": sql_template},
            confidence="low",
        )

    table = _compute_top_states(orders, cfg)
    answer = (
        "This query calculates revenue by multiplying quantity and unit price, "
        f"grouping by Brazilian {cfg.dataset.geography_label} "
        f"(mapped from customer_state in the {cfg.columns.geography} column), "
        "and sorting states by highest revenue. "
        "Sample preview based on local demo data — not final production truth."
    )

    return format_response(
        "sample_revenue_query",
        answer,
        data={"sql": sql_template, "table": table},
        confidence="medium",
    )
