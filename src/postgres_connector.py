"""User-supplied Postgres connector (separate from the app's own DATABASE_URL).

Passwords are held only in an in-process session cache for the lifetime of the
API process. They are never written to SQLite and never returned in API bodies.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd
import psycopg
from psycopg import sql

from src.csv_ingest import MAX_UPLOAD_ROWS, CsvSchemaMismatch, validate_raw_orders_frame
from src.config_loader import AurumDatasetConfig
from src.db_config import db_connect_timeout
from src.metadata_discovery import list_tables

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EXCLUDED_SCHEMAS = frozenset({"pg_catalog", "information_schema"})
_EXCLUDED_SCHEMA_PREFIXES = ("pg_toast", "pg_temp_")
SESSION_TTL_SECONDS = 30 * 60


@dataclass(frozen=True)
class UserPostgresTarget:
    host: str
    port: int
    database: str
    username: str
    password: str


@dataclass
class SessionConnection:
    connection_id: str
    project_id: Optional[str]
    name: str
    host: str
    port: int
    database: str
    username: str
    password: str  # session-only; never persisted / never returned
    created_at_monotonic: float = field(default_factory=time.monotonic)


_SESSION_LOCK = threading.Lock()
_SESSION_CONNECTIONS: dict[str, SessionConnection] = {}


def _quote_ident(name: str) -> sql.Identifier:
    if not _IDENTIFIER.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return sql.Identifier(name)


def _qualified_table(schema_name: str, table_name: str) -> sql.Composed:
    return sql.SQL("{}.{}").format(_quote_ident(schema_name), _quote_ident(table_name))


def build_user_conninfo(target: UserPostgresTarget) -> str:
    """Libpq keyword string for a user-specified Postgres (never uses DATABASE_URL)."""
    return (
        f"host={target.host} "
        f"port={int(target.port)} "
        f"dbname={target.database} "
        f"user={target.username} "
        f"password={target.password}"
    )


def classify_connect_error(exc: BaseException) -> str:
    """Map psycopg/OS errors to honest, specific user-facing messages."""
    text = str(exc).strip() or exc.__class__.__name__
    lowered = text.lower()

    if isinstance(exc, TimeoutError) or "timeout" in lowered or "timed out" in lowered:
        return "Connection timed out — host unreachable or not accepting connections"
    if "password authentication failed" in lowered:
        return "Authentication failed — wrong username or password"
    if "could not connect" in lowered or "connection refused" in lowered:
        return "Host unreachable or wrong port — connection refused"
    if (
        "name or service not known" in lowered
        or "nodename nor servname" in lowered
        or "getaddrinfo failed" in lowered
        or "failed to resolve host" in lowered
    ):
        return "Host unreachable — DNS lookup failed"
    if "does not exist" in lowered and "database" in lowered:
        return "Database does not exist"
    if "permission denied" in lowered:
        return "Permission denied for this database user"
    if "ssl" in lowered and ("required" in lowered or "error" in lowered):
        return f"SSL/connection error: {text}"
    return f"Connection failed: {text}"


def test_user_postgres(target: UserPostgresTarget) -> dict[str, Any]:
    """Attempt a short-timeout connection. Never returns the password."""
    try:
        with psycopg.connect(
            build_user_conninfo(target),
            connect_timeout=db_connect_timeout(),
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return {
            "connected": True,
            "host": target.host,
            "port": int(target.port),
            "database": target.database,
            "username": target.username,
        }
    except Exception as exc:  # noqa: BLE001 — must never 500 on connect failures
        return {
            "connected": False,
            "error": classify_connect_error(exc),
            "host": target.host,
            "port": int(target.port),
            "database": target.database,
            "username": target.username,
        }


def store_session_connection(
    target: UserPostgresTarget,
    *,
    project_id: Optional[str] = None,
    name: Optional[str] = None,
) -> SessionConnection:
    connection_id = f"conn_{uuid.uuid4().hex[:12]}"
    session = SessionConnection(
        connection_id=connection_id,
        project_id=project_id,
        name=name or f"{target.database}@{target.host}",
        host=target.host,
        port=int(target.port),
        database=target.database,
        username=target.username,
        password=target.password,
    )
    with _SESSION_LOCK:
        _prune_expired_sessions_locked(time.monotonic())
        _SESSION_CONNECTIONS[connection_id] = session
    return session


def _session_expired(session: SessionConnection, now: float) -> bool:
    return now - session.created_at_monotonic > SESSION_TTL_SECONDS


def _prune_expired_sessions_locked(now: float) -> None:
    expired = [
        connection_id
        for connection_id, session in _SESSION_CONNECTIONS.items()
        if _session_expired(session, now)
    ]
    for connection_id in expired:
        del _SESSION_CONNECTIONS[connection_id]


def get_session_connection(connection_id: str) -> Optional[SessionConnection]:
    now = time.monotonic()
    with _SESSION_LOCK:
        session = _SESSION_CONNECTIONS.get(connection_id)
        if session is None:
            return None
        if _session_expired(session, now):
            del _SESSION_CONNECTIONS[connection_id]
            return None
        return session


def clear_session_connections() -> None:
    """Test helper — wipe in-process session cache."""
    with _SESSION_LOCK:
        _SESSION_CONNECTIONS.clear()


def session_public_view(session: SessionConnection) -> dict[str, Any]:
    """Safe metadata for API responses (no password)."""
    return {
        "connection_id": session.connection_id,
        "project_id": session.project_id,
        "name": session.name,
        "host": session.host,
        "port": session.port,
        "database": session.database,
        "username": session.username,
        "type": "postgresql",
        "status": "active",
    }


def open_session_connection(session: SessionConnection):
    """Open a short-timeout psycopg connection for a stored session."""
    target = UserPostgresTarget(
        host=session.host,
        port=session.port,
        database=session.database,
        username=session.username,
        password=session.password,
    )
    return psycopg.connect(
        build_user_conninfo(target),
        connect_timeout=db_connect_timeout(),
        autocommit=True,
    )


def list_user_schemas(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT schema_name
            FROM information_schema.schemata
            ORDER BY schema_name
            """
        )
        rows = cur.fetchall()
    schemas: list[str] = []
    for (name,) in rows:
        if name in _EXCLUDED_SCHEMAS:
            continue
        if any(name.startswith(prefix) for prefix in _EXCLUDED_SCHEMA_PREFIXES):
            continue
        schemas.append(name)
    return schemas


def list_user_tables(conn, schema: Optional[str] = None) -> list[dict[str, str]]:
    return list_tables(conn, schema_filter=schema)


def read_table_as_dataframe(
    conn,
    schema: str,
    table: str,
    *,
    max_rows: int = MAX_UPLOAD_ROWS,
) -> pd.DataFrame:
    """Read a user table into a DataFrame, enforcing the Stage 4 row cap."""
    qualified = _qualified_table(schema, table)
    with conn.cursor() as cur:
        timeout_ms = int(db_connect_timeout() * 1000)
        cur.execute(sql.SQL("SET statement_timeout = {}").format(timeout_ms))
        try:
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(qualified))
            count = int(cur.fetchone()[0])
        except psycopg.errors.QueryCanceled:
            raise CsvSchemaMismatch(
                missing_columns=[],
                error=f"Table row count could not be determined within {db_connect_timeout()} seconds — table may be too large or the connection is slow.",
            ) from None
        finally:
            cur.execute("SET statement_timeout = 0")
    if count == 0:
        raise CsvSchemaMismatch(
            missing_columns=[],
            error="table contains no data rows",
        )
    if count > max_rows:
        raise CsvSchemaMismatch(
            missing_columns=[],
            error=f"file exceeds maximum of {max_rows:,} data rows",
        )

    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT * FROM {}").format(qualified))
        columns = [desc.name for desc in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame.from_records(rows, columns=columns)


def load_and_validate_user_table(
    session: SessionConnection,
    schema: str,
    table: str,
    cfg: Optional[AurumDatasetConfig] = None,
) -> pd.DataFrame:
    """Connect → read table → apply the same Olist-shape validators as CSV upload."""
    try:
        with open_session_connection(session) as conn:
            # Confirm table exists before reading.
            matches = list_tables(conn, schema_filter=schema, table_name_filter=table)
            if not matches:
                raise CsvSchemaMismatch(
                    missing_columns=[],
                    error=f"Table '{schema}.{table}' was not found",
                )
            frame = read_table_as_dataframe(conn, schema, table)
    except CsvSchemaMismatch:
        raise
    except Exception as exc:  # noqa: BLE001
        raise CsvSchemaMismatch(
            missing_columns=[],
            error=classify_connect_error(exc),
        ) from None

    return validate_raw_orders_frame(frame, cfg)
