"""Ring 3 API tests for React migration readiness."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from src.contracts import CHECK_STATUSES

EXPECTED_REPORT_KEYS = frozenset(
    {
        "project",
        "description",
        "pipeline",
        "dataset",
        "run_id",
        "layer_status",
        "final_verdict",
        "severity",
        "first_failed_layer",
        "root_cause",
        "business_impact",
        "suggested_action",
        "coverage",
        "detection_layers",
        "checks",
    }
)


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


def _mock_pg_connect(monkeypatch):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.__exit__.return_value = False
    mock_cursor.__enter__.return_value = mock_cursor
    mock_cursor.__exit__.return_value = False
    mock_conn.cursor.return_value = mock_cursor
    monkeypatch.setattr(api_main.psycopg, "connect", lambda *args, **kwargs: mock_conn)
    return mock_cursor


def test_health_ok(client, monkeypatch):
    mock_cursor = _mock_pg_connect(monkeypatch)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    mock_cursor.execute.assert_called_once_with("SELECT 1")


def test_health_degraded_503_when_db_unreachable(client, monkeypatch):
    def fail_connect(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(api_main.psycopg, "connect", fail_connect)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unreachable"}


def test_post_runs_returns_full_15_key_report(client):
    response = client.post("/runs", json={"run_id": "api_test_run"})
    assert response.status_code == 200
    report = response.json()
    assert set(report.keys()) == set(EXPECTED_REPORT_KEYS)
    assert "coverage" in report
    assert isinstance(report["coverage"], dict)
    assert "full_coverage" in report["coverage"]


def test_report_includes_skipped_status(client):
    response = client.post("/runs", json={"run_id": "api_skipped_status"})
    assert response.status_code == 200
    report = response.json()
    assert "SKIPPED" in CHECK_STATUSES
    check_statuses = {
        check["status"]
        for section in report["checks"].values()
        for check in section
    }
    assert "SKIPPED" in check_statuses or report["coverage"].get("skipped", 0) >= 1


def test_latest_matches_post_runs(client):
    post = client.post("/runs", json={"run_id": "parity_run_001"})
    assert post.status_code == 200
    latest = client.get("/reports/latest")
    assert latest.status_code == 200
    assert latest.json() == post.json()


def test_report_by_id_works_for_latest_matching_id(client):
    post = client.post("/runs", json={"run_id": "by_id_test"})
    assert post.status_code == 200
    by_id = client.get("/reports/by_id_test")
    assert by_id.status_code == 200
    assert by_id.json() == post.json()


def test_report_by_id_wrong_run_id_returns_404(client):
    post = client.post("/runs", json={"run_id": "correct_id"})
    assert post.status_code == 200
    wrong = client.get("/reports/wrong_id")
    assert wrong.status_code == 404
    assert "not found" in wrong.json()["detail"].lower()


def test_cors_preflight_localhost_5173(client):
    response = client.options(
        "/runs",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "POST" in response.headers.get("access-control-allow-methods", "")
