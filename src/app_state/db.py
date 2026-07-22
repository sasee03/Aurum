"""SQLite connection and schema for Aurum app state."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_RELATIVE_PATH = Path("data") / "app_state.sqlite"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    environment TEXT NOT NULL DEFAULT 'Development',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_run_id TEXT,
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS data_connections (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    host TEXT,
    port INTEGER,
    database_name TEXT,
    username TEXT,
    status TEXT NOT NULL DEFAULT 'inactive',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS validation_runs (
    run_id TEXT PRIMARY KEY,
    project_id TEXT,
    connection_id TEXT,
    status TEXT NOT NULL,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error_message TEXT,
    source_schema TEXT,
    source_table TEXT,
    display_name TEXT,
    session_schema TEXT,
    dataset_config TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (connection_id) REFERENCES data_connections(id)
);

CREATE TABLE IF NOT EXISTS validation_reports (
    run_id TEXT PRIMARY KEY,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES validation_runs(run_id)
);

CREATE TABLE IF NOT EXISTS table_rules (
    table_name TEXT PRIMARY KEY,
    rules_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generated_sql_review (
    run_id TEXT PRIMARY KEY,
    table_name TEXT NOT NULL,
    sql_text TEXT NOT NULL,
    planned_changes_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def app_state_path() -> Path:
    """Return SQLite file path (env override or gitignored default under data/)."""
    override = os.getenv("AURUM_APP_STATE_DB", "").strip()
    if override:
        return Path(override)
    return DEFAULT_RELATIVE_PATH


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """Add a column to an existing table if missing (SQLite has no IF NOT EXISTS for columns)."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {row[1] for row in rows}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    # Migrate older DBs created before source_schema/source_table existed.
    _ensure_column(conn, "validation_runs", "source_schema", "source_schema TEXT")
    _ensure_column(conn, "validation_runs", "source_table", "source_table TEXT")
    _ensure_column(conn, "validation_runs", "display_name", "display_name TEXT")
    _ensure_column(conn, "validation_runs", "session_schema", "session_schema TEXT")
    _ensure_column(conn, "validation_runs", "dataset_config", "dataset_config TEXT")
    _ensure_column(conn, "generated_sql_review", "status", "status TEXT")
    _ensure_column(conn, "generated_sql_review", "promoted_at", "promoted_at TEXT")
    conn.commit()


def get_connection() -> sqlite3.Connection:
    path = app_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn
