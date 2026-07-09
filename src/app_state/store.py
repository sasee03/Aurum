"""CRUD operations for Aurum SQLite app state."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .db import get_connection


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_project(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "environment": row["environment"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_run_id": row["last_run_id"],
        "status": row["status"],
    }


def create_project(
    name: str,
    description: str = "",
    environment: str = "Development",
) -> dict[str, Any]:
    project_id = str(uuid.uuid4())
    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO projects (id, name, description, environment, created_at, updated_at, status)
            VALUES (?, ?, ?, ?, ?, ?, 'active')
            """,
            (project_id, name, description, environment, now, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _row_to_project(row)


def list_projects() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC"
        ).fetchall()
    return [_row_to_project(row) for row in rows]


def get_project(project_id: str) -> Optional[dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        return None
    return _row_to_project(row)


def save_validation_run(
    run_id: str,
    *,
    project_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    status: str = "completed",
    mode: str = "live",
    started_at: Optional[str] = None,
    finished_at: Optional[str] = None,
    error_message: Optional[str] = None,
    source_schema: Optional[str] = None,
    source_table: Optional[str] = None,
) -> None:
    started = started_at or _utc_now()
    finished = finished_at or _utc_now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO validation_runs (
                run_id, project_id, connection_id, status, mode,
                started_at, finished_at, error_message,
                source_schema, source_table
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                project_id,
                connection_id,
                status,
                mode,
                started,
                finished,
                error_message,
                source_schema,
                source_table,
            ),
        )
        if project_id:
            conn.execute(
                "UPDATE projects SET last_run_id = ?, updated_at = ? WHERE id = ?",
                (run_id, finished, project_id),
            )
        conn.commit()


def get_validation_run(run_id: str) -> Optional[dict[str, Any]]:
    """Return a single validation_runs row (including source_schema/table), or None."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                run_id, project_id, connection_id, status, mode,
                started_at, finished_at, error_message,
                source_schema, source_table
            FROM validation_runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "run_id": row["run_id"],
        "project_id": row["project_id"],
        "connection_id": row["connection_id"],
        "status": row["status"],
        "mode": row["mode"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "error_message": row["error_message"],
        "source_schema": row["source_schema"],
        "source_table": row["source_table"],
    }


def save_validation_report(run_id: str, report: dict[str, Any]) -> None:
    now = _utc_now()
    payload = json.dumps(report, default=str)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO validation_reports (run_id, report_json, created_at)
            VALUES (?, ?, ?)
            """,
            (run_id, payload, now),
        )
        conn.commit()


def get_report_by_run_id(run_id: str) -> Optional[dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT report_json FROM validation_reports WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["report_json"])


def list_validation_runs() -> list[dict[str, Any]]:
    """List persisted runs from SQLite only (never CSV/JSON bootstrap files)."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                r.run_id,
                r.project_id,
                r.connection_id,
                r.status,
                r.mode,
                r.started_at,
                r.finished_at,
                r.error_message,
                r.source_schema,
                r.source_table,
                rep.report_json
            FROM validation_runs r
            LEFT JOIN validation_reports rep ON rep.run_id = r.run_id
            ORDER BY r.started_at DESC
            """
        ).fetchall()

    runs: list[dict[str, Any]] = []
    for row in rows:
        trust_score = None
        final_verdict = None
        if row["report_json"]:
            report = json.loads(row["report_json"])
            trust_score = report.get("trust_score")
            final_verdict = report.get("final_verdict")
        runs.append(
            {
                "run_id": row["run_id"],
                "project_id": row["project_id"],
                "connection_id": row["connection_id"],
                "status": row["status"],
                "mode": row["mode"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "error_message": row["error_message"],
                "source_schema": row["source_schema"],
                "source_table": row["source_table"],
                "trust_score": trust_score,
                "final_verdict": final_verdict,
            }
        )
    return runs


def _row_to_connection(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "type": row["type"],
        "name": row["name"],
        "host": row["host"],
        "port": row["port"],
        "database_name": row["database_name"],
        "username": row["username"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def save_data_connection(
    *,
    connection_id: str,
    project_id: str,
    name: str,
    host: str,
    port: int,
    database_name: str,
    username: str,
    status: str = "active",
    connection_type: str = "postgresql",
) -> dict[str, Any]:
    """Persist connection metadata only — never stores a password."""
    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO data_connections (
                id, project_id, type, name, host, port, database_name,
                username, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                connection_id,
                project_id,
                connection_type,
                name,
                host,
                int(port),
                database_name,
                username,
                status,
                now,
                now,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM data_connections WHERE id = ?",
            (connection_id,),
        ).fetchone()
    return _row_to_connection(row)


def get_data_connection(connection_id: str) -> Optional[dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM data_connections WHERE id = ?",
            (connection_id,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_connection(row)
