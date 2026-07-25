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
