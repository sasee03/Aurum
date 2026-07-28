from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.main import app
from src.app_state.db import compute_rule_revision, get_connection
from src.silver_rules import (
    PostgresColumnType,
    SilverRuleError,
    build_deterministic_silver_sql,
    validate_deterministic_rules,
)


def _type(name, *, schema="pg_catalog", kind="b"):
    return PostgresColumnType(
        type_oid=100,
        type_schema=schema,
        type_name=name,
        type_kind=kind,
    )


@pytest.mark.parametrize(
    ("type_name", "operator", "value"),
    [
        ("int4", ">=", 10),
        ("numeric", "<", 12.5),
        ("text", "=", "abc"),
        ("bool", "=", True),
        ("uuid", "=", "12345678-1234-5678-1234-567812345678"),
    ],
)
def test_compare_accepts_explicit_compatible_builtin_types(
    type_name,
    operator,
    value,
):
    rules = validate_deterministic_rules(
        [
            {
                "type": "compare",
                "column": "value",
                "operator": operator,
                "value": value,
            }
        ],
        available_columns={"value"},
        column_types={"value": _type(type_name)},
    )
    assert rules[0]["value"] == value


@pytest.mark.parametrize(
    ("column_type", "operator", "value", "message"),
    [
        (_type("int4"), ">=", "not-a-number", "JSON numeric"),
        (_type("bool"), ">", True, "supports only"),
        (_type("text"), ">=", 123, "JSON string"),
        (_type("uuid"), "=", "garbage", "valid UUID"),
        (_type("jsonb"), ">", "abc", "unsupported"),
        (
            _type("custom_type", schema="tenant"),
            "=",
            "value",
            "non-built-in",
        ),
        (_type("enum_type", schema="tenant", kind="e"), "=", "x", "non-built-in"),
    ],
)
def test_compare_rejects_incompatible_or_unsupported_types(
    column_type,
    operator,
    value,
    message,
):
    with pytest.raises(SilverRuleError, match=message):
        validate_deterministic_rules(
            [
                {
                    "type": "compare",
                    "column": "value",
                    "operator": operator,
                    "value": value,
                }
            ],
            available_columns={"value"},
            column_types={"value": column_type},
        )


def test_rule_for_unknown_column_is_rejected():
    with pytest.raises(SilverRuleError, match="does not exist"):
        validate_deterministic_rules(
            [{"type": "not_null", "column": "fabricated"}],
            available_columns={"actual"},
        )


def test_deterministic_compiler_quotes_identifiers_and_literals():
    column = 'value"quoted'
    literal = "x'; DROP TABLE bronze.arbitrary; --"
    rules = validate_deterministic_rules(
        [
            {
                "type": "compare",
                "column": column,
                "operator": "=",
                "value": literal,
            }
        ],
        available_columns={column},
        column_types={column: _type("text")},
    )

    sql = build_deterministic_silver_sql(
        candidate_schema="silver_candidates",
        candidate_name="arbitrary_candidate_run_rules",
        bronze_schema="bronze",
        bronze_relation="arbitrary",
        rules=rules,
    )

    assert '"value""quoted"' in sql
    assert "DROP TABLE" in sql
    assert sql.count("CREATE TABLE") == 1
    assert len(compute_rule_revision(rules)) == 64


class _CatalogCursor:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchall(self):
        return list(self.rows)


class _CatalogConnection:
    def __init__(self, cursor):
        self.cursor_value = cursor

    def cursor(self):
        return self.cursor_value


class _CatalogContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *args):
        return None


class _CatalogPool:
    def __init__(self, rows):
        self.cursor = _CatalogCursor(rows)
        self.acquisitions = 0

    def connection(self):
        self.acquisitions += 1
        return _CatalogContext(_CatalogConnection(self.cursor))


class _BarePool:
    def __init__(self, connection):
        self.connection_value = connection

    def connection(self):
        return _CatalogContext(self.connection_value)


def _identity(*, schema, table, relation_oid, namespace_oid, database_oid=101):
    return {
        "database_oid": database_oid,
        "namespace_oid": namespace_oid,
        "relation_oid": relation_oid,
        "schema": schema,
        "relation_name": table,
        "relation_kind": "r",
    }


def _session_connection(database="aurum"):
    from src.postgres_connector import (
        UserPostgresTarget,
        clear_session_connections,
        store_session_connection,
    )

    clear_session_connections()
    return store_session_connection(
        UserPostgresTarget(
            host="127.0.0.1",
            port=5432,
            database=database,
            username="aurum",
            password="secret-never-persist",
        ),
        project_id="project_1",
        name="test connector",
    )


def _save_connector_bronze_authority(
    *,
    connection_id,
    source_schema="schema_b",
    source_table="orders",
    bronze_schema="bronze",
    bronze_table="orders",
    database_name="aurum",
    database_oid=101,
    ingest_id="bronze_ready_1",
    source_relation_oid=201,
    bronze_relation_oid=301,
    project_id="project_1",
):
    now = "2026-07-29T00:00:00+00:00"
    source_identity = _identity(
        schema=source_schema,
        table=source_table,
        relation_oid=source_relation_oid,
        namespace_oid=21,
        database_oid=database_oid,
    )
    bronze_identity = _identity(
        schema=bronze_schema,
        table=bronze_table,
        relation_oid=bronze_relation_oid,
        namespace_oid=31,
        database_oid=database_oid,
    )
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO projects (
                id, name, description, environment, created_at, updated_at, status
            )
            VALUES (?, 'Project', '', 'Test', ?, ?, 'active')
            """,
            (project_id, now, now),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO data_connections (
                id, project_id, type, name, host, port, database_name,
                username, status, created_at, updated_at
            )
            VALUES (?, ?, 'postgresql', 'test connector', '127.0.0.1',
                    5432, ?, 'aurum', 'active', ?, ?)
            """,
            (connection_id, project_id, database_name, now, now),
        )
        conn.execute(
            """
            INSERT INTO bronze_ingest_authority (
                ingest_id, project_id, connection_id, database_name,
                source_schema, source_relation, source_identity_json,
                bronze_schema, bronze_relation, bronze_identity_json,
                status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'READY', ?, ?)
            """,
            (
                ingest_id,
                project_id,
                connection_id,
                database_name,
                source_schema,
                source_table,
                json.dumps(source_identity, sort_keys=True, separators=(",", ":")),
                bronze_schema,
                bronze_table,
                json.dumps(bronze_identity, sort_keys=True, separators=(",", ":")),
                now,
                now,
            ),
        )
        conn.commit()
    return source_identity, bronze_identity


def _save_deterministic_orders_rule(client):
    response = client.post(
        "/api/v1/transform/rules",
        json={
            "table_name": "orders",
            "rules": [{"type": "not_null", "column": "id"}],
        },
    )
    assert response.status_code == 200


def _patch_connector_generation_catalog(
    monkeypatch,
    *,
    session_database_identity=(101, "aurum"),
    aurum_database_identity=None,
    identities=None,
):
    import api.bronze_silver_router as router

    calls = []
    identities = identities or {}
    aurum_database_identity = aurum_database_identity or session_database_identity
    session_connection = object()
    execution_connection = object()

    monkeypatch.setattr(
        router,
        "_database_identity",
        lambda conn: (
            session_database_identity
            if conn is session_connection
            else aurum_database_identity
        ),
    )
    monkeypatch.setattr(
        router,
        "open_session_connection",
        lambda _session: _CatalogContext(session_connection),
    )
    monkeypatch.setattr(
        router,
        "get_generated_sql_pool",
        lambda: _BarePool(execution_connection),
    )
    monkeypatch.setattr(
        router,
        "_load_exact_bronze_column_types",
        lambda _identity: {"id": _type("int4")},
    )

    def fake_resolve(_conn, schema, table):
        calls.append((schema, table))
        return identities.get((schema, table))

    monkeypatch.setattr(router, "resolve_relation_identity", fake_resolve)
    return calls


def test_connector_bound_silver_generation_uses_exact_bronze_authority(
    isolated_app_state_db,
    monkeypatch,
):
    client = TestClient(app)
    session = _session_connection()
    source_identity, bronze_identity = _save_connector_bronze_authority(
        connection_id=session.connection_id,
    )
    calls = _patch_connector_generation_catalog(
        monkeypatch,
        identities={
            ("schema_b", "orders"): source_identity,
            ("bronze", "orders"): bronze_identity,
        },
    )
    _save_deterministic_orders_rule(client)

    response = client.post(
        "/api/v1/transform/generate",
        json={
            "table_name": "orders",
            "connection_id": session.connection_id,
            "source": {"schema": "schema_b", "table": "orders"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["connection_id"] == session.connection_id
    assert body["source"]["schema"] == "schema_b"
    assert body["bronze"]["schema"] == "bronze"
    assert body["bronze"]["identity"] == bronze_identity
    assert body["silver"] == {"schema": "silver", "table": "orders"}
    assert '"bronze"."orders"' in body["sql_text"]
    assert ("schema_b", "orders") in calls
    assert ("bronze", "orders") in calls

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT project_id, connection_id, source_identity_json, silver_lineage_id
            FROM generated_sql_review
            WHERE run_id = ?
            """,
            (body["run_id"],),
        ).fetchone()
    assert row["project_id"] == "project_1"
    assert row["connection_id"] == session.connection_id
    assert row["connection_id"] != "default_connection"
    assert json.loads(row["source_identity_json"]) == bronze_identity
    assert len(row["silver_lineage_id"]) == 64


def test_connector_bound_silver_generation_never_falls_back_by_table_name(
    isolated_app_state_db,
    monkeypatch,
):
    client = TestClient(app)
    session = _session_connection()
    source_identity, bronze_identity = _save_connector_bronze_authority(
        connection_id=session.connection_id,
        source_schema="schema_b",
        source_table="orders",
    )
    calls = _patch_connector_generation_catalog(
        monkeypatch,
        identities={
            ("schema_b", "orders"): source_identity,
            ("bronze", "orders"): bronze_identity,
        },
    )
    _save_deterministic_orders_rule(client)

    response = client.post(
        "/api/v1/transform/generate",
        json={
            "table_name": "orders",
            "connection_id": session.connection_id,
            "source": {"schema": "schema_a", "table": "orders"},
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "connector_bronze_authority_not_found"
    assert calls == []


def test_connector_bound_silver_generation_rejects_invalid_or_stale_connection(
    isolated_app_state_db,
    monkeypatch,
):
    client = TestClient(app)
    _patch_connector_generation_catalog(monkeypatch)
    _save_deterministic_orders_rule(client)

    invalid = client.post(
        "/api/v1/transform/generate",
        json={
            "table_name": "orders",
            "connection_id": "conn_missing",
            "source": {"schema": "schema_b", "table": "orders"},
        },
    )
    assert invalid.status_code == 404
    assert invalid.json()["detail"]["error"] == "connection_not_found"

    from src.postgres_connector import SESSION_TTL_SECONDS, get_session_connection

    session = _session_connection()
    session.created_at_monotonic -= SESSION_TTL_SECONDS + 1
    assert get_session_connection(session.connection_id) is None
    stale = client.post(
        "/api/v1/transform/generate",
        json={
            "table_name": "orders",
            "connection_id": session.connection_id,
            "source": {"schema": "schema_b", "table": "orders"},
        },
    )
    assert stale.status_code == 404
    assert stale.json()["detail"]["error"] == "connection_not_found"


def test_connector_bound_silver_generation_rejects_authority_database_identity_mismatch(
    isolated_app_state_db,
    monkeypatch,
):
    client = TestClient(app)
    session = _session_connection()
    _save_connector_bronze_authority(connection_id=session.connection_id)
    _patch_connector_generation_catalog(
        monkeypatch,
        session_database_identity=(999, "aurum"),
        aurum_database_identity=(999, "aurum"),
    )
    _save_deterministic_orders_rule(client)

    response = client.post(
        "/api/v1/transform/generate",
        json={
            "table_name": "orders",
            "connection_id": session.connection_id,
            "source": {"schema": "schema_b", "table": "orders"},
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "connector_bronze_database_mismatch"


def test_connector_bound_silver_generation_rejects_non_aurum_database_without_fallback(
    isolated_app_state_db,
    monkeypatch,
):
    client = TestClient(app)
    session = _session_connection()
    calls = _patch_connector_generation_catalog(
        monkeypatch,
        session_database_identity=(101, "aurum_connector"),
        aurum_database_identity=(202, "aurum_managed"),
    )

    response = client.post(
        "/api/v1/transform/generate",
        json={
            "table_name": "orders",
            "connection_id": session.connection_id,
            "source": {"schema": "schema_b", "table": "orders"},
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "CONNECTOR_DATABASE_NOT_AURUM_DATABASE"
    assert calls == []


def test_connector_bound_silver_generation_rejects_table_name_mismatch(
    isolated_app_state_db,
    monkeypatch,
):
    client = TestClient(app)
    session = _session_connection()
    source_identity, bronze_identity = _save_connector_bronze_authority(
        connection_id=session.connection_id,
    )
    _patch_connector_generation_catalog(
        monkeypatch,
        identities={
            ("schema_b", "orders"): source_identity,
            ("bronze", "orders"): bronze_identity,
        },
    )

    response = client.post(
        "/api/v1/transform/generate",
        json={
            "table_name": "customers",
            "connection_id": session.connection_id,
            "source": {"schema": "schema_b", "table": "orders"},
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "connector_table_authority_mismatch"


@pytest.mark.parametrize(
    ("live_bronze", "status_code", "error"),
    [
        (None, 404, "bronze_target_missing"),
        (
            _identity(
                schema="bronze",
                table="orders",
                relation_oid=999,
                namespace_oid=31,
            ),
            409,
            "bronze_identity_changed",
        ),
    ],
)
def test_connector_bound_silver_generation_rejects_missing_or_replaced_bronze_target(
    isolated_app_state_db,
    monkeypatch,
    live_bronze,
    status_code,
    error,
):
    client = TestClient(app)
    session = _session_connection()
    source_identity, _bronze_identity = _save_connector_bronze_authority(
        connection_id=session.connection_id,
    )
    _patch_connector_generation_catalog(
        monkeypatch,
        identities={
            ("schema_b", "orders"): source_identity,
            ("bronze", "orders"): live_bronze,
        },
    )
    _save_deterministic_orders_rule(client)

    response = client.post(
        "/api/v1/transform/generate",
        json={
            "table_name": "orders",
            "connection_id": session.connection_id,
            "source": {"schema": "schema_b", "table": "orders"},
        },
    )

    assert response.status_code == status_code
    assert response.json()["detail"]["error"] == error


def test_incompatible_compare_is_rejected_before_claim_or_ctas(
    isolated_app_state_db,
    monkeypatch,
):
    import api.bronze_silver_router as router

    run_id = "run_type_guard"
    table_name = "arbitrary"
    source_identity = {
        "database_oid": 11,
        "namespace_oid": 22,
        "relation_oid": 33,
        "schema": "bronze",
        "relation_name": table_name,
        "relation_kind": "r",
    }
    rules = [
        {
            "type": "compare",
            "column": "quantity",
            "operator": ">=",
            "value": "not-a-number",
        }
    ]
    rule_revision = compute_rule_revision(rules)
    assert rule_revision is not None
    sql_text = build_deterministic_silver_sql(
        candidate_schema="silver_candidates",
        candidate_name=f"{table_name}_candidate_{run_id}",
        bronze_schema="bronze",
        bronze_relation=table_name,
        rules=rules,
    )
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO table_rules (
                table_name, rules_json, rule_revision, updated_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                table_name,
                json.dumps(rules, sort_keys=True, separators=(",", ":")),
                rule_revision,
                "2026-07-26T00:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO generated_sql_review (
                run_id, table_name, sql_text, planned_changes_json,
                created_at, status, candidate_schema, generator_provenance,
                rule_revision, project_id, connection_id, silver_lineage_id,
                source_identity_json
            )
            VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                table_name,
                sql_text,
                json.dumps(
                    {"rules": rules},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "2026-07-26T00:00:00+00:00",
                "silver_candidates",
                router.SERVER_DETERMINISTIC_PROVENANCE,
                rule_revision,
                "project",
                "connection",
                "lineage",
                json.dumps(
                    source_identity,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
        conn.commit()

    pool = _CatalogPool(
        [
            (
                11,
                22,
                33,
                "bronze",
                table_name,
                "r",
                "quantity",
                23,
                "pg_catalog",
                "int4",
                "b",
            )
        ]
    )
    monkeypatch.setattr(router, "get_generated_sql_pool", lambda: pool)
    client = TestClient(app)

    response = client.post(f"/api/v1/transform/execute/{run_id}")

    assert response.status_code == 422
    assert "JSON numeric" in response.json()["detail"]
    with get_connection() as conn:
        status = conn.execute(
            "SELECT status FROM generated_sql_review WHERE run_id = ?",
            (run_id,),
        ).fetchone()["status"]
    assert status == "PENDING"
    assert pool.acquisitions == 1
    assert any(
        "pg_catalog.pg_type" in statement
        for statement, _ in pool.cursor.statements
    )
