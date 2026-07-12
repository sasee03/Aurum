"""Gold layer quality checks (G1-G10).

Gold holds business metrics aggregated from Silver. We reconcile each metric
against a fresh recomputation from Silver (catches calculation bugs) and compare
revenue against the learned baseline (catches upstream damage -> IMPACTED).
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from .baseline import column_stats, tolerance_band
from .contracts import CheckResult, FAIL, GOLD, IMPACTED, PASS, WARN
from .data_loader import DataLoader
from .resilience import Check, run_checks
from .revenue_tolerance import REVENUE_ROUNDING_TOLERANCE, revenue_tolerance_detail
from .config_loader import load_dataset_config, AurumDatasetConfig

AOV_TOLERANCE = 0.01
RPC_TOLERANCE = 0.01


def _history(loader: DataLoader) -> Optional[pd.DataFrame]:
    if loader.table_exists("historical_runs"):
        return loader.query("SELECT * FROM historical_runs")
    return None


def g1_revenue_reconciliation(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
    revenue_col = cfg.columns.revenue if cfg else "net_revenue"
    revenue_metric = cfg.metrics.total_revenue_metric if cfg else "total_revenue"
    tolerance = REVENUE_ROUNDING_TOLERANCE
    silver_rev = float(loader.scalar(f"SELECT SUM({revenue_col}) FROM silver_orders") or 0)
    gold_rev = float(loader.scalar(f"SELECT {revenue_metric} FROM gold_metrics") or 0)
    diff = abs(silver_rev - gold_rev)
    match = diff <= tolerance
    tol_note = revenue_tolerance_detail(tolerance)
    status = PASS if match else FAIL
    detail = (
        f"Gold {revenue_metric} reconciles with Silver ({tol_note})."
        if match
        else (
            f"Gold revenue {gold_rev:,.2f} != Silver revenue {silver_rev:,.2f} "
            f"(diff {diff:.2f} > tolerance {tolerance})."
        )
    )
    return CheckResult(
        "G1", "Revenue Reconciliation (within rounding tolerance)", GOLD, status,
        observed={"gold_revenue": gold_rev, "difference": diff,
                  "revenue_rounding_tolerance": tolerance},
        expected={"silver_revenue": silver_rev},
        detail=detail,
        evidence_query=f"SELECT SUM({revenue_col}) FROM silver_orders",
        extra={"revenue_rounding_tolerance": tolerance},
    )


def g2_order_count_reconciliation(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
    order_id_expression = cfg.metrics.order_id_expression if cfg else "REGEXP_REPLACE(invoice_no, '_[0-9]+$', '')"
    silver_orders = int(
        loader.scalar(
            f"SELECT COUNT(DISTINCT {order_id_expression}) FROM silver_orders"
        )
        or 0
    )
    gold_orders = int(loader.scalar("SELECT total_orders FROM gold_metrics") or 0)
    match = silver_orders == gold_orders
    status = PASS if match else FAIL
    detail = (
        "Gold total_orders reconciles with Silver."
        if match
        else f"Gold orders {gold_orders:,} != Silver distinct invoices {silver_orders:,}."
    )
    return CheckResult(
        "G2", "Order Count Reconciliation", GOLD, status,
        observed=gold_orders, expected=silver_orders, detail=detail,
        evidence_query=f"SELECT COUNT(DISTINCT {order_id_expression}) FROM silver_orders",
    )


def g3_customer_count_reconciliation(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
    cust_col = cfg.columns.customer_id if cfg else "customer_id"
    cust_metric = cfg.metrics.total_customers_metric if cfg else "total_customers"
    silver_customers = int(
        loader.scalar(f"SELECT COUNT(DISTINCT {cust_col}) FROM silver_orders") or 0
    )
    gold_customers = int(loader.scalar(f"SELECT {cust_metric} FROM gold_metrics") or 0)
    match = silver_customers == gold_customers
    status = PASS if match else FAIL
    detail = (
        f"Gold {cust_metric} reconciles with Silver."
        if match
        else f"Gold customers {gold_customers:,} != Silver distinct {silver_customers:,}."
    )
    return CheckResult(
        "G3", "Customer Count Reconciliation", GOLD, status,
        observed=gold_customers, expected=silver_customers, detail=detail,
        evidence_query=f"SELECT COUNT(DISTINCT {cust_col}) FROM silver_orders",
    )


def g4_average_order_value(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
    rev_metric = cfg.metrics.total_revenue_metric if cfg else "total_revenue"
    orders_metric = cfg.metrics.total_orders_metric if cfg else "total_orders"
    aov_metric = cfg.metrics.average_order_value_metric if cfg else "average_order_value"
    row = loader.query(
        f"SELECT {rev_metric}, {orders_metric}, {aov_metric} FROM gold_metrics"
    ).to_dict("records")[0]
    orders = float(row[orders_metric] or 0)
    recomputed = float(row[rev_metric]) / orders if orders else 0.0
    gold_aov = float(row[aov_metric] or 0)
    match = abs(recomputed - gold_aov) <= AOV_TOLERANCE
    status = PASS if match else FAIL
    detail = (
        f"Gold AOV reconciles (recomputed {recomputed:,.2f})."
        if match
        else f"Gold AOV {gold_aov:,.2f} != recomputed {recomputed:,.2f}."
    )
    return CheckResult(
        "G4", "Average Order Value Check", GOLD, status,
        observed=gold_aov, expected=round(recomputed, 2), detail=detail,
        evidence_query=f"SELECT {rev_metric} / {orders_metric} FROM gold_metrics",
    )


def g5_revenue_vs_baseline(
    loader: DataLoader, upstream_status: Optional[str] = None, cfg: Optional[AurumDatasetConfig] = None
) -> CheckResult:
    revenue_metric = cfg.metrics.total_revenue_metric if cfg else "total_revenue"
    revenue_col = cfg.columns.revenue if cfg else "net_revenue"
    gold_rev = float(loader.scalar(f"SELECT {revenue_metric} FROM gold_metrics") or 0)
    silver_rev = float(loader.scalar(f"SELECT SUM({revenue_col}) FROM silver_orders") or 0)
    gold_math_correct = abs(silver_rev - gold_rev) <= REVENUE_ROUNDING_TOLERANCE

    stats = column_stats(_history(loader), "gold_revenue")
    if not stats or stats["std"] == 0:
        return CheckResult(
            "G5", "Revenue vs Expected Baseline", GOLD, WARN,
            observed=gold_rev, expected="no baseline available",
            detail="No historical revenue baseline to compare against.",
            evidence_query=f"SELECT {revenue_metric} FROM gold_metrics",
        )

    band = tolerance_band(stats, k=3.0)
    expected = stats["mean"]
    impact = expected - gold_rev
    within = band["lower"] <= gold_rev <= band["upper"]

    if within:
        status, detail = PASS, "Gold revenue is within the expected baseline range."
    elif not gold_math_correct:
        status = FAIL
        detail = "Gold revenue is wrong and does not reconcile with Silver."
    elif gold_rev < band["lower"] and upstream_status in (FAIL, IMPACTED, WARN):
        status = IMPACTED
        detail = (
            f"Gold math is correct, but revenue is {impact:,.0f} below the expected "
            "baseline -- impacted by an upstream layer failure."
        )
    elif gold_rev < band["lower"]:
        status = WARN
        detail = (
            f"Gold revenue is {impact:,.0f} below baseline, but no upstream failure "
            "was established; review as a business anomaly."
        )
    else:
        status, detail = WARN, "Gold revenue is mildly above the expected baseline."

    return CheckResult(
        "G5", "Revenue vs Expected Baseline", GOLD, status,
        observed=gold_rev, expected=round(expected, 0), detail=detail,
        evidence_query=f"SELECT {revenue_metric} FROM gold_metrics",
        extra={"expected_revenue": round(expected, 0),
               "actual_revenue": gold_rev,
               "impact": round(impact, 0),
               "gold_math_correct": gold_math_correct},
    )


def g6_country_revenue_reconciliation(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
    geo_col = cfg.columns.geography if cfg else "country"
    rev_col = cfg.columns.revenue if cfg else "net_revenue"
    agg_rev = cfg.metrics.aggregate_revenue_metric if cfg else "revenue"
    if not loader.table_exists("gold_country_revenue"):
        return CheckResult(
            "G6", "Country-wise Revenue Reconciliation", GOLD, WARN,
            observed="n/a", expected="n/a",
            detail="No gold_country_revenue table to reconcile.",
            evidence_query="",
        )
    mismatch = int(
        loader.scalar(
            f"""
            WITH silver_by_country AS (
                SELECT {geo_col}, SUM({rev_col}) AS revenue
                FROM silver_orders GROUP BY {geo_col}
            )
            SELECT COUNT(*) FROM gold_country_revenue g
            FULL OUTER JOIN silver_by_country s ON g.{geo_col} = s.{geo_col}
            WHERE ABS(COALESCE(g.revenue, 0) - COALESCE(s.revenue, 0)) > 1.0
            """
        )
    )
    status = PASS if mismatch == 0 else FAIL
    detail = (
        "Country-wise revenue reconciles with Silver."
        if mismatch == 0
        else f"{mismatch} countries have mismatched revenue."
    )
    return CheckResult(
        "G6", "Country-wise Revenue Reconciliation", GOLD, status,
        observed=mismatch, expected=0, detail=detail,
        evidence_query=f"SELECT {geo_col}, SUM({rev_col}) FROM silver_orders GROUP BY {geo_col}",
    )


def g7_metrics_cardinality(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
    n = int(loader.scalar("SELECT COUNT(*) FROM gold_metrics") or 0)
    status = PASS if n == 1 else FAIL
    detail = (
        "Gold metrics table has exactly one aggregate row."
        if n == 1
        else f"Gold metrics table has {n:,} rows; expected exactly 1."
    )
    return CheckResult(
        "G7", "Gold Metrics Row Cardinality", GOLD, status,
        observed=n, expected=1, detail=detail,
        evidence_query="SELECT COUNT(*) FROM gold_metrics",
    )


def g8_mandatory_metrics_not_null(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
    gold_mandatory = [
        cfg.metrics.total_revenue_metric,
        cfg.metrics.total_orders_metric,
        cfg.metrics.total_customers_metric,
        cfg.metrics.average_order_value_metric,
    ] if cfg else [
        "total_revenue",
        "total_orders",
        "total_customers",
        "average_order_value",
    ]
    cols = loader.columns("gold_metrics")
    null_counts = {}
    for col in gold_mandatory:
        if col in cols:
            null_counts[col] = int(
                loader.scalar(f"SELECT COUNT(*) FROM gold_metrics WHERE {col} IS NULL")
            )
    total = sum(null_counts.values())
    status = PASS if total == 0 else FAIL
    detail = (
        "All mandatory Gold metric columns are non-null."
        if total == 0
        else f"Gold metrics contain nulls: {null_counts}."
    )
    rev_metric = cfg.metrics.total_revenue_metric if cfg else "total_revenue"
    return CheckResult(
        "G8", "Mandatory Gold Metrics Not Null", GOLD, status,
        observed=null_counts, expected={c: 0 for c in null_counts}, detail=detail,
        evidence_query=f"SELECT COUNT(*) FROM gold_metrics WHERE {rev_metric} IS NULL",
    )


def g9_revenue_per_customer(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
    revenue_col = cfg.columns.revenue if cfg else "net_revenue"
    customer_col = cfg.columns.customer_id if cfg else "customer_id"
    revenue_metric = cfg.metrics.total_revenue_metric if cfg else "total_revenue"
    customers_metric = cfg.metrics.total_customers_metric if cfg else "total_customers"
    silver_rpc = float(
        loader.scalar(
            f"""
            SELECT SUM({revenue_col})::DOUBLE
                 / NULLIF(COUNT(DISTINCT {customer_col}), 0)
            FROM silver_orders
            """
        )
        or 0
    )
    gold_rpc = float(
        loader.scalar(
            f"""
            SELECT {revenue_metric}::DOUBLE
                 / NULLIF({customers_metric}, 0)
            FROM gold_metrics
            """
        )
        or 0
    )
    diff = abs(silver_rpc - gold_rpc)
    match = diff <= RPC_TOLERANCE
    status = PASS if match else FAIL
    detail = (
        f"Gold revenue-per-customer reconciles with Silver (diff {diff:.4f})."
        if match
        else (
            f"Gold RPC {gold_rpc:,.2f} != Silver RPC {silver_rpc:,.2f} "
            f"(diff {diff:.4f} > tolerance {RPC_TOLERANCE})."
        )
    )
    return CheckResult(
        "G9", "Revenue per Customer Reconciliation", GOLD, status,
        observed={"gold_rpc": round(gold_rpc, 2), "difference": round(diff, 4)},
        expected={"silver_rpc": round(silver_rpc, 2)},
        detail=detail,
        evidence_query=(
            f"SELECT {revenue_metric} / NULLIF({customers_metric}, 0) FROM gold_metrics"
        ),
    )


def g10_country_coverage(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:
    geo_col = cfg.columns.geography if cfg else "country"
    if not loader.table_exists("gold_country_revenue"):
        return CheckResult(
            "G10", "Country Coverage Reconciliation", GOLD, WARN,
            observed="n/a", expected="n/a",
            detail="No gold_country_revenue table to reconcile country coverage.",
            evidence_query="",
        )
    silver_countries = int(
        loader.scalar(f"SELECT COUNT(DISTINCT {geo_col}) FROM silver_orders") or 0
    )
    gold_countries = int(
        loader.scalar("SELECT COUNT(*) FROM gold_country_revenue") or 0
    )
    match = silver_countries == gold_countries
    status = PASS if match else FAIL
    detail = (
        "Gold country coverage matches Silver distinct countries."
        if match
        else (
            f"Silver has {silver_countries:,} countries but "
            f"gold_country_revenue has {gold_countries:,} rows."
        )
    )
    return CheckResult(
        "G10", "Country Coverage Reconciliation", GOLD, status,
        observed=gold_countries, expected=silver_countries, detail=detail,
        evidence_query=f"SELECT COUNT(DISTINCT {geo_col}) FROM silver_orders",
    )


def validate_gold(
    loader: DataLoader, upstream_status: Optional[str] = None
) -> list[CheckResult]:
    cfg = load_dataset_config()
    return run_checks(
        [
            Check(lambda: g1_revenue_reconciliation(loader, cfg), "G1", "Revenue Reconciliation (within rounding tolerance)", GOLD),
            Check(lambda: g2_order_count_reconciliation(loader, cfg), "G2", "Order Count Reconciliation", GOLD),
            Check(lambda: g3_customer_count_reconciliation(loader, cfg), "G3", "Customer Count Reconciliation", GOLD),
            Check(lambda: g4_average_order_value(loader, cfg), "G4", "Average Order Value Check", GOLD),
            Check(lambda: g5_revenue_vs_baseline(loader, upstream_status=upstream_status, cfg=cfg), "G5", "Revenue vs Expected Baseline", GOLD),
            Check(lambda: g6_country_revenue_reconciliation(loader, cfg), "G6", "Country-wise Revenue Reconciliation", GOLD),
            Check(lambda: g7_metrics_cardinality(loader, cfg), "G7", "Gold Metrics Row Cardinality", GOLD),
            Check(lambda: g8_mandatory_metrics_not_null(loader, cfg), "G8", "Mandatory Gold Metrics Not Null", GOLD),
            Check(lambda: g9_revenue_per_customer(loader, cfg), "G9", "Revenue per Customer Reconciliation", GOLD),
            Check(lambda: g10_country_coverage(loader, cfg), "G10", "Country Coverage Reconciliation", GOLD),
        ]
    )


if __name__ == "__main__":
    from .silver_validator import validate_silver
    from .verdict_engine import compute_layer_status

    loader = DataLoader()
    silver_status = compute_layer_status(validate_silver(loader))
    for result in validate_gold(loader, upstream_status=silver_status):
        print(result.status, result.check_id, result.detail)
