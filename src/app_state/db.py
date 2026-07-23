"""SQLite connection and schema for Aurum app state."""

from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_RELATIVE_PATH = Path("data") / "app_state.sqlite"

REVISION_REGEX = re.compile(r"^[0-9a-f]{64}$")


def is_valid_rule_revision(value: Any) -> bool:
    """Return True if value is exactly a 64-character lowercase hex SHA-256 string."""
    return isinstance(value, str) and bool(REVISION_REGEX.match(value))

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

CREATE TABLE IF NOT EXISTS gold_security_state (
    run_id TEXT PRIMARY KEY,
    model_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    business_requirement TEXT NOT NULL,
    selected_sources_json TEXT NOT NULL,
    target_schema TEXT NOT NULL,
    target_name TEXT NOT NULL,
    candidate_schema TEXT NOT NULL,
    candidate_name TEXT NOT NULL,
    generator_provenance TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    review_snapshot_json TEXT NOT NULL,
    review_revision TEXT NOT NULL,
    approval_snapshot_json TEXT,
    approved_revision TEXT,
    approved_at TEXT,
    overwrite_authorized INTEGER
        CHECK (overwrite_authorized IS NULL OR overwrite_authorized IN (0, 1)),
    source_identities_json TEXT,
    target_identity_json TEXT,
    execution_claim_id TEXT,
    execution_claimed_at TEXT,
    candidate_identity_json TEXT,
    execution_failure_code TEXT,
    FOREIGN KEY (run_id) REFERENCES generated_sql_review(run_id)
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


def compute_rule_revision(rules: Any) -> str | None:
    """Compute deterministic canonical full 64-char SHA-256 rule revision hash.

    Returns None if rules is not a valid list[str].
    """
    if not isinstance(rules, list) or not all(isinstance(x, str) for x in rules):
        return None
    normalized = [r.strip() for r in rules if isinstance(r, str) and r.strip()]
    canonical_json = json.dumps(normalized, separators=(',', ':'))
    return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest().lower()


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
    _ensure_column(conn, "generated_sql_review", "candidate_schema", "candidate_schema TEXT")
    _ensure_column(conn, "generated_sql_review", "attribution_log_json", "attribution_log_json TEXT")
    _ensure_column(conn, "generated_sql_review", "generator_provenance", "generator_provenance TEXT")
    _ensure_column(conn, "table_rules", "rule_revision", "rule_revision TEXT")
    _ensure_column(conn, "generated_sql_review", "rule_revision", "rule_revision TEXT")
    _ensure_column(
        conn,
        "gold_security_state",
        "execution_claim_id",
        "execution_claim_id TEXT",
    )
    _ensure_column(
        conn,
        "gold_security_state",
        "execution_claimed_at",
        "execution_claimed_at TEXT",
    )
    _ensure_column(
        conn,
        "gold_security_state",
        "candidate_identity_json",
        "candidate_identity_json TEXT",
    )
    _ensure_column(
        conn,
        "gold_security_state",
        "execution_failure_code",
        "execution_failure_code TEXT",
    )

    # Migration: Backfill existing valid table_rules rows where rule_revision IS NULL
    try:
        rows = conn.execute("SELECT table_name, rules_json FROM table_rules WHERE rule_revision IS NULL").fetchall()
        for row in rows:
            try:
                decoded = json.loads(row["rules_json"])
                rev = compute_rule_revision(decoded)
                if rev is not None:
                    conn.execute("UPDATE table_rules SET rule_revision = ? WHERE table_name = ?", (rev, row["table_name"]))
            except Exception:
                pass
    except Exception as e:
        logger.warning("Failed to backfill table_rules rule_revision: %s", e)

    # Idempotent migration: Quarantine existing historical runs missing provenance
    conn.execute(
        "UPDATE generated_sql_review SET generator_provenance = 'untrusted_legacy' WHERE generator_provenance IS NULL"
    )
    conn.commit()


def get_connection() -> sqlite3.Connection:
    path = app_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn
