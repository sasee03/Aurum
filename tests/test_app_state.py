"""Tests for SQLite app-state store and project/report persistence."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from src.app_state.db import get_connection
from src.app_state.store import (
    create_project,
    get_project,
    get_validation_run,
    get_report_by_run_id,
    list_projects,
    list_validation_runs,
    save_validation_report,
    save_validation_run,
)


@pytest.fixture
def app_state_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_app_state.sqlite"
    monkeypatch.setenv("AURUM_APP_STATE_DB", str(db_path))
    return db_path


def test_create_and_list_projects(app_state_db):
    created = create_project("Retail QA", description="Olist walkthrough", environment="QA")
    assert created["id"]
    assert created["name"] == "Retail QA"
    assert created["environment"] == "QA"
    assert created["status"] == "active"

    projects = list_projects()
    assert len(projects) == 1
    assert projects[0]["id"] == created["id"]


def test_get_project_missing_returns_none(app_state_db):
    assert get_project("nonexistent") is None


def test_save_and_load_report_by_run_id(app_state_db):
    report = {"run_id": "demo_run_001", "final_verdict": "NOT TRUSTED", "trust_score": 40}
    save_validation_run("demo_run_001", status="completed", mode="live")
    save_validation_report("demo_run_001", report)

    loaded = get_report_by_run_id("demo_run_001")
    assert loaded == report


def test_corrupt_report_json_returns_honest_error(app_state_db):
    from src.report_safety import ReportLoadError

    save_validation_run("broken_report_run", status="completed", mode="live")
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO validation_reports (run_id, report_json, created_at)
            VALUES (?, ?, ?)
            """,
            ("broken_report_run", "{not valid json", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()

    with pytest.raises(ReportLoadError):
        get_report_by_run_id("broken_report_run")

    with TestClient(api_main.app) as client:
        response = client.get("/reports/broken_report_run")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "report_load_failed"
    assert "invalid JSON" in detail["reason"]

    with TestClient(api_main.app) as client:
        runs_response = client.get("/runs")
    assert runs_response.status_code == 422
    assert runs_response.json()["detail"]["error"] == "report_load_failed"


def test_wrong_shape_report_json_returns_honest_error(app_state_db):
    save_validation_run("wrong_shape_report_run", status="completed", mode="live")
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO validation_reports (run_id, report_json, created_at)
            VALUES (?, ?, ?)
            """,
            (
                "wrong_shape_report_run",
                json.dumps(
                    {
                        "run_id": "wrong_shape_report_run",
                        "checks": {"silver": {"not": "a-list"}},
                    }
                ),
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.commit()

    with TestClient(api_main.app) as client:
        response = client.get("/reports/wrong_shape_report_run")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "report_load_failed"
    assert "checks.silver" in detail["reason"]


def test_projects_api_crud(app_state_db):
    with TestClient(api_main.app) as client:
        create_resp = client.post(
            "/projects",
            json={
                "name": "Office Pilot",
                "description": "Local validation",
                "environment": "Development",
            },
        )
        assert create_resp.status_code == 201
        body = create_resp.json()
        assert body["name"] == "Office Pilot"
        project_id = body["id"]

        list_resp = client.get("/projects")
        assert list_resp.status_code == 200
        assert len(list_resp.json()["projects"]) == 1

        get_resp = client.get(f"/projects/{project_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == project_id

        missing = client.get("/projects/does-not-exist")
        assert missing.status_code == 404


def _mock_pg_connect(monkeypatch):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.__exit__.return_value = False
    mock_cursor.__enter__.return_value = mock_cursor
    mock_cursor.__exit__.return_value = False
    mock_conn.cursor.return_value = mock_cursor
    monkeypatch.setattr(api_main.psycopg, "connect", lambda *args, **kwargs: mock_conn)


def test_post_runs_persists_report_and_get_by_run_id(app_state_db, monkeypatch):
    sample_report = {
        "run_id": "persist_run_001",
        "final_verdict": "NOT TRUSTED",
        "trust_score": 40,
        "business_impact": {"estimated_loss": 13447000.57},
        "checks": {"silver": [{"check_id": "L1-SIL-CONS-FK-CUST", "status": "SKIPPED"}]},
    }

    _mock_pg_connect(monkeypatch)
    monkeypatch.setattr(api_main, "run_validation", lambda run_id="demo_run_001": (sample_report, "aurum_session_demo"))
    monkeypatch.setattr(
        api_main,
        "attach_trust_narrative",
        lambda report: {**report, "trust_narrative": ""},
    )

    with TestClient(api_main.app) as client:
        post = client.post("/runs", json={"run_id": "persist_run_001"})
        assert post.status_code == 200
        assert post.json()["run_id"] == "persist_run_001"

        api_main._last_report = None

        by_id = client.get("/reports/persist_run_001")
        assert by_id.status_code == 200
        assert by_id.json()["run_id"] == "persist_run_001"
        assert by_id.json()["trust_score"] == 40

    saved_run = get_validation_run("persist_run_001")
    assert saved_run is not None
    assert saved_run["session_schema"] == "aurum_session_demo"
    assert saved_run["dataset_config"] == "olist"


def test_get_report_by_run_id_not_found(app_state_db):
    with TestClient(api_main.app) as client:
        api_main._last_report = None
        resp = client.get("/reports/unknown_run_xyz")
        assert resp.status_code == 404


def test_list_validation_runs_from_sqlite_only(app_state_db):
    save_validation_run(
        "run_a",
        status="completed",
        mode="live",
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:05+00:00",
    )
    save_validation_report(
        "run_a",
        {"run_id": "run_a", "trust_score": 40, "final_verdict": "NOT TRUSTED"},
    )
    save_validation_run(
        "run_b",
        status="failed",
        mode="live",
        started_at="2026-01-02T00:00:00+00:00",
        finished_at="2026-01-02T00:00:01+00:00",
        error_message="db timeout",
    )

    runs = list_validation_runs()
    assert len(runs) == 2
    assert runs[0]["run_id"] == "run_b"
    assert runs[0]["trust_score"] is None
    assert runs[1]["run_id"] == "run_a"
    assert runs[1]["trust_score"] == 40
    assert runs[1]["final_verdict"] == "NOT TRUSTED"


def test_get_runs_endpoint(app_state_db):
    save_validation_run(
        "api_run_001",
        status="completed",
        mode="live",
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:05+00:00",
    )
    save_validation_report(
        "api_run_001",
        {"run_id": "api_run_001", "trust_score": 85, "final_verdict": "WARNING"},
    )

    with TestClient(api_main.app) as client:
        resp = client.get("/runs")
        assert resp.status_code == 200
        body = resp.json()
        assert "runs" in body
        assert len(body["runs"]) == 1
        assert body["runs"][0]["run_id"] == "api_run_001"
        assert body["runs"][0]["trust_score"] == 85
        assert body["runs"][0]["display_name"] == "Validation (2026-01-01)"


def test_resolve_run_display_name_upload_connector_demo():
    from src.app_state.store import resolve_run_display_name

    assert (
        resolve_run_display_name(
            mode="upload",
            display_name="sales_test.csv",
            started_at="2026-07-10T12:00:00+00:00",
        )
        == "sales_test.csv"
    )
    assert (
        resolve_run_display_name(
            mode="upload",
            started_at="2026-07-10T12:00:00+00:00",
        )
        == "Uploaded file (2026-07-10)"
    )
    assert (
        resolve_run_display_name(
            mode="connector",
            source_schema="public",
            source_table="raw_orders",
        )
        == "public.raw_orders"
    )
    assert resolve_run_display_name(mode="demo") == "Sample dataset"
