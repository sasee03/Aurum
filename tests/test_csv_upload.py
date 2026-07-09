"""Tests for CSV upload ingestion (POST /datasets/upload)."""

from __future__ import annotations

import io
import json
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from src.app_state.db import get_connection
from src.csv_ingest import RAW_ORDERS_COLUMNS
from src.db_config import db_connect_timeout
from tests.builders import make_rows, to_df

BASELINE_PATH = Path(__file__).resolve().parent / "fixtures" / "olist_post_runs_baseline.json"
GOLDEN_RUN_ID = "golden_olist_baseline"
# Ollama trust_narrative is attached after the deterministic report is built and may vary.
VOLATILE_REPORT_KEYS = frozenset({"trust_narrative"})


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


def _sqlite_validation_counts() -> tuple[int, int]:
    with get_connection() as conn:
        runs = conn.execute("SELECT COUNT(*) FROM validation_runs").fetchone()[0]
        reports = conn.execute("SELECT COUNT(*) FROM validation_reports").fetchone()[0]
    return int(runs), int(reports)


def _strip_volatile(report: dict) -> dict:
    return {key: value for key, value in report.items() if key not in VOLATILE_REPORT_KEYS}


def _csv_bytes(**overrides) -> bytes:
    rows = make_rows(25, **overrides)
    return to_df(rows).to_csv(index=False).encode("utf-8")


def _bad_csv_bytes() -> bytes:
    rows = make_rows(5)
    df = to_df(rows).drop(columns=["country"])
    return df.to_csv(index=False).encode("utf-8")


def _numeric_invoice_no_csv_bytes() -> bytes:
    rows = make_rows(5)
    df = to_df(rows)
    df["invoice_no"] = range(536365, 536365 + len(df))
    return df.to_csv(index=False).encode("utf-8")


def test_upload_numeric_invoice_no_honest_rejection(client):
    sentinel = {"run_id": "sentinel_numeric_invoice", "final_verdict": "SENTINEL"}
    api_main._last_report = sentinel
    runs_before, reports_before = _sqlite_validation_counts()

    response = client.post(
        "/datasets/upload",
        files={
            "file": (
                "numeric_invoice.csv",
                io.BytesIO(_numeric_invoice_no_csv_bytes()),
                "text/csv",
            )
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["schema_match"] is False
    assert body["missing_columns"] == []
    assert body["expected_columns"] == list(RAW_ORDERS_COLUMNS)
    assert body["error"] == "invoice_no must be a text/string value, not numeric"

    runs_after, reports_after = _sqlite_validation_counts()
    assert runs_after == runs_before
    assert reports_after == reports_before
    assert api_main._last_report == sentinel


def test_upload_matching_csv_returns_report(client):
    response = client.post(
        "/datasets/upload",
        files={"file": ("orders.csv", io.BytesIO(_csv_bytes()), "text/csv")},
    )
    assert response.status_code == 200
    report = response.json()
    assert report["run_id"].startswith("upload_")
    assert report["final_verdict"]
    assert "checks" in report
    assert len(report["checks"]["bronze"]) >= 1


def test_upload_mismatched_csv_honest_rejection(client):
    sentinel = {"run_id": "sentinel_last_report", "final_verdict": "SENTINEL"}
    api_main._last_report = sentinel
    runs_before, reports_before = _sqlite_validation_counts()

    response = client.post(
        "/datasets/upload",
        files={"file": ("bad.csv", io.BytesIO(_bad_csv_bytes()), "text/csv")},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["schema_match"] is False
    assert body["missing_columns"] == ["country"]
    assert body["expected_columns"] == list(RAW_ORDERS_COLUMNS)
    assert "schema" in body["error"].lower()

    runs_after, reports_after = _sqlite_validation_counts()
    assert runs_after == runs_before
    assert reports_after == reports_before
    assert api_main._last_report == sentinel


def test_upload_refused_when_db_unreachable(client, monkeypatch):
    def fail_connect(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(api_main.psycopg, "connect", fail_connect)

    started = time.perf_counter()
    response = client.post(
        "/datasets/upload",
        files={"file": ("orders.csv", io.BytesIO(_csv_bytes()), "text/csv")},
    )
    elapsed = time.perf_counter() - started

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "live_validation_unavailable"
    assert elapsed <= db_connect_timeout() + 2


def test_upload_persists_upload_mode(client):
    response = client.post(
        "/datasets/upload",
        files={"file": ("orders.csv", io.BytesIO(_csv_bytes()), "text/csv")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    runs = client.get("/runs")
    assert runs.status_code == 200
    matched = next(r for r in runs.json()["runs"] if r["run_id"] == run_id)
    assert matched["mode"] == "upload"


def test_upload_does_not_change_reports_latest(client):
    """Upload persists by run_id; GET /reports/latest must remain the demo report."""
    demo = client.post("/runs", json={"run_id": "latest_guard_demo"})
    assert demo.status_code == 200
    demo_report = demo.json()

    latest_before = client.get("/reports/latest")
    assert latest_before.status_code == 200
    assert latest_before.json() == demo_report

    upload = client.post(
        "/datasets/upload",
        files={"file": ("orders.csv", io.BytesIO(_csv_bytes()), "text/csv")},
    )
    assert upload.status_code == 200
    assert upload.json()["run_id"].startswith("upload_")

    latest_after = client.get("/reports/latest")
    assert latest_after.status_code == 200
    assert latest_after.json() == demo_report
    assert api_main._last_report == demo_report


def test_post_runs_demo_path_unchanged_after_upload_added(client):
    """Golden regression: POST /runs matches captured Olist baseline (minus trust_narrative)."""
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    response = client.post("/runs", json={"run_id": GOLDEN_RUN_ID})
    assert response.status_code == 200
    assert _strip_volatile(response.json()) == baseline
