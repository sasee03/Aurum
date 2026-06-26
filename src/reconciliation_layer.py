"""Layer 2 — Reconciliation: cross-layer equalities (Pain 1 key layer).

Count and key-set checks use exact integer equality. Revenue reconciliation
allows a named rounding tolerance — see revenue_tolerance.py.
"""

from __future__ import annotations

from typing import Any

from .contracts import (
    ACCURACY,
    COMPLETENESS,
    CONSISTENCY,
    GOLD,
    SILVER,
    DETECTION_LAYER_2,
    CheckResult,
    FAIL,
    PASS,
)
from .data_loader import DataLoader
from .revenue_tolerance import REVENUE_ROUNDING_TOLERANCE, revenue_tolerance_detail
from .table_specs import VALID_ROW_PREDICATE


def _result(
    check_id: str,
    check_name: str,
    layer: str,
    dimension: str,
    status: str,
    observed: Any,
    expected: Any,
    detail: str,
    sql: str,
    **extra: Any,
) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        check_name=check_name,
        layer=layer,
        status=status,
        observed=observed,
        expected=expected,
        detail=detail,
        evidence_query=sql,
        extra={
            "dimension": dimension,
            "detection_layer": DETECTION_LAYER_2,
            **extra,
        },
    )


def rec_count_unexplained_loss(loader: DataLoader) -> CheckResult:
    """Valid Bronze rows that vanished from Silver without a legitimate reason."""
    valid_bronze = int(
        loader.scalar(f"SELECT COUNT(*) FROM bronze_orders WHERE {VALID_ROW_PREDICATE}")
    )
    silver = loader.count("silver_orders")
    missing_valid = int(
        loader.scalar(
            f"""
            SELECT COUNT(*) FROM bronze_orders b
            WHERE {VALID_ROW_PREDICATE}
              AND NOT EXISTS (
                SELECT 1 FROM silver_orders s WHERE s.invoice_no = b.invoice_no
              )
            """
        )
    )
    # Legitimate removals: invalid rows (qty<=0 or price<=0) never expected in Silver.
    legit_removable = int(
        loader.scalar(
            "SELECT COUNT(*) FROM bronze_orders "
            "WHERE quantity <= 0 OR unit_price <= 0"
        )
    )
    bronze_total = loader.count("bronze_orders")
    explained_drop = legit_removable
    unexplained = missing_valid
    status = PASS if unexplained == 0 else FAIL
    return _result(
        "L2-REC-COUNT",
        "Count Reconciliation: Unexplained Valid Row Loss",
        SILVER, COMPLETENESS, status,
        observed={
            "bronze_total": bronze_total,
            "bronze_valid": valid_bronze,
            "silver_count": silver,
            "missing_valid": missing_valid,
            "explained_removals": explained_drop,
            "unexplained_loss": unexplained,
        },
        expected={"unexplained_loss": 0},
        detail=(
            "All valid Bronze rows accounted for in Silver."
            if status == PASS
            else (
                f"{unexplained:,} valid Bronze rows missing from Silver "
                f"({explained_drop:,} invalid rows legitimately removed)."
            )
        ),
        sql=(
            "SELECT COUNT(*) FROM bronze_orders b WHERE "
            f"{VALID_ROW_PREDICATE} AND NOT EXISTS "
            "(SELECT 1 FROM silver_orders s WHERE s.invoice_no = b.invoice_no)"
        ),
    )


def rec_revenue(loader: DataLoader) -> CheckResult:
    """Silver revenue vs Gold total_revenue — within documented rounding tolerance."""
    tolerance = REVENUE_ROUNDING_TOLERANCE
    silver_rev = float(loader.scalar("SELECT SUM(net_revenue) FROM silver_orders") or 0)
    gold_rev = float(loader.scalar("SELECT total_revenue FROM gold_metrics") or 0)
    diff = abs(silver_rev - gold_rev)
    status = PASS if diff <= tolerance else FAIL
    tol_note = revenue_tolerance_detail(tolerance)
    return _result(
        "L2-REC-REV",
        "Revenue Reconciliation: Silver SUM vs Gold (within rounding tolerance)",
        GOLD, ACCURACY, status,
        observed={
            "silver_revenue": silver_rev,
            "gold_revenue": gold_rev,
            "difference": diff,
            "revenue_rounding_tolerance": tolerance,
        },
        expected={"difference": f"<= {tolerance} ({tol_note})"},
        detail=(
            f"Silver revenue reconciles with Gold ({tol_note})."
            if status == PASS
            else (
                f"Revenue mismatch: Silver={silver_rev:,.2f}, Gold={gold_rev:,.2f}, "
                f"diff={diff:,.2f} exceeds tolerance {tolerance}."
            )
        ),
        sql="SELECT SUM(net_revenue) FROM silver_orders",
        table="gold_metrics",
        revenue_rounding_tolerance=tolerance,
    )


def rec_key_set(loader: DataLoader) -> CheckResult:
    """invoice_no in Silver must be subset of Bronze; Gold orders <= Silver orders."""
    silver_not_in_bronze = int(
        loader.scalar(
            """
            SELECT COUNT(*) FROM silver_orders s
            WHERE NOT EXISTS (
                SELECT 1 FROM bronze_orders b WHERE b.invoice_no = s.invoice_no
            )
            """
        )
    )
    silver_distinct = int(
        loader.scalar("SELECT COUNT(DISTINCT invoice_no) FROM silver_orders")
    )
    gold_orders = int(loader.scalar("SELECT total_orders FROM gold_metrics") or 0)
    gold_excess = gold_orders - silver_distinct
    violations = silver_not_in_bronze + max(0, gold_excess)
    status = PASS if violations == 0 else FAIL
    return _result(
        "L2-REC-KEY",
        "Key-Set Reconciliation: Bronze ⊇ Silver, Silver ⊇ Gold keys",
        SILVER, CONSISTENCY, status,
        observed={
            "silver_keys_not_in_bronze": silver_not_in_bronze,
            "silver_distinct_invoices": silver_distinct,
            "gold_total_orders": gold_orders,
            "gold_excess_over_silver": max(0, gold_excess),
        },
        expected={"violations": 0},
        detail=(
            "Key sets are consistent across layers."
            if status == PASS
            else (
                f"Key-set violation: {silver_not_in_bronze} Silver keys not in Bronze, "
                f"Gold orders exceed Silver by {max(0, gold_excess)}."
            )
        ),
        sql=(
            "SELECT COUNT(*) FROM silver_orders s WHERE NOT EXISTS "
            "(SELECT 1 FROM bronze_orders b WHERE b.invoice_no = s.invoice_no)"
        ),
    )


def rec_aggregate_crosscheck(loader: DataLoader) -> CheckResult:
    """Recompute all Gold aggregates from Silver and compare."""
    silver = loader.query(
        """
        SELECT
            SUM(net_revenue) AS revenue,
            COUNT(DISTINCT invoice_no) AS orders,
            COUNT(DISTINCT customer_id) AS customers
        FROM silver_orders
        """
    ).to_dict("records")[0]
    gold = loader.query(
        "SELECT total_revenue, total_orders, total_customers FROM gold_metrics"
    ).to_dict("records")[0]

    mismatches = []
    tol = REVENUE_ROUNDING_TOLERANCE
    rev_diff = abs(float(silver["revenue"]) - float(gold["total_revenue"]))
    if rev_diff > tol:
        mismatches.append(f"total_revenue (diff={rev_diff:.2f}, tolerance={tol})")
    if int(silver["orders"]) != int(gold["total_orders"]):
        mismatches.append("total_orders")
    if int(silver["customers"]) != int(gold["total_customers"]):
        mismatches.append("total_customers")

    status = PASS if not mismatches else FAIL
    return _result(
        "L2-REC-AGG",
        "Aggregate Cross-Check: Recompute Gold from Silver",
        GOLD, ACCURACY, status,
        observed={"silver": silver, "gold": gold, "mismatched_fields": mismatches},
        expected={"mismatched_fields": []},
        detail=(
            "All Gold aggregates match Silver recomputation (revenue within rounding tolerance)."
            if status == PASS
            else f"Aggregate mismatch in: {mismatches}."
        ),
        sql=(
            "SELECT SUM(net_revenue), COUNT(DISTINCT invoice_no), "
            "COUNT(DISTINCT customer_id) FROM silver_orders"
        ),
        table="gold_metrics",
    )


def run_reconciliation_layer(loader: DataLoader) -> list[CheckResult]:
    results = []
    if loader.table_exists("bronze_orders") and loader.table_exists("silver_orders"):
        results.append(rec_count_unexplained_loss(loader))
        results.append(rec_key_set(loader))
    if loader.table_exists("silver_orders") and loader.table_exists("gold_metrics"):
        results.append(rec_revenue(loader))
        results.append(rec_aggregate_crosscheck(loader))
    return results
