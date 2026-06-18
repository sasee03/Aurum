"""Gold validator tests."""

import pandas as pd
from builders import gold_from_silver, historical_df, loader_from, make_rows, to_silver

from src.contracts import FAIL, IMPACTED, PASS
from src.gold_validator import (
    g1_revenue_reconciliation,
    g2_order_count_reconciliation,
    g5_revenue_vs_baseline,
)


def test_g1_revenue_matches_passes():
    silver = to_silver(make_rows(10))
    gold = gold_from_silver(silver)
    loader = loader_from(silver_orders=silver, gold_metrics=gold)
    assert g1_revenue_reconciliation(loader).status == PASS


def test_g1_revenue_mismatch_fails():
    silver = to_silver(make_rows(10))
    gold = pd.DataFrame(
        [{"total_revenue": 999.0, "total_orders": 10,
          "total_customers": 10, "average_order_value": 99.9}]
    )
    loader = loader_from(silver_orders=silver, gold_metrics=gold)
    assert g1_revenue_reconciliation(loader).status == FAIL


def test_g2_order_count_mismatch_fails():
    silver = to_silver(make_rows(10))
    gold = gold_from_silver(silver)
    gold.loc[0, "total_orders"] = 999
    loader = loader_from(silver_orders=silver, gold_metrics=gold)
    assert g2_order_count_reconciliation(loader).status == FAIL


def test_g5_impacted_when_below_baseline():
    silver = to_silver(make_rows(10))          # revenue = 100, gold math correct
    gold = gold_from_silver(silver)
    historical = historical_df(
        bronze_counts=[100] * 5,
        drop_pcts=[5, 5, 5, 5, 5],
        gold_revenues=[1000, 1010, 990, 1005, 995],  # baseline ~1000, std > 0
    )
    loader = loader_from(
        silver_orders=silver, gold_metrics=gold, historical_runs=historical
    )
    assert g5_revenue_vs_baseline(loader).status == IMPACTED
