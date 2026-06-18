"""End-to-end report contract regression test."""

from src.data_loader import DataLoader
from src.report_builder import build_report


def test_demo_report_contract_and_story():
    report = build_report(DataLoader())

    required = {
        "project", "pipeline", "layer_status", "final_verdict",
        "first_failed_layer", "root_cause", "business_impact",
        "suggested_action", "checks",
    }
    assert required <= set(report)
    assert report["layer_status"] == {
        "bronze": "PASS", "silver": "FAIL", "gold": "IMPACTED"
    }
    assert report["final_verdict"] == "NOT TRUSTED"
    assert report["first_failed_layer"] == "Bronze \u2192 Silver"
    assert report["business_impact"]["estimated_loss"] == 4_800_000.0
