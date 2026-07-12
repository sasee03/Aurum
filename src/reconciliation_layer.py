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
from .config_loader import AurumDatasetConfig, load_dataset_config
from .data_loader import DataLoader
from .resilience import Check, run_checks
from .revenue_tolerance import REVENUE_ROUNDING_TOLERANCE, revenue_tolerance_detail


def _valid_row_predicate(cfg: AurumDatasetConfig) -> str:
    return (
        f"{cfg.columns.quantity} > 0 AND {cfg.columns.unit_price} > 0 "
        f"AND {cfg.columns.primary_key} IS NOT NULL AND {cfg.columns.product_id} IS NOT NULL"
    )


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


def rec_count_unexplained_loss(loader: DataLoader, cfg: AurumDatasetConfig | None = None) -> CheckResult:
    """Valid Bronze rows that vanished from Silver without a legitimate reason."""
    cfg = cfg or load_dataset_config()
    valid_predicate = _valid_row_predicate(cfg)
    primary_key = cfg.columns.primary_key
    valid_bronze = int(
        loader.scalar(f"SELECT COUNT(*) FROM bronze_orders WHERE {valid_predicate}")
    )
    silver = loader.count("silver_orders")
    missing_valid = int(
        loader.scalar(
            f"""
            SELECT COUNT(*) FROM bronze_orders b
            WHERE {valid_predicate}
              AND NOT EXISTS (
                SELECT 1 FROM silver_orders s WHERE s.{primary_key} = b.{primary_key}
              )
            """
        )
    )
    # Legitimate removals: invalid rows (qty<=0 or price<=0) never expected in Silver.
    legit_removable = int(
        loader.scalar(
            f"SELECT COUNT(*) FROM bronze_orders WHERE {cfg.columns.quantity} <= 0 "
            f"OR {cfg.columns.unit_price} <= 0"
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
            f"{valid_predicate} AND NOT EXISTS "
            f"(SELECT 1 FROM silver_orders s WHERE s.{primary_key} = b.{primary_key})"
        ),
    )


def rec_revenue(loader: DataLoader, cfg: AurumDatasetConfig | None = None) -> CheckResult:
    """Silver revenue vs Gold total_revenue — within documented rounding tolerance."""
    cfg = cfg or load_dataset_config()
    tolerance = REVENUE_ROUNDING_TOLERANCE
    silver_rev = float(loader.scalar(f"SELECT SUM({cfg.columns.revenue}) FROM silver_orders") or 0)
    gold_rev = float(loader.scalar(f"SELECT {cfg.metrics.total_revenue_metric} FROM gold_metrics") or 0)
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
        sql=f"SELECT SUM({cfg.columns.revenue}) FROM silver_orders",
        table="gold_metrics",
        revenue_rounding_tolerance=tolerance,
    )


def rec_key_set(loader: DataLoader, cfg: AurumDatasetConfig | None = None) -> CheckResult:
    """invoice_no in Silver must be subset of Bronze; Gold orders <= Silver orders."""
    cfg = cfg or load_dataset_config()
    primary_key = cfg.columns.primary_key
    business_key = cfg.columns.resolve_business_key()
    silver_not_in_bronze = int(
        loader.scalar(
            f"""
            SELECT COUNT(*) FROM silver_orders s
            WHERE NOT EXISTS (
                SELECT 1 FROM bronze_orders b WHERE b.{primary_key} = s.{primary_key}
            )
            """
        )
    )
    silver_distinct = int(
        loader.scalar(
            f"SELECT COUNT(DISTINCT {business_key}) FROM silver_orders"
        )
    )
    gold_orders = int(loader.scalar(f"SELECT {cfg.metrics.total_orders_metric} FROM gold_metrics") or 0)
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
            f"(SELECT 1 FROM bronze_orders b WHERE b.{primary_key} = s.{primary_key})"
        ),
    )


def rec_aggregate_crosscheck(loader: DataLoader, cfg: AurumDatasetConfig | None = None) -> CheckResult:
    """Recompute all Gold aggregates from Silver and compare."""
    cfg = cfg or load_dataset_config()
    silver = loader.query(
        f"""
        SELECT
            SUM({cfg.columns.revenue}) AS revenue,
            COUNT(DISTINCT {cfg.columns.resolve_business_key()}) AS orders,
            COUNT(DISTINCT {cfg.columns.customer_id}) AS customers
        FROM silver_orders
        """
    ).to_dict("records")[0]
    gold = loader.query(
        f"SELECT {cfg.metrics.total_revenue_metric} AS total_revenue, "
        f"{cfg.metrics.total_orders_metric} AS total_orders, "
        f"{cfg.metrics.total_customers_metric} AS total_customers FROM gold_metrics"
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
            f"SELECT SUM({cfg.columns.revenue}), COUNT(DISTINCT {cfg.columns.resolve_business_key()}), "
            f"COUNT(DISTINCT {cfg.columns.customer_id}) FROM silver_orders"
        ),
        table="gold_metrics",
    )


def run_reconciliation_layer(loader: DataLoader) -> list[CheckResult]:
    cfg = load_dataset_config()
    checks: list[Check] = []
    if loader.table_exists("bronze_orders") and loader.table_exists("silver_orders"):
        checks.append(Check(lambda: rec_count_unexplained_loss(loader, cfg), "L2-REC-COUNT", "Count Reconciliation: Unexplained Valid Row Loss", SILVER))
        checks.append(Check(lambda: rec_key_set(loader, cfg), "L2-REC-KEY", "Key-Set Reconciliation", SILVER))
    if loader.table_exists("silver_orders") and loader.table_exists("gold_metrics"):
        checks.append(Check(lambda: rec_revenue(loader, cfg), "L2-REC-REV", "Revenue Reconciliation", GOLD))
        checks.append(Check(lambda: rec_aggregate_crosscheck(loader, cfg), "L2-REC-AGG", "Aggregate Cross-Check", GOLD))
    return run_checks(checks)
