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
import src.config_loader as config_loader
from src.app_state.db import get_connection
from src.csv_ingest import MAX_UPLOAD_ROWS
from src.config_loader import load_dataset_config
from src.db_config import postgres_conninfo
from src.config_loader import load_dataset_config
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
def client(monkeypatch):
    monkeypatch.setattr(
        "api.connectors_router.resolve_config_for_project_or_table",
        lambda _project_id, _table: load_dataset_config(),
    )
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


def test_connector_without_custom_config_refuses_olist_before_load(client, monkeypatch):
    session = store_session_connection(
        UserPostgresTarget(
            host="localhost",
            port=5433,
            database="aurum",
            username="aurum",
            password="aurum",
        )
    )
    load_table = MagicMock()
    monkeypatch.setattr(
        "api.connectors_router.resolve_config_for_project_or_table",
        config_loader.resolve_config_for_project_or_table,
    )
    monkeypatch.setattr("api.connectors_router.load_and_validate_user_table", load_table)

    response = client.post(
        "/connectors/postgres/validate",
        json={
            "connection_id": session.connection_id,
            "schema": "public",
            "table": "no_such_config",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"] == "dataset_config_not_found"
    assert "refusing to substitute" in response.json()["message"]
    load_table.assert_not_called()


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
    assert body["expected_columns"] == load_dataset_config().columns.resolve_raw_required_columns()
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


def test_validate_success_persists_connector_mode(client, schema_tracker):
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
    schema_tracker.track_run(report["run_id"])
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


def test_connector_validation_bounds_optional_narrative_wait(client, schema_tracker):
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
    schema_tracker.track_run(response.json()["run_id"])
    assert attach_narrative.call_args.kwargs["timeout_seconds"] == 15


def test_validate_returns_exactly_17_key_report(client, schema_tracker):
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
    schema_tracker.track_run(report["run_id"])
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


def test_preview_endpoint(client):
    """
    Test the preview endpoint hits a real Postgres table, validates actual content,
    and returns correct column types directly from the database connection.
    """
    import psycopg
    from uuid import uuid4
    from src.postgres_connector import UserPostgresTarget, build_user_conninfo

    target = UserPostgresTarget(
        host="localhost",
        port=5433,
        database="aurum",
        username="aurum",
        password="aurum",
    )
    session = store_session_connection(target)
    conninfo = build_user_conninfo(target)

    table_name = f"test_preview_{uuid4().hex[:8]}"

    try:
        with psycopg.connect(conninfo, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f"CREATE TABLE {table_name} (id INT, name TEXT)")
                cur.execute(f"INSERT INTO {table_name} VALUES (1, 'Alice'), (2, 'Bob')")

        response = client.get(
            f"/connectors/postgres/tables/{table_name}/preview?connection_id={session.connection_id}&schema=public"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["connection_id"] == session.connection_id
        assert body["schema"] == "public"
        assert body["table"] == table_name

        # Verify metadata
        metadata = body["metadata"]
        assert metadata["row_count"] == 2
        assert metadata["column_count"] == 2

        # Verify types
        columns = {c["name"]: c for c in metadata["columns"]}
        assert columns["id"]["data_type"] == "integer"
        assert columns["name"]["data_type"] == "text"

        # Verify actual data returned
        data = body["data"]
        assert len(data) == 2

        # Find Alice row
        alice_row = next(row for row in data if row["id"] == 1)
        assert alice_row["name"] == "Alice"

    finally:
        try:
            with psycopg.connect(conninfo, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"DROP TABLE IF EXISTS {table_name}")
        except Exception:
            pass


class _FakeConnectionContext:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnectorConn:
    pass


def _identity(
    *,
    database_oid: int = 101,
    namespace_oid: int,
    relation_oid: int,
    schema: str,
    table: str,
    relation_kind: str = "r",
) -> dict:
    return {
        "database_oid": database_oid,
        "namespace_oid": namespace_oid,
        "relation_oid": relation_oid,
        "schema": schema,
        "relation_name": table,
        "relation_kind": relation_kind,
    }


def _connector_bronze_session(password: str = "aurum") -> str:
    session = store_session_connection(
        UserPostgresTarget(
            host="localhost",
            port=5433,
            database="aurum",
            username="aurum",
            password=password,
        )
    )
    return session.connection_id


def _patch_connector_bronze_happy_path(monkeypatch, *, source_schema: str, source_table: str):
    fake_conn = _FakeConnectorConn()
    state = {
        "bronze_exists": False,
        "source_database_oid": 101,
        "source_namespace_oid": 201,
        "source_relation_oid": 301,
        "bronze_database_oid": 101,
        "bronze_namespace_oid": 202,
        "bronze_relation_oid": 302,
    }
    copied: dict = {"_state": state}

    def fake_list_user_tables(_conn, schema=None):
        if schema == source_schema:
            return [
                {"schema": source_schema, "table": source_table, "layer": "unknown"},
                {"schema": "other_schema", "table": source_table, "layer": "unknown"},
            ]
        return []

    def fake_resolve(_conn, schema, table):
        if schema == source_schema and table == source_table:
            return _identity(
                database_oid=state["source_database_oid"],
                namespace_oid=state["source_namespace_oid"],
                relation_oid=state["source_relation_oid"],
                schema=schema,
                table=table,
            )
        if schema == "bronze" and table == source_table and state["bronze_exists"]:
            return _identity(
                database_oid=state["bronze_database_oid"],
                namespace_oid=state["bronze_namespace_oid"],
                relation_oid=state["bronze_relation_oid"],
                schema=schema,
                table=table,
            )
        return None

    def fake_copy(_conn, **kwargs):
        copied.update(kwargs)
        state["bronze_exists"] = True
        return {
            "source_row_count": 3,
            "bronze_row_count": 3,
            "match": True,
            "bronze_identity": _identity(
                database_oid=state["bronze_database_oid"],
                namespace_oid=state["bronze_namespace_oid"],
                relation_oid=state["bronze_relation_oid"],
                schema=kwargs["bronze_schema"],
                table=kwargs["bronze_table"],
            ),
        }

    monkeypatch.setattr(
        "api.connectors_router.open_session_connection",
        lambda _session: _FakeConnectionContext(fake_conn),
    )
    monkeypatch.setattr(
        "api.connectors_router._open_managed_ingestion_connection",
        lambda: _FakeConnectionContext(fake_conn),
    )
    monkeypatch.setattr("api.connectors_router._database_identity", lambda _conn: (101, "aurum"))
    monkeypatch.setattr("api.connectors_router._namespace_oid", lambda _conn, _schema: 202)
    monkeypatch.setattr("api.connectors_router.list_user_tables", fake_list_user_tables)
    monkeypatch.setattr("api.connectors_router.resolve_relation_identity", fake_resolve)
    monkeypatch.setattr("api.connectors_router._copy_relation_to_bronze", fake_copy)
    return copied


def _patch_connector_bronze_verify_counts(
    monkeypatch,
    *,
    source_rows: int = 3,
    bronze_rows: int = 3,
):
    counted = []

    def fake_count(_conn, *, schema_name: str, table_name: str):
        counted.append((schema_name, table_name))
        if schema_name == "bronze":
            return bronze_rows
        return source_rows

    monkeypatch.setattr("api.connectors_router._count_relation_rows", fake_count)
    return counted


def test_connector_preview_uses_exact_selected_schema_and_never_falls_back(client, monkeypatch):
    connection_id = _connector_bronze_session()
    fake_conn = _FakeConnectorConn()
    discover = MagicMock()
    monkeypatch.setattr(
        "api.connectors_router.open_session_connection",
        lambda _session: _FakeConnectionContext(fake_conn),
    )
    monkeypatch.setattr(
        "api.connectors_router.list_user_tables",
        lambda _conn, schema=None: [
            {"schema": "public", "table": "online_retail_uci", "layer": "unknown"}
        ] if schema == "public" else [],
    )
    monkeypatch.setattr("api.connectors_router.discover_table_metadata", discover)

    response = client.get(
        f"/connectors/postgres/tables/online_retail_uci/preview?connection_id={connection_id}&schema=source"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "source_relation_not_found"
    assert response.json()["detail"]["source"] == {
        "schema": "source",
        "table": "online_retail_uci",
    }
    discover.assert_not_called()


def test_connector_bound_bronze_copy_uses_managed_ingestion_role_not_connector_session(client, monkeypatch):
    connection_id = _connector_bronze_session(password="source-reader-only")
    session_conn = _FakeConnectorConn()
    managed_conn = _FakeConnectorConn()
    copied = {}

    monkeypatch.setattr(
        "api.connectors_router.open_session_connection",
        lambda _session: _FakeConnectionContext(session_conn),
    )
    monkeypatch.setattr(
        "api.connectors_router._open_managed_ingestion_connection",
        lambda: _FakeConnectionContext(managed_conn),
    )
    monkeypatch.setattr(
        "api.connectors_router._database_identity",
        lambda _conn: (101, "aurum"),
    )
    monkeypatch.setattr("api.connectors_router._namespace_oid", lambda _conn, _schema: 202)
    monkeypatch.setattr(
        "api.connectors_router.list_user_tables",
        lambda _conn, schema=None: [
            {"schema": "source", "table": "online_retail_uci", "layer": "source"}
        ],
    )

    def fake_resolve(_conn, schema, table):
        if schema == "source" and table == "online_retail_uci":
            return _identity(namespace_oid=201, relation_oid=301, schema=schema, table=table)
        return None

    def fake_copy(conn, **kwargs):
        copied["conn"] = conn
        copied.update(kwargs)
        return {
            "source_row_count": 541_909,
            "bronze_row_count": 541_909,
            "match": True,
            "bronze_identity": _identity(
                namespace_oid=202,
                relation_oid=302,
                schema="bronze",
                table="online_retail_uci",
            ),
        }

    monkeypatch.setattr("api.connectors_router.resolve_relation_identity", fake_resolve)
    monkeypatch.setattr("api.connectors_router._copy_relation_to_bronze", fake_copy)

    response = client.post(
        "/connectors/postgres/bronze/ingest",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "source", "table": "online_retail_uci"}],
        },
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "success"
    assert result["source_row_count"] == 541_909
    assert result["bronze_row_count"] == 541_909
    assert copied["conn"] is managed_conn
    assert copied["conn"] is not session_conn
    assert copied["source_schema"] == "source"
    assert copied["source_table"] == "online_retail_uci"


def test_connector_bound_bronze_ingests_exact_selected_relation(client, monkeypatch):
    connection_id = _connector_bronze_session(password="secret-never-return")
    copied = _patch_connector_bronze_happy_path(
        monkeypatch,
        source_schema="tenant_a",
        source_table="events",
    )

    response = client.post(
        "/connectors/postgres/bronze/ingest",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "tenant_a", "table": "events"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    result = body["results"][0]
    assert result["status"] == "success"
    assert result["connection_id"] == connection_id
    assert result["source"] == {"schema": "tenant_a", "table": "events"}
    assert result["bronze"] == {"schema": "bronze", "table": "events"}
    assert result["source_row_count"] == 3
    assert result["bronze_row_count"] == 3
    assert result["row_count"] == 3
    assert copied["source_schema"] == "tenant_a"
    assert copied["source_table"] == "events"
    assert "secret-never-return" not in response.text
    assert "password" not in response.text.lower()


def test_connector_bound_bronze_preserves_schema_when_table_names_overlap(client, monkeypatch):
    connection_id = _connector_bronze_session()
    copied = _patch_connector_bronze_happy_path(
        monkeypatch,
        source_schema="tenant_b",
        source_table="orders",
    )
    monkeypatch.setenv("AURUM_SCHEMA_SOURCE", "configured_source_must_not_be_used")

    response = client.post(
        "/connectors/postgres/bronze/ingest",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "tenant_b", "table": "orders"}],
        },
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["source"] == {"schema": "tenant_b", "table": "orders"}
    assert copied["source_schema"] == "tenant_b"
    assert copied["source_schema"] != "configured_source_must_not_be_used"


def test_connector_bound_bronze_rejects_unknown_connection(client):
    response = client.post(
        "/connectors/postgres/bronze/ingest",
        json={
            "connection_id": "conn_missing",
            "relations": [{"schema": "public", "table": "orders"}],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "connection_not_found"


def test_connector_bound_bronze_rejects_expired_session(client):
    connection_id = _connector_bronze_session()
    session = get_session_connection(connection_id)
    assert session is not None
    session.created_at_monotonic -= SESSION_TTL_SECONDS + 1

    response = client.post(
        "/connectors/postgres/bronze/ingest",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "public", "table": "orders"}],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "connection_not_found"


def test_connector_bound_bronze_rejects_nonexistent_selected_relation(client, monkeypatch):
    connection_id = _connector_bronze_session()
    fake_conn = _FakeConnectorConn()
    copy = MagicMock()
    monkeypatch.setattr(
        "api.connectors_router.open_session_connection",
        lambda _session: _FakeConnectionContext(fake_conn),
    )
    monkeypatch.setattr(
        "api.connectors_router._open_managed_ingestion_connection",
        lambda: _FakeConnectionContext(fake_conn),
    )
    monkeypatch.setattr("api.connectors_router._database_identity", lambda _conn: (101, "aurum"))
    monkeypatch.setattr("api.connectors_router._namespace_oid", lambda _conn, _schema: 202)
    monkeypatch.setattr("api.connectors_router.list_user_tables", lambda _conn, schema=None: [])
    monkeypatch.setattr("api.connectors_router._copy_relation_to_bronze", copy)

    response = client.post(
        "/connectors/postgres/bronze/ingest",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "tenant_a", "table": "missing"}],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "source_relation_not_found"
    copy.assert_not_called()


def test_connector_bound_bronze_rejects_source_identity_from_other_database(client, monkeypatch):
    connection_id = _connector_bronze_session()
    fake_conn = _FakeConnectorConn()
    monkeypatch.setattr(
        "api.connectors_router.open_session_connection",
        lambda _session: _FakeConnectionContext(fake_conn),
    )
    monkeypatch.setattr(
        "api.connectors_router._open_managed_ingestion_connection",
        lambda: _FakeConnectionContext(fake_conn),
    )
    monkeypatch.setattr("api.connectors_router._database_identity", lambda _conn: (101, "aurum"))
    monkeypatch.setattr("api.connectors_router._namespace_oid", lambda _conn, _schema: 202)
    monkeypatch.setattr(
        "api.connectors_router.list_user_tables",
        lambda _conn, schema=None: [{"schema": "tenant_a", "table": "orders"}],
    )
    monkeypatch.setattr(
        "api.connectors_router.resolve_relation_identity",
        lambda _conn, schema, table: _identity(
            database_oid=999,
            namespace_oid=201,
            relation_oid=301,
            schema=schema,
            table=table,
        ),
    )

    response = client.post(
        "/connectors/postgres/bronze/ingest",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "tenant_a", "table": "orders"}],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "source_database_identity_mismatch"


def test_connector_bound_bronze_rejects_same_table_two_schema_target_collision(client):
    connection_id = _connector_bronze_session()

    response = client.post(
        "/connectors/postgres/bronze/ingest",
        json={
            "connection_id": connection_id,
            "relations": [
                {"schema": "tenant_a", "table": "orders"},
                {"schema": "tenant_b", "table": "orders"},
            ],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "bronze_target_name_collision"


def test_connector_bound_bronze_verify_uses_recorded_exact_source(client, monkeypatch):
    connection_id = _connector_bronze_session(password="secret-never-return")
    _patch_connector_bronze_happy_path(
        monkeypatch,
        source_schema="schema_b",
        source_table="orders",
    )
    counted = _patch_connector_bronze_verify_counts(monkeypatch)

    ingest = client.post(
        "/connectors/postgres/bronze/ingest",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_b", "table": "orders"}],
        },
    )
    assert ingest.status_code == 200

    response = client.post(
        "/connectors/postgres/bronze/verify",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_b", "table": "orders"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    result = body["results"][0]
    assert result["status"] == "success"
    assert result["source"] == {"schema": "schema_b", "table": "orders"}
    assert result["bronze"] == {"schema": "bronze", "table": "orders"}
    assert result["source_row_count"] == 3
    assert result["bronze_row_count"] == 3
    assert result["row_count"] == 3
    assert counted == [("schema_b", "orders"), ("bronze", "orders")]
    assert "secret-never-return" not in response.text
    assert "password" not in response.text.lower()


def test_connector_bound_bronze_verify_never_uses_configured_source(client, monkeypatch):
    connection_id = _connector_bronze_session()
    _patch_connector_bronze_happy_path(
        monkeypatch,
        source_schema="schema_b",
        source_table="orders",
    )
    counted = _patch_connector_bronze_verify_counts(monkeypatch)
    monkeypatch.setenv("AURUM_SCHEMA_SOURCE", "schema_a")

    ingest = client.post(
        "/connectors/postgres/bronze/ingest",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_b", "table": "orders"}],
        },
    )
    assert ingest.status_code == 200

    response = client.post(
        "/connectors/postgres/bronze/verify",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_b", "table": "orders"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["source"] == {
        "schema": "schema_b",
        "table": "orders",
    }
    assert ("schema_a", "orders") not in counted
    assert ("schema_b", "orders") in counted


def test_connector_bound_bronze_verify_rejects_wrong_requested_schema(client, monkeypatch):
    connection_id = _connector_bronze_session()
    _patch_connector_bronze_happy_path(
        monkeypatch,
        source_schema="schema_b",
        source_table="orders",
    )
    _patch_connector_bronze_verify_counts(monkeypatch)

    ingest = client.post(
        "/connectors/postgres/bronze/ingest",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_b", "table": "orders"}],
        },
    )
    assert ingest.status_code == 200

    response = client.post(
        "/connectors/postgres/bronze/verify",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_a", "table": "orders"}],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "connector_bronze_authority_not_found"


def test_connector_bound_bronze_verify_rejects_unknown_connection(client):
    response = client.post(
        "/connectors/postgres/bronze/verify",
        json={
            "connection_id": "conn_missing",
            "relations": [{"schema": "public", "table": "orders"}],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "connection_not_found"


def test_connector_bound_bronze_verify_rejects_expired_session(client):
    connection_id = _connector_bronze_session()
    session = get_session_connection(connection_id)
    assert session is not None
    session.created_at_monotonic -= SESSION_TTL_SECONDS + 1

    response = client.post(
        "/connectors/postgres/bronze/verify",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "public", "table": "orders"}],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "connection_not_found"


def test_connector_bound_bronze_verify_rejects_missing_authority(client, monkeypatch):
    connection_id = _connector_bronze_session()
    fake_conn = _FakeConnectorConn()
    monkeypatch.setattr(
        "api.connectors_router.open_session_connection",
        lambda _session: _FakeConnectionContext(fake_conn),
    )
    monkeypatch.setattr(
        "api.connectors_router._open_managed_ingestion_connection",
        lambda: _FakeConnectionContext(fake_conn),
    )
    monkeypatch.setattr("api.connectors_router._database_identity", lambda _conn: (101, "aurum"))

    response = client.post(
        "/connectors/postgres/bronze/verify",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_b", "table": "orders"}],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "connector_bronze_authority_not_found"


def test_connector_bound_bronze_verify_rejects_database_identity_mismatch(client, monkeypatch):
    connection_id = _connector_bronze_session()
    _patch_connector_bronze_happy_path(
        monkeypatch,
        source_schema="schema_b",
        source_table="orders",
    )
    _patch_connector_bronze_verify_counts(monkeypatch)

    ingest = client.post(
        "/connectors/postgres/bronze/ingest",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_b", "table": "orders"}],
        },
    )
    assert ingest.status_code == 200
    monkeypatch.setattr("api.connectors_router._database_identity", lambda _conn: (999, "other"))

    response = client.post(
        "/connectors/postgres/bronze/verify",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_b", "table": "orders"}],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "connector_bronze_database_mismatch"


def test_connector_bound_bronze_verify_rejects_changed_source_identity(client, monkeypatch):
    connection_id = _connector_bronze_session()
    copied = _patch_connector_bronze_happy_path(
        monkeypatch,
        source_schema="schema_b",
        source_table="orders",
    )
    _patch_connector_bronze_verify_counts(monkeypatch)

    ingest = client.post(
        "/connectors/postgres/bronze/ingest",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_b", "table": "orders"}],
        },
    )
    assert ingest.status_code == 200
    copied["_state"]["source_relation_oid"] = 999

    response = client.post(
        "/connectors/postgres/bronze/verify",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_b", "table": "orders"}],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "source_identity_changed"


def test_connector_bound_bronze_verify_rejects_missing_bronze_target(client, monkeypatch):
    connection_id = _connector_bronze_session()
    copied = _patch_connector_bronze_happy_path(
        monkeypatch,
        source_schema="schema_b",
        source_table="orders",
    )
    _patch_connector_bronze_verify_counts(monkeypatch)

    ingest = client.post(
        "/connectors/postgres/bronze/ingest",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_b", "table": "orders"}],
        },
    )
    assert ingest.status_code == 200
    copied["_state"]["bronze_exists"] = False

    response = client.post(
        "/connectors/postgres/bronze/verify",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_b", "table": "orders"}],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "bronze_target_missing"


def test_connector_bound_bronze_verify_rejects_replaced_bronze_target(client, monkeypatch):
    connection_id = _connector_bronze_session()
    copied = _patch_connector_bronze_happy_path(
        monkeypatch,
        source_schema="schema_b",
        source_table="orders",
    )
    _patch_connector_bronze_verify_counts(monkeypatch)

    ingest = client.post(
        "/connectors/postgres/bronze/ingest",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_b", "table": "orders"}],
        },
    )
    assert ingest.status_code == 200
    copied["_state"]["bronze_relation_oid"] = 999

    response = client.post(
        "/connectors/postgres/bronze/verify",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_b", "table": "orders"}],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "bronze_identity_changed"


def test_connector_bound_bronze_verify_reports_count_mismatch(client, monkeypatch):
    connection_id = _connector_bronze_session()
    _patch_connector_bronze_happy_path(
        monkeypatch,
        source_schema="schema_b",
        source_table="orders",
    )
    _patch_connector_bronze_verify_counts(monkeypatch, source_rows=3, bronze_rows=2)

    ingest = client.post(
        "/connectors/postgres/bronze/ingest",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_b", "table": "orders"}],
        },
    )
    assert ingest.status_code == 200

    response = client.post(
        "/connectors/postgres/bronze/verify",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_b", "table": "orders"}],
        },
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "error"
    assert result["match"] is False
    assert result["source_row_count"] == 3
    assert result["bronze_row_count"] == 2
    assert result["row_count"] is None


def test_connector_bound_bronze_verify_rejects_invalid_identifier(client):
    connection_id = _connector_bronze_session()

    response = client.post(
        "/connectors/postgres/bronze/verify",
        json={
            "connection_id": connection_id,
            "relations": [{"schema": "schema_b", "table": "orders; drop table x"}],
        },
    )

    assert response.status_code == 422


def test_connector_bound_bronze_legacy_verify_contract_unchanged(client):
    response = client.post(
        "/api/v1/source/verify-bronze",
        json={
            "connection_id": "conn_ignored_by_legacy_model",
            "relations": [{"schema": "tenant_a", "table": "orders"}],
            "tables": [],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "No tables specified."


def test_connector_bound_bronze_legacy_source_endpoint_contract_unchanged(client):
    response = client.post(
        "/api/v1/source/ingest-to-bronze",
        json={
            "connection_id": "conn_ignored_by_legacy_model",
            "relations": [{"schema": "tenant_a", "table": "orders"}],
            "tables": [],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "No tables selected for ingestion."
