from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from sqlglot import exp


class SilverRuleError(ValueError):
    """A configured Silver rule is malformed or cannot bind to its source."""


_COMPARE_OPERATORS = frozenset({"=", "!=", "<>", "<", "<=", ">", ">="})
_EQUALITY_OPERATORS = frozenset({"=", "!=", "<>"})
_NUMERIC_TYPES = frozenset(
    {"int2", "int4", "int8", "numeric", "float4", "float8"}
)
_TEXT_TYPES = frozenset({"text", "varchar", "bpchar"})


@dataclass(frozen=True)
class PostgresColumnType:
    """Exact trusted catalog type metadata for one Bronze column."""

    type_oid: int
    type_schema: str
    type_name: str
    type_kind: str


def _validate_compare_compatibility(
    *,
    column: str,
    operator: str,
    value: Any,
    column_types: Mapping[str, PostgresColumnType],
) -> None:
    column_type = column_types.get(column)
    if column_type is None:
        raise SilverRuleError(
            f"Silver rule column {column!r} has no trusted catalog type"
        )
    if (
        type(column_type.type_oid) is not int
        or column_type.type_oid <= 0
        or column_type.type_schema != "pg_catalog"
        or column_type.type_kind != "b"
    ):
        raise SilverRuleError(
            "compare is unsupported for non-built-in PostgreSQL type "
            f"{column_type.type_schema}.{column_type.type_name}"
        )
    type_name = column_type.type_name
    if type_name in _NUMERIC_TYPES:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SilverRuleError(
                f"compare on {type_name} requires a JSON numeric value"
            )
        return
    if type_name in _TEXT_TYPES:
        if not isinstance(value, str):
            raise SilverRuleError(
                f"compare on {type_name} requires a JSON string value"
            )
        return
    if type_name == "bool":
        if type(value) is not bool:
            raise SilverRuleError(
                "compare on bool requires a JSON boolean value"
            )
        if operator not in _EQUALITY_OPERATORS:
            raise SilverRuleError(
                "compare on bool supports only =, !=, and <>"
            )
        return
    if type_name == "uuid":
        if not isinstance(value, str):
            raise SilverRuleError(
                "compare on uuid requires a valid UUID string"
            )
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError):
            raise SilverRuleError(
                "compare on uuid requires a valid UUID string"
            ) from None
        return
    raise SilverRuleError(
        f"compare is unsupported for PostgreSQL type {type_name}"
    )


def _column(value: Any, *, available_columns: set[str] | None) -> str:
    if not isinstance(value, str) or not value:
        raise SilverRuleError("Silver rule column must be a non-empty string")
    if "\x00" in value or len(value.encode("utf-8")) > 63:
        raise SilverRuleError("Silver rule column is not a valid PostgreSQL identifier")
    if available_columns is not None and value not in available_columns:
        raise SilverRuleError(
            f"Silver rule column {value!r} does not exist in the exact Bronze relation"
        )
    return value


def _literal(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        raise SilverRuleError("Silver comparison value must be a non-null JSON scalar")
    if isinstance(value, float) and not math.isfinite(value):
        raise SilverRuleError("Silver comparison value must be finite")
    if not isinstance(value, (str, int, float, bool)):
        raise SilverRuleError("Silver comparison value has an unsupported type")
    return value


def validate_deterministic_rules(
    rules: Any,
    *,
    available_columns: Iterable[str] | None = None,
    column_types: Mapping[str, PostgresColumnType] | None = None,
) -> list[dict[str, Any]]:
    """Return a strict canonical rule list; an explicit empty list is valid."""
    if not isinstance(rules, list):
        raise SilverRuleError("Silver deterministic rules must be a list")
    available = set(available_columns) if available_columns is not None else None
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(rules):
        if not isinstance(raw, dict):
            raise SilverRuleError(
                f"Silver deterministic rule #{index + 1} must be an object"
            )
        rule_type = raw.get("type")
        if rule_type == "not_null":
            if set(raw) != {"type", "column"}:
                raise SilverRuleError("not_null rule has invalid keys")
            normalized.append(
                {
                    "type": "not_null",
                    "column": _column(
                        raw["column"], available_columns=available
                    ),
                }
            )
        elif rule_type == "compare":
            if set(raw) != {"type", "column", "operator", "value"}:
                raise SilverRuleError("compare rule has invalid keys")
            operator = raw["operator"]
            if not isinstance(operator, str) or operator not in _COMPARE_OPERATORS:
                raise SilverRuleError("compare rule operator is unsupported")
            column = _column(
                raw["column"], available_columns=available
            )
            value = _literal(raw["value"])
            if column_types is not None:
                _validate_compare_compatibility(
                    column=column,
                    operator=operator,
                    value=value,
                    column_types=column_types,
                )
            normalized.append(
                {
                    "type": "compare",
                    "column": column,
                    "operator": operator,
                    "value": value,
                }
            )
        elif rule_type == "distinct":
            if set(raw) != {"type"}:
                raise SilverRuleError("distinct rule has invalid keys")
            normalized.append({"type": "distinct"})
        else:
            raise SilverRuleError(
                f"Silver deterministic rule #{index + 1} has unsupported type"
            )
    return normalized


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def build_deterministic_silver_sql(
    *,
    candidate_schema: str,
    candidate_name: str,
    bronze_schema: str,
    bronze_relation: str,
    rules: list[dict[str, Any]],
) -> str:
    """Compile a validated rule snapshot into the existing sequential CTE policy."""
    normalized = validate_deterministic_rules(rules)
    steps = [
        "step_1 AS (SELECT * FROM "
        f"{_quote_identifier(bronze_schema)}.{_quote_identifier(bronze_relation)})"
    ]
    for index, rule in enumerate(normalized, start=2):
        previous = f"step_{index - 1}"
        if rule["type"] == "not_null":
            body = (
                f"SELECT * FROM {previous} WHERE "
                f"{_quote_identifier(rule['column'])} IS NOT NULL"
            )
        elif rule["type"] == "compare":
            literal = exp.convert(rule["value"]).sql(dialect="postgres")
            body = (
                f"SELECT * FROM {previous} WHERE "
                f"{_quote_identifier(rule['column'])} "
                f"{rule['operator']} {literal}"
            )
        else:
            body = f"SELECT DISTINCT * FROM {previous}"
        steps.append(f"step_{index} AS ({body})")
    final_step = f"step_{len(steps)}"
    return (
        f"CREATE TABLE {_quote_identifier(candidate_schema)}."
        f"{_quote_identifier(candidate_name)} AS WITH "
        + ", ".join(steps)
        + f" SELECT * FROM {final_step}"
    )


def rule_attribution_label(rule: dict[str, Any]) -> str:
    if rule["type"] == "not_null":
        return f"{rule['column']} is not null"
    if rule["type"] == "compare":
        return f"{rule['column']} {rule['operator']} configured value"
    return "Remove exact duplicate rows"

