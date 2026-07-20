"""Dynamic Postgres metadata discovery for the Metadata Discovery API.

Read-only profiling of live tables via information_schema and exact aggregates.
Demo-session discovery reuses DataLoader's connection and exact session schema.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import psycopg
from psycopg import Connection, sql

from .db_config import postgres_conninfo
from .table_specs import build_table_specs

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_EXCLUDED_SCHEMAS = frozenset({"pg_catalog", "information_schema"})
_EXCLUDED_SCHEMA_PREFIXES = ("pg_toast", "pg_temp_")

_MINMAX_DATA_TYPES = frozenset(
    {
        "smallint",
        "integer",
        "bigint",
        "numeric",
        "decimal",
        "real",
        "double precision",
        "date",
        "timestamp without time zone",
        "timestamp with time zone",
        "time without time zone",
        "time with time zone",
    }
)

_CANDIDATE_KEY_MIN_UNIQUENESS = 99.5

# Postgres `json` has no equality operator — DISTINCT / COUNT(DISTINCT) are unsafe.
_DISTINCT_UNSAFE_TYPES = frozenset({"json"})

# v1: profile jsonb with DISTINCT but never treat as candidate keys.
_CANDIDATE_KEY_EXCLUDED_TYPES = frozenset({"json", "jsonb"})


def _quote_ident(name: str) -> sql.Identifier:
    if not _IDENTIFIER.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return sql.Identifier(name)


def _qualified_table(schema_name: str, table_name: str) -> sql.Composed:
    return sql.SQL("{}.{}").format(_quote_ident(schema_name), _quote_ident(table_name))


def classify_layer(schema_name: str, table_name: str) -> str:
    """Classify a table into bronze/silver/gold/unknown from naming patterns."""
    lowered = table_name.lower()
    if "bronze" in lowered:
        return "bronze"
    if "silver" in lowered:
        return "silver"
    if "gold" in lowered:
        return "gold"

    spec = build_table_specs().get(table_name)
    if spec:
        hinted = str(spec.get("layer", "")).lower()
        if hinted in {"bronze", "silver", "gold"}:
            return hinted
    return "unknown"


def _schema_excluded(schema_name: str) -> bool:
    if schema_name in _EXCLUDED_SCHEMAS:
        return True
    return any(schema_name.startswith(prefix) for prefix in _EXCLUDED_SCHEMA_PREFIXES)


def list_tables(
    conn: Connection,
    schema_filter: Optional[str] = None,
    table_name_filter: Optional[str] = None,
) -> list[dict]:
    """List BASE TABLE entries from information_schema with layer classification."""
    query = """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
    """
    params: list[Any] = []
    if schema_filter is not None:
        query += " AND table_schema = %s"
        params.append(schema_filter)
    if table_name_filter is not None:
        query += " AND table_name = %s"
        params.append(table_name_filter)
    query += " ORDER BY table_schema, table_name"

    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    tables: list[dict] = []
    for schema_name, table_name in rows:
        if _schema_excluded(schema_name):
            continue
        tables.append(
            {
                "schema": schema_name,
                "table": table_name,
                "layer": classify_layer(schema_name, table_name),
            }
        )
    return tables


def describe_table(conn: Connection, schema_name: str, table_name: str) -> list[dict]:
    """Return column definitions from information_schema.columns."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, data_type, is_nullable, ordinal_position
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            [schema_name, table_name],
        )
        rows = cur.fetchall()

    return [
        {
            "name": name,
            "data_type": data_type,
            "nullable": is_nullable == "YES",
            "ordinal_position": ordinal_position,
        }
        for name, data_type, is_nullable, ordinal_position in rows
    ]


def get_row_count(conn: Connection, schema_name: str, table_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM {}").format(
                _qualified_table(schema_name, table_name)
            )
        )
        row = cur.fetchone()
    return int(row[0]) if row else 0


def get_column_count(conn: Connection, schema_name: str, table_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            """,
            [schema_name, table_name],
        )
        row = cur.fetchone()
    return int(row[0]) if row else 0


def _supports_minmax(data_type: str) -> bool:
    return data_type.lower() in _MINMAX_DATA_TYPES


def _normalized_type(data_type: str) -> str:
    return data_type.lower().strip()


def _supports_distinct_profiling(data_type: str) -> bool:
    """Whether COUNT(DISTINCT) and SELECT DISTINCT are safe for this column type."""
    return _normalized_type(data_type) not in _DISTINCT_UNSAFE_TYPES


def _eligible_for_candidate_key(profile: dict) -> bool:
    """Candidate keys require exact distinct/uniqueness/null stats and safe types."""
    if profile.get("null_percent") is None:
        return False
    if profile.get("distinct_count") is None:
        return False
    if profile.get("uniqueness_percent") is None:
        return False
    if _normalized_type(profile.get("data_type", "")) in _CANDIDATE_KEY_EXCLUDED_TYPES:
        return False
    return True


def profile_columns(
    conn: Connection,
    schema_name: str,
    table_name: str,
    sample_limit: int = 5,
) -> list[dict]:
    """Profile columns using exact full-table aggregates; samples are limited only."""
    columns = describe_table(conn, schema_name, table_name)
    row_count = get_row_count(conn, schema_name, table_name)
    qualified = _qualified_table(schema_name, table_name)
    profiles: list[dict] = []

    for column in columns:
        col_name = column["name"]
        col_ident = _quote_ident(col_name)
        data_type = column["data_type"]

        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT COUNT(*) FROM {} WHERE {} IS NULL").format(
                    qualified, col_ident
                )
            )
            null_count = int(cur.fetchone()[0])

            distinct_count: Optional[int] = None
            uniqueness_percent: Optional[float] = None
            sample_values: list[Any] = []

            if _supports_distinct_profiling(data_type):
                cur.execute(
                    sql.SQL("SELECT COUNT(DISTINCT {}) FROM {}").format(
                        col_ident, qualified
                    )
                )
                distinct_count = int(cur.fetchone()[0])
                uniqueness_percent = (
                    0.0
                    if row_count == 0
                    else round(distinct_count / row_count * 100, 2)
                )
                cur.execute(
                    sql.SQL(
                        "SELECT DISTINCT {} FROM {} WHERE {} IS NOT NULL LIMIT %s"
                    ).format(col_ident, qualified, col_ident),
                    [sample_limit],
                )
                sample_values = [row[0] for row in cur.fetchall()]

            min_value = None
            max_value = None
            if _supports_minmax(data_type):
                cur.execute(
                    sql.SQL("SELECT MIN({}), MAX({}) FROM {}").format(
                        col_ident, col_ident, qualified
                    )
                )
                min_value, max_value = cur.fetchone()

        null_percent = 0.0 if row_count == 0 else round(null_count / row_count * 100, 2)

        profiles.append(
            {
                "name": col_name,
                "data_type": data_type,
                "nullable": column["nullable"],
                "null_count": null_count,
                "null_percent": null_percent,
                "distinct_count": distinct_count,
                "uniqueness_percent": uniqueness_percent,
                "min": min_value,
                "max": max_value,
                "sample_values": sample_values,
            }
        )

    return profiles


def infer_candidate_keys(column_profiles: list[dict], row_count: int) -> list[str]:
    if row_count == 0:
        return []
    keys: list[str] = []
    for profile in column_profiles:
        if not _eligible_for_candidate_key(profile):
            continue
        if (
            profile["null_percent"] == 0.0
            and profile["uniqueness_percent"] >= _CANDIDATE_KEY_MIN_UNIQUENESS
        ):
            keys.append(profile["name"])
    return keys


def merge_table_spec_overrides(discovered_table: dict, table_specs: dict) -> dict:
    """Attach static TABLE_SPECS entry without overwriting dynamic fields."""
    table_name = discovered_table.get("table")
    if table_name and table_name in table_specs:
        discovered_table = {
            **discovered_table,
            "spec_overrides": table_specs[table_name],
        }
    else:
        discovered_table = {**discovered_table, "spec_overrides": {}}
    return discovered_table


def discover_table_metadata(
    conn: Connection,
    schema_name: str,
    table_name: str,
    sample_limit: int = 5,
) -> dict:
    row_count = get_row_count(conn, schema_name, table_name)
    column_count = get_column_count(conn, schema_name, table_name)
    column_profiles = profile_columns(
        conn, schema_name, table_name, sample_limit=sample_limit
    )
    candidate_keys = infer_candidate_keys(column_profiles, row_count)
    table = {
        "schema": schema_name,
        "table": table_name,
        "layer": classify_layer(schema_name, table_name),
        "row_count": row_count,
        "column_count": column_count,
        "candidate_keys": candidate_keys,
        "columns": column_profiles,
    }
    return merge_table_spec_overrides(table, build_table_specs())


def discover_table_metadata_lightweight(
    conn: Connection,
    schema_name: str,
    table_name: str,
) -> dict:
    return {
        "schema": schema_name,
        "table": table_name,
        "layer": classify_layer(schema_name, table_name),
        "row_count": get_row_count(conn, schema_name, table_name),
        "column_count": get_column_count(conn, schema_name, table_name),
    }


def _build_summary(tables: list[dict]) -> dict:
    summary = {
        "total_tables": len(tables),
        "bronze_tables": 0,
        "silver_tables": 0,
        "gold_tables": 0,
        "unknown_tables": 0,
        "total_columns": 0,
    }
    for table in tables:
        layer = table.get("layer", "unknown")
        if layer == "bronze":
            summary["bronze_tables"] += 1
        elif layer == "silver":
            summary["silver_tables"] += 1
        elif layer == "gold":
            summary["gold_tables"] += 1
        else:
            summary["unknown_tables"] += 1
        summary["total_columns"] += int(table.get("column_count", 0))
    return summary


def _build_response(
    tables: list[dict],
    *,
    source: str,
    status: str = "ok",
) -> dict:
    return {
        "database": {"type": "postgres", "status": status, "source": source},
        "summary": _build_summary(tables),
        "tables": tables,
    }


def discover_from_connection(
    conn: Connection,
    *,
    schema: Optional[str] = None,
    table_name: Optional[str] = None,
    sample_limit: int = 5,
    source: str = "live",
    lightweight: bool = False,
) -> dict:
    listed = list_tables(conn, schema_filter=schema, table_name_filter=table_name)
    tables: list[dict] = []
    for entry in listed:
        schema_name = entry["schema"]
        name = entry["table"]
        if lightweight:
            tables.append(discover_table_metadata_lightweight(conn, schema_name, name))
        else:
            tables.append(
                discover_table_metadata(
                    conn, schema_name, name, sample_limit=sample_limit
                )
            )
    return _build_response(tables, source=source)


def discover_live_metadata(
    schema: Optional[str] = None,
    table_name: Optional[str] = None,
    sample_limit: int = 5,
) -> dict:
    """Read-only discovery against existing Postgres tables (no DataLoader)."""
    with psycopg.connect(postgres_conninfo(), autocommit=True) as conn:
        return discover_from_connection(
            conn,
            schema=schema,
            table_name=table_name,
            sample_limit=sample_limit,
            source="live",
            lightweight=False,
        )


def discover_live_tables_lightweight(schema: Optional[str] = None) -> dict:
    """Lightweight table list without column profiling or candidate keys."""
    with psycopg.connect(postgres_conninfo(), autocommit=True) as conn:
        return discover_from_connection(
            conn,
            schema=schema,
            source="live",
            lightweight=True,
        )


def discover_live_table_detail(
    table_name: str,
    schema: Optional[str] = None,
    sample_limit: int = 5,
) -> dict:
    """Read-only full metadata for a single table."""
    with psycopg.connect(postgres_conninfo(), autocommit=True) as conn:
        matches = list_tables(
            conn, schema_filter=schema, table_name_filter=table_name
        )
        if not matches:
            raise LookupError(f"Table '{table_name}' not found.")
        if schema is None and len(matches) > 1:
            schemas = sorted({m["schema"] for m in matches})
            raise AmbiguousTableError(
                f"Table '{table_name}' exists in multiple schemas: {schemas}. "
                "Provide the schema query parameter."
            )
        match = matches[0]
        table = discover_table_metadata(
            conn,
            match["schema"],
            match["table"],
            sample_limit=sample_limit,
        )
        return _build_response([table], source="live")


def discover_demo_session_metadata(sample_limit: int = 5) -> dict:
    """Materialize demo tables via DataLoader and profile exact session schema."""
    from .data_loader import DataLoader

    loader = DataLoader()
    try:
        return discover_from_connection(
            loader._pg_conn,
            schema=loader.session_schema,
            sample_limit=sample_limit,
            source="demo_session",
            lightweight=False,
        )
    finally:
        loader.close()


class AmbiguousTableError(ValueError):
    """Raised when a table name exists in multiple schemas without a filter."""
