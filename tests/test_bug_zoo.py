"""Bug zoo — prove Pain-1 layers catch unanticipated bugs (no bug-specific checks)."""

import pandas as pd
import pytest

from builders import gold_from_silver, historical_df, loader_from, make_rows, to_df, to_silver

from src.bug_zoo import (
    assert_caught,
    flagged_checks,
    plant_duplicate_batch,
    plant_inflate_price,
    plant_null_keys,
    plant_orphan_payments,
    plant_random_row_drop,
    plant_scale_quantities,
    run_zoo_case,
)
from src.contracts import DETECTION_LAYER_1, DETECTION_LAYER_2, DETECTION_LAYER_3
from src.report_builder import build_report


def _healthy_loader(n: int = 100) -> "DataLoader":
    bronze = make_rows(n)
    silver = to_silver(bronze)
    gold = gold_from_silver(silver)
    revenue = float(silver["net_revenue"].sum())
    history = historical_df(
        bronze_counts=[n] * 15,
        drop_pcts=[0.0] * 15,
        gold_revenues=[revenue] * 15,
    )
    return loader_from(
        bronze_orders=to_df(bronze),
        silver_orders=silver,
        gold_metrics=gold,
        historical_runs=history,
    )


def test_zoo_random_row_drop_caught_by_reconciliation():
    loader = _healthy_loader(100)
    plant_random_row_drop(loader, fraction=0.3)
    result = run_zoo_case(loader)
    assert_caught(
        result,
        detection_layer=DETECTION_LAYER_2,
        description="random row drop in Silver",
        check_id_prefix="L2-REC-COUNT",
    )


def test_zoo_duplicate_batch_caught_by_uniqueness():
    loader = _healthy_loader(50)
    plant_duplicate_batch(loader, n_dup=10)
    result = run_zoo_case(loader)
    assert_caught(
        result,
        detection_layer=DETECTION_LAYER_1,
        description="duplicate batch in Silver",
    )
    hits = flagged_checks(result, detection_layer=DETECTION_LAYER_1)
    assert any("UNIQ" in c.check_id for c in hits)


def test_zoo_orphan_payments_caught_by_fk_consistency():
    loader = _healthy_loader(50)
    plant_orphan_payments(loader)
    result = run_zoo_case(loader)
    assert_caught(
        result,
        detection_layer=DETECTION_LAYER_1,
        description="orphan payment FK violation",
        check_id_prefix="L1-ORD-CONS-FK-BRON",
    )


def test_zoo_inflate_price_caught_by_revenue_reconciliation():
    loader = _healthy_loader(50)
    plant_inflate_price(loader, factor=2.0)
    result = run_zoo_case(loader)
    assert_caught(
        result,
        detection_layer=DETECTION_LAYER_2,
        description="inflated Silver prices with stale Gold",
        check_id_prefix="L2-REC-REV",
    )


def test_zoo_null_keys_caught_by_completeness():
    loader = _healthy_loader(50)
    plant_null_keys(loader, n=5)
    result = run_zoo_case(loader)
    assert_caught(
        result,
        detection_layer=DETECTION_LAYER_1,
        description="null invoice_no in Silver",
        check_id_prefix="L1-SIL-COMP-NULL",
    )


def test_zoo_scale_quantities_caught_by_robust_anomaly():
    loader = _healthy_loader(100)
    plant_scale_quantities(loader, factor=2.0)
    result = run_zoo_case(loader)
    assert_caught(
        result,
        detection_layer=DETECTION_LAYER_3,
        description="scaled quantities shifting revenue distribution",
        check_id_prefix="L3-ANO-GOLD_R",
    )


def test_demo_bug_still_not_trusted():
    """Original planted demo bug must still produce the same verdict story."""
    from src.data_loader import DataLoader

    report = build_report(DataLoader())
    assert report["layer_status"]["bronze"] == "PASS"
    assert report["layer_status"]["silver"] == "FAIL"
    assert report["layer_status"]["gold"] == "IMPACTED"
    assert report["final_verdict"] == "NOT TRUSTED"
    assert report["first_failed_layer"] == "Bronze \u2192 Silver"
    assert "detection_layers" in report
    l2 = report["detection_layers"]["layer_2_reconciliation"]
    assert any(c["check_id"] == "L2-REC-COUNT" and c["status"] == "FAIL" for c in l2)
