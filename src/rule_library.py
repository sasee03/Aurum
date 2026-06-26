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
    """Anti-join FK check — orphan keys only; does not detect valid-key swaps."""
    results = []
    for fk in spec.get("foreign_keys", []):
        col = fk["column"]
        ref_table = fk.get("ref_table") or fk.get("parent_table")
        ref_column = fk.get("ref_column") or fk.get("parent_column")
        if not ref_table or not loader.table_exists(ref_table):
            continue
        orphans = int(loader.scalar(
            f"""
            SELECT COUNT(*) FROM {table} child
            LEFT JOIN {ref_table} ref ON child.{col} = ref.{ref_column}
            WHERE child.{col} IS NOT NULL AND ref.{ref_column} IS NULL
            """
        ))
        status = PASS if orphans == 0 else FAIL
        ref_tag = ref_table[:4].upper()
        results.append(_result(
            f"L1-{table[:3].upper()}-CONS-FK-{ref_tag}",
            f"Foreign Key Integrity: {col} -> {ref_table}.{ref_column}",
            spec["layer"], table, CONSISTENCY, status,
            observed=orphans, expected=0,
            detail=(
                "No orphan foreign keys."
                if orphans == 0
                else (
                    f"{orphans:,} rows reference missing {ref_table}.{ref_column} "
                    "(orphan FK; does not detect valid-key swaps)."
                )
            ),
            sql=(
                f"SELECT COUNT(*) FROM {table} child LEFT JOIN {ref_table} ref "
                f"ON child.{col} = ref.{ref_column} "
                f"WHERE child.{col} IS NOT NULL AND ref.{ref_column} IS NULL"
            ),
        ))
    return results


def _check_freshness(loader: DataLoader, table: str, spec: dict) -> list[CheckResult]:
    """Future-date FAIL + staleness WARN driven by table_specs date freshness fields."""
    date_col = spec.get("date_column")
    if not date_col:
        cols = spec.get("date_columns", [])
        if not cols:
            return []
        date_col = cols[0]
    if date_col not in loader.columns(table):
        return []
    if spec.get("expected_freshness_days") is None and spec.get("max_future_days") is None:
        return []

    max_future_days = spec.get("max_future_days", 0)
    expected_freshness_days = spec.get("expected_freshness_days", 365)

    sql = (
        f"SELECT MAX(TRY_CAST({date_col} AS DATE)) AS max_d, CURRENT_DATE AS run_date "
        f"FROM {table} WHERE {date_col} IS NOT NULL"
    )
    bounds = loader.query(
        f"""
        SELECT
            MAX(TRY_CAST({date_col} AS DATE)) AS max_d,
            CURRENT_DATE AS run_date,
            CURRENT_DATE + INTERVAL '{max_future_days} days' AS future_limit,
            CURRENT_DATE - INTERVAL '{expected_freshness_days} days' AS stale_limit
        FROM {table} WHERE {date_col} IS NOT NULL
        """
    ).to_dict("records")[0]
    max_d = bounds["max_d"]

    if max_d is None:
        return [
            _result(
                f"L1-{table[:3].upper()}-TIME-FRESH",
                f"Date Freshness: {date_col}",
                spec["layer"], table, TIMELINESS, WARN,
                observed=None, expected="parseable max date",
                detail="No parseable dates for freshness check.",
                sql=sql,
            )
        ]

    future_limit = bounds["future_limit"]
    stale_limit = bounds["stale_limit"]

    if max_d > future_limit:
        status = FAIL
        detail = (
            f"Max {date_col} ({max_d}) is beyond allowed future window "
            f"(run_date + {max_future_days} day buffer) — likely date corruption."
        )
    elif max_d < stale_limit:
        status = WARN
        detail = (
            f"Max {date_col} ({max_d}) is older than freshness window "
            f"({expected_freshness_days} days before run_date) — data may be stale."
        )
    else:
        status = PASS
        detail = (
            f"Max {date_col} ({max_d}) is within freshness window "
            f"(not future, not stale beyond {expected_freshness_days} days)."
        )

    return [
        _result(
            f"L1-{table[:3].upper()}-TIME-FRESH",
            f"Date Freshness: {date_col}",
            spec["layer"], table, TIMELINESS, status,
            observed={
                "max_date": str(max_d),
                "run_date": str(bounds["run_date"]),
                "max_future_days": max_future_days,
                "expected_freshness_days": expected_freshness_days,
            },
            expected=f"max_date <= run_date + {max_future_days}d and not stale",
            detail=detail,
            sql=sql,
        )
    ]


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
        results.extend(_check_freshness(loader, table, spec))
        results.extend(_check_timeliness(loader, table, spec))
    return results
