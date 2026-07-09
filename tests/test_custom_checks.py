"""Tests for real custom-check execution (non-SQL types)."""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from src.custom_checks import evaluate_check_on_frame, execute_custom_check
from src.run_demo import run_validation


@pytest.fixture
def client():
    with TestClient(api_main.app) as test_client:
        yield test_client


def _check(**overrides):
    base = {
        "check_id": "custom_silver_001",
        "layer": "silver",
        "check_name": "test",
        "rule_type": "not_null",
        "column": "customer_id",
        "operator": "is",
        "value": "not null",
        "severity": "medium",
        "description": "",
    }
    base.update(overrides)
    return base


def test_not_null_pass_and_fail():
    pass_df = pd.DataFrame({"customer_id": ["A", "B", "C"]})
    fail_df = pd.DataFrame({"customer_id": ["A", None, "  "]})

    passed = evaluate_check_on_frame(_check(rule_type="not_null"), pass_df)
    failed = evaluate_check_on_frame(_check(rule_type="not_null"), fail_df)

    assert passed["status"] == "PASS"
    assert passed["observed_value"] == 0
    assert failed["status"] == "FAIL"
    assert failed["observed_value"] == 2
    assert "2 of 3" in failed["message"]


def test_unique_pass_and_fail():
    pass_df = pd.DataFrame({"invoice_no": ["1", "2", "3"]})
    fail_df = pd.DataFrame({"invoice_no": ["1", "2", "1"]})

    passed = evaluate_check_on_frame(
        _check(rule_type="unique", column="invoice_no"), pass_df
    )
    failed = evaluate_check_on_frame(
        _check(rule_type="unique", column="invoice_no"), fail_df
    )

    assert passed["status"] == "PASS"
    assert passed["observed_value"] == 0
    assert failed["status"] == "FAIL"
    assert failed["observed_value"] == 1


def test_accepted_values_pass_and_fail():
    pass_df = pd.DataFrame({"country": ["UK", "France"]})
    fail_df = pd.DataFrame({"country": ["UK", "Atlantis"]})
    check = _check(
        rule_type="accepted_values",
        column="country",
        operator="in",
        value="UK,France,Germany",
    )

    passed = evaluate_check_on_frame(check, pass_df)
    failed = evaluate_check_on_frame(check, fail_df)

    assert passed["status"] == "PASS"
    assert passed["observed_value"] == 0
    assert failed["status"] == "FAIL"
    assert failed["observed_value"] == 1


def test_numeric_range_pass_and_fail():
    pass_df = pd.DataFrame({"unit_price": [1.0, 5.0, 9.5]})
    fail_df = pd.DataFrame({"unit_price": [1.0, -2.0, 11.0]})
    check = _check(
        rule_type="numeric_range",
        column="unit_price",
        operator="between",
        value="0,10",
    )

    passed = evaluate_check_on_frame(check, pass_df)
    failed = evaluate_check_on_frame(check, fail_df)

    assert passed["status"] == "PASS"
    assert passed["observed_value"] == 0
    assert failed["status"] == "FAIL"
    assert failed["observed_value"] == 2


def test_row_count_condition_pass_and_fail():
    pass_df = pd.DataFrame({"x": [1, 2, 3]})
    fail_df = pd.DataFrame({"x": [1]})
    check = _check(
        rule_type="row_count_condition",
        column="x",
        operator=">",
        value="2",
    )

    passed = evaluate_check_on_frame(check, pass_df)
    failed = evaluate_check_on_frame(check, fail_df)

    assert passed["status"] == "PASS"
    assert passed["observed_value"] == 3
    assert failed["status"] == "FAIL"
    assert failed["observed_value"] == 1


def test_missing_column_returns_skipped():
    df = pd.DataFrame({"customer_id": ["A"]})
    result = evaluate_check_on_frame(
        _check(rule_type="not_null", column="missing_col"), df
    )
    assert result["status"] == "SKIPPED"
    assert "not found" in result["message"].lower()


def test_sql_rule_type_not_executed():
    # Even with a malicious-looking value, SQL checks must never run.
    check = _check(
        rule_type="custom_sql_demo",
        column="customer_id",
        operator="sql",
        value="DROP TABLE silver_orders; SELECT 1",
    )
    result = evaluate_check_on_frame(check, pd.DataFrame({"customer_id": ["A"]}))
    assert result["status"] == "SKIPPED"
    assert "not yet supported" in result["message"].lower()
    assert result["observed_value"] is None


def test_execute_sql_check_skips_without_loading_data(monkeypatch):
    called = {"load": False}

    def _boom(*_a, **_k):
        called["load"] = True
        raise AssertionError("SQL checks must not load data")

    monkeypatch.setattr("src.custom_checks.load_layer_dataframe", _boom)
    result = execute_custom_check(
        _check(rule_type="custom_sql_demo", value="SELECT 1")
    )
    assert result["status"] == "SKIPPED"
    assert called["load"] is False


def test_custom_checks_do_not_change_engine_verdict(monkeypatch):
    """Running custom checks must not alter core report verdict fields."""
    monkeypatch.setattr(
        "src.custom_checks.load_layer_dataframe",
        lambda layer: pd.DataFrame({"x": [1, 2, 3]}),
    )

    before = run_validation(run_id="verdict_before_custom")
    core_before = {
        "trust_score": before["trust_score"],
        "final_verdict": before["final_verdict"],
        "layer_status": before["layer_status"],
    }

    # Separate additive path — must not feed into the next engine run.
    result = execute_custom_check(
        _check(
            check_id="custom_silver_999",
            rule_type="row_count_condition",
            operator=">",
            value="0",
        )
    )
    assert result["status"] == "PASS"

    after = run_validation(run_id="verdict_after_custom")
    core_after = {
        "trust_score": after["trust_score"],
        "final_verdict": after["final_verdict"],
        "layer_status": after["layer_status"],
    }
    assert core_before == core_after
    assert "custom_check" not in after
    assert "custom_check_results" not in after


def test_api_run_returns_real_observed_value(client, monkeypatch):
    sample = _check(
        rule_type="row_count_condition",
        column="discount_applied",
        operator=">",
        value="0",
    )
    monkeypatch.setattr(
        "api.aurum_assistant.router.load_custom_checks",
        lambda: [sample],
    )
    # Avoid full Olist load in this API unit — inject a tiny frame via execute path.
    monkeypatch.setattr(
        "src.custom_checks.load_layer_dataframe",
        lambda layer: pd.DataFrame({"x": [1, 2, 3, 4]}),
    )
    response = client.post("/custom-checks/run", json={"check_id": "custom_silver_001"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert body["observed_value"] == 4
    assert "demo" not in body["message"].lower()
    assert "preview" not in body["message"].lower()


def test_api_sql_check_skipped(client, monkeypatch):
    sample = _check(rule_type="custom_sql_demo", value="SELECT * FROM users")
    monkeypatch.setattr(
        "api.aurum_assistant.router.load_custom_checks",
        lambda: [sample],
    )
    response = client.post("/custom-checks/run", json={"check_id": "custom_silver_001"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SKIPPED"
    assert "not yet supported" in body["message"].lower()
