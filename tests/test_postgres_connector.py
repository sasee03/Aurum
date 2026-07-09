"""Tests for user-supplied Postgres connector endpoints."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from src.app_state.db import get_connection
from src.csv_ingest import MAX_UPLOAD_ROWS, RAW_ORDERS_COLUMNS
from src.postgres_connector import (
    SESSION_TTL_SECONDS,
    UserPostgresTarget,
    clear_session_connections,
    classify_connect_error,
    get_session_connection,
    store_session_connection,
)
from tests.builders import make_rows, to_df


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
    clear_session_connections()
    with _reset_last_report():
        with TestClient(api_main.app) as test_client:
            yield test_client
    clear_session_connections()


def _olist_frame(n: int = 5) -> pd.DataFrame:
    return to_df(make_rows(n))


def test_classify_wrong_password():
    assert "Authentication failed" in classify_connect_error(
        Exception("password authentication failed for user \"aurum\"")
    )


def test_classify_wrong_port_refused():
    assert "wrong port" in classify_connect_error(
        Exception("connection refused")
    ).lower() or "unreachable" in classify_connect_error(
        Exception("connection refused")
    ).lower()


def test_classify_host_unreachable_dns():
    msg = classify_connect_error(Exception("could not translate host name to address: Name or service not known"))
    assert "unreachable" in msg.lower() or "dns" in msg.lower()


def test_classify_host_unreachable_windows_getaddrinfo():
    msg = classify_connect_error(
        Exception("failed to resolve host 'no.such.host.invalid': [Errno 11001] getaddrinfo failed")
    )
    assert msg == "Host unreachable — DNS lookup failed"


def test_classify_database_missing():
    assert "does not exist" in classify_connect_error(
        Exception('database "nope" does not exist')
    ).lower()


def test_classify_permission_denied():
    assert "Permission denied" in classify_connect_error(
        Exception("permission denied for database aurum")
    )


def test_classify_timeout():
    assert "timed out" in classify_connect_error(TimeoutError("timeout")).lower()


def test_test_connection_wrong_password_honest(client):
    with patch("src.postgres_connector.psycopg.connect") as connect:
        connect.side_effect = Exception("password authentication failed for user \"x\"")
        response = client.post(
            "/connectors/postgres/test",
            json={
                "host": "localhost",
                "port": 5433,
                "database": "aurum",
                "username": "aurum",
                "password": "wrong",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert "Authentication failed" in body["error"]
    assert "password" not in body
    assert body.get("password") is None


def test_test_connection_wrong_port_honest(client):
    with patch("src.postgres_connector.psycopg.connect") as connect:
        connect.side_effect = Exception("connection to server at \"localhost\" (127.0.0.1), port 9999 failed: Connection refused")
        response = client.post(
            "/connectors/postgres/test",
            json={
                "host": "localhost",
                "port": 9999,
                "database": "aurum",
                "username": "aurum",
                "password": "aurum",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert "port" in body["error"].lower() or "unreachable" in body["error"].lower()


def test_test_connection_host_unreachable_honest(client):
    with patch("src.postgres_connector.psycopg.connect") as connect:
        connect.side_effect = Exception("could not translate host name \"no.such.host\" to address: Name or service not known")
        response = client.post(
            "/connectors/postgres/test",
            json={
                "host": "no.such.host",
                "port": 5432,
                "database": "aurum",
                "username": "aurum",
                "password": "aurum",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert "unreachable" in body["error"].lower() or "dns" in body["error"].lower()


def test_test_connection_success_returns_connection_id_no_password(client):
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = (1,)

    with patch("src.postgres_connector.psycopg.connect", return_value=mock_conn):
        response = client.post(
            "/connectors/postgres/test",
            json={
                "host": "localhost",
                "port": 5433,
                "database": "aurum",
                "username": "aurum",
                "password": "secret-never-echo",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    assert body["connection_id"].startswith("conn_")
    assert "password" not in body
    assert "secret-never-echo" not in str(body)


def test_validate_schema_mismatch_honest_422(client):
    session = store_session_connection(
        UserPostgresTarget(
            host="localhost",
            port=5433,
            database="aurum",
            username="aurum",
            password="aurum",
        )
    )
    from src.csv_ingest import CsvSchemaMismatch

    with patch(
        "api.connectors_router.load_and_validate_user_table",
        side_effect=CsvSchemaMismatch(
            missing_columns=["country"],
            error="This file doesn't match the expected schema.",
        ),
    ):
        response = client.post(
            "/connectors/postgres/validate",
            json={
                "connection_id": session.connection_id,
                "schema": "public",
                "table": "orders",
            },
        )
    assert response.status_code == 422
    body = response.json()
    assert body["schema_match"] is False
    assert body["missing_columns"] == ["country"]
    assert body["expected_columns"] == list(RAW_ORDERS_COLUMNS)
    assert "schema" in body["error"].lower()


def test_validate_oversized_table_honest_422(client):
    session = store_session_connection(
        UserPostgresTarget(
            host="localhost",
            port=5433,
            database="aurum",
            username="aurum",
            password="aurum",
        )
    )
    from src.csv_ingest import CsvSchemaMismatch

    with patch(
        "api.connectors_router.load_and_validate_user_table",
        side_effect=CsvSchemaMismatch(
            missing_columns=[],
            error=f"file exceeds maximum of {MAX_UPLOAD_ROWS:,} data rows",
        ),
    ):
        response = client.post(
            "/connectors/postgres/validate",
            json={
                "connection_id": session.connection_id,
                "schema": "public",
                "table": "huge_orders",
            },
        )
    assert response.status_code == 422
    body = response.json()
    assert body["schema_match"] is False
    assert "500,000" in body["error"]


def test_validate_success_persists_connector_mode(client):
    session = store_session_connection(
        UserPostgresTarget(
            host="localhost",
            port=5433,
            database="aurum",
            username="aurum",
            password="aurum",
        )
    )
    frame = _olist_frame(8)

    with patch(
        "api.connectors_router.load_and_validate_user_table",
        return_value=frame,
    ):
        response = client.post(
            "/connectors/postgres/validate",
            json={
                "connection_id": session.connection_id,
                "schema": "public",
                "table": "raw_orders",
            },
        )
    assert response.status_code == 200
    report = response.json()
    assert report["run_id"].startswith("connector_")
    assert "checks" in report

    runs = client.get("/runs")
    assert runs.status_code == 200
    matched = next(r for r in runs.json()["runs"] if r["run_id"] == report["run_id"])
    assert matched["mode"] == "connector"


def test_validate_returns_exactly_17_key_report(client):
    """Connector validate must return the 17-key contract — source coords stay on the run row."""
    from tests.test_api import EXPECTED_REPORT_KEYS
    from src.app_state.store import get_validation_run

    session = store_session_connection(
        UserPostgresTarget(
            host="localhost",
            port=5433,
            database="aurum",
            username="aurum",
            password="aurum",
        )
    )
    frame = _olist_frame(4)

    with patch(
        "api.connectors_router.load_and_validate_user_table",
        return_value=frame,
    ):
        response = client.post(
            "/connectors/postgres/validate",
            json={
                "connection_id": session.connection_id,
                "schema": "public",
                "table": "raw_orders",
            },
        )
    assert response.status_code == 200
    report = response.json()
    assert set(report.keys()) == set(EXPECTED_REPORT_KEYS)
    assert "source_schema" not in report
    assert "source_table" not in report

    run = get_validation_run(report["run_id"])
    assert run is not None
    assert run["source_schema"] == "public"
    assert run["source_table"] == "raw_orders"
    assert run["mode"] == "connector"


def test_schemas_unknown_connection_404(client):
    response = client.get("/connectors/postgres/schemas?connection_id=conn_missing")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["error"] == "connection_not_found"


def test_expired_session_is_evicted_and_rejected(client):
    session = store_session_connection(
        UserPostgresTarget(
            host="localhost",
            port=5433,
            database="aurum",
            username="aurum",
            password="aurum",
        )
    )
    session.created_at_monotonic -= SESSION_TTL_SECONDS + 1

    assert get_session_connection(session.connection_id) is None

    response = client.get(
        f"/connectors/postgres/schemas?connection_id={session.connection_id}"
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "connection_not_found"


def test_password_never_persisted_to_sqlite(client):
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = (1,)

    project = client.post(
        "/projects",
        json={"name": "Connector Test Project", "environment": "Development"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    with patch("src.postgres_connector.psycopg.connect", return_value=mock_conn):
        response = client.post(
            "/connectors/postgres/test",
            json={
                "host": "localhost",
                "port": 5433,
                "database": "aurum",
                "username": "aurum",
                "password": "super-secret-password",
                "project_id": project_id,
            },
        )
    assert response.status_code == 200
    connection_id = response.json()["connection_id"]

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM data_connections WHERE id = ?",
            (connection_id,),
        ).fetchone()
        dump = str(dict(row)) if row else ""
    assert row is not None
    assert "super-secret-password" not in dump
    assert "password" not in row.keys()
