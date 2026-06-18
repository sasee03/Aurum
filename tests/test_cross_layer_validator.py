"""Cross-layer validator tests."""

import pandas as pd
from builders import loader_from, make_rows, to_df

from src.contracts import FAIL, IMPACTED, PASS, WARN
from src.cross_layer_validator import build_business_impact, first_failed_layer

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
