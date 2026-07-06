"""End-to-end report contract regression test."""

from src.bronze_validator import validate_bronze
from src.data_loader import DataLoader
from src.gold_validator import validate_gold
from src.report_builder import build_report
from src.silver_validator import validate_silver
from src.verdict_engine import compute_layer_status


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
    assert report["business_impact"]["estimated_loss"] == 13_447_000.57


def test_bronze_returns_exactly_10_checks():
    assert len(validate_bronze(DataLoader())) == 10


def test_silver_returns_exactly_10_checks():
    assert len(validate_silver(DataLoader())) == 10


def test_gold_returns_exactly_10_checks():
    loader = DataLoader()
    silver_status = compute_layer_status(validate_silver(loader))
    assert len(validate_gold(loader, upstream_status=silver_status)) == 10


def test_report_has_10_checks_per_pipeline_layer():
    checks = build_report(DataLoader())["checks"]
    assert len(checks["bronze"]) == 10
    assert len(checks["silver"]) == 10
    assert len(checks["gold"]) == 10


def test_cross_layer_checks_remain_separate():
    checks = build_report(DataLoader())["checks"]
    assert "cross_layer" in checks
    assert len(checks["cross_layer"]) == 4
    pipeline_ids = {
        check["check_id"]
        for layer in ("bronze", "silver", "gold")
        for check in checks[layer]
    }
    cross_ids = {check["check_id"] for check in checks["cross_layer"]}
    assert pipeline_ids.isdisjoint(cross_ids)


def test_demo_verdict_remains_not_trusted():
    report = build_report(DataLoader())
    assert report["final_verdict"] == "NOT TRUSTED"
