"""Layer 1 — Rule Library: exact, deterministic DQ checks from table specs.

Each check maps to one of six DQ dimensions. Checks are config-driven via
`table_specs.TABLE_SPECS` — adding a table means adding config, not code.
"""

from __future__ import annotations

from typing import Any, Optional

from .contracts import (
    ACCURACY,
    COMPLETENESS,
    CONSISTENCY,
    DETECTION_LAYER_1,
    CheckResult,
    FAIL,
    PASS,
    TIMELINESS,
    UNIQUENESS,
    VALIDITY,
    WARN,
)
from .data_loader import DataLoader
from .table_specs import TABLE_SPECS


def _result(
    check_id: str,
    check_name: str,
    layer: str,
    table: str,
    dimension: str,
    status: str,
    observed: Any,
    expected: Any,
    detail: str,
    sql: str = "",
    **extra: Any,
) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        check_name=check_name,
        layer=layer,
        status=status,
        observed=observed,
        expected=expected,
        detail=detail,
        evidence_query=sql,
        extra={
            "dimension": dimension,
            "detection_layer": DETECTION_LAYER_1,
            "table": table,
            **extra,
        },
    )


def _check_completeness_nulls(loader: DataLoader, table: str, spec: dict) -> CheckResult:
    layer = spec["layer"]
    null_counts = {}
    for col in spec.get("mandatory_columns", []):
        if col in loader.columns(table):
            null_counts[col] = int(
                loader.scalar(f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL")
            )
    total = sum(null_counts.values())
    status = PASS if total == 0 else FAIL
    sql = f"SELECT COUNT(*) FROM {table} WHERE {spec['mandatory_columns'][0]} IS NULL"
    return _result(
        f"L1-{table[:3].upper()}-COMP-NULL",
        "Mandatory Column Null Check",
        layer, table, COMPLETENESS, status,
        observed=null_counts, expected={c: 0 for c in null_counts},
        detail="No nulls in mandatory columns." if total == 0
        else f"Mandatory nulls found: {null_counts}.",
        sql=sql,
    )


def _check_completeness_empty(loader: DataLoader, table: str, spec: dict) -> CheckResult:
    count = loader.count(table)
    status = PASS if count > 0 else FAIL
    return _result(
        f"L1-{table[:3].upper()}-COMP-EMPTY",
        "Empty Table Check",
        spec["layer"], table, COMPLETENESS, status,
        observed=count, expected="> 0",
        detail="Table has rows." if count > 0 else "Table is empty.",
        sql=f"SELECT COUNT(*) FROM {table}",
    )


def _check_completeness_source_match(
    loader: DataLoader, table: str, spec: dict
) -> Optional[CheckResult]:
    source = spec.get("source_table")
    if not source or not loader.table_exists(source):
        return None
    src_count = loader.count(source)
    tbl_count = loader.count(table)
    status = PASS if src_count == tbl_count else FAIL
    return _result(
        f"L1-{table[:3].upper()}-COMP-SRC",
        "Source to Table Row Count",
        spec["layer"], table, COMPLETENESS, status,
        observed=tbl_count, expected=src_count,
        detail="Row counts match." if status == PASS
        else f"Source {src_count:,} != {table} {tbl_count:,}.",
        sql=f"SELECT COUNT(*) FROM {table}",
    )


def _check_validity_ranges(loader: DataLoader, table: str, spec: dict) -> list[CheckResult]:
    results = []
    for col, rules in spec.get("range_checks", {}).items():
        if col not in loader.columns(table):
            continue
        strict_min = rules.get("strict_min", False)
        min_v = rules.get("min")
        if min_v is not None:
            op = "<=" if strict_min else "<"
            bad = int(loader.scalar(
                f"SELECT COUNT(*) FROM {table} WHERE {col} {op} {min_v}"
            ))
            status = PASS if bad == 0 else FAIL
            results.append(_result(
                f"L1-{table[:3].upper()}-VAL-{col[:4].upper()}",
                f"Range Check: {col}",
                spec["layer"], table, VALIDITY, status,
                observed=bad, expected=0,
                detail=f"No invalid {col} values." if bad == 0
                else f"{bad:,} rows violate {col} range rule.",
                sql=f"SELECT COUNT(*) FROM {table} WHERE {col} {op} {min_v}",
            ))
    return results


def _check_validity_dates(loader: DataLoader, table: str, spec: dict) -> list[CheckResult]:
    results = []
    for col in spec.get("date_columns", []):
        if col not in loader.columns(table):
            continue
        bad = int(loader.scalar(
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE {col} IS NOT NULL AND TRY_CAST({col} AS DATE) IS NULL"
        ))
        status = PASS if bad == 0 else FAIL
        results.append(_result(
            f"L1-{table[:3].upper()}-VAL-DATE",
            f"Date Parse Validity: {col}",
            spec["layer"], table, VALIDITY, status,
            observed=bad, expected=0,
            detail=f"All {col} values parse as dates." if bad == 0
            else f"{bad:,} rows have unparseable {col}.",
            sql=f"SELECT COUNT(*) FROM {table} WHERE TRY_CAST({col} AS DATE) IS NULL",
        ))
    return results


def _check_uniqueness_pk(loader: DataLoader, table: str, spec: dict) -> Optional[CheckResult]:
    pk = spec.get("primary_key", [])
    if not pk:
        return None
    key_cols = ", ".join(pk)
    dup = int(loader.scalar(
        f"""
        SELECT COALESCE(SUM(cnt - 1), 0) FROM (
            SELECT COUNT(*) AS cnt FROM {table}
            GROUP BY {key_cols} HAVING COUNT(*) > 1
        )
        """
    ))
    status = PASS if dup == 0 else FAIL
    return _result(
        f"L1-{table[:3].upper()}-UNIQ-PK",
        "Primary Key Duplicate Check",
        spec["layer"], table, UNIQUENESS, status,
        observed=dup, expected=0,
        detail="No primary-key duplicates." if dup == 0
        else f"{dup:,} duplicate primary-key rows.",
        sql=f"SELECT {key_cols}, COUNT(*) FROM {table} GROUP BY {key_cols} HAVING COUNT(*) > 1",
    )


def _check_uniqueness_full_row(loader: DataLoader, table: str, spec: dict) -> CheckResult:
    total = loader.count(table)
    distinct = int(loader.scalar(f"SELECT COUNT(*) FROM (SELECT DISTINCT * FROM {table})"))
    dup = total - distinct
    status = PASS if dup == 0 else WARN
    return _result(
        f"L1-{table[:3].upper()}-UNIQ-FULL",
        "Full Row Duplicate Check",
        spec["layer"], table, UNIQUENESS, status,
        observed=dup, expected=0,
        detail="No full-row duplicates." if dup == 0
        else f"{dup:,} full-row duplicate(s) detected.",
        sql=f"SELECT COUNT(*) - (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM {table})) FROM {table}",
    )


def _check_consistency_fk(loader: DataLoader, table: str, spec: dict) -> list[CheckResult]:
    results = []
    for fk in spec.get("foreign_keys", []):
        col = fk["column"]
        parent = fk["parent_table"]
        parent_col = fk["parent_column"]
        if not loader.table_exists(parent):
            continue
        orphans = int(loader.scalar(
            f"""
            SELECT COUNT(*) FROM {table} child
            LEFT JOIN {parent} parent ON child.{col} = parent.{parent_col}
            WHERE parent.{parent_col} IS NULL
            """
        ))
        status = PASS if orphans == 0 else FAIL
        results.append(_result(
            f"L1-{table[:3].upper()}-CONS-FK",
            f"Foreign Key Integrity: {col} -> {parent}.{parent_col}",
            spec["layer"], table, CONSISTENCY, status,
            observed=orphans, expected=0,
            detail="No orphan foreign keys." if orphans == 0
            else f"{orphans:,} orphan rows (FK violation).",
            sql=(
                f"SELECT COUNT(*) FROM {table} child LEFT JOIN {parent} parent "
                f"ON child.{col} = parent.{parent_col} WHERE parent.{parent_col} IS NULL"
            ),
        ))
    return results


def _check_timeliness(loader: DataLoader, table: str, spec: dict) -> list[CheckResult]:
    results = []
    days = spec.get("timeliness_days")
    if not days:
        return results
    for col in spec.get("date_columns", []):
        if col not in loader.columns(table):
            continue
        row = loader.query(
            f"""
            SELECT MIN(TRY_CAST({col} AS DATE)) AS min_d,
                   MAX(TRY_CAST({col} AS DATE)) AS max_d
            FROM {table} WHERE {col} IS NOT NULL
            """
        ).to_dict("records")[0]
        if row["max_d"] is None:
            results.append(_result(
                f"L1-{table[:3].upper()}-TIME",
                f"Timeliness: {col}",
                spec["layer"], table, TIMELINESS, WARN,
                observed=None, expected=f"within {days} days",
                detail="No parseable dates for timeliness check.",
                sql=f"SELECT MAX({col}) FROM {table}",
            ))
            continue
        span = (row["max_d"] - row["min_d"]).days if row["min_d"] else 0
        status = PASS if span <= days else WARN
        results.append(_result(
            f"L1-{table[:3].upper()}-TIME",
            f"Timeliness Window: {col}",
            spec["layer"], table, TIMELINESS, status,
            observed=f"span={span}d", expected=f"<= {days}d",
            detail=f"Date span {span} days within window." if status == PASS
            else f"Date span {span} days exceeds {days}-day window.",
            sql=f"SELECT MIN({col}), MAX({col}) FROM {table}",
        ))
    return results


def run_rule_library(loader: DataLoader) -> list[CheckResult]:
    """Run all Layer-1 config-driven checks for tables that exist."""
    results: list[CheckResult] = []
    for table, spec in TABLE_SPECS.items():
        if not loader.table_exists(table):
            continue
        results.append(_check_completeness_empty(loader, table, spec))
        results.append(_check_completeness_nulls(loader, table, spec))
        src = _check_completeness_source_match(loader, table, spec)
        if src:
            results.append(src)
        results.extend(_check_validity_ranges(loader, table, spec))
        results.extend(_check_validity_dates(loader, table, spec))
        pk = _check_uniqueness_pk(loader, table, spec)
        if pk:
            results.append(pk)
        results.append(_check_uniqueness_full_row(loader, table, spec))
        results.extend(_check_consistency_fk(loader, table, spec))
        results.extend(_check_timeliness(loader, table, spec))
    return results
