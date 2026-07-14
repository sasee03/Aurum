"""Bronze layer quality checks (B1-B10).

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
from .resilience import Check, run_checks
from .config_loader import load_dataset_config, AurumDatasetConfig



# Fallback thresholds used only when no historical baseline is available.
CONFIG_MIN_ROWS = 90_000
CONFIG_MAX_ROWS = 130_000


def _history(loader: DataLoader) -> Optional[pd.DataFrame]:
    if loader.table_exists("historical_runs"):
        return loader.query("SELECT * FROM historical_runs")
    return None


def b1_source_to_bronze_count(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
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


def b2_count_band(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
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


def b3_empty_table(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
    bronze = loader.count("bronze_orders")
    status = PASS if bronze > 0 else FAIL
    detail = "Bronze table has rows." if bronze > 0 else "Bronze table is empty."
    return CheckResult(
        "B3", "Empty Table Check", BRONZE, status,
        observed=bronze, expected="> 0", detail=detail,
        evidence_query="SELECT COUNT(*) FROM bronze_orders",
    )


def b4_required_columns(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
    required_cols = [
        cfg.columns.primary_key,
        cfg.columns.product_id,
        cfg.columns.product_description,
        cfg.columns.quantity,
        cfg.columns.timestamp,
        cfg.columns.unit_price,
        cfg.columns.customer_id,
        cfg.columns.geography,
    ]
    cols = loader.columns("bronze_orders")
    missing = [c for c in required_cols if c not in cols]
    status = PASS if not missing else FAIL
    detail = (
        "All required columns are present."
        if not missing
        else f"Missing required columns: {missing}."
    )
    return CheckResult(
        "B4", "Required Columns Present", BRONZE, status,
        observed=cols, expected=required_cols, detail=detail,
        evidence_query="SELECT * FROM bronze_orders LIMIT 0",
    )


def b5_extra_missing_columns(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
    required_cols = [
        cfg.columns.primary_key,
        cfg.columns.product_id,
        cfg.columns.product_description,
        cfg.columns.quantity,
        cfg.columns.timestamp,
        cfg.columns.unit_price,
        cfg.columns.customer_id,
        cfg.columns.geography,
    ]
    cols = loader.columns("bronze_orders")
    missing = [c for c in required_cols if c not in cols]
    extra = [c for c in cols if c not in required_cols]
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


def b6_mandatory_nulls(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
    mandatory_not_null = [
        cfg.columns.primary_key,
        cfg.columns.quantity,
        cfg.columns.timestamp,
        cfg.columns.unit_price,
        cfg.columns.geography,
    ]
    cols = loader.columns("bronze_orders")
    null_counts = {}
    for col in mandatory_not_null:
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
            f"SELECT COUNT(*) FROM bronze_orders WHERE {cfg.columns.primary_key} IS NULL"
        ),
    )


def b7_negative_values(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
    qty_col = cfg.columns.quantity
    price_col = cfg.columns.unit_price
    neg_qty = int(loader.scalar(f"SELECT COUNT(*) FROM bronze_orders WHERE {qty_col} < 0"))
    neg_price = int(
        loader.scalar(f"SELECT COUNT(*) FROM bronze_orders WHERE {price_col} < 0")
    )
    total = neg_qty + neg_price
    status = PASS if total == 0 else WARN
    detail = (
        f"No negative {qty_col} or {price_col} values."
        if total == 0
        else (
            f"Profiled {neg_qty:,} negative-{qty_col} and {neg_price:,} "
            f"negative-{price_col} rows (expected to be cleaned in Silver)."
        )
    )
    return CheckResult(
        "B7", "Negative Value Profiling", BRONZE, status,
        observed={"negative_quantity": neg_qty, "negative_unit_price": neg_price},
        expected="profiled (not blocking at Bronze)", detail=detail,
        evidence_query=f"SELECT COUNT(*) FROM bronze_orders WHERE {qty_col} < 0",
    )


def b8_duplicates(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
    key_cols_list = [
        cfg.columns.primary_key,
        cfg.columns.product_id,
        cfg.columns.customer_id,
        cfg.columns.timestamp
    ]
    key_cols = ", ".join(key_cols_list)
    total = loader.count("bronze_orders")
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


def b9_invoice_date_parse(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
    ts_col = cfg.columns.timestamp
    bad = int(
        loader.scalar(
            f"""
            SELECT COUNT(*) FROM bronze_orders
            WHERE {ts_col} IS NOT NULL
              AND TRY_CAST({ts_col} AS DATE) IS NULL
            """
        )
    )
    status = PASS if bad == 0 else FAIL
    detail = (
        f"All non-null {ts_col} values parse as dates."
        if bad == 0
        else f"{bad:,} rows have non-null {ts_col} that does not parse as a date."
    )
    return CheckResult(
        "B9", "Invoice Date Parse Validity", BRONZE, status,
        observed=bad, expected=0, detail=detail,
        evidence_query=(
            f"SELECT COUNT(*) FROM bronze_orders "
            f"WHERE {ts_col} IS NOT NULL "
            f"AND TRY_CAST({ts_col} AS DATE) IS NULL"
        ),
    )


def b10_future_invoice_dates(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
    ts_col = cfg.columns.timestamp
    future = int(
        loader.scalar(
            f"""
            SELECT COUNT(*) FROM bronze_orders
            WHERE TRY_CAST({ts_col} AS DATE) > CURRENT_DATE
            """
        )
    )
    status = PASS if future == 0 else WARN
    detail = (
        f"No {ts_col} values are in the future."
        if future == 0
        else (
            f"{future:,} rows have {ts_col} after the run date "
            "(profiled; expected to be filtered in Silver)."
        )
    )
    return CheckResult(
        "B10", "Future Invoice Date Profiling", BRONZE, status,
        observed=future, expected=0, detail=detail,
        evidence_query=(
            f"SELECT COUNT(*) FROM bronze_orders "
            f"WHERE TRY_CAST({ts_col} AS DATE) > CURRENT_DATE"
        ),
    )


def validate_bronze(
    loader: DataLoader,
    cfg: Optional[AurumDatasetConfig] = None,
) -> list[CheckResult]:
    cfg = cfg or load_dataset_config()
    core = run_checks(
        [
            Check(lambda: b1_source_to_bronze_count(loader, cfg), "B1", "Source to Bronze Row Count", BRONZE),
            Check(lambda: b2_count_band(loader, cfg), "B2", "Low / High / Normal Count", BRONZE),
            Check(lambda: b3_empty_table(loader, cfg), "B3", "Empty Table Check", BRONZE),
            Check(lambda: b4_required_columns(loader, cfg), "B4", "Required Columns Present", BRONZE),
        ]
    )
    # Preserve original control flow: only a hard FAIL on required columns stops
    # the deeper profile checks (they would be meaningless). A SKIPPED B4 does not.
    if core and core[-1].check_id == "B4" and core[-1].status == FAIL:
        return core
    return core + run_checks(
        [
            Check(lambda: b5_extra_missing_columns(loader, cfg), "B5", "Extra / Missing Columns", BRONZE),
            Check(lambda: b6_mandatory_nulls(loader, cfg), "B6", "Null Count per Mandatory Column", BRONZE),
            Check(lambda: b7_negative_values(loader, cfg), "B7", "Negative Value Profiling", BRONZE),
            Check(lambda: b8_duplicates(loader, cfg), "B8", "Duplicate Check", BRONZE),
            Check(lambda: b9_invoice_date_parse(loader, cfg), "B9", "Invoice Date Parse Validity", BRONZE),
            Check(lambda: b10_future_invoice_dates(loader, cfg), "B10", "Future Invoice Date Profiling", BRONZE),
        ]
    )


if __name__ == "__main__":
    for result in validate_bronze(DataLoader()):
        print(result.status, result.check_id, result.detail)
