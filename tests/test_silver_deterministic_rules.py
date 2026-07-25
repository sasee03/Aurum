"""Deterministic configured Silver plan compiler tests."""

from __future__ import annotations

import pytest

from src.app_state.db import compute_rule_revision
from src.silver_rules import (
    PostgresColumnType,
    SilverRuleError,
    build_deterministic_silver_sql,
    validate_deterministic_rules,
)
from src.sql_safety import SqlSafetyViolation, validate_generated_sql


def _compile(rules):
    sql = build_deterministic_silver_sql(
        candidate_schema="silver_candidates",
        candidate_name="arbitrary_candidate_run_rules",
        bronze_schema="bronze",
        bronze_relation="arbitrary",
        rules=rules,
    )
    return validate_generated_sql(
        sql,
        expected_schema="silver_candidates",
        expected_table_name="arbitrary",
        expected_bronze_schema="bronze",
        run_id="run_rules",
        expected_step_count=len(rules) + 1,
        mode="p2_silver",
    )


def _type(name, *, schema="pg_catalog", kind="b"):
    return PostgresColumnType(
        type_oid=100,
        type_schema=schema,
        type_name=name,
        type_kind=kind,
    )


def test_nonempty_generic_rule_plan_compiles_through_p2_policy():
    rules = validate_deterministic_rules(
        [
            {"type": "not_null", "column": "opaque_payload"},
            {
                "type": "compare",
                "column": "quality_measure",
                "operator": ">=",
                "value": 0,
            },
        ],
        available_columns={"opaque_payload", "quality_measure"},
    )
    sql = _compile(rules)
    assert '"opaque_payload" IS NULL' in sql
    assert '"quality_measure" >= 0' in sql
    assert len(compute_rule_revision(rules)) == 64


def test_explicit_zero_rule_plan_uses_same_compiler_and_policy():
    rules = validate_deterministic_rules([], available_columns={"anything"})
    sql = _compile(rules)
    assert "step_1" in sql
    assert "WHERE" not in sql
    assert compute_rule_revision(rules) == compute_rule_revision([])


@pytest.mark.parametrize(
    ("rules", "columns"),
    [
        ([{"type": "not_null", "column": "alpha"}], {"alpha", "beta"}),
        (
            [{"type": "compare", "column": "temperature", "operator": "<", "value": 50}],
            {"temperature", "captured_at"},
        ),
    ],
)
def test_unrelated_shapes_bind_only_configured_discovered_columns(
    rules, columns
):
    assert validate_deterministic_rules(
        rules, available_columns=columns
    ) == rules


def test_rule_for_unknown_column_is_rejected():
    with pytest.raises(SilverRuleError, match="does not exist"):
        validate_deterministic_rules(
            [{"type": "not_null", "column": "fabricated"}],
            available_columns={"actual"},
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
    type_name, operator, value
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
        (_type("int4"), ">=", "10", "JSON numeric"),
        (_type("bool"), ">", True, "supports only"),
        (_type("text"), ">=", 123, "JSON string"),
        (_type("uuid"), "=", "garbage", "valid UUID"),
        (_type("jsonb"), ">", "abc", "unsupported"),
        (_type("date"), ">=", "2026-07-25", "unsupported"),
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
    column_type, operator, value, message
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


def test_distinct_compiles_as_whole_row_deduplication():
    rules = validate_deterministic_rules([{"type": "distinct"}])
    sql = _compile(rules)
    assert "SELECT DISTINCT * FROM step_1" in sql


def test_hostile_column_and_literal_are_structurally_quoted():
    column = 'value" OR TRUE --'
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
    assert '"value"" OR TRUE --"' in sql
    assert "DROP TABLE" in sql
    assert sql.count("CREATE TABLE") == 1
    with pytest.raises(SqlSafetyViolation, match="comments"):
        validate_generated_sql(
            sql,
            expected_schema="silver_candidates",
            expected_table_name="arbitrary",
            expected_bronze_schema="bronze",
            run_id="run_rules",
            expected_step_count=2,
            mode="p2_silver",
        )
