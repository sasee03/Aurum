"""Gold layer quality checks (G1-G6).

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

AOV_TOLERANCE = 0.01


def _history(loader: DataLoader) -> Optional[pd.DataFrame]:
    if loader.table_exists("historical_runs"):
        return loader.query("SELECT * FROM historical_runs")
    return None


def g1_revenue_reconciliation(loader: DataLoader) -> CheckResult:
    tolerance = REVENUE_ROUNDING_TOLERANCE
    silver_rev = float(loader.scalar("SELECT SUM(net_revenue) FROM silver_orders") or 0)
    gold_rev = float(loader.scalar("SELECT total_revenue FROM gold_metrics") or 0)
    diff = abs(silver_rev - gold_rev)
    match = diff <= tolerance
    tol_note = revenue_tolerance_detail(tolerance)
    status = PASS if match else FAIL
    detail = (
        f"Gold total_revenue reconciles with Silver ({tol_note})."
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
        evidence_query="SELECT SUM(net_revenue) FROM silver_orders",
        extra={"revenue_rounding_tolerance": tolerance},
    )


def g2_order_count_reconciliation(loader: DataLoader) -> CheckResult:
    silver_orders = int(
        loader.scalar("SELECT COUNT(DISTINCT invoice_no) FROM silver_orders") or 0
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
        evidence_query="SELECT COUNT(DISTINCT invoice_no) FROM silver_orders",
    )


def g3_customer_count_reconciliation(loader: DataLoader) -> CheckResult:
    silver_customers = int(
        loader.scalar("SELECT COUNT(DISTINCT customer_id) FROM silver_orders") or 0
    )
    gold_customers = int(loader.scalar("SELECT total_customers FROM gold_metrics") or 0)
    match = silver_customers == gold_customers
    status = PASS if match else FAIL
    detail = (
        "Gold total_customers reconciles with Silver."
        if match
        else f"Gold customers {gold_customers:,} != Silver distinct {silver_customers:,}."
    )
    return CheckResult(
        "G3", "Customer Count Reconciliation", GOLD, status,
        observed=gold_customers, expected=silver_customers, detail=detail,
        evidence_query="SELECT COUNT(DISTINCT customer_id) FROM silver_orders",
    )


def g4_average_order_value(loader: DataLoader) -> CheckResult:
    row = loader.query(
        "SELECT total_revenue, total_orders, average_order_value FROM gold_metrics"
    ).to_dict("records")[0]
    orders = float(row["total_orders"] or 0)
    recomputed = float(row["total_revenue"]) / orders if orders else 0.0
    gold_aov = float(row["average_order_value"] or 0)
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
        evidence_query="SELECT total_revenue / total_orders FROM gold_metrics",
    )


def g5_revenue_vs_baseline(
    loader: DataLoader, upstream_status: Optional[str] = None
) -> CheckResult:
    gold_rev = float(loader.scalar("SELECT total_revenue FROM gold_metrics") or 0)
    silver_rev = float(loader.scalar("SELECT SUM(net_revenue) FROM silver_orders") or 0)
    gold_math_correct = abs(silver_rev - gold_rev) <= REVENUE_ROUNDING_TOLERANCE

    stats = column_stats(_history(loader), "gold_revenue")
    if not stats or stats["std"] == 0:
        return CheckResult(
            "G5", "Revenue vs Expected Baseline", GOLD, WARN,
            observed=gold_rev, expected="no baseline available",
            detail="No historical revenue baseline to compare against.",
            evidence_query="SELECT total_revenue FROM gold_metrics",
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
        evidence_query="SELECT total_revenue FROM gold_metrics",
        extra={"expected_revenue": round(expected, 0),
               "actual_revenue": gold_rev,
               "impact": round(impact, 0),
               "gold_math_correct": gold_math_correct},
    )


def g6_country_revenue_reconciliation(loader: DataLoader) -> CheckResult:
    if not loader.table_exists("gold_country_revenue"):
        return CheckResult(
            "G6", "Country-wise Revenue Reconciliation", GOLD, WARN,
            observed="n/a", expected="n/a",
            detail="No gold_country_revenue table to reconcile.",
            evidence_query="",
        )
    mismatch = int(
        loader.scalar(
            """
            WITH silver_by_country AS (
                SELECT country, SUM(net_revenue) AS revenue
                FROM silver_orders GROUP BY country
            )
            SELECT COUNT(*) FROM gold_country_revenue g
            FULL OUTER JOIN silver_by_country s ON g.country = s.country
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
        evidence_query="SELECT country, SUM(net_revenue) FROM silver_orders GROUP BY country",
    )


def validate_gold(
    loader: DataLoader, upstream_status: Optional[str] = None
) -> list[CheckResult]:
    return run_checks(
        [
            Check(lambda: g1_revenue_reconciliation(loader), "G1", "Revenue Reconciliation (within rounding tolerance)", GOLD),
            Check(lambda: g2_order_count_reconciliation(loader), "G2", "Order Count Reconciliation", GOLD),
            Check(lambda: g3_customer_count_reconciliation(loader), "G3", "Customer Count Reconciliation", GOLD),
            Check(lambda: g4_average_order_value(loader), "G4", "Average Order Value Check", GOLD),
            Check(lambda: g5_revenue_vs_baseline(loader, upstream_status=upstream_status), "G5", "Revenue vs Expected Baseline", GOLD),
            Check(lambda: g6_country_revenue_reconciliation(loader), "G6", "Country-wise Revenue Reconciliation", GOLD),
        ]
    )


if __name__ == "__main__":
    from .silver_validator import validate_silver
    from .verdict_engine import compute_layer_status

    loader = DataLoader()
    silver_status = compute_layer_status(validate_silver(loader))
    for result in validate_gold(loader, upstream_status=silver_status):
        print(result.status, result.check_id, result.detail)
