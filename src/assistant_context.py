"""Deterministic, read-only facts about the current Aurum pipeline.

This module is deliberately not a chat implementation.  It reads only the
persisted app-state records already owned by the pipeline and, when the active
connector session is still available, asks the existing metadata reader for
the exact selected source relation's column definitions.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.app_state.db import get_readonly_connection


ASSISTANT_CONTEXT_SCHEMA_VERSION = "aurum-assistant-context-v1"

SourceColumnsReader = Callable[[str, str, str], Optional[List[Dict[str, Any]]]]

_SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|secret|api[_-]?key|token|authorization|credential)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"\b(password|passwd|secret|api[_-]?key|token|authorization|credential)"
    r"\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)
_URI_USERINFO = re.compile(r"(?<=://)[^\s/:@]+:[^\s/@]+@")


def _redact_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    result = _SENSITIVE_VALUE.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    return _URI_USERINFO.sub("[REDACTED]@", result)


def _safe_value(value: Any) -> Any:
    """Remove sensitive keys recursively before returning persisted user data."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else _safe_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    return _redact_text(value)


def _json_object(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _source_columns_from_active_session(
    connection_id: str,
    schema: str,
    relation: str,
) -> list[dict[str, Any]] | None:
    """Read columns for one persisted source; never accepts caller SQL."""
    from src.metadata_discovery import describe_table
    from src.postgres_connector import open_session_connection, peek_session_connection

    session = peek_session_connection(connection_id)
    if session is None:
        return None
    try:
        with open_session_connection(session) as conn:
            return describe_table(conn, schema, relation)
    except Exception:  # Connector failures are represented as unavailable facts.
        return None


class AssistantContextService:
    """Build a stable assistant context from existing read-only state owners."""

    def __init__(
        self,
        *,
        state_path: Path | None = None,
        source_columns_reader: SourceColumnsReader = _source_columns_from_active_session,
    ) -> None:
        self._state_path = state_path
        self._source_columns_reader = source_columns_reader

    def build(self, *, run_id: str | None = None) -> dict[str, Any]:
        context = _empty_context()
        try:
            conn = get_readonly_connection(self._state_path)
        except sqlite3.OperationalError:
            return context

        try:
            run = self._load_run(conn, run_id)
            if run is None:
                return context

            context["run"] = {
                "id": run["run_id"],
                "status": run["status"],
                "mode": run["mode"],
                "started_at": run["started_at"],
                "finished_at": run["finished_at"],
                "dataset_config": run["dataset_config"],
            }
            if run["error_message"]:
                context["messages"].append(
                    {
                        "area": "validation_run",
                        "code": "run_error",
                        "message": _redact_text(run["error_message"]),
                    }
                )

            connection = self._load_connection(conn, run["connection_id"])
            if connection is not None:
                context["connection"] = {
                    "id": connection["id"],
                    "database_name": connection["database_name"],
                    "status": connection["status"],
                }

            source_schema = run["source_schema"]
            source_relation = run["source_table"]
            context["source"] = {
                "schema": source_schema,
                "relation": source_relation,
                "columns": None,
            }
            if run["connection_id"] and source_schema and source_relation:
                columns = self._source_columns_reader(
                    run["connection_id"], source_schema, source_relation
                )
                if columns is not None:
                    context["source"]["columns"] = _safe_value(columns)

            report = self._load_report(conn, run["run_id"])
            context["bronze"] = self._bronze_context(
                conn, run, report
            )
            context["silver"] = self._silver_context(conn, context["bronze"], report)
            context["gold"] = self._gold_context(conn, context["messages"])
            return context
        finally:
            conn.close()

    @staticmethod
    def _fetchone(conn: sqlite3.Connection, query: str, params: tuple = ()) -> sqlite3.Row | None:
        try:
            return conn.execute(query, params).fetchone()
        except sqlite3.OperationalError:
            return None

    def _load_run(self, conn: sqlite3.Connection, run_id: str | None) -> sqlite3.Row | None:
        fields = """
            run_id, connection_id, status, mode, started_at, finished_at,
            error_message, source_schema, source_table, dataset_config
        """
        if run_id:
            return self._fetchone(
                conn, f"SELECT {fields} FROM validation_runs WHERE run_id = ?", (run_id,)
            )
        return self._fetchone(
            conn,
            f"SELECT {fields} FROM validation_runs ORDER BY started_at DESC, run_id DESC LIMIT 1",
        )

    def _load_connection(self, conn: sqlite3.Connection, connection_id: str | None) -> sqlite3.Row | None:
        if not connection_id:
            return None
        return self._fetchone(
            conn,
            "SELECT id, database_name, status FROM data_connections WHERE id = ?",
            (connection_id,),
        )

    def _load_report(self, conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
        row = self._fetchone(
            conn, "SELECT report_json FROM validation_reports WHERE run_id = ?", (run_id,)
        )
        return _json_object(row["report_json"]) if row is not None else None

    def _bronze_context(
        self, conn: sqlite3.Connection, run: sqlite3.Row, report: dict[str, Any] | None
    ) -> dict[str, Any]:
        authority = None
        if run["connection_id"] and run["source_schema"] and run["source_table"]:
            authority = self._fetchone(
                conn,
                """
                SELECT ingest_id, bronze_schema, bronze_relation, status
                FROM bronze_ingest_authority
                WHERE connection_id = ? AND source_schema = ? AND source_relation = ?
                ORDER BY updated_at DESC, ingest_id DESC LIMIT 1
                """,
                (run["connection_id"], run["source_schema"], run["source_table"]),
            )
        b1 = _find_check(report, "bronze", "B1")
        return {
            "authority_status": authority["status"] if authority is not None else None,
            "ingest_id": authority["ingest_id"] if authority is not None else None,
            "schema": authority["bronze_schema"] if authority is not None else None,
            "relation": authority["bronze_relation"] if authority is not None else None,
            "validation_status": _layer_status(report, "bronze"),
            "row_count": _as_int(b1.get("observed")) if b1 else None,
        }

    def _silver_context(
        self, conn: sqlite3.Connection, bronze: dict[str, Any], report: dict[str, Any] | None
    ) -> dict[str, Any]:
        rules_row = None
        bronze_relation = bronze.get("relation")
        if bronze_relation:
            rules_row = self._fetchone(
                conn,
                "SELECT rules_json, rule_revision, updated_at FROM table_rules WHERE table_name = ?",
                (bronze_relation,),
            )
        s1 = _find_check(report, "silver", "S1")
        s8 = _find_check(report, "silver", "S8")
        s10 = _find_check(report, "silver", "S10")
        s1_extra = _as_dict(s1.get("extra")) if s1 else {}
        s8_extra = _as_dict(s8.get("extra")) if s8 else {}
        s10_extra = _as_dict(s10.get("extra")) if s10 else {}
        root_cause = _as_dict(_as_dict(report).get("root_cause"))
        rules = _json_object(rules_row["rules_json"]) if rules_row is not None else None
        if rules is None and rules_row is not None:
            try:
                parsed_rules = json.loads(rules_row["rules_json"])
            except (TypeError, ValueError):
                parsed_rules = None
            rules = {"rules": parsed_rules} if isinstance(parsed_rules, list) else None
        return {
            "validation_status": _layer_status(report, "silver"),
            "row_count": _as_int(s1_extra.get("silver")),
            "retained_count": None,
            "removed_count": _as_int(s8_extra.get("missing")),
            "invalid_count": None,
            "transformation": {
                "rules": _safe_value(rules.get("rules")) if rules else None,
                "rule_revision": rules_row["rule_revision"] if rules_row is not None else None,
                "updated_at": rules_row["updated_at"] if rules_row is not None else None,
                "summary": _safe_value(root_cause.get("summary")),
                "suspected_filter": _safe_value(s10_extra.get("suspected_filter")) if s10_extra else None,
            },
        }

    def _gold_context(self, conn: sqlite3.Connection, messages: list[dict[str, Any]]) -> dict[str, Any]:
        row = self._fetchone(
            conn,
            """
            SELECT r.run_id, r.status, r.created_at, r.table_name, r.planned_changes_json,
                   s.business_requirement, s.selected_sources_json, s.target_schema,
                   s.target_name, s.candidate_schema, s.candidate_name,
                   s.execution_failure_code, s.promotion_failure_code
            FROM generated_sql_review r
            JOIN gold_security_state s ON s.run_id = r.run_id
            ORDER BY r.created_at DESC, r.run_id DESC LIMIT 1
            """,
        )
        if row is None:
            return _empty_gold_context()
        for field, code in (
            ("execution_failure_code", "execution_failed"),
            ("promotion_failure_code", "promotion_failed"),
        ):
            if row[field]:
                messages.append(
                    {
                        "area": "gold",
                        "code": code,
                        "message": _safe_value(row[field]),
                    }
                )
        planned = _json_object(row["planned_changes_json"])
        sources = _json_object(row["selected_sources_json"])
        return {
            "run_id": row["run_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "business_requirement": _safe_value(row["business_requirement"]),
            "planned_calculation": _safe_value(planned),
            "sources": _safe_value(sources.get("sources")) if sources else None,
            "target": {
                "schema": row["target_schema"],
                "relation": row["target_name"] or row["table_name"],
            },
            "candidate": {
                "schema": row["candidate_schema"],
                "relation": row["candidate_name"],
            },
        }


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _find_check(report: dict[str, Any] | None, layer: str, check_id: str) -> dict[str, Any] | None:
    checks = _as_dict(_as_dict(report).get("checks"))
    candidates = checks.get(layer)
    if not isinstance(candidates, list):
        return None
    return next(
        (item for item in candidates if isinstance(item, dict) and item.get("check_id") == check_id),
        None,
    )


def _layer_status(report: dict[str, Any] | None, layer: str) -> str | None:
    status = _as_dict(_as_dict(report).get("layer_status")).get(layer)
    return status if isinstance(status, str) else None


def _empty_gold_context() -> dict[str, Any]:
    return {
        "run_id": None,
        "status": None,
        "created_at": None,
        "business_requirement": None,
        "planned_calculation": None,
        "sources": None,
        "target": {"schema": None, "relation": None},
        "candidate": {"schema": None, "relation": None},
    }


def _empty_context() -> dict[str, Any]:
    return {
        "schema_version": ASSISTANT_CONTEXT_SCHEMA_VERSION,
        "run": {
            "id": None,
            "status": None,
            "mode": None,
            "started_at": None,
            "finished_at": None,
            "dataset_config": None,
        },
        "connection": {"id": None, "database_name": None, "status": None},
        "source": {"schema": None, "relation": None, "columns": None},
        "bronze": {
            "authority_status": None,
            "ingest_id": None,
            "schema": None,
            "relation": None,
            "validation_status": None,
            "row_count": None,
        },
        "silver": {
            "validation_status": None,
            "row_count": None,
            "retained_count": None,
            "removed_count": None,
            "invalid_count": None,
            "transformation": {
                "rules": None,
                "rule_revision": None,
                "updated_at": None,
                "summary": None,
                "suspected_filter": None,
            },
        },
        "gold": _empty_gold_context(),
        "messages": [],
    }


def build_assistant_context(
    *, run_id: str | None = None, state_path: Path | None = None
) -> dict[str, Any]:
    """Return the deterministic context contract for a persisted run or latest run."""
    return AssistantContextService(state_path=state_path).build(run_id=run_id)
