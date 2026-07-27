"""Validation and deterministic SQL compilation for Structured Gold V1."""

from __future__ import annotations

import re
from typing import Any, Mapping

from sqlglot import exp

from src.gold_catalog import GoldCatalogColumn


class StructuredGoldDefinitionError(ValueError):
    """A structured Gold definition cannot bind safely to its exact source."""


_ALLOWED_AGGREGATIONS = frozenset({"sum", "count", "avg", "min", "max"})
_BINARY_OPERATORS = {
    "add": exp.Add,
    "subtract": exp.Sub,
    "multiply": exp.Mul,
}
_AGGREGATIONS = {
    "sum": exp.Sum,
    "count": exp.Count,
    "avg": exp.Avg,
    "min": exp.Min,
    "max": exp.Max,
}
_NUMERIC_TYPES = frozenset(
    {"int2", "int4", "int8", "numeric", "float4", "float8"}
)
_SAFE_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_POSTGRES_IDENTIFIER_MAX_BYTES = 63


def _safe_authority_identifier(value: Any, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not _SAFE_IDENTIFIER_RE.fullmatch(value)
        or len(value.encode("utf-8")) > _POSTGRES_IDENTIFIER_MAX_BYTES
    ):
        raise StructuredGoldDefinitionError(
            f"{field} is not a safe PostgreSQL identifier"
        )
    return value


def _referenced_column(
    value: Any,
    *,
    field: str,
    columns: Mapping[str, GoldCatalogColumn],
) -> GoldCatalogColumn:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or len(value.encode("utf-8")) > _POSTGRES_IDENTIFIER_MAX_BYTES
    ):
        raise StructuredGoldDefinitionError(
            f"{field} is not a valid PostgreSQL identifier"
        )
    column = columns.get(value)
    if column is None:
        raise StructuredGoldDefinitionError(
            f"{field} does not exist in the exact authorized Silver relation"
        )
    return column


def _is_numeric(column: GoldCatalogColumn) -> bool:
    return (
        column.type_schema == "pg_catalog"
        and column.type_kind == "b"
        and column.type_name in _NUMERIC_TYPES
    )


def validate_structured_gold_definition(
    *,
    dimension: str,
    aggregation: str,
    expression: Mapping[str, Any],
    alias: str,
    columns: Mapping[str, GoldCatalogColumn],
) -> dict[str, Any]:
    """Return a strict canonical definition bound to discovered source columns."""
    _referenced_column(
        dimension,
        field="Structured Gold dimension",
        columns=columns,
    )
    output_alias = _safe_authority_identifier(
        alias,
        field="Structured Gold metric alias",
    )
    if aggregation not in _ALLOWED_AGGREGATIONS:
        raise StructuredGoldDefinitionError(
            "Structured Gold aggregation is unsupported"
        )
    if not isinstance(expression, Mapping):
        raise StructuredGoldDefinitionError(
            "Structured Gold metric expression must be an object"
        )

    expression_type = expression.get("type")
    if expression_type == "column":
        if set(expression) != {"type", "column"}:
            raise StructuredGoldDefinitionError(
                "Structured Gold column expression has invalid keys"
            )
        metric_column = _referenced_column(
            expression["column"],
            field="Structured Gold metric column",
            columns=columns,
        )
        if aggregation in {"sum", "avg"} and not _is_numeric(metric_column):
            raise StructuredGoldDefinitionError(
                f"Structured Gold {aggregation.upper()} requires a numeric expression"
            )
        if (
            aggregation in {"min", "max"}
            and aggregation not in metric_column.supported_aggregations
        ):
            raise StructuredGoldDefinitionError(
                f"Structured Gold {aggregation.upper()} is unsupported for "
                f"PostgreSQL type {metric_column.type_schema}.{metric_column.type_name}"
            )
        normalized_expression = {
            "type": "column",
            "column": metric_column.name,
        }
    elif expression_type == "binary":
        if set(expression) != {
            "type",
            "operator",
            "left_column",
            "right_column",
        }:
            raise StructuredGoldDefinitionError(
                "Structured Gold binary expression has invalid keys"
            )
        operator = expression["operator"]
        if operator not in _BINARY_OPERATORS:
            raise StructuredGoldDefinitionError(
                "Structured Gold binary operator is unsupported"
            )
        if aggregation == "count":
            raise StructuredGoldDefinitionError(
                "Structured Gold COUNT requires an explicit column expression"
            )
        left = _referenced_column(
            expression["left_column"],
            field="Structured Gold left metric column",
            columns=columns,
        )
        right = _referenced_column(
            expression["right_column"],
            field="Structured Gold right metric column",
            columns=columns,
        )
        if not _is_numeric(left) or not _is_numeric(right):
            raise StructuredGoldDefinitionError(
                "Structured Gold binary expressions require numeric operands"
            )
        normalized_expression = {
            "type": "binary",
            "operator": operator,
            "left_column": left.name,
            "right_column": right.name,
        }
    else:
        raise StructuredGoldDefinitionError(
            "Structured Gold metric expression type is unsupported"
        )

    return {
        "dimension": dimension,
        "aggregation": aggregation,
        "expression": normalized_expression,
        "alias": output_alias,
    }


def _quoted_identifier(value: str) -> exp.Identifier:
    return exp.Identifier(this=value, quoted=True)


def _column_expression(column_name: str) -> exp.Column:
    return exp.Column(this=_quoted_identifier(column_name))


def compile_structured_gold_sql(
    *,
    candidate_schema: str,
    candidate_name: str,
    source_schema: str,
    source_relation: str,
    definition: Mapping[str, Any],
) -> str:
    """Compile one validated Structured Gold definition into deterministic CTAS."""
    candidate_schema = _safe_authority_identifier(
        candidate_schema,
        field="Structured Gold candidate schema",
    )
    candidate_name = _safe_authority_identifier(
        candidate_name,
        field="Structured Gold candidate relation",
    )
    source_schema = _safe_authority_identifier(
        source_schema,
        field="Structured Gold source schema",
    )
    source_relation = _safe_authority_identifier(
        source_relation,
        field="Structured Gold source relation",
    )
    dimension = definition["dimension"]
    aggregation = definition["aggregation"]
    expression = definition["expression"]
    alias = _safe_authority_identifier(
        definition["alias"],
        field="Structured Gold metric alias",
    )

    dimension_expression = _column_expression(dimension)
    if expression["type"] == "column":
        metric_expression: exp.Expression = _column_expression(
            expression["column"]
        )
    else:
        operator_class = _BINARY_OPERATORS[expression["operator"]]
        metric_expression = operator_class(
            this=_column_expression(expression["left_column"]),
            expression=_column_expression(expression["right_column"]),
        )

    aggregate_expression = _AGGREGATIONS[aggregation](this=metric_expression)
    select = (
        exp.select(
            dimension_expression.copy(),
            exp.Alias(
                this=aggregate_expression,
                alias=_quoted_identifier(alias),
            ),
        )
        .from_(
            exp.Table(
                this=_quoted_identifier(source_relation),
                db=_quoted_identifier(source_schema),
            )
        )
        .group_by(dimension_expression.copy())
    )
    statement = exp.Create(
        this=exp.Table(
            this=_quoted_identifier(candidate_name),
            db=_quoted_identifier(candidate_schema),
        ),
        kind="TABLE",
        expression=select,
    )
    return statement.sql(dialect="postgres")
