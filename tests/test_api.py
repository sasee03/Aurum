"""Ring 3 API tests for React migration readiness."""

from __future__ import annotations

import time
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from src.contracts import CHECK_STATUSES
from src.db_config import db_connect_timeout

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
        "trust_score",
        "trust_narrative",
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
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["database_target"]["host"] == "localhost"
    assert "password" not in str(body).lower()
    mock_cursor.execute.assert_called_once_with("SELECT 1")


def test_health_degraded_503_when_db_unreachable(client, monkeypatch):
    def fail_connect(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(api_main.psycopg, "connect", fail_connect)
    response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unreachable"
    assert "database_target" in body
    assert "password" not in str(body).lower()


def test_health_passes_connect_timeout(client, monkeypatch):
    captured: dict = {}
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.__exit__.return_value = False
    mock_cursor.__enter__.return_value = mock_cursor
    mock_cursor.__exit__.return_value = False
    mock_conn.cursor.return_value = mock_cursor

    def capture_connect(*args, **kwargs):
        captured.update(kwargs)
        return mock_conn

    monkeypatch.setattr(api_main.psycopg, "connect", capture_connect)
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "2")
    client.get("/health")
    assert captured.get("connect_timeout") == 2


def test_post_runs_returns_full_17_key_report(client):
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


def test_post_runs_persists_demo_mode(client):
    """POST /runs validates the prepared Olist demo — mode must be 'demo', not 'live'."""
    response = client.post("/runs", json={"run_id": "mode_label_check"})
    assert response.status_code == 200

    runs = client.get("/runs")
    assert runs.status_code == 200
    matched = next(r for r in runs.json()["runs"] if r["run_id"] == "mode_label_check")
    assert matched["mode"] == "demo"


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


def test_post_runs_refused_when_db_unreachable(client, monkeypatch):
    """API-layer live guard: POST /runs must refuse (503) when the DB is down.

    The guard is the guarantee (not the disabled UI button). It must fail
    BEFORE the engine is constructed — a stale click / direct call must not run.
    """
    def fail_connect(*args, **kwargs):
        raise OSError("connection refused")

    def _engine_must_not_run(*args, **kwargs):
        raise AssertionError("run_validation must not be called when DB is degraded")

    monkeypatch.setattr(api_main.psycopg, "connect", fail_connect)
    monkeypatch.setattr(api_main, "run_validation", _engine_must_not_run)

    response = client.post("/runs", json={"run_id": "should_not_run"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "live_validation_unavailable"
    assert "database_target" in detail
    assert "password" not in str(detail).lower()


def test_post_runs_does_not_hang_when_db_unreachable(client, monkeypatch):
    """Degraded DB must fail fast via DB_CONNECT_TIMEOUT — never hang the caller."""
    def fail_connect(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(api_main.psycopg, "connect", fail_connect)

    started = time.perf_counter()
    response = client.post("/runs", json={"run_id": "no_hang"})
    elapsed = time.perf_counter() - started

    assert response.status_code == 503
    # Mocked immediate failure returns well under the configured connect budget.
    assert elapsed <= db_connect_timeout() + 2


def test_health_fast_fail_against_unroutable_db(client, monkeypatch):
    """/health must resolve degraded within DB_CONNECT_TIMEOUT against a bad host."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_HOST", "10.255.255.1")  # RFC 5737-style blackhole
    monkeypatch.setenv("DB_PORT", "5433")
    monkeypatch.setenv("DB_NAME", "aurum")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "1")

    started = time.perf_counter()
    response = client.get("/health")
    elapsed = time.perf_counter() - started

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unreachable"
    # Fast fail: bounded by the connect timeout plus generous scheduling slack;
    # the assertion's real job is proving it does not hang.
    assert elapsed < 15


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
