"""Tests for CSV upload ingestion (POST /datasets/upload)."""

from __future__ import annotations

import io
import json
import time
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api.main as api_main
import src.config_loader as config_loader
from src.app_state.db import get_connection
from src.app_state.store import get_project
from src.config_loader import ConfigResolutionError, load_dataset_config
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
def client(monkeypatch):
    def resolve_explicit_test_olist(project_id, _file_name):
        if project_id and get_project(project_id) is None:
            raise ConfigResolutionError(
                "project_not_found",
                f"Project '{project_id}' was not found while resolving its dataset config.",
            )
        return load_dataset_config()

    monkeypatch.setattr(
        "api.datasets_router.resolve_config_for_project_or_table",
        resolve_explicit_test_olist,
    )
    with _reset_last_report():
        with TestClient(api_main.app) as test_client:
            yield test_client


def _sqlite_validation_counts() -> tuple[int, int]:
    with get_connection() as conn:
        runs = conn.execute("SELECT COUNT(*) FROM validation_runs").fetchone()[0]
        reports = conn.execute("SELECT COUNT(*) FROM validation_reports").fetchone()[0]
    return int(runs), int(reports)


def test_upload_without_custom_config_refuses_olist_before_parse(client, monkeypatch):
    parse_called = False

    def track_parse(*_args, **_kwargs):
        nonlocal parse_called
        parse_called = True

    monkeypatch.setattr(
        "api.datasets_router.resolve_config_for_project_or_table",
        config_loader.resolve_config_for_project_or_table,
    )
    monkeypatch.setattr("api.datasets_router.parse_raw_orders_csv", track_parse)

    response = client.post(
        "/datasets/upload",
        files={"file": ("no_such_config.csv", io.BytesIO(_csv_bytes()), "text/csv")},
    )

    assert response.status_code == 422
    assert response.json()["error"] == "dataset_config_not_found"
    assert "refusing to substitute" in response.json()["message"]
    assert parse_called is False


def test_upload_project_store_failure_returns_clear_500(client, monkeypatch):
    def fail_resolution(*_args, **_kwargs):
        raise ConfigResolutionError(
            "project_store_lookup_failed",
            "Could not look up project 'broken': store unavailable",
        )

    monkeypatch.setattr(
        "api.datasets_router.resolve_config_for_project_or_table",
        fail_resolution,
    )
    response = client.post(
        "/datasets/upload",
        files={"file": ("orders.csv", io.BytesIO(_csv_bytes()), "text/csv")},
        data={"project_id": "broken"},
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": "project_store_lookup_failed",
        "message": "Could not look up project 'broken': store unavailable",
    }


def _strip_volatile(report: dict) -> dict:
    """Normalize a report for golden comparison by dropping volatile fields."""
    import copy
    trimmed = {key: value for key, value in report.items() if key not in VOLATILE_REPORT_KEYS}

    if "checks" in trimmed and "custom" in trimmed["checks"]:
        del trimmed["checks"]["custom"]

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


def test_upload_duplicate_business_key_runs_engine_s3_check(client, schema_tracker):
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
    schema_tracker.track_run(report["run_id"])
    silver_checks = report["checks"]["silver"]
    s3 = next(check for check in silver_checks if check["check_id"] == "S3")
    assert s3["observed"]["bronze_duplicates"] >= 1
    assert s3["observed"]["silver_duplicates"] >= 1


def test_upload_matching_csv_returns_report(client, schema_tracker):
    response = client.post(
        "/datasets/upload",
        files={"file": ("orders.csv", io.BytesIO(_csv_bytes()), "text/csv")},
    )
    assert response.status_code == 200
    report = response.json()
    schema_tracker.track_run(report["run_id"])
    assert report["run_id"].startswith("upload_")
    assert report["final_verdict"]
    assert "checks" in report
    assert len(report["checks"]["bronze"]) >= 1

    runs = client.get("/runs").json()["runs"]
    match = next(r for r in runs if r["run_id"] == report["run_id"])
    assert match["display_name"] == "orders.csv"


def test_upload_accepts_alphanumeric_customer_id_identifier(client, schema_tracker):
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
    schema_tracker.track_run(report["run_id"])
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


def test_upload_post_parse_failure_returns_clean_error(client, monkeypatch):
    sentinel = {"run_id": "sentinel_post_parse", "final_verdict": "SENTINEL"}
    api_main._last_report = sentinel
    monkeypatch.setattr(
        "api.datasets_router.api_main._database_reachable", lambda: True
    )

    def fail_after_parse(*args, **kwargs):
        raise RuntimeError("engine unavailable after parse")

    monkeypatch.setattr(
        "api.datasets_router.run_validation_from_raw_orders", fail_after_parse
    )
    runs_before, reports_before = _sqlite_validation_counts()

    response = client.post(
        "/datasets/upload",
        files={"file": ("orders.csv", io.BytesIO(_csv_bytes()), "text/csv")},
    )

    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "upload_validation_failed"
    assert "parsed successfully" in body["message"]
    assert "detail" not in body
    assert "engine unavailable after parse" not in str(body)
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


def test_upload_persists_upload_mode(client, schema_tracker):
    response = client.post(
        "/datasets/upload",
        files={"file": ("orders.csv", io.BytesIO(_csv_bytes()), "text/csv")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    schema_tracker.track_run(run_id)

    runs = client.get("/runs")
    assert runs.status_code == 200
    matched = next(r for r in runs.json()["runs"] if r["run_id"] == run_id)
    assert matched["mode"] == "upload"


def test_upload_does_not_change_reports_latest(client, schema_tracker):
    """Upload persists by run_id; GET /reports/latest must remain the demo report."""
    demo = client.post("/runs", json={"run_id": "latest_guard_demo"})
    assert demo.status_code == 200
    schema_tracker.track_run("latest_guard_demo")
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
    schema_tracker.track_run(upload.json()["run_id"])

    latest_after = client.get("/reports/latest")
    assert latest_after.status_code == 200
    assert latest_after.json() == demo_report
    assert api_main._last_report == demo_report


def test_post_runs_demo_path_unchanged_after_upload_added(client, schema_tracker):
    """Golden regression: POST /runs matches captured Olist baseline."""
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    response = client.post("/runs", json={"run_id": GOLDEN_RUN_ID})
    assert response.status_code == 200
    schema_tracker.track_run(GOLDEN_RUN_ID)
    assert _strip_volatile(response.json()) == _strip_volatile(baseline)


def test_validate_raw_orders_frame_custom_config():
    from src.csv_ingest import validate_raw_orders_frame
    from src.config_loader import AurumDatasetConfig, DatasetInfo, TablesInfo, ColumnsInfo, MetricsInfo, GoldTablesInfo
    import pytest
    from src.csv_ingest import CsvSchemaMismatch

    custom_cfg = AurumDatasetConfig(
        dataset=DatasetInfo(name="Custom", currency="USD", domain="retail", geography_label="region"),
        tables=TablesInfo(
            raw="r",
            bronze="b",
            silver="s",
            gold=GoldTablesInfo(metrics="g", country_revenue="gc", product_sales="gp")
        ),
        columns=ColumnsInfo(
            primary_key="custom_id",
            customer_id="cust_uuid",
            timestamp="created_at",
            quantity="qty",
            unit_price="price",
            geography="region",
            revenue="rev",
            product_id="prod_id",
            product_description="desc",
            order_id="custom_id",
            order_id_expression="custom_id",
            line_item_key=("custom_id", "prod_id", "cust_uuid", "created_at"),
        ),
        metrics=MetricsInfo(
            revenue_formula="qty * price",
            order_id_expression="custom_id",
            top_revenue_dimension="region",
            top_revenue_label="region",
            total_revenue_metric="t_rev",
            total_orders_metric="t_ord",
            total_customers_metric="t_cust",
            average_order_value_metric="aov",
            aggregate_revenue_metric="a_rev",
            total_quantity_metric="t_qty",
        )
    )

    df_valid = pd.DataFrame({
        "custom_id": ["INV-01"],
        "prod_id": ["P01"],
        "desc": ["Product 1"],
        "qty": [10],
        "created_at": ["2026-07-12"],
        "price": [9.99],
        "cust_uuid": ["CUST-01"],
        "region": ["US"],
    })

    out = validate_raw_orders_frame(df_valid, custom_cfg)
    assert list(out.columns) == [
        "custom_id",
        "prod_id",
        "desc",
        "qty",
        "created_at",
        "price",
        "cust_uuid",
        "region",
    ]

    df_invalid = pd.DataFrame({
        "custom_id": ["INV-01"],
        "prod_id": ["P01"],
        "desc": ["Product 1"],
        "qty": [10],
        "created_at": ["2026-07-12"],
        "price": [9.99],
        "cust_uuid": ["CUST-01"],
    })

    with pytest.raises(CsvSchemaMismatch) as exc_info:
        validate_raw_orders_frame(df_invalid, custom_cfg)
    assert exc_info.value.missing_columns == ["region"]


def test_run_validation_from_raw_orders_custom_config_no_olist_fallback(schema_tracker):
    from src.config_loader import (
        AurumDatasetConfig,
        ColumnsInfo,
        DatasetInfo,
        MetricsInfo,
        TablesInfo,
        GoldTablesInfo,
    )
    from src.csv_ingest import run_validation_from_raw_orders, validate_raw_orders_frame

    custom_cfg = AurumDatasetConfig(
        dataset=DatasetInfo(
            name="Custom Orders",
            currency="USD",
            domain="retail",
            geography_label="market",
        ),
        tables=TablesInfo(
            raw="raw_orders",
            bronze="bronze_orders",
            silver="silver_orders",
            gold=GoldTablesInfo(
                metrics="gold_metrics",
                country_revenue="gold_country_revenue",
                product_sales="gold_product_sales"
            )
        ),
        columns=ColumnsInfo(
            primary_key="salelineid",
            customer_id="buyerref",
            timestamp="soldat",
            quantity="units",
            unit_price="priceeach",
            geography="market",
            revenue="linerevenue",
            product_id="sku",
            product_description="itemname",
            order_id="orderref",
            order_id_expression="{order_id}",
            line_item_key=("salelineid", "sku", "buyerref", "soldat"),
        ),
        metrics=MetricsInfo(
            revenue_formula="units * priceeach",
            order_id_expression="{order_id}",
            top_revenue_dimension="market",
            top_revenue_label="market",
            total_revenue_metric="total_revenue",
            total_orders_metric="total_orders",
            total_customers_metric="total_customers",
            average_order_value_metric="average_order_value",
            aggregate_revenue_metric="revenue",
            total_quantity_metric="total_quantity",
        ),
    )

    uploaded = pd.DataFrame(
        {
            "SaleLineId": ["L1", "L2"],
            "OrderRef": ["O1", "O2"],
            "Sku": ["A", "B"],
            "ItemName": ["Alpha", "Beta"],
            "BuyerRef": ["C1", "C2"],
            "SoldAt": ["2026-01-01", "2026-01-02"],
            "Units": [2, 3],
            "PriceEach": [10.0, 30.0],
            "Market": ["US", "CA"],
        }
    )
    validated = validate_raw_orders_frame(uploaded, custom_cfg)
    report, schema = run_validation_from_raw_orders(validated, "custom_upload", custom_cfg)
    schema_tracker.add(schema)

    assert report["run_id"] == "custom_upload"
    assert report["dataset"] == "Custom Orders"
    assert report["business_impact"]["expected_revenue"] == 110.0
    assert report["business_impact"]["actual_revenue"] == 110.0

    silver_checks = {check["check_id"]: check for check in report["checks"]["silver"]}
    gold_checks = {check["check_id"]: check for check in report["checks"]["gold"]}
    cross_checks = {check["check_id"]: check for check in report["checks"]["cross_layer"]}
    assert silver_checks["S7"]["status"] == "PASS"
    assert silver_checks["S11"]["status"] == "PASS"
    assert gold_checks["G1"]["status"] == "PASS"
    assert gold_checks["G2"]["status"] == "PASS"
    assert cross_checks["X3"]["status"] == "PASS"
    assert len(report["detection_layers"]["layer_2_reconciliation"]) == 0
