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

TABLE_SPECS: dict[str, dict] = {
    "raw_orders": {
        "layer": BRONZE,
        "label": "Raw Source",
        "primary_key": ["invoice_no"],
        "mandatory_columns": [
            "invoice_no", "stock_code", "quantity", "unit_price",
            "invoice_date", "customer_id", "country",
        ],
        "range_checks": {
            "unit_price": {"min": 0, "strict_min": True},
        },
        "date_columns": ["invoice_date"],
        "date_column": "invoice_date",
        "max_future_days": 0,
        "expected_freshness_days": 365,
        "timeliness_days": 365,
    },
    "bronze_orders": {
        "layer": BRONZE,
        "label": "Bronze",
        "primary_key": ["invoice_no"],
        "mandatory_columns": [
            "invoice_no", "stock_code", "quantity", "unit_price",
            "invoice_date", "customer_id", "country",
        ],
        "range_checks": {
            "quantity": {"min": None, "max": None},  # profile only at Bronze
            "unit_price": {"min": 0, "strict_min": False},
        },
        "date_columns": ["invoice_date"],
        "date_column": "invoice_date",
        "max_future_days": 0,
        "expected_freshness_days": 365,
        "timeliness_days": 365,
        "source_table": "raw_orders",
    },
    "silver_orders": {
        "layer": SILVER,
        "label": "Silver",
        "primary_key": ["invoice_no"],
        "mandatory_columns": [
            "invoice_no", "stock_code", "quantity", "unit_price",
            "invoice_date", "customer_id", "country",
        ],
        "range_checks": {
            "quantity": {"min": 0, "strict_min": True},
            "unit_price": {"min": 0, "strict_min": True},
        },
        "date_columns": ["invoice_date"],
        "date_column": "invoice_date",
        "max_future_days": 0,
        "expected_freshness_days": 365,
        "timeliness_days": 365,
        "parent_table": "bronze_orders",
        "parent_key": "invoice_no",
        "child_key": "invoice_no",
        # FK to customers dimension — check runs only when customers table exists.
        # Catches orphan keys, NOT coherent swaps between valid keys (known limitation).
        "foreign_keys": [
            {
                "column": "customer_id",
                "ref_table": "customers",
                "ref_column": "customer_id",
            }
        ],
    },
    "gold_metrics": {
        "layer": GOLD,
        "label": "Gold Metrics",
        "primary_key": [],
        "mandatory_columns": [
            "total_revenue", "total_orders", "total_customers", "average_order_value",
        ],
        "range_checks": {
            "total_revenue": {"min": 0, "strict_min": False},
            "total_orders": {"min": 0, "strict_min": False},
            "total_customers": {"min": 0, "strict_min": False},
        },
        "date_columns": [],
        "reconcile_from": "silver_orders",
    },
    # Optional child table — FK checks run only when this table exists (bug zoo).
    "order_payments": {
        "layer": BRONZE,
        "label": "Order Payments",
        "primary_key": ["payment_id"],
        "mandatory_columns": ["payment_id", "invoice_no", "amount"],
        "range_checks": {"amount": {"min": 0, "strict_min": True}},
        "date_columns": [],
        "foreign_keys": [
            {
                "column": "invoice_no",
                "ref_table": "bronze_orders",
                "ref_column": "invoice_no",
            }
        ],
    },
}


def build_table_specs(cfg: AurumDatasetConfig | None = None) -> dict[str, dict]:
    """Return Layer-1 table specs, using dataset config when provided."""
    if cfg is None:
        return deepcopy(TABLE_SPECS)
    if (
        cfg.columns.primary_key == "invoice_no"
        and cfg.columns.product_id == "stock_code"
        and cfg.columns.customer_id == "customer_id"
        and cfg.columns.timestamp == "invoice_date"
        and cfg.columns.quantity == "quantity"
        and cfg.columns.unit_price == "unit_price"
        and cfg.columns.geography == "country"
    ):
        return deepcopy(TABLE_SPECS)
    raw_columns = cfg.columns.resolve_raw_required_columns()
    silver_columns = list(raw_columns)
    if cfg.columns.revenue not in silver_columns:
        silver_columns.append(cfg.columns.revenue)

    line_item_key = list(cfg.columns.resolve_line_item_key())
    return {
        "raw_orders": {
            "_quote_identifiers": True,
            "layer": BRONZE,
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
        "bronze_orders": {
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
            "source_table": "raw_orders",
        },
        "silver_orders": {
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
            "parent_table": "bronze_orders",
            "parent_key": cfg.columns.primary_key,
            "child_key": cfg.columns.primary_key,
            "foreign_keys": [],
        },
        "gold_metrics": {
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
            "reconcile_from": "silver_orders",
        },
    }
