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
_REPORT_DETAIL_KEY = re.compile(
    r"(?:sql|query|statement|ddl|dml|prompt|credential|secret|token|api[_-]?key)",
    re.IGNORECASE,
)


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


def _safe_report_summary(value: Any) -> Any:
    """Keep human report summaries while dropping raw SQL/query/detail fields."""
    if isinstance(value, dict):
        return {
            str(key): _safe_report_summary(item)
            for key, item in value.items()
            if not _REPORT_DETAIL_KEY.search(str(key))
        }
    if isinstance(value, list):
        return [_safe_report_summary(item) for item in value]
    return _safe_value(value)


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
        if not run_id:
            return _finalize_context(context)

        try:
            conn = get_readonly_connection(self._state_path)
        except sqlite3.OperationalError:
            return _finalize_context(context)

        try:
            run = self._load_run(conn, run_id)
            if run is None:
                gold_run = self._load_gold_run_header(conn, run_id)
                if gold_run is not None:
                    return _finalize_context(self._build_from_gold_run(conn, context, gold_run))
                silver_run = self._load_silver_run_header(conn, run_id)
                if silver_run is not None:
                    return _finalize_context(self._build_from_silver_run(conn, context, silver_run))
                return _finalize_context(context)

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
            context["gold"] = self._gold_context(conn, context["messages"], run_id=run["run_id"])
            context["quality"] = _quality_context(report)
            return _finalize_context(context)
        finally:
            conn.close()

    @staticmethod
    def _fetchone(conn: sqlite3.Connection, query: str, params: tuple = ()) -> sqlite3.Row | None:
        try:
            return conn.execute(query, params).fetchone()
        except sqlite3.OperationalError:
            return None

    @staticmethod
    def _fetchall(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[sqlite3.Row]:
        try:
            return conn.execute(query, params).fetchall()
        except sqlite3.OperationalError:
            return []

    def _find_gold_bronze_authority(
        self,
        conn: sqlite3.Connection,
        connection_id: str | None,
        first_source: dict[str, Any] | None,
    ) -> sqlite3.Row | None:
        if not first_source:
            return None

        source_schema = first_source.get("schema")
        source_table = first_source.get("table")
        if not source_table:
            return None

        if connection_id:
            if source_schema:
                query = """
                    SELECT ingest_id, project_id, connection_id, database_name,
                           source_schema, source_relation, bronze_schema, bronze_relation, status
                    FROM bronze_ingest_authority
                    WHERE connection_id = ?
                      AND (
                        (source_schema = ? AND source_relation = ?)
                        OR (bronze_schema = ? AND bronze_relation = ?)
                      )
                """
                params = (connection_id, source_schema, source_table, source_schema, source_table)
            else:
                query = """
                    SELECT ingest_id, project_id, connection_id, database_name,
                           source_schema, source_relation, bronze_schema, bronze_relation, status
                    FROM bronze_ingest_authority
                    WHERE connection_id = ?
                      AND (source_relation = ? OR bronze_relation = ?)
                """
                params = (connection_id, source_table, source_table)
            rows = self._fetchall(conn, query, params)
            if len(rows) == 1:
                return rows[0]
            return None

        if source_schema:
            query = """
                SELECT ingest_id, project_id, connection_id, database_name,
                       source_schema, source_relation, bronze_schema, bronze_relation, status
                FROM bronze_ingest_authority
                WHERE (source_schema = ? AND source_relation = ?)
                   OR (bronze_schema = ? AND bronze_relation = ?)
            """
            params = (source_schema, source_table, source_schema, source_table)
        else:
            query = """
                SELECT ingest_id, project_id, connection_id, database_name,
                       source_schema, source_relation, bronze_schema, bronze_relation, status
                FROM bronze_ingest_authority
                WHERE source_relation = ? OR bronze_relation = ?
            """
            params = (source_table, source_table)

        rows = self._fetchall(conn, query, params)
        if len(rows) == 1:
            return rows[0]

        return None

    def _load_run(self, conn: sqlite3.Connection, run_id: str | None) -> sqlite3.Row | None:
        fields = """
            run_id, connection_id, status, mode, started_at, finished_at,
            error_message, source_schema, source_table, dataset_config
        """
        if not run_id:
            return None
        return self._fetchone(
            conn, f"SELECT {fields} FROM validation_runs WHERE run_id = ?", (run_id,)
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
        rule_list = rules.get("rules") if rules else None
        rule_summary = _safe_value(root_cause.get("summary"))
        if not rule_summary and rule_list:
            rule_summary = f"Silver transformation configured with rules: {json.dumps(rule_list)}"
        val_status = _layer_status(report, "silver")
        if not val_status and rules_row is not None:
            val_status = "RULES_CONFIGURED"
        return {
            "validation_status": val_status,
            "row_count": _as_int(s1_extra.get("silver")),
            "retained_count": None,
            "removed_count": _as_int(s8_extra.get("missing")),
            "invalid_count": None,
            "transformation": {
                "rules": _safe_value(rule_list),
                "rule_revision": rules_row["rule_revision"] if rules_row is not None else None,
                "updated_at": rules_row["updated_at"] if rules_row is not None else None,
                "summary": rule_summary,
                "suspected_filter": _safe_value(s10_extra.get("suspected_filter")) if s10_extra else None,
            },
        }

    def _load_gold_run_header(self, conn: sqlite3.Connection, run_id: str | None) -> sqlite3.Row | None:
        fields = """
            r.run_id, r.status, r.created_at, r.table_name, r.planned_changes_json,
            s.business_requirement, s.selected_sources_json, s.target_schema,
            s.target_name, s.candidate_schema, s.candidate_name,
            s.execution_failure_code, s.promotion_failure_code,
            r.connection_id
        """
        if not run_id:
            return None
        return self._fetchone(
            conn,
            f"""
            SELECT {fields}
            FROM generated_sql_review r
            JOIN gold_security_state s ON s.run_id = r.run_id
            WHERE r.run_id = ?
            """,
            (run_id,),
        )

    def _load_silver_run_header(self, conn: sqlite3.Connection, run_id: str | None) -> sqlite3.Row | None:
        fields = """
            run_id, status, created_at, table_name, planned_changes_json,
            connection_id, source_identity_json, rule_revision
        """
        if not run_id:
            return None
        return self._fetchone(
            conn,
            f"SELECT {fields} FROM generated_sql_review WHERE run_id = ?",
            (run_id,),
        )

    def _build_from_silver_run(
        self, conn: sqlite3.Connection, context: dict[str, Any], silver_run: sqlite3.Row
    ) -> dict[str, Any]:
        context["run"] = {
            "id": silver_run["run_id"],
            "status": silver_run["status"],
            "mode": "silver",
            "started_at": silver_run["created_at"],
            "finished_at": silver_run["created_at"],
            "dataset_config": None,
        }
        connection_id = silver_run["connection_id"]
        if connection_id:
            connection = self._load_connection(conn, connection_id)
            if connection is not None:
                context["connection"] = {
                    "id": connection["id"],
                    "database_name": connection["database_name"],
                    "status": connection["status"],
                }

        source_ident = _json_object(silver_run["source_identity_json"])
        source_schema = source_ident.get("schema") if source_ident else None
        source_table = (
            (source_ident.get("relation_name") or source_ident.get("relation") or source_ident.get("table"))
            if source_ident
            else silver_run["table_name"]
        )

        authority = None
        if connection_id and source_table:
            if source_schema:
                query = """
                    SELECT ingest_id, source_schema, source_relation,
                           bronze_schema, bronze_relation, status
                    FROM bronze_ingest_authority
                    WHERE connection_id = ? AND (
                        (source_schema = ? AND source_relation = ?)
                        OR (bronze_schema = ? AND bronze_relation = ?)
                    )
                """
                params = (connection_id, source_schema, source_table, source_schema, source_table)
            else:
                query = """
                    SELECT ingest_id, source_schema, source_relation,
                           bronze_schema, bronze_relation, status
                    FROM bronze_ingest_authority
                    WHERE connection_id = ? AND (
                        source_relation = ? OR bronze_relation = ?
                    )
                """
                params = (connection_id, source_table, source_table)
            rows = self._fetchall(conn, query, params)
            if len(rows) == 1:
                authority = rows[0]

        context["source"] = {
            "schema": source_schema or (authority["source_schema"] if authority else None),
            "relation": source_table,
            "columns": None,
        }
        eff_schema = context["source"]["schema"]
        if connection_id and eff_schema and source_table:
            columns = self._source_columns_reader(connection_id, eff_schema, source_table)
            if columns is not None:
                context["source"]["columns"] = _safe_value(columns)

        context["bronze"] = {
            "authority_status": authority["status"] if authority is not None else None,
            "ingest_id": authority["ingest_id"] if authority is not None else None,
            "schema": authority["bronze_schema"] if authority is not None else None,
            "relation": authority["bronze_relation"] if authority is not None else None,
            "validation_status": None,
            "row_count": None,
        }

        context["silver"] = self._silver_context(conn, context["bronze"], None)
        planned = _json_object(silver_run["planned_changes_json"])
        if planned and isinstance(context["silver"], dict) and isinstance(context["silver"].get("transformation"), dict):
            rules = planned.get("rules")
            if rules:
                context["silver"]["transformation"]["rules"] = _safe_value(rules)

        return context

    def _build_from_gold_run(
        self, conn: sqlite3.Connection, context: dict[str, Any], gold_run: sqlite3.Row
    ) -> dict[str, Any]:
        context["run"] = {
            "id": gold_run["run_id"],
            "status": gold_run["status"],
            "mode": "gold",
            "started_at": gold_run["created_at"],
            "finished_at": gold_run["created_at"],
            "dataset_config": None,
        }
        connection_id = gold_run["connection_id"]
        if connection_id:
            connection = self._load_connection(conn, connection_id)
            if connection is not None:
                context["connection"] = {
                    "id": connection["id"],
                    "database_name": connection["database_name"],
                    "status": connection["status"],
                }

        sources_obj = _json_object(gold_run["selected_sources_json"])
        sources_list = sources_obj.get("sources") if sources_obj else None
        first_source = (
            sources_list[0]
            if isinstance(sources_list, list)
            and len(sources_list) > 0
            and isinstance(sources_list[0], dict)
            else None
        )

        authority = self._find_gold_bronze_authority(conn, connection_id, first_source)
        silver_relation = None
        if authority is not None:
            context["source"] = {
                "schema": authority["source_schema"],
                "relation": authority["source_relation"],
                "columns": None,
            }
            conn_id = connection_id or authority["connection_id"]
            if conn_id and authority["source_schema"] and authority["source_relation"]:
                columns = self._source_columns_reader(
                    conn_id, authority["source_schema"], authority["source_relation"]
                )
                if columns is not None:
                    context["source"]["columns"] = _safe_value(columns)
            context["bronze"] = {
                "authority_status": authority["status"],
                "ingest_id": authority["ingest_id"],
                "schema": authority["bronze_schema"],
                "relation": authority["bronze_relation"],
                "validation_status": None,
                "row_count": None,
            }
            silver_relation = authority["bronze_relation"]
        elif first_source and first_source.get("table"):
            silver_relation = first_source["table"]
            rules_check = self._fetchone(conn, "SELECT table_name FROM table_rules WHERE table_name = ?", (silver_relation,))
            if rules_check is not None:
                context["source"] = {
                    "schema": "bronze",
                    "relation": silver_relation,
                    "columns": None,
                }
                context["bronze"] = {
                    "authority_status": "READY",
                    "ingest_id": None,
                    "schema": "bronze",
                    "relation": silver_relation,
                    "validation_status": "READY",
                    "row_count": None,
                }

        if silver_relation:
            context["silver"] = self._silver_context(conn, {"relation": silver_relation}, None)

        context["gold"] = self._gold_context(
            conn, context["messages"], run_id=gold_run["run_id"]
        )
        return context

    def _gold_context(
        self, conn: sqlite3.Connection, messages: list[dict[str, Any]], run_id: str | None = None
    ) -> dict[str, Any]:
        if not run_id:
            return _empty_gold_context()
        fields = """
            r.run_id, r.status, r.created_at, r.table_name, r.planned_changes_json,
            s.business_requirement, s.selected_sources_json, s.target_schema,
            s.target_name, s.candidate_schema, s.candidate_name,
            s.execution_failure_code, s.promotion_failure_code
        """
        query = f"""
            SELECT {fields}
            FROM generated_sql_review r
            JOIN gold_security_state s ON s.run_id = r.run_id
            WHERE r.run_id = ?
            LIMIT 1
        """
        row = self._fetchone(conn, query, (run_id,))
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


def _safe_check_summaries(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    checks = _as_dict(_as_dict(report).get("checks"))
    for layer, layer_checks in checks.items():
        if not isinstance(layer, str) or not isinstance(layer_checks, list):
            continue
        for check in layer_checks:
            if not isinstance(check, dict):
                continue
            status = check.get("status")
            if status != "FAIL":
                continue
            summary = {
                "layer": layer,
                "check_id": check.get("check_id"),
                "name": check.get("name"),
                "status": status,
                "meaning": check.get("meaning"),
                "observed": check.get("observed"),
                "expected": check.get("expected"),
            }
            summaries.append(_safe_value({k: v for k, v in summary.items() if v is not None}))
    return summaries


def _quality_context(report: dict[str, Any] | None) -> dict[str, Any]:
    report_obj = _as_dict(report)
    return {
        "layer_status": _safe_value(_as_dict(report_obj.get("layer_status"))),
        "first_failed_layer": _safe_value(report_obj.get("first_failed_layer")),
        "trust_decision": _safe_value(
            report_obj.get("trust_decision")
            or report_obj.get("trust_status")
            or report_obj.get("verdict")
        ),
        "root_cause": _safe_report_summary(report_obj.get("root_cause")),
        "business_impact": _safe_report_summary(report_obj.get("business_impact")),
        "suggested_action": _safe_report_summary(report_obj.get("suggested_action")),
        "failed_checks": _safe_check_summaries(report),
    }


def _relation_fact(schema: Any, relation: Any) -> dict[str, Any] | None:
    if isinstance(schema, str) and isinstance(relation, str):
        return {"schema": schema, "relation": relation}
    return None


def _has_known_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return any(_has_known_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_known_value(item) for item in value)
    return True


def _dataset_context(context: dict[str, Any]) -> dict[str, Any]:
    run = _as_dict(context.get("run"))
    source = _as_dict(context.get("source"))
    bronze = _as_dict(context.get("bronze"))
    silver = _as_dict(context.get("silver"))
    gold = _as_dict(context.get("gold"))
    gold_target = _as_dict(gold.get("target"))

    layer_relations = {
        "source": _relation_fact(source.get("schema"), source.get("relation")),
        "bronze": _relation_fact(bronze.get("schema"), bronze.get("relation")),
        "gold": _relation_fact(gold_target.get("schema"), gold_target.get("relation")),
    }
    available_layers = [
        layer
        for layer, facts in (
            ("source", layer_relations["source"]),
            ("bronze", layer_relations["bronze"] or bronze.get("authority_status")),
            ("silver", silver.get("validation_status") or _as_dict(silver.get("transformation"))),
            ("gold", gold.get("status") or layer_relations["gold"]),
        )
        if _has_known_value(facts)
    ]
    return {
        "config": run.get("dataset_config"),
        "source": layer_relations["source"],
        "available_layers": available_layers,
        "layer_relations": layer_relations,
        "row_counts": {
            "bronze": bronze.get("row_count"),
            "silver": silver.get("row_count"),
        },
        "quality_status": _as_dict(context.get("quality")).get("layer_status"),
    }


def _finalize_context(context: dict[str, Any]) -> dict[str, Any]:
    context["dataset"] = _dataset_context(context)
    return context


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
        "dataset": {
            "config": None,
            "source": None,
            "available_layers": [],
            "layer_relations": {"source": None, "bronze": None, "gold": None},
            "row_counts": {"bronze": None, "silver": None},
            "quality_status": {},
        },
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
        "quality": _quality_context(None),
        "messages": [],
    }


def build_assistant_context(
    *, run_id: str | None = None, state_path: Path | None = None
) -> dict[str, Any]:
    """Return the deterministic context contract for a persisted run or latest run."""
    return AssistantContextService(state_path=state_path).build(run_id=run_id)
