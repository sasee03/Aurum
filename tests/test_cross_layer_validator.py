"""Cross-layer validator tests."""

import pandas as pd
from builders import loader_from, make_rows, to_df

from src.contracts import CheckResult, FAIL, GOLD, IMPACTED, PASS, WARN
from src.cross_layer_validator import (
    build_business_impact,
    first_failed_layer,
    x3_silver_to_gold,
)

BRONZE_SILVER = "Bronze \u2192 Silver"
SOURCE_BRONZE = "Source \u2192 Bronze"


def test_first_failed_layer_bronze_to_silver():
    status = {"bronze": PASS, "silver": FAIL, "gold": IMPACTED}
    assert first_failed_layer(status) == BRONZE_SILVER


def test_first_failed_layer_source_to_bronze():
    status = {"bronze": FAIL, "silver": PASS, "gold": PASS}
    assert first_failed_layer(status) == SOURCE_BRONZE


def test_first_failed_layer_gold_impacted_points_upstream():
    status = {"bronze": PASS, "silver": WARN, "gold": IMPACTED}
    assert first_failed_layer(status) == BRONZE_SILVER


def test_first_failed_layer_none_when_all_pass():
    status = {"bronze": PASS, "silver": PASS, "gold": PASS}
    assert first_failed_layer(status) is None


def test_business_impact_computes_loss():
    bronze = make_rows(100)  # 100 valid rows * (1 * 10) = expected 1000
    gold = pd.DataFrame(
        [{"total_revenue": 760.0, "total_orders": 76,
          "total_customers": 76, "average_order_value": 10.0}]
    )
    loader = loader_from(bronze_orders=to_df(bronze), gold_metrics=gold)
    impact = build_business_impact(loader)
    assert impact["expected_revenue"] == 1000.0
    assert impact["actual_revenue"] == 760.0
    assert impact["estimated_loss"] == 240.0


def test_business_impact_treats_null_gold_revenue_as_zero():
    bronze = make_rows(10)
    gold = pd.DataFrame(
        [{"total_revenue": None, "total_orders": 0,
          "total_customers": 0, "average_order_value": 0.0}]
    )
    loader = loader_from(bronze_orders=to_df(bronze), gold_metrics=gold)
    impact = build_business_impact(loader)
    assert impact["actual_revenue"] == 0.0
    assert impact["estimated_loss"] == 100.0


def test_x3_includes_g4_and_g6_reconciliation_failures():
    results = [
        CheckResult("G1", "Revenue", GOLD, PASS, None, None, ""),
        CheckResult("G2", "Orders", GOLD, PASS, None, None, ""),
        CheckResult("G3", "Customers", GOLD, PASS, None, None, ""),
        CheckResult("G4", "AOV", GOLD, FAIL, None, None, ""),
        CheckResult("G6", "Country", GOLD, PASS, None, None, ""),
    ]
    assert x3_silver_to_gold(results).status == FAIL
