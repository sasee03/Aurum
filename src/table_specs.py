"""Config-driven per-table data quality specifications.

Adding a new table to the rule library means adding an entry here — not writing
new check code. Each spec declares keys, mandatory columns, valid ranges, FK
relationships, and timeliness windows.
"""

from __future__ import annotations

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
        "timeliness_days": 365,
        "parent_table": "bronze_orders",
        "parent_key": "invoice_no",
        "child_key": "invoice_no",
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
                "parent_table": "bronze_orders",
                "parent_column": "invoice_no",
            }
        ],
    },
}
