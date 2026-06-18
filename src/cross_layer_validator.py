"""Cross-layer validation (X1-X6).

These checks reason across layer boundaries: they reuse the per-layer check
results to assess each transition, locate the first failed layer, build the root
cause from failed Silver checks, and quantify business impact from the data.
"""

from __future__ import annotations

from typing import Optional

from .contracts import (
    BRONZE,
    CROSS_LAYER,
    CheckResult,
    FAIL,
    IMPACTED,
    PASS,
    SILVER,
    WARN,
)
from .data_loader import DataLoader

VALID_BRONZE_PREDICATE = "quantity > 0 AND unit_price > 0"


def _by_id(results: list[CheckResult], check_id: str) -> Optional[CheckResult]:
    for r in results:
        if r.check_id == check_id:
            return r
    return None


def _rollup(results: list[CheckResult], ids: list[str]) -> str:
    statuses = [r.status for r in results if r.check_id in ids]
    if FAIL in statuses:
        return FAIL
    if IMPACTED in statuses:
        return IMPACTED
    if WARN in statuses:
        return WARN
    return PASS


def x1_source_to_bronze(bronze_results: list[CheckResult]) -> CheckResult:
    status = _rollup(bronze_results, ["B1", "B3"])
    b1 = _by_id(bronze_results, "B1")
    detail = b1.detail if b1 else "Source-to-Bronze completeness evaluated."
    return CheckResult(
        "X1", "Source to Bronze Completeness", CROSS_LAYER, status,
        observed=status, expected=PASS, detail=detail,
    )


def x2_bronze_to_silver(silver_results: list[CheckResult]) -> CheckResult:
    ids = ["S1", "S8", "S9", "S10"]
    status = _rollup(silver_results, ids)
    failed = [r.check_id for r in silver_results if r.check_id in ids and r.status == FAIL]
    detail = (
        "Bronze-to-Silver transformation quality is sound."
        if status == PASS
        else f"Transformation quality issues in checks: {failed}."
    )
    return CheckResult(
        "X2", "Bronze to Silver Transformation Quality", CROSS_LAYER, status,
        observed=status, expected=PASS, detail=detail,
    )


def x3_silver_to_gold(gold_results: list[CheckResult]) -> CheckResult:
    ids = ["G1", "G2", "G3", "G4", "G6"]
    status = _rollup(gold_results, ids)
    detail = (
        "Silver-to-Gold metrics reconcile correctly."
        if status == PASS
        else "Silver-to-Gold metric reconciliation found mismatches."
    )
    return CheckResult(
        "X3", "Silver to Gold Metric Correctness", CROSS_LAYER, status,
        observed=status, expected=PASS, detail=detail,
    )


def first_failed_layer(layer_status: dict) -> Optional[str]:
    if layer_status.get("bronze") == FAIL:
        return "Source \u2192 Bronze"
    if layer_status.get("silver") == FAIL:
        return "Bronze \u2192 Silver"
    if layer_status.get("gold") == FAIL:
        return "Silver \u2192 Gold"
    # Gold only impacted because an upstream layer degraded it.
    if layer_status.get("gold") == IMPACTED and layer_status.get("silver") != PASS:
        return "Bronze \u2192 Silver"
    return None


def x4_first_failed_layer(layer_status: dict) -> CheckResult:
    layer = first_failed_layer(layer_status)
    status = PASS if layer is None else FAIL
    detail = (
        "No failed layer detected." if layer is None
        else f"First failed transition: {layer}."
    )
    return CheckResult(
        "X4", "First Failed Layer Locator", CROSS_LAYER, status,
        observed=layer, expected=None, detail=detail,
    )


def build_root_cause(silver_results: list[CheckResult]) -> dict:
    failed = [r for r in silver_results if r.status == FAIL]
    failed_ids = [r.check_id for r in failed]
    s8 = _by_id(silver_results, "S8")
    s9 = _by_id(silver_results, "S9")
    s10 = _by_id(silver_results, "S10")

    if s8 and s8.status == FAIL:
        worst_segment = None
        if s9 and s9.extra.get("segments"):
            worst_segment = s9.extra["segments"][0].get("segment")
        if worst_segment and "quantity >" in str(worst_segment):
            summary = (
                "Valid high-quantity orders were wrongly removed during the Silver "
                "transformation."
            )
        else:
            summary = (
                "Valid business records were wrongly removed during the Silver "
                "transformation."
            )
    elif failed:
        summary = f"Silver transformation failed checks {failed_ids}."
    else:
        summary = "No failing transformation detected."

    evidence = [
        {
            "check_id": r.check_id,
            "detail": r.detail,
            "evidence_query": r.evidence_query,
        }
        for r in failed
    ]
    suspected_filter = s10.extra.get("suspected_filter") if s10 else None
    return {
        "summary": summary,
        "failed_check_ids": failed_ids,
        "suspected_filter": suspected_filter,
        "evidence": evidence,
    }


def build_business_impact(loader: DataLoader) -> dict:
    expected = loader.scalar(
        f"SELECT COALESCE(SUM(quantity * unit_price), 0) "
        f"FROM bronze_orders WHERE {VALID_BRONZE_PREDICATE}"
    )
    actual = loader.scalar("SELECT COALESCE(total_revenue, 0) FROM gold_metrics")

    if expected is None or actual is None:
        return {
            "status": "NOT_AVAILABLE",
            "detail": "Expected baseline not available.",
        }

    expected = float(expected)
    actual = float(actual)
    loss = expected - actual
    loss_pct = (loss / expected * 100) if expected else 0.0
    return {
        "expected_revenue": round(expected, 2),
        "actual_revenue": round(actual, 2),
        "estimated_loss": round(loss, 2),
        "loss_percent": round(loss_pct, 2),
        "detail": (
            "Expected revenue is the revenue of all valid Bronze records; actual is "
            "current Gold revenue. The gap is the value lost to dropped valid records."
        ),
    }


def validate_cross_layer(
    bronze_results: list[CheckResult],
    silver_results: list[CheckResult],
    gold_results: list[CheckResult],
    layer_status: dict,
) -> list[CheckResult]:
    return [
        x1_source_to_bronze(bronze_results),
        x2_bronze_to_silver(silver_results),
        x3_silver_to_gold(gold_results),
        x4_first_failed_layer(layer_status),
    ]
