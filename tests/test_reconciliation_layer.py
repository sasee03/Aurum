"""Focused tests for cross-layer reconciliation checks."""

import pytest

from builders import gold_from_silver, loader_from, make_rows, to_df, to_silver

from src.contracts import FAIL, PASS
from src.gold_validator import validate_gold
from src.reconciliation_layer import (
    rec_aggregate_crosscheck,
    rec_key_set,
    run_reconciliation_layer,
)


def _loader_with_gold_order_count(gold_orders: int):
    rows = make_rows(2)
    silver = to_silver(rows)
    gold = gold_from_silver(silver)
    gold.loc[0, "total_orders"] = gold_orders
    gold.loc[0, "average_order_value"] = (
        gold.loc[0, "total_revenue"] / gold_orders if gold_orders else 0.0
    )
    return loader_from(
        bronze_orders=to_df(rows),
        silver_orders=silver,
        gold_metrics=gold,
    )


def test_gold_order_undercount_produces_only_one_failure_via_g2():
    loader = _loader_with_gold_order_count(1)
    results = run_reconciliation_layer(loader) + validate_gold(loader, upstream_status=PASS)

    failures = [result for result in results if result.status == FAIL]
    assert [(result.check_id, result.detail) for result in failures] == [
        ("G2", "Gold orders 1 != Silver distinct invoices 2.")
    ]

    by_id = {result.check_id: result for result in results}
    assert by_id["L2-REC-KEY"].status == PASS
    assert "owned by G2" in by_id["L2-REC-KEY"].detail
    assert by_id["L2-REC-AGG"].status == PASS
    assert "owned by G2" in by_id["L2-REC-AGG"].detail


def test_rec_key_set_still_fails_for_silver_key_missing_from_bronze():
    rows = make_rows(2)
    silver = to_silver(rows)
    loader = loader_from(
        bronze_orders=to_df(rows[:1]),
        silver_orders=silver,
        gold_metrics=gold_from_silver(silver),
    )

    result = rec_key_set(loader)

    assert result.status == FAIL
    assert result.observed["silver_keys_not_in_bronze"] == 1
    assert "Silver keys are not present in Bronze" in result.detail


@pytest.mark.parametrize(
    ("field", "bad_value", "mismatch"),
    [
        ("total_revenue", 0.0, "total_revenue"),
        ("total_customers", 0, "total_customers"),
    ],
)
def test_rec_aggregate_crosscheck_retains_non_order_checks(field, bad_value, mismatch):
    silver = to_silver(make_rows(2))
    gold = gold_from_silver(silver)
    gold.loc[0, field] = bad_value
    loader = loader_from(silver_orders=silver, gold_metrics=gold)

    result = rec_aggregate_crosscheck(loader)

    assert result.status == FAIL
    assert any(
        field.startswith(mismatch) for field in result.observed["mismatched_fields"]
    )
