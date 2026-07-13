"""Tests for user-supplied Postgres connector endpoints."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pandas as pd
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

import api.main as api_main
from src.app_state.db import get_connection
from src.csv_ingest import MAX_UPLOAD_ROWS, RAW_ORDERS_COLUMNS
from src.db_config import postgres_conninfo
from src.postgres_connector import (
    SESSION_TTL_SECONDS,
    UserPostgresTarget,
    build_user_conninfo,
    clear_session_connections,
    classify_connect_error,
    get_session_connection,
    store_session_connection,
    test_user_postgres as check_user_postgres,
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


def _sqlite_validation_counts() -> tuple[int, int]:
    with get_connection() as conn:
        runs = conn.execute("SELECT COUNT(*) FROM validation_runs").fetchone()[0]
        reports = conn.execute("SELECT COUNT(*) FROM validation_reports").fetchone()[0]
    return int(runs), int(reports)


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


@pytest.mark.parametrize(
    "password",
    ["contains space", "single'quote", "back\\slash", "equals=sign", ""],
)
def test_build_user_conninfo_quotes_special_character_passwords(password):
    target = UserPostgresTarget("localhost", 5433, "aurum", "aurum", password)

    parsed = conninfo_to_dict(build_user_conninfo(target))

    assert parsed["password"] == password


def test_real_postgres_connects_with_special_character_password(caplog):
    role = f"aurum_conninfo_{uuid4().hex}"
    password = "space quote' slash\\ equals="
    wrong_password = "wrong secret' \\ ="

    with psycopg.connect(postgres_conninfo(), autocommit=True) as admin:
        target = UserPostgresTarget(
            admin.info.host,
            admin.info.port,
            admin.info.dbname,
            role,
            password,
        )
        try:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )

            result = check_user_postgres(target)
            assert result["connected"] is True

            wrong_target = UserPostgresTarget(
                target.host,
                target.port,
                target.database,
                target.username,
                wrong_password,
            )
            with pytest.raises(psycopg.OperationalError) as exc_info:
                psycopg.connect(build_user_conninfo(wrong_target))
            assert password not in str(exc_info.value)
            assert wrong_password not in str(exc_info.value)

            failed = check_user_postgres(wrong_target)
            assert failed["connected"] is False
            assert password not in str(failed)
            assert wrong_password not in str(failed)
            assert password not in caplog.text
            assert wrong_password not in caplog.text
        finally:
            admin.execute(
                sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role))
            )


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


def test_validate_post_parse_failure_returns_clean_error(client, monkeypatch):
    session = store_session_connection(
        UserPostgresTarget(
            host="localhost",
            port=5433,
            database="aurum",
            username="aurum",
            password="aurum",
        )
    )
    monkeypatch.setattr(
        "api.connectors_router.api_main._database_reachable", lambda: True
    )
    monkeypatch.setattr(
        "api.connectors_router.load_and_validate_user_table",
        lambda *args, **kwargs: _olist_frame(5),
    )

    def fail_after_parse(*args, **kwargs):
        raise RuntimeError("connector engine unavailable after parse")

    monkeypatch.setattr(
        "api.connectors_router.run_validation_from_raw_orders", fail_after_parse
    )
    runs_before, reports_before = _sqlite_validation_counts()

    response = client.post(
        "/connectors/postgres/validate",
        json={
            "connection_id": session.connection_id,
            "schema": "public",
            "table": "raw_orders",
        },
    )

    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "connector_validation_failed"
    assert "matched the expected schema" in body["message"]
    assert "detail" not in body
    assert "connector engine unavailable after parse" not in str(body)
    runs_after, reports_after = _sqlite_validation_counts()
    assert runs_after == runs_before
    assert reports_after == reports_before


def test_connector_validation_bounds_optional_narrative_wait(client):
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
    ), patch(
        "api.connectors_router.attach_trust_narrative",
        side_effect=lambda report, **_: report,
    ) as attach_narrative:
        response = client.post(
            "/connectors/postgres/validate",
            json={
                "connection_id": session.connection_id,
                "schema": "public",
                "table": "raw_orders",
            },
        )

    assert response.status_code == 200
    assert attach_narrative.call_args.kwargs["timeout_seconds"] == 15


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


def test_test_connection_metadata_save_failure(client, monkeypatch):
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = (1,)

    project = client.post(
        "/projects",
        json={"name": "Fail Save Project", "environment": "Development"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    def fail_save(*args, **kwargs):
        raise Exception("sqlite disk full or locked")

    monkeypatch.setattr("api.connectors_router.save_data_connection", fail_save)

    with patch("src.postgres_connector.psycopg.connect", return_value=mock_conn):
        response = client.post(
            "/connectors/postgres/test",
            json={
                "host": "localhost",
                "port": 5433,
                "database": "aurum",
                "username": "aurum",
                "password": "aurum",
                "project_id": project_id,
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert "Connection succeeded, but saving connection metadata failed" in body["error"]


def test_validate_count_timeout_honest_422(client, monkeypatch):
    import psycopg
    session = store_session_connection(
        UserPostgresTarget(
            host="localhost",
            port=5433,
            database="aurum",
            username="aurum",
            password="aurum",
        )
    )

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    def mock_cursor_enter(*args, **kwargs):
        mock_cur = MagicMock()
        def mock_execute(query, *a, **kw):
            if "SELECT COUNT(*)" in str(query):
                raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")
        mock_cur.execute.side_effect = mock_execute
        return mock_cur

    mock_conn.cursor.return_value.__enter__ = mock_cursor_enter
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(
        "src.postgres_connector.open_session_connection",
        MagicMock(return_value=mock_conn),
    )
    monkeypatch.setattr(
        "src.postgres_connector.list_tables",
        MagicMock(return_value=[{"schema": "public", "name": "orders", "type": "table"}]),
    )

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
    assert "Table row count could not be determined" in body["error"]
    assert "too large" in body["error"]
