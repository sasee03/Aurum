"""Tests for Aurum Assistant API."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import api.main as api_main

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports" / "report.json"
CUSTOM_CHECKS_PATH = ROOT / "data" / "custom_checks" / "custom_checks.json"


@contextmanager
def _reset_last_report():
    previous = api_main._last_report
    api_main._last_report = None
    try:
        yield
    finally:
        api_main._last_report = previous


@pytest.fixture
def client():
    with _reset_last_report():
        with TestClient(api_main.app) as test_client:
            yield test_client


@pytest.fixture
def sample_report():
    if REPORT_PATH.exists():
        return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    return {
        "run_id": "demo_run_001",
        "layer_status": {"bronze": "PASS", "silver": "FAIL", "gold": "IMPACTED"},
        "final_verdict": "NOT TRUSTED",
        "severity": "HIGH",
        "first_failed_layer": "Bronze → Silver",
        "root_cause": {
            "summary": "Valid records were removed during Silver transformation.",
            "suspected_filter": "unit_price > 20.0",
        },
        "business_impact": {
            "expected_revenue": 100.0,
            "actual_revenue": 50.0,
            "estimated_loss": 50.0,
            "loss_percent": 50.0,
            "detail": "Revenue gap from dropped records.",
        },
        "suggested_action": "Fix Silver filter and rerun.",
        "coverage": {},
        "checks": {
            "bronze": [{"check_id": "B1", "observed": 100000, "status": "PASS"}],
            "silver": [
                {
                    "check_id": "S1",
                    "status": "FAIL",
                    "detail": "Drop outside normal range.",
                    "extra": {"bronze": 100000, "silver": 72000},
                }
            ],
            "gold": [],
            "cross_layer": [],
        },
    }


def _chat(client, question: str, **kwargs):
    payload = {
        "page": kwargs.get("page", "validation"),
        "run_id": "latest",
        "layer": kwargs.get("layer"),
        "question": question,
        "context": {},
    }
    return client.post("/aurum-assistant/chat", json=payload)


def test_why_did_silver_fail(client, sample_report):
    api_main._last_report = sample_report
    response = _chat(client, "Why did Silver fail?", layer="silver")
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "validation_explanation"
    assert "silver" in body["answer"].lower() or "Silver" in body["answer"]
    assert body["confidence"] in ("high", "medium", "low")


def test_explain_primary_key_issue(client, sample_report):
    api_main._last_report = sample_report
    response = _chat(client, "Explain primary key issue")
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "primary_key_explanation"
    assert "primary" in body["answer"].lower() or "key" in body["answer"].lower()


def test_explain_timestamp_issue(client, sample_report):
    api_main._last_report = sample_report
    response = _chat(client, "Explain timestamp issue")
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "datetime_explanation"


def test_top_states_revenue(client, sample_report):
    api_main._last_report = sample_report
    response = _chat(client, "Show top 5 states by revenue", page="gold")
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "sample_revenue_query"
    assert "sql" in body["data"]
    assert "silver_orders" in body["data"]["sql"]
    assert "table" in body["data"]
    assert len(body["data"]["table"]) <= 5
    assert "state" in body["data"]["table"][0]
    assert "demo" in body["answer"].lower()


def test_compare_with_history(client, sample_report):
    from src.app_state.store import save_validation_report, save_validation_run

    save_validation_run("history_sqlite_01", status="completed", mode="live")
    save_validation_report(
        "history_sqlite_01",
        {
            "run_id": "history_sqlite_01",
            "final_verdict": "TRUSTED",
            "checks": {
                "bronze": [{"check_id": "B1", "observed": 100000, "status": "PASS"}],
                "silver": [
                    {
                        "check_id": "S1",
                        "status": "PASS",
                        "extra": {"bronze": 100000, "silver": 95000},
                    }
                ],
                "gold": [],
                "cross_layer": [],
            },
        },
    )

    api_main._last_report = sample_report
    response = _chat(client, "Compare this run with history", page="history")
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "history_explanation"
    assert "histor" in body["answer"].lower()
    assert body["data"]["table"][-1]["run_id"] == "history_sqlite_01"


def test_assistant_history_from_sqlite_not_bootstrap_csv():
    """Assistant history must match GET /runs — never historical_runs.csv."""
    from api.aurum_assistant.context import load_history_records
    from src.app_state.store import save_validation_report, save_validation_run

    # Repo ships historical_runs.csv with bootstrap rows; isolated SQLite starts empty.
    assert load_history_records() == []

    save_validation_run("sparse_run_001", status="completed", mode="live")
    save_validation_report(
        "sparse_run_001",
        {
            "run_id": "sparse_run_001",
            "final_verdict": "NOT TRUSTED",
            "trust_score": 40,
            "checks": {
                "bronze": [{"check_id": "B1", "observed": 50000, "status": "PASS"}],
                "silver": [
                    {
                        "check_id": "S1",
                        "status": "FAIL",
                        "extra": {"bronze": 50000, "silver": 40000},
                    }
                ],
                "gold": [],
                "cross_layer": [],
            },
        },
    )

    records = load_history_records()
    assert len(records) == 1
    assert records[0]["run_id"] == "sparse_run_001"
    assert records[0]["bronze_rows"] == 50000
    assert records[0]["silver_rows"] == 40000
    assert records[0]["final_verdict"] == "NOT TRUSTED"
    assert all(not r["run_id"].startswith("history_") for r in records)


def test_draft_stakeholder_email(client, sample_report):
    api_main._last_report = sample_report
    response = _chat(client, "Draft stakeholder email", page="failure")
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "email_draft"
    assert "email_draft" in body["data"]
    assert "subject" in body["data"]["email_draft"]
    assert "body" in body["data"]["email_draft"]


def test_custom_check_builder(client, sample_report):
    api_main._last_report = sample_report
    response = _chat(client, "Help me add a custom Silver check", page="custom_checks")
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "custom_check_builder"
    assert "custom_check" in body["data"]


def test_create_custom_check(client, tmp_path, monkeypatch):
    checks_file = tmp_path / "custom_checks.json"
    checks_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        "api.aurum_assistant.router.load_custom_checks",
        lambda: json.loads(checks_file.read_text(encoding="utf-8")),
    )

    saved: list = []

    def _save(checks):
        saved.extend(checks)
        checks_file.write_text(json.dumps(checks, indent=2), encoding="utf-8")

    monkeypatch.setattr("api.aurum_assistant.router.save_custom_checks", _save)

    payload = {
        "layer": "silver",
        "check_name": "Discounted orders should not be removed",
        "rule_type": "row_count_condition",
        "column": "discount_applied",
        "operator": ">",
        "value": 0,
        "severity": "high",
        "description": "Ensures discounted orders are still present.",
    }
    response = client.post("/custom-checks", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "saved"
    assert body["check_id"].startswith("custom_silver_")


def test_list_custom_checks(client, monkeypatch):
    monkeypatch.setattr(
        "api.aurum_assistant.router.load_custom_checks",
        lambda: [{"check_id": "custom_silver_001", "layer": "silver"}],
    )
    response = client.get("/custom-checks")
    assert response.status_code == 200
    assert len(response.json()["checks"]) == 1


def test_run_custom_check(client, monkeypatch):
    sample = {
        "check_id": "custom_silver_001",
        "layer": "silver",
        "check_name": "Test",
        "rule_type": "row_count_condition",
        "column": "discount_applied",
        "operator": ">",
        "value": "0",
    }
    monkeypatch.setattr(
        "api.aurum_assistant.router.load_custom_checks",
        lambda: [sample],
    )
    # Keep this assistant regression fast: inject a tiny frame instead of full ETL.
    monkeypatch.setattr(
        "src.custom_checks.load_layer_dataframe",
        lambda layer: __import__("pandas").DataFrame({"x": [1, 2, 3]}),
    )
    response = client.post("/custom-checks/run", json={"check_id": "custom_silver_001"})
    assert response.status_code == 200
    body = response.json()
    assert body["check_id"] == "custom_silver_001"
    assert body["status"] == "PASS"
    assert body["observed_value"] == 3
    assert body["data_source"] == "Olist demo validation session"
    assert "uploaded or connector run" in body["scope_note"].lower()


def test_fallback_missing_report(client):
    api_main._last_report = None
    with patch("api.aurum_assistant.context.load_json_file", return_value=None):
        with patch("api.aurum_assistant.handlers.validation_explainer.load_latest_report", return_value=None):
            response = _chat(client, "Why did Silver fail?")
    assert response.status_code == 200
    body = response.json()
    assert body["confidence"] == "low"
    assert "could not find" in body["answer"].lower()


def test_assistant_alias_route(client, sample_report):
    api_main._last_report = sample_report
    response = client.post(
        "/assistant/chat",
        json={"page": "validation", "run_id": "latest", "question": "Summarize failure", "context": {}},
    )
    assert response.status_code == 200
    assert response.json()["intent"] == "failure_summary"
