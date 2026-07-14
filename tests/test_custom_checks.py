"""Tests for real custom-check execution (non-SQL types)."""

from __future__ import annotations

import io
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from src.app_state.store import create_project, save_data_connection
from src.custom_checks import (
    evaluate_check_on_frame,
    execute_custom_check,
    execute_custom_check_against_frame,
)
from src.postgres_connector import UserPostgresTarget, store_session_connection
from src.run_demo import run_validation
from tests.builders import make_rows, to_df


@pytest.fixture
def client(monkeypatch):
    from src.config_loader import load_dataset_config
    monkeypatch.setattr(
        "api.connectors_router.resolve_config_for_project_or_table",
        lambda *args, **kwargs: load_dataset_config()
    )
    monkeypatch.setattr(
        "api.datasets_router.resolve_config_for_project_or_table",
        lambda *args, **kwargs: load_dataset_config()
    )
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


def test_corrupt_custom_checks_json_returns_honest_error(client, tmp_path, monkeypatch):
    corrupt_file = tmp_path / "custom_checks.json"
    corrupt_file.write_text('{"oops": ', encoding="utf-8")
    monkeypatch.setattr("api.aurum_assistant.context.CUSTOM_CHECKS_PATH", corrupt_file)

    response = client.get("/custom-checks")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "custom_checks_invalid"
    assert "not valid json" in detail["reason"].lower()


def test_wrong_shape_custom_checks_json_returns_honest_error(client, tmp_path, monkeypatch):
    checks_file = tmp_path / "custom_checks.json"
    checks_file.write_text('{"oops": true}', encoding="utf-8")
    monkeypatch.setattr("api.aurum_assistant.context.CUSTOM_CHECKS_PATH", checks_file)

    response = client.get("/custom-checks")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "custom_checks_invalid"
    assert "list of checks" in detail["reason"]


def test_custom_checks_json_filters_non_object_entries(tmp_path, monkeypatch):
    checks_file = tmp_path / "custom_checks.json"
    checks_file.write_text(
        '[{"check_id": "custom_silver_001", "layer": "silver"}, "bad", 7, []]',
        encoding="utf-8",
    )
    monkeypatch.setattr("api.aurum_assistant.context.CUSTOM_CHECKS_PATH", checks_file)

    from api.aurum_assistant.context import load_custom_checks

    assert load_custom_checks() == [
        {"check_id": "custom_silver_001", "layer": "silver"}
    ]


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


def test_all_real_rule_types_include_scope_fields():
    cases = [
        (_check(rule_type="not_null", column="customer_id"), pd.DataFrame({"customer_id": ["A"]})),
        (_check(rule_type="unique", column="invoice_no"), pd.DataFrame({"invoice_no": ["1", "2"]})),
        (
            _check(rule_type="accepted_values", column="country", operator="in", value="UK,France"),
            pd.DataFrame({"country": ["UK"]}),
        ),
        (
            _check(rule_type="numeric_range", column="unit_price", operator="between", value="0,10"),
            pd.DataFrame({"unit_price": [1.0, 2.0]}),
        ),
        (
            _check(rule_type="row_count_condition", operator=">", value="0"),
            pd.DataFrame({"x": [1]}),
        ),
    ]
    for check, frame in cases:
        result = evaluate_check_on_frame(check, frame)
        assert result["data_source"] == "Olist demo validation session"
        assert "scope_note" in result
        assert "uploaded or connector run" in result["scope_note"].lower()


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
    assert result["data_source"] == "Olist demo validation session"
    assert "scope_note" in result


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


def test_custom_checks_do_change_engine_verdict(monkeypatch):
    """Running custom checks MUST alter core report verdict fields."""
    monkeypatch.setattr(
        "src.custom_checks.load_layer_dataframe",
        lambda layer: pd.DataFrame({"x": [1, 2, 3]}),
    )

    # Empty custom checks
    monkeypatch.setattr("api.aurum_assistant.context.load_custom_checks", lambda: [])
    before = run_validation(run_id="verdict_before_custom")
    base_score = before["trust_score"]

    # Add a BLOCKING failing custom check
    sample = _check(
        check_id="custom_silver_999",
        rule_type="row_count_condition",
        operator="<",
        value="0",
        severity="BLOCKING",
    )
    monkeypatch.setattr("api.aurum_assistant.context.load_custom_checks", lambda: [sample])

    after = run_validation(run_id="verdict_after_custom")
    assert after["trust_score"] < base_score
    assert after["final_verdict"] == "NOT TRUSTED"
    assert after["layer_status"]["custom"] == "FAIL"
    assert any(c["check_id"] == "custom_silver_999" for c in after["checks"].get("custom", []))


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
    assert body["data_source"] == "Olist demo validation session"
    assert "olist demo" in body["scope_note"].lower()
    assert "uploaded or connector run" in body["scope_note"].lower()


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
    assert body["data_source"] == "Olist demo validation session"
    assert "deferred for safety" in body["scope_note"].lower()


# ── run-scoped check tests ──────────────────────────────────────────────────


def test_demo_scope_no_run_id_unchanged(client, monkeypatch):
    """No run_id → demo session, same behaviour as before this unit."""
    sample = _check(
        rule_type="row_count_condition",
        operator=">",
        value="0",
    )
    monkeypatch.setattr("api.aurum_assistant.router.load_custom_checks", lambda: [sample])
    monkeypatch.setattr(
        "src.custom_checks.load_layer_dataframe",
        lambda layer: pd.DataFrame({"x": [1, 2, 3]}),
    )
    response = client.post("/custom-checks/run", json={"check_id": "custom_silver_001"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert body["data_source"] == "Olist demo validation session"


def test_run_id_not_found_returns_honest_skipped(client, monkeypatch):
    """Providing a run_id that doesn't exist must return SKIPPED, not a crash."""
    sample = _check(rule_type="not_null", column="customer_id")
    monkeypatch.setattr("api.aurum_assistant.router.load_custom_checks", lambda: [sample])
    monkeypatch.setattr("api.aurum_assistant.router.run_info_for_check", lambda run_id: None)
    response = client.post(
        "/custom-checks/run",
        json={"check_id": "custom_silver_001", "run_id": "upload_nonexistent_abc"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SKIPPED"
    assert "not found" in body["message"].lower()


def test_upload_run_without_file_returns_honest_skipped(client, monkeypatch):
    """Upload run_id without a re-attached file → SKIPPED with clear instructions."""
    sample = _check(rule_type="not_null", column="customer_id")
    monkeypatch.setattr("api.aurum_assistant.router.load_custom_checks", lambda: [sample])
    monkeypatch.setattr(
        "api.aurum_assistant.router.run_info_for_check",
        lambda run_id: {
            "run_id": "upload_abc123",
            "mode": "upload",
            "connection_id": None,
            "project_id": None,
            "status": "completed",
            "started_at": "2026-07-10T00:00:00Z",
            "finished_at": "2026-07-10T00:01:00Z",
            "error_message": None,
            "source_schema": None,
            "source_table": None,
        },
    )
    response = client.post(
        "/custom-checks/run",
        json={"check_id": "custom_silver_001", "run_id": "upload_abc123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SKIPPED"
    assert "not persisted" in body["message"].lower()
    assert "upload_abc123" in body["data_source"]


def test_run_with_file_executes_real_check(client, monkeypatch):
    """POST /custom-checks/run-with-file runs the check against the re-uploaded CSV."""
    sample = _check(
        rule_type="row_count_condition",
        operator=">",
        value="0",
    )
    monkeypatch.setattr("api.aurum_assistant.router.load_custom_checks", lambda: [sample])
    monkeypatch.setattr(
        "api.aurum_assistant.router.run_info_for_check",
        lambda run_id: {
            "run_id": run_id,
            "mode": "upload",
            "connection_id": None,
            "project_id": None,
            "status": "completed",
            "started_at": "2026-07-10T00:00:00Z",
            "finished_at": "2026-07-10T00:01:00Z",
            "error_message": None,
            "source_schema": None,
            "source_table": None,
        },
    )

    # Minimal valid Olist-shaped CSV.
    csv_rows = [
        "invoice_no,stock_code,description,quantity,invoice_date,unit_price,customer_id,country",
        "INV001,SC001,Widget,1,2024-01-01,9.99,CUST001,UK",
        "INV002,SC002,Gadget,2,2024-01-02,19.99,CUST002,France",
    ]
    csv_bytes = "\n".join(csv_rows).encode()

    # Patch build_layer_frame_from_raw to avoid a full Postgres pipeline in the unit test.
    monkeypatch.setattr(
        "src.custom_checks.build_layer_frame_from_raw",
        lambda raw, layer: pd.DataFrame({"x": [1, 2]}),
    )

    response = client.post(
        "/custom-checks/run-with-file",
        data={"check_id": "custom_silver_001", "run_id": "upload_test_run"},
        files={"file": ("orders.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("PASS", "FAIL")
    assert "orders.csv" in body["data_source"]
    assert "upload_test_run" in body["data_source"]
    assert "demo" not in body["data_source"].lower()
    assert "file identity is not verified" in body["scope_note"].lower()


def test_run_with_file_rejects_nonexistent_run_id(client, monkeypatch):
    """run-with-file must SKIP when run_id is missing — not silently proceed."""
    sample = _check(rule_type="row_count_condition", operator=">", value="0")
    monkeypatch.setattr("api.aurum_assistant.router.load_custom_checks", lambda: [sample])
    monkeypatch.setattr("api.aurum_assistant.router.run_info_for_check", lambda run_id: None)

    csv = (
        "invoice_no,stock_code,description,quantity,invoice_date,unit_price,customer_id,country\n"
        "INV001,SC001,Widget,1,2024-01-01,9.99,CUST001,UK\n"
    ).encode()
    response = client.post(
        "/custom-checks/run-with-file",
        data={"check_id": "custom_silver_001", "run_id": "upload_DOES_NOT_EXIST"},
        files={"file": ("wrong.csv", io.BytesIO(csv), "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SKIPPED"
    assert "not found" in body["message"].lower()
    assert body["data_source"] == "unavailable"
    assert "file identity is not verified" in body["scope_note"].lower()


def test_run_with_file_rejects_non_upload_mode(client, monkeypatch):
    """run-with-file must SKIP when run_id exists but mode is not upload."""
    sample = _check(rule_type="row_count_condition", operator=">", value="0")
    monkeypatch.setattr("api.aurum_assistant.router.load_custom_checks", lambda: [sample])
    monkeypatch.setattr(
        "api.aurum_assistant.router.run_info_for_check",
        lambda run_id: {
            "run_id": run_id,
            "mode": "connector",
            "connection_id": "conn_x",
            "project_id": None,
            "status": "completed",
            "started_at": "2026-07-10T00:00:00Z",
            "finished_at": "2026-07-10T00:01:00Z",
            "error_message": None,
            "source_schema": "public",
            "source_table": "raw_orders",
        },
    )
    csv = (
        "invoice_no,stock_code,description,quantity,invoice_date,unit_price,customer_id,country\n"
        "INV001,SC001,Widget,1,2024-01-01,9.99,CUST001,UK\n"
    ).encode()
    response = client.post(
        "/custom-checks/run-with-file",
        data={"check_id": "custom_silver_001", "run_id": "connector_xyz"},
        files={"file": ("orders.csv", io.BytesIO(csv), "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SKIPPED"
    assert "not 'upload'" in body["message"].lower() or "mode" in body["message"].lower()


def test_run_with_file_bad_csv_returns_skipped(client, monkeypatch):
    """A garbage file to run-with-file returns SKIPPED, not a crash."""
    sample = _check(rule_type="not_null", column="customer_id")
    monkeypatch.setattr("api.aurum_assistant.router.load_custom_checks", lambda: [sample])
    monkeypatch.setattr(
        "api.aurum_assistant.router.run_info_for_check",
        lambda run_id: {
            "run_id": run_id,
            "mode": "upload",
            "connection_id": None,
            "project_id": None,
            "status": "completed",
            "started_at": "2026-07-10T00:00:00Z",
            "finished_at": "2026-07-10T00:01:00Z",
            "error_message": None,
            "source_schema": None,
            "source_table": None,
        },
    )

    garbage = b"this is not a csv\x00\x01\x02"
    response = client.post(
        "/custom-checks/run-with-file",
        data={"check_id": "custom_silver_001", "run_id": "upload_garbage"},
        files={"file": ("bad.csv", io.BytesIO(garbage), "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SKIPPED"
    assert "schema" in body["message"].lower()
    assert "file identity is not verified" in body["scope_note"].lower()


def test_connector_run_expired_session_honest_skipped(client, monkeypatch):
    """Connector run with an expired/unknown session → SKIPPED, not a crash."""
    sample = _check(rule_type="not_null", column="customer_id")
    monkeypatch.setattr("api.aurum_assistant.router.load_custom_checks", lambda: [sample])
    monkeypatch.setattr(
        "api.aurum_assistant.router.run_info_for_check",
        lambda run_id: {
            "run_id": "connector_xyz789",
            "mode": "connector",
            "connection_id": "conn_expired",
            "project_id": None,
            "status": "completed",
            "started_at": "2026-07-10T00:00:00Z",
            "finished_at": "2026-07-10T00:01:00Z",
            "error_message": None,
            "source_schema": "public",
            "source_table": "raw_orders",
        },
    )
    # Session store returns None (expired / unknown).
    monkeypatch.setattr(
        "src.postgres_connector.get_session_connection",
        lambda conn_id: None,
    )
    response = client.post(
        "/custom-checks/run",
        json={
            "check_id": "custom_silver_001",
            "run_id": "connector_xyz789",
            "connection_id": "conn_expired",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SKIPPED"
    assert "expired" in body["message"].lower() or "unknown" in body["message"].lower()


def test_run_with_file_different_csv_shows_identity_disclaimer(client, monkeypatch):
    """Real upload run_id + different re-attached CSV: disclaimer, not rejection."""
    sample = _check(rule_type="row_count_condition", operator=">", value="0")
    monkeypatch.setattr("api.aurum_assistant.router.load_custom_checks", lambda: [sample])

    upload_csv = to_df(make_rows(10)).to_csv(index=False).encode("utf-8")
    different_csv = to_df(make_rows(5, start=100)).to_csv(index=False).encode("utf-8")

    upload = client.post(
        "/datasets/upload",
        files={"file": ("upload_a.csv", io.BytesIO(upload_csv), "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    run_id = upload.json()["run_id"]

    response = client.post(
        "/custom-checks/run-with-file",
        data={"check_id": "custom_silver_001", "run_id": run_id},
        files={"file": ("upload_b.csv", io.BytesIO(different_csv), "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("PASS", "FAIL")
    assert body["observed_value"] == 5
    assert "file identity is not verified" in body["scope_note"].lower()
    assert run_id in body["data_source"]


def test_connector_fresh_session_reauth_succeeds(client, monkeypatch):
    """Fresh connection_id with persisted metadata re-runs check against connector run."""
    sample = _check(rule_type="row_count_condition", operator=">", value="0")
    monkeypatch.setattr("api.aurum_assistant.router.load_custom_checks", lambda: [sample])

    frame = to_df(make_rows(10))
    project = create_project("Connector reauth test")
    session = store_session_connection(
        UserPostgresTarget("localhost", 5433, "aurum", "aurum", "aurum"),
        project_id=project["id"],
    )
    save_data_connection(
        connection_id=session.connection_id,
        project_id=project["id"],
        name="kiro-reauth",
        host="localhost",
        port=5433,
        database_name="aurum",
        username="aurum",
    )

    with patch("api.connectors_router.load_and_validate_user_table", return_value=frame):
        validated = client.post(
            "/connectors/postgres/validate",
            json={
                "connection_id": session.connection_id,
                "schema": "public",
                "table": "raw_orders",
                "project_id": project["id"],
            },
        )
    assert validated.status_code == 200, validated.text
    connector_run_id = validated.json()["run_id"]

    fresh_session = store_session_connection(
        UserPostgresTarget("localhost", 5433, "aurum", "aurum", "aurum"),
        project_id=project["id"],
    )
    with patch("src.postgres_connector.load_and_validate_user_table", return_value=frame):
        with patch(
            "src.custom_checks.build_layer_frame_from_raw",
            lambda raw, layer: pd.DataFrame({"x": list(range(len(raw)))}),
        ):
            response = client.post(
                "/custom-checks/run",
                json={
                    "check_id": "custom_silver_001",
                    "run_id": connector_run_id,
                    "connection_id": fresh_session.connection_id,
                },
            )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert body["observed_value"] == 10


def test_execute_against_frame_sets_real_data_source():
    """execute_custom_check_against_frame sets data_source to the supplied label."""
    df = pd.DataFrame({"customer_id": ["A", "B", "C"]})
    check = _check(rule_type="not_null", column="customer_id")
    result = execute_custom_check_against_frame(check, df, "Uploaded file: test.csv (run upload_abc)")
    assert result["status"] == "PASS"
    assert result["data_source"] == "Uploaded file: test.csv (run upload_abc)"
    assert "demo" not in result["data_source"].lower()



