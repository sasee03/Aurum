"""Bronze layer quality checks (B1-B8).

Bronze is the raw landing layer. We confirm ingestion completeness, structural
correctness, and profile data-quality issues that Silver is expected to clean.
Each check returns a `CheckResult`; the verdict engine rolls them up.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from .baseline import column_stats, tolerance_band
from .contracts import BRONZE, CheckResult, FAIL, PASS, WARN
from .data_loader import DataLoader

REQUIRED_COLUMNS = [
    "invoice_no",
    "stock_code",
    "description",
    "quantity",
    "invoice_date",
    "unit_price",
    "customer_id",
    "country",
]

MANDATORY_NOT_NULL = ["invoice_no", "quantity", "invoice_date", "unit_price", "country"]

DUP_KEY = ["invoice_no", "stock_code", "customer_id", "invoice_date"]

# Fallback thresholds used only when no historical baseline is available.
CONFIG_MIN_ROWS = 50_000
CONFIG_MAX_ROWS = 150_000


def _history(loader: DataLoader) -> Optional[pd.DataFrame]:
    if loader.table_exists("historical_runs"):
        return loader.query("SELECT * FROM historical_runs")
    return None


def b1_source_to_bronze_count(loader: DataLoader) -> CheckResult:
    source = loader.count("raw_orders") if loader.table_exists("raw_orders") else None
    bronze = loader.count("bronze_orders")
    if source is None:
        status, detail = WARN, "No raw_orders source table to reconcile against."
    elif source == bronze:
        status = PASS
        detail = "Source and Bronze row counts match."
    else:
        status = FAIL
        detail = f"Source has {source:,} rows but Bronze has {bronze:,}."
    return CheckResult(
        "B1", "Source to Bronze Row Count", BRONZE, status,
        observed=bronze, expected=source,
        detail=detail,
        evidence_query="SELECT COUNT(*) FROM bronze_orders",
    )


def b2_count_band(loader: DataLoader) -> CheckResult:
    bronze = loader.count("bronze_orders")
    stats = column_stats(_history(loader), "bronze_count")
    if stats and stats["std"] > 0:
        band = tolerance_band(stats, k=3.0)
        wide = tolerance_band(stats, k=5.0)
        if band["lower"] <= bronze <= band["upper"]:
            status, detail = PASS, "Bronze count is within the learned normal range."
        elif wide["lower"] <= bronze <= wide["upper"]:
            status, detail = WARN, "Bronze count is slightly outside the normal range."
        else:
            status, detail = FAIL, "Bronze count is far outside the normal range."
        expected = f"{band['lower']:.0f}-{band['upper']:.0f} (mean +/- 3 std)"
    else:
        if CONFIG_MIN_ROWS <= bronze <= CONFIG_MAX_ROWS:
            status, detail = PASS, "Bronze count within configured min/max thresholds."
        else:
            status, detail = FAIL, "Bronze count outside configured min/max thresholds."
        expected = f"{CONFIG_MIN_ROWS:,}-{CONFIG_MAX_ROWS:,} (configured)"
    return CheckResult(
        "B2", "Low / High / Normal Count", BRONZE, status,
        observed=bronze, expected=expected, detail=detail,
        evidence_query="SELECT COUNT(*) FROM bronze_orders",
    )


def b3_empty_table(loader: DataLoader) -> CheckResult:
    bronze = loader.count("bronze_orders")
    status = PASS if bronze > 0 else FAIL
    detail = "Bronze table has rows." if bronze > 0 else "Bronze table is empty."
    return CheckResult(
        "B3", "Empty Table Check", BRONZE, status,
        observed=bronze, expected="> 0", detail=detail,
        evidence_query="SELECT COUNT(*) FROM bronze_orders",
    )


def b4_required_columns(loader: DataLoader) -> CheckResult:
    cols = loader.columns("bronze_orders")
    missing = [c for c in REQUIRED_COLUMNS if c not in cols]
    status = PASS if not missing else FAIL
    detail = (
        "All required columns are present."
        if not missing
        else f"Missing required columns: {missing}."
    )
    return CheckResult(
        "B4", "Required Columns Present", BRONZE, status,
        observed=cols, expected=REQUIRED_COLUMNS, detail=detail,
        evidence_query="SELECT * FROM bronze_orders LIMIT 0",
    )


def b5_extra_missing_columns(loader: DataLoader) -> CheckResult:
    cols = loader.columns("bronze_orders")
    missing = [c for c in REQUIRED_COLUMNS if c not in cols]
    extra = [c for c in cols if c not in REQUIRED_COLUMNS]
    status = WARN if missing else PASS
    detail = f"missing_columns={missing}, extra_columns={extra}"
    return CheckResult(
        "B5", "Extra / Missing Columns", BRONZE, status,
        observed={"missing_columns": missing, "extra_columns": extra},
        expected={"missing_columns": [], "extra_columns": []},
        detail=detail,
        evidence_query="SELECT * FROM bronze_orders LIMIT 0",
        extra={"missing_columns": missing, "extra_columns": extra},
    )


def b6_mandatory_nulls(loader: DataLoader) -> CheckResult:
    cols = loader.columns("bronze_orders")
    null_counts = {}
    for col in MANDATORY_NOT_NULL:
        if col in cols:
            null_counts[col] = int(
                loader.scalar(f"SELECT COUNT(*) FROM bronze_orders WHERE {col} IS NULL")
            )
    total_nulls = sum(null_counts.values())
    status = PASS if total_nulls == 0 else FAIL
    detail = (
        "No nulls in mandatory columns."
        if total_nulls == 0
        else f"Mandatory columns contain nulls: {null_counts}."
    )
    return CheckResult(
        "B6", "Null Count per Mandatory Column", BRONZE, status,
        observed=null_counts, expected={c: 0 for c in null_counts}, detail=detail,
        evidence_query=(
            "SELECT COUNT(*) FROM bronze_orders WHERE invoice_no IS NULL"
        ),
    )


def b7_negative_values(loader: DataLoader) -> CheckResult:
    neg_qty = int(loader.scalar("SELECT COUNT(*) FROM bronze_orders WHERE quantity < 0"))
    neg_price = int(
        loader.scalar("SELECT COUNT(*) FROM bronze_orders WHERE unit_price < 0")
    )
    total = neg_qty + neg_price
    status = PASS if total == 0 else WARN
    detail = (
        "No negative quantity or unit_price values."
        if total == 0
        else (
            f"Profiled {neg_qty:,} negative-quantity and {neg_price:,} "
            "negative-price rows (expected to be cleaned in Silver)."
        )
    )
    return CheckResult(
        "B7", "Negative Value Profiling", BRONZE, status,
        observed={"negative_quantity": neg_qty, "negative_unit_price": neg_price},
        expected="profiled (not blocking at Bronze)", detail=detail,
        evidence_query="SELECT COUNT(*) FROM bronze_orders WHERE quantity < 0",
    )


def b8_duplicates(loader: DataLoader) -> CheckResult:
    total = loader.count("bronze_orders")
    key_cols = ", ".join(DUP_KEY)
    dup_rows = int(
        loader.scalar(
            f"""
            SELECT COALESCE(SUM(cnt - 1), 0) FROM (
                SELECT COUNT(*) AS cnt FROM bronze_orders
                GROUP BY {key_cols} HAVING COUNT(*) > 1
            )
            """
        )
    )
    dup_pct = (dup_rows / total * 100) if total else 0
    if dup_rows == 0:
        status, detail = PASS, "No duplicate business keys in Bronze."
    elif dup_pct < 5:
        status = WARN
        detail = f"{dup_rows:,} duplicate business keys ({dup_pct:.2f}%); Silver should dedupe."
    else:
        status = FAIL
        detail = f"Extreme duplicate load: {dup_rows:,} rows ({dup_pct:.2f}%)."
    return CheckResult(
        "B8", "Duplicate Check", BRONZE, status,
        observed=dup_rows, expected=0, detail=detail,
        evidence_query=(
            f"SELECT {key_cols}, COUNT(*) FROM bronze_orders "
            f"GROUP BY {key_cols} HAVING COUNT(*) > 1"
        ),
    )


def validate_bronze(loader: DataLoader) -> list[CheckResult]:
    return [
        b1_source_to_bronze_count(loader),
        b2_count_band(loader),
        b3_empty_table(loader),
        b4_required_columns(loader),
        b5_extra_missing_columns(loader),
        b6_mandatory_nulls(loader),
        b7_negative_values(loader),
        b8_duplicates(loader),
    ]


if __name__ == "__main__":
    for result in validate_bronze(DataLoader()):
        print(result.status, result.check_id, result.detail)
