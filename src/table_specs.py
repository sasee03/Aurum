"""Config-driven per-table data quality specifications.

Adding a new table to the rule library means adding an entry here — not writing
new check code. Each spec declares keys, mandatory columns, valid ranges, FK
relationships, and timeliness windows.
"""

from __future__ import annotations

from copy import deepcopy

from .config_loader import AurumDatasetConfig
from .contracts import BRONZE, GOLD, SILVER

# Valid business row predicate used for reconciliation (Layer 2).
VALID_ROW_PREDICATE = (
    "quantity > 0 AND unit_price > 0 "
    "AND invoice_no IS NOT NULL AND stock_code IS NOT NULL"
)




def build_table_specs(cfg: AurumDatasetConfig | None = None) -> dict[str, dict]:
    """Return Layer-1 table specs, using dataset config when provided."""
    if cfg is None:
        from .config_loader import load_dataset_config
        cfg = load_dataset_config()
    raw_columns = cfg.columns.resolve_raw_required_columns()
    silver_columns = list(raw_columns)
    if cfg.columns.revenue not in silver_columns:
        silver_columns.append(cfg.columns.revenue)

    line_item_key = list(cfg.columns.resolve_line_item_key())
    return {
        cfg.tables.raw: {
            "_quote_identifiers": True,
            "layer": "raw",
            "label": "Raw Source",
            "primary_key": [cfg.columns.primary_key],
            "business_key": line_item_key,
            "mandatory_columns": raw_columns,
            "range_checks": {
                cfg.columns.unit_price: {"min": 0, "strict_min": True},
            },
            "date_columns": [cfg.columns.timestamp],
            "date_column": cfg.columns.timestamp,
            "max_future_days": 0,
            "expected_freshness_days": 365,
            "timeliness_days": 365,
        },
        cfg.tables.bronze: {
            "_quote_identifiers": True,
            "layer": BRONZE,
            "label": "Bronze",
            "primary_key": [cfg.columns.primary_key],
            "business_key": line_item_key,
            "mandatory_columns": raw_columns,
            "range_checks": {
                cfg.columns.quantity: {"min": None, "max": None},
                cfg.columns.unit_price: {"min": 0, "strict_min": False},
            },
            "date_columns": [cfg.columns.timestamp],
            "date_column": cfg.columns.timestamp,
            "max_future_days": 0,
            "expected_freshness_days": 365,
            "timeliness_days": 365,
            "source_table": cfg.tables.raw,
        },
        cfg.tables.silver: {
            "_quote_identifiers": True,
            "layer": SILVER,
            "label": "Silver",
            "primary_key": [cfg.columns.primary_key],
            "business_key": line_item_key,
            "mandatory_columns": silver_columns,
            "range_checks": {
                cfg.columns.quantity: {"min": 0, "strict_min": True},
                cfg.columns.unit_price: {"min": 0, "strict_min": True},
                cfg.columns.revenue: {"min": 0, "strict_min": False},
            },
            "date_columns": [cfg.columns.timestamp],
            "date_column": cfg.columns.timestamp,
            "max_future_days": 0,
            "expected_freshness_days": 365,
            "timeliness_days": 365,
            "parent_table": cfg.tables.bronze,
            "parent_key": cfg.columns.primary_key,
            "child_key": cfg.columns.primary_key,
            "foreign_keys": [
                {
                    "column": cfg.columns.customer_id,
                    "ref_table": "customers",
                    "ref_column": cfg.columns.customer_id,
                }
            ],
        },
        cfg.tables.gold.metrics: {
            "_quote_identifiers": True,
            "layer": GOLD,
            "label": "Gold Metrics",
            "primary_key": [],
            "mandatory_columns": [
                cfg.metrics.total_revenue_metric,
                cfg.metrics.total_orders_metric,
                cfg.metrics.total_customers_metric,
                cfg.metrics.average_order_value_metric,
            ],
            "range_checks": {
                cfg.metrics.total_revenue_metric: {"min": 0, "strict_min": False},
                cfg.metrics.total_orders_metric: {"min": 0, "strict_min": False},
                cfg.metrics.total_customers_metric: {"min": 0, "strict_min": False},
            },
            "date_columns": [],
            "reconcile_from": cfg.tables.silver,
        },
        "order_payments": {
            "layer": BRONZE,
            "label": "Order Payments",
            "primary_key": ["payment_id"],
            "mandatory_columns": ["payment_id", cfg.columns.primary_key, "amount"],
            "range_checks": {"amount": {"min": 0, "strict_min": True}},
            "date_columns": [],
            "foreign_keys": [
                {
                    "column": cfg.columns.primary_key,
                    "ref_table": cfg.tables.bronze,
                    "ref_column": cfg.columns.primary_key,
                }
            ],
        },
    }

