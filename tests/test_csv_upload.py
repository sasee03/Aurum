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
from src.csv_ingest import MAX_UPLOAD_ROWS, RAW_ORDERS_COLUMNS
from src.db_config import db_connect_timeout
from tests.builders import make_rows, to_df

BASELINE_PATH = Path(__file__).resolve().parent / "fixtures" / "olist_post_runs_baseline.json"
GOLDEN_RUN_ID = "golden_olist_baseline"
# Volatile fields excluded from golden baseline comparison:
# - trust_narrative: Ollama-attached after deterministic report
# - run_date (nested in detection_layers observed dicts): CURRENT_DATE at run time
VOLATILE_REPORT_KEYS = frozenset({"trust_narrative"})
VOLATILE_NESTED_KEYS = frozenset({"run_date"})


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
    """Normalize a report for golden comparison by dropping volatile fields."""
    trimmed = {key: value for key, value in report.items() if key not in VOLATILE_REPORT_KEYS}

    def _walk(value):
        if isinstance(value, dict):
            return {
                key: _walk(nested)
                for key, nested in value.items()
                if key not in VOLATILE_NESTED_KEYS
            }
        if isinstance(value, list):
            return [_walk(item) for item in value]
        return value

    return _walk(trimmed)


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


def _headers_only_csv_bytes() -> bytes:
    return (",".join(RAW_ORDERS_COLUMNS) + "\n").encode("utf-8")


def _blank_required_field_csv_bytes(column: str = "unit_price") -> bytes:
    rows = make_rows(3)
    rows[1][column] = ""
    return to_df(rows).to_csv(index=False).encode("utf-8")


def _non_numeric_unit_price_csv_bytes() -> bytes:
    rows = make_rows(3)
    for row in rows:
        row["unit_price"] = "not-a-price"
    return to_df(rows).to_csv(index=False).encode("utf-8")


def _duplicate_business_key_csv_bytes() -> bytes:
    rows = make_rows(3)
    rows[2] = dict(rows[0])
    return to_df(rows).to_csv(index=False).encode("utf-8")


def _alphanumeric_customer_id_csv_bytes() -> bytes:
    rows = make_rows(25)
    for idx, row in enumerate(rows, start=1):
        row["customer_id"] = f"CUST-{idx:03d}"
    return to_df(rows).to_csv(index=False).encode("utf-8")


def _assert_upload_rejected(client, payload: bytes, filename: str, expected_error: str):
    sentinel = {"run_id": "sentinel_reject", "final_verdict": "SENTINEL"}
    api_main._last_report = sentinel
    runs_before, reports_before = _sqlite_validation_counts()

    response = client.post(
        "/datasets/upload",
        files={"file": (filename, io.BytesIO(payload), "text/csv")},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["schema_match"] is False
    assert body["missing_columns"] == []
    assert body["expected_columns"] == list(RAW_ORDERS_COLUMNS)
    assert body["error"] == expected_error

    runs_after, reports_after = _sqlite_validation_counts()
    assert runs_after == runs_before
    assert reports_after == reports_before
    assert api_main._last_report == sentinel


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


def test_upload_headers_only_no_rows_honest_rejection(client):
    _assert_upload_rejected(
        client,
        _headers_only_csv_bytes(),
        "headers_only.csv",
        "file contains no data rows",
    )


def test_upload_empty_file_honest_rejection(client):
    _assert_upload_rejected(client, b"", "empty.csv", "file is empty")


def test_upload_garbage_file_honest_rejection(client):
    _assert_upload_rejected(
        client,
        b"this is not csv content {{{",
        "garbage.csv",
        "file is not a valid CSV",
    )


def test_upload_blank_required_field_honest_rejection(client):
    _assert_upload_rejected(
        client,
        _blank_required_field_csv_bytes("unit_price"),
        "blank_unit_price.csv",
        "Required column 'unit_price' has 1 missing or blank value(s)",
    )


def test_upload_non_numeric_unit_price_honest_rejection(client):
    _assert_upload_rejected(
        client,
        _non_numeric_unit_price_csv_bytes(),
        "bad_unit_price.csv",
        "unit_price must be a numeric value",
    )


def test_upload_oversized_row_count_honest_rejection(client, monkeypatch):
    monkeypatch.setattr("src.csv_ingest.MAX_UPLOAD_ROWS", 2)
    _assert_upload_rejected(
        client,
        _csv_bytes(),
        "too_many_rows.csv",
        "file exceeds maximum of 2 data rows",
    )


def test_upload_oversized_file_bytes_honest_rejection(client, monkeypatch):
    monkeypatch.setattr("src.csv_ingest.MAX_UPLOAD_BYTES", 64)
    payload = _csv_bytes()
    assert len(payload) > 64
    _assert_upload_rejected(
        client,
        payload,
        "too_large.csv",
        "file exceeds maximum size of 64 bytes",
    )


def test_upload_duplicate_business_key_runs_engine_s3_check(client):
    response = client.post(
        "/datasets/upload",
        files={
            "file": (
                "duplicate_keys.csv",
                io.BytesIO(_duplicate_business_key_csv_bytes()),
                "text/csv",
            )
        },
    )
    assert response.status_code == 200
    report = response.json()
    silver_checks = report["checks"]["silver"]
    s3 = next(check for check in silver_checks if check["check_id"] == "S3")
    assert s3["observed"]["bronze_duplicates"] >= 1
    assert s3["observed"]["silver_duplicates"] >= 1


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

    runs = client.get("/runs").json()["runs"]
    match = next(r for r in runs if r["run_id"] == report["run_id"])
    assert match["display_name"] == "orders.csv"


def test_upload_accepts_alphanumeric_customer_id_identifier(client):
    response = client.post(
        "/datasets/upload",
        files={
            "file": (
                "customer_ids.csv",
                io.BytesIO(_alphanumeric_customer_id_csv_bytes()),
                "text/csv",
            )
        },
    )
    assert response.status_code == 200
    report = response.json()
    assert report["run_id"].startswith("upload_")
    assert report["final_verdict"]
    assert "checks" in report


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


def test_upload_nonexistent_project_id_honest_rejection(client):
    sentinel = {"run_id": "sentinel_missing_project", "final_verdict": "SENTINEL"}
    api_main._last_report = sentinel
    runs_before, reports_before = _sqlite_validation_counts()

    response = client.post(
        "/datasets/upload",
        files={"file": ("orders.csv", io.BytesIO(_csv_bytes()), "text/csv")},
        data={"project_id": "project_does_not_exist"},
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": "Project not found",
        "project_id": "project_does_not_exist",
    }
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
    """Golden regression: POST /runs matches captured Olist baseline."""
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    response = client.post("/runs", json={"run_id": GOLDEN_RUN_ID})
    assert response.status_code == 200
    assert _strip_volatile(response.json()) == _strip_volatile(baseline)
