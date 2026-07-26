"""API Router for P2-A Bronze-to-Silver transformations."""

from __future__ import annotations

import json
import re
import logging
import datetime
from typing import List, Optional, Set, Tuple, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.app_state.db import get_connection, compute_rule_revision, is_valid_rule_revision, compute_silver_lineage_id, validate_promoted_identity_json
from src.db_config import (
    get_ingestion_pool, 
    get_generated_sql_pool, 
    postgres_promotion_conninfo,
    postgres_target_info,
    load_layer_schemas,
    load_postgres_config,
)
from src.sql_safety import validate_generated_sql, execute_candidate_sql
from src.promotion import promote_candidate_table, resolve_relation_identity
from src.generator_trust import GeneratorTrustPolicy
from src.silver_rules import (
    PostgresColumnType,
    SilverRuleError,
    build_deterministic_silver_sql,
    rule_attribution_label,
    validate_deterministic_rules,
)
import sqlglot

try:
    import psycopg
    from psycopg import OperationalError as PsycopgOperationalError
except ImportError:
    PsycopgOperationalError = None

try:
    from psycopg_pool import PoolTimeout, PoolClosed
except ImportError:
    PoolTimeout = PoolClosed = None

def is_db_connection_error(exc: Exception) -> bool:
    """Return True if exc is a genuine Postgres/pool connection operational error."""
    if PsycopgOperationalError is not None and isinstance(exc, PsycopgOperationalError):
        return True
    if PoolTimeout is not None and isinstance(exc, PoolTimeout):
        return True
    if PoolClosed is not None and isinstance(exc, PoolClosed):
        return True
    return False

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/transform", tags=["transform"])

# Approved trusted generator provenances for execution eligibility
SERVER_DETERMINISTIC_PROVENANCE = "server_deterministic_rules_v1"
TRUSTED_GENERATOR_PROVENANCES: Set[str] = {
    "ollama_v1_generic",
    SERVER_DETERMINISTIC_PROVENANCE,
}
SILVER_GENERATOR_TRUST = GeneratorTrustPolicy(
    pipeline="silver",
    trusted_hardened_provenances=frozenset(TRUSTED_GENERATOR_PROVENANCES),
)

class RulesPayload(BaseModel):
    table_name: str
    rules: List[Any]

class GeneratePayload(BaseModel):
    table_name: str

def is_trusted_provenance(provenance: Optional[str]) -> bool:
    """Return True if provenance is recognized as a trusted generator implementation."""
    return SILVER_GENERATOR_TRUST.trusts_run(provenance)

def validate_sql_identifier(identifier: str) -> str:
    """Ensure string is a safe SQL identifier matching standard naming patterns."""
    if not identifier or not isinstance(identifier, str) or not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", identifier):
        raise ValueError(f"Invalid SQL identifier: {identifier}")
    return identifier

def validate_rules_shape(rules: Any) -> list[Any]:
    """Validate one homogeneous legacy-text or deterministic rule list."""
    if not isinstance(rules, list):
        raise ValueError("Rules must be a list.")
    if not rules:
        return []
    if all(isinstance(item, str) for item in rules):
        return rules
    if all(isinstance(item, dict) for item in rules):
        return validate_deterministic_rules(rules)
    raise ValueError(
        "Rules must be either legacy text strings or deterministic rule objects."
    )


def _load_exact_bronze_column_types(
    source_identity: dict[str, Any],
) -> dict[str, PostgresColumnType]:
    """Load exact pg_type metadata and bind it to the persisted Bronze identity."""
    with get_generated_sql_pool().connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT database.oid,
                       namespace.oid,
                       relation.oid,
                       namespace.nspname,
                       relation.relname,
                       relation.relkind,
                       attribute.attname,
                       type.oid,
                       type_namespace.nspname,
                       type.typname,
                       type.typtype
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                JOIN pg_catalog.pg_database AS database
                  ON database.datname = pg_catalog.current_database()
                JOIN pg_catalog.pg_type AS type
                  ON type.oid = attribute.atttypid
                JOIN pg_catalog.pg_namespace AS type_namespace
                  ON type_namespace.oid = type.typnamespace
                WHERE namespace.nspname = %s
                  AND relation.relname = %s
                  AND relation.relkind IN ('r', 'p')
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                ORDER BY attribute.attnum
                """,
                (
                    source_identity["schema"],
                    source_identity["relation_name"],
                ),
            )
            rows = cursor.fetchall()
    if not rows:
        raise SilverRuleError(
            "Exact Bronze relation has no trusted PostgreSQL column metadata"
        )
    column_types: dict[str, PostgresColumnType] = {}
    identity_fields = (
        "database_oid",
        "namespace_oid",
        "relation_oid",
        "schema",
        "relation_name",
        "relation_kind",
    )
    for row in rows:
        live_identity = dict(zip(identity_fields, row[:6]))
        if any(
            live_identity[field] != source_identity[field]
            for field in identity_fields
        ):
            raise SilverRuleError(
                "Exact Bronze relation identity changed before type validation"
            )
        column_types[str(row[6])] = PostgresColumnType(
            type_oid=int(row[7]),
            type_schema=str(row[8]),
            type_name=str(row[9]),
            type_kind=str(row[10]),
        )
    return column_types

def parse_attribution_log(raw_json: Optional[str]) -> Tuple[Optional[List[str]], bool]:
    """Structurally parse stored attribution_log_json.

    Returns (attribution_list, attribution_available).
    Only valid list[str] payloads are returned as attribution_list.
    Malformed JSON, dicts, scalars, or mixed arrays return (None, False).
    """
    if not raw_json or not isinstance(raw_json, str):
        return None, False
    try:
        data = json.loads(raw_json)
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            return data, True
        logger.warning("Stored attribution_log_json is not a list[str]: %r", type(data))
        return None, False
    except Exception as e:
        logger.warning("Failed to parse attribution_log_json: %s", e)
        return None, False

def _update_run_status(run_id: str, status: str, **kwargs) -> bool:
    """Helper for atomic terminal/lifecycle run-state transitions in SQLite."""
    try:
        fields = ["status = ?"]
        params = [status]
        for k, v in kwargs.items():
            fields.append(f"{k} = ?")
            params.append(v)
        params.append(run_id)
        set_clause = ", ".join(fields)
        with get_connection() as conn:
            cursor = conn.execute(f"UPDATE generated_sql_review SET {set_clause} WHERE run_id = ?", params)
            conn.commit()
            return cursor.rowcount > 0
    except Exception as e:
        logger.error("Failed to update status to %s for run %s: %s", status, run_id, e)
        return False

class TableNotFoundError(Exception):
    """Raised when a table is not found in the target schema."""
    pass

class DatabaseConnectionError(Exception):
    """Raised when database connection or query fails."""
    pass

class ConfigurationError(Exception):
    """Raised when Aurum layer/schema configuration is invalid."""
    pass

def get_table_schema(table_name: str) -> str:
    """Fetch schema details for a table in the bronze schema."""
    table_name = validate_sql_identifier(table_name)
    try:
        schemas = load_layer_schemas()
        bronze_schema = validate_sql_identifier(schemas.bronze)
    except Exception as e:
        logger.error("Failed to load layer schemas: %s", e)
        raise ConfigurationError("Invalid Aurum layer configuration.")

    try:
        with get_ingestion_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (bronze_schema, table_name)
                )
                rows = cur.fetchall()
                if not rows:
                    raise TableNotFoundError(f"Table {bronze_schema}.{table_name} not found.")
                return "\n".join([f"- {r[0]} ({r[1]})" for r in rows])
    except (TableNotFoundError, ConfigurationError):
        raise
    except Exception as e:
        logger.error("Failed to retrieve schema for %s: %s", table_name, e)
        if is_db_connection_error(e):
            raise DatabaseConnectionError("Database service is currently unavailable.")
        raise

@router.post("/rules")
def save_rules(payload: RulesPayload):
    """Save one legacy-text or deterministic Silver rule plan."""
    try:
        validate_sql_identifier(payload.table_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        validated_rules = validate_rules_shape(payload.rules)
    except (ValueError, SilverRuleError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not validated_rules:
        raise HTTPException(status_code=400, detail="Rules must not be empty.")

    if all(isinstance(item, str) for item in validated_rules):
        if any(not item.strip() for item in validated_rules):
            raise HTTPException(
                status_code=400,
                detail="Rules cannot contain empty or whitespace-only entries.",
            )
        normalized_rules: list[Any] = [
            item.strip() for item in validated_rules
        ]
        if len(normalized_rules) != len(set(normalized_rules)):
            raise HTTPException(
                status_code=400,
                detail="Duplicate rules are not allowed.",
            )
    else:
        normalized_rules = validated_rules

    rule_rev = compute_rule_revision(normalized_rules)
    if not rule_rev:
        raise HTTPException(status_code=400, detail="Failed to compute rule revision.")
    now = datetime.datetime.utcnow().isoformat()
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO table_rules (table_name, rules_json, rule_revision, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(table_name) DO UPDATE SET 
                    rules_json=excluded.rules_json,
                    rule_revision=excluded.rule_revision,
                    updated_at=excluded.updated_at
                """,
                (
                    payload.table_name,
                    json.dumps(
                        normalized_rules,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    rule_rev,
                    now,
                )
            )
            conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to save rules for table %s: %s", payload.table_name, e)
        raise HTTPException(status_code=500, detail="Failed to save table rules.")

    return {"status": "success", "message": "Rules saved successfully", "rule_revision": rule_rev}

@router.get("/rules/{table_name}")
def get_rules(table_name: str):
    """Fetch saved rules for a table with canonical rule revision."""
    try:
        validate_sql_identifier(table_name)
        with get_connection() as conn:
            row = conn.execute("SELECT rules_json, rule_revision FROM table_rules WHERE table_name = ?", (table_name,)).fetchone()
            if row:
                try:
                    rules = json.loads(row["rules_json"])
                    validate_rules_shape(rules)
                except Exception as e:
                    logger.error("Corrupt rules_json in table_rules for table %s: %s", table_name, e)
                    raise HTTPException(status_code=500, detail="Internal server error.")

                rule_rev = compute_rule_revision(rules)
                if not rule_rev:
                    raise HTTPException(status_code=500, detail="Internal server error.")
                return {"table_name": table_name, "rules": rules, "rule_revision": rule_rev}

            empty_rev = compute_rule_revision([])
            return {"table_name": table_name, "rules": [], "rule_revision": empty_rev}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to fetch rules for table %s: %s", table_name, e)
        raise HTTPException(status_code=500, detail="Failed to fetch table rules.")

@router.post("/generate")
def generate_sql(payload: GeneratePayload):
    """P2.2 & P2.3: Generate SQL for requested table (503 contained if no deterministic rules)."""
    # 1. Fetch rules
    rules_resp = get_rules(payload.table_name)
    rules = rules_resp.get("rules", [])
    if not rules or not (isinstance(rules, list) and all(isinstance(r, dict) for r in rules)):
        raise HTTPException(
            status_code=503,
            detail="Production Silver generation is unavailable."
        )

    try:
        schemas = load_layer_schemas()
        with get_generated_sql_pool().connection() as pg_conn:
            source_identity = resolve_relation_identity(pg_conn, schemas.bronze, payload.table_name)
            if not source_identity:
                raise HTTPException(status_code=404, detail=f"Bronze table '{payload.table_name}' not found.")
            column_types = _load_exact_bronze_column_types(source_identity)
            
        validated_rules = validate_deterministic_rules(
            rules,
            available_columns=column_types,
            column_types=column_types,
        )
        rule_rev = compute_rule_revision(validated_rules)
        import uuid
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        candidate_name = f"{payload.table_name}_candidate_{run_id}"
        
        sql_text = build_deterministic_silver_sql(
            candidate_schema=schemas.silver_candidates,
            candidate_name=candidate_name,
            bronze_schema=schemas.bronze,
            bronze_relation=payload.table_name,
            rules=validated_rules,
        )
        
        lineage_id = compute_silver_lineage_id(
            project_id="default_project",
            connection_id="default_connection",
            database_name=postgres_target_info()["database"],
            bronze_schema=schemas.bronze,
            bronze_relation=payload.table_name,
            silver_schema=schemas.silver,
            silver_target_relation=payload.table_name,
        )
        
        created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        planned_changes = {"rules": validated_rules}
        
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO generated_sql_review (
                    run_id, table_name, sql_text, planned_changes_json,
                    created_at, status, candidate_schema, generator_provenance,
                    rule_revision, project_id, connection_id, silver_lineage_id,
                    source_identity_json
                )
                VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    payload.table_name,
                    sql_text,
                    json.dumps(planned_changes, sort_keys=True, separators=(",", ":")),
                    created_at,
                    schemas.silver_candidates,
                    SERVER_DETERMINISTIC_PROVENANCE,
                    rule_rev,
                    "default_project",
                    "default_connection",
                    lineage_id,
                    json.dumps(source_identity, sort_keys=True, separators=(",", ":")),
                ),
            )
            conn.commit()
            
        return {
            "run_id": run_id,
            "table_name": payload.table_name,
            "sql_text": sql_text,
            "planned_changes": planned_changes,
            "status": "PENDING",
            "rule_revision": rule_rev,
            "generator_provenance": SERVER_DETERMINISTIC_PROVENANCE,
        }
    except SilverRuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to generate deterministic Silver SQL for %s", payload.table_name)
        raise HTTPException(status_code=500, detail="Failed to generate Silver SQL.")

@router.get("/review/{run_id}")
def review_sql(run_id: str):
    """P2.5: Review the generated SQL and validate it again (no execution)."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT table_name, sql_text, planned_changes_json, created_at,
                   status, generator_provenance, rule_revision,
                   promoted_target_identity_json, source_identity_json
            FROM generated_sql_review
            WHERE run_id = ?
            """,
            (run_id,)
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Run ID not found.")

    sql_text = row["sql_text"]
    table_name = row["table_name"]
    try:
        planned_changes = json.loads(row["planned_changes_json"])
        if not isinstance(planned_changes, dict) or "rules" not in planned_changes:
            raise ValueError("planned_changes_json missing rules dictionary")
        validate_rules_shape(planned_changes["rules"])
    except Exception as e:
        logger.error("Corrupt planned_changes_json for review run %s: %s", run_id, e)
        raise HTTPException(status_code=500, detail="Internal server error.")

    status_val = row["status"] or "PENDING"
    provenance = row["generator_provenance"]
    run_rule_rev = row["rule_revision"]

    # Fetch current saved table rule revision
    rules_info = get_rules(table_name)
    current_table_rule_rev = rules_info.get("rule_revision")

    if status_val == "PROMOTED":
        promoted_ident = validate_promoted_identity_json(row["promoted_target_identity_json"])
        if not promoted_ident:
            raise HTTPException(
                status_code=409,
                detail="Run status is PROMOTED but promoted target identity is missing or malformed. Manual reconciliation required."
            )
        executed = True
    else:
        executed = False

    # Check structural SQL validity
    sql_is_valid = False
    validated_sql = sql_text
    try:
        schemas = load_layer_schemas()
        source_identity = validate_promoted_identity_json(
            row["source_identity_json"]
        )
        bronze_schema = validate_sql_identifier(
            source_identity["schema"] if source_identity else schemas.bronze
        )
        bronze_table = validate_sql_identifier(
            source_identity["relation_name"] if source_identity else table_name
        )
        candidate_schema = validate_sql_identifier(schemas.silver_candidates)
        validated_sql = validate_generated_sql(
            sql_text,
            expected_schema=candidate_schema,
            expected_table_name=table_name,
            expected_bronze_schema=bronze_schema,
            expected_bronze_table_name=bronze_table,
            run_id=run_id,
            expected_step_count=(
                len(planned_changes.get("rules", [])) + 1
                if provenance == SERVER_DETERMINISTIC_PROVENANCE
                else len(planned_changes.get("rules", []))
            ),
            mode="p2_silver",
        )
        sql_is_valid = True
    except Exception as e:
        logger.warning("SQL validation failed for review run %s: %s", run_id, e)

    # Executable requires: PENDING status, trusted provenance, matching valid 64-char rule revision against current saved rules, valid SQL
    revision_matches = (
        is_valid_rule_revision(run_rule_rev)
        and is_valid_rule_revision(current_table_rule_rev)
        and run_rule_rev == current_table_rule_rev
    )
    executable = (
        status_val == "PENDING"
        and is_trusted_provenance(provenance)
        and revision_matches
        and sql_is_valid
    )

    return {
        "run_id": run_id,
        "table_name": table_name,
        "planned_changes": planned_changes,
        "sql_text": validated_sql,
        "executed": executed,
        "executable": executable,
        "status": status_val,
        "generator_provenance": provenance,
        "rule_revision": run_rule_rev,
        "message": (
            "SQL has already been executed and promoted." if executed
            else "SQL is validated and ready for execution." if executable
            else "SQL review is untrusted, stale, or non-executable."
        )
    }

@router.post("/execute/{run_id}")
def execute_sql(run_id: str):
    """P2-B: Execute generated SQL, compute cumulative attribution, and promote to silver."""
    # 1. PRECLAIM IMMUTABLE VALIDATION BEFORE ATOMIC CLAIM
    with get_connection() as conn_db:
        row = conn_db.execute(
            """
            SELECT table_name, sql_text, planned_changes_json, status, generator_provenance, rule_revision,
                   project_id, connection_id, silver_lineage_id, source_identity_json
            FROM generated_sql_review
            WHERE run_id = ?
            """,
            (run_id,)
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Run ID not found.")

    table_name = validate_sql_identifier(row["table_name"])
    status_val = row["status"]
    provenance = row["generator_provenance"]
    run_rule_rev = row["rule_revision"]

    if status_val == "PROMOTED":
        with get_connection() as conn_db:
            promoted_row = conn_db.execute(
                "SELECT attribution_log_json, promoted_target_identity_json FROM generated_sql_review WHERE run_id = ?",
                (run_id,)
            ).fetchone()
        promoted_ident = validate_promoted_identity_json(promoted_row["promoted_target_identity_json"] if promoted_row else None)
        if not promoted_ident:
            raise HTTPException(
                status_code=409,
                detail="Run status is PROMOTED but promoted target identity is missing or malformed. Manual reconciliation required."
            )
        attr_log, attr_avail = parse_attribution_log(promoted_row["attribution_log_json"] if promoted_row else None)
        return {
            "status": "success",
            "run_id": run_id,
            "table_name": table_name,
            "target": promoted_ident,
            "attribution_log": attr_log,
            "attribution_available": attr_avail,
            "message": f"Transformation for '{table_name}' was already executed and promoted."
        }
    elif status_val in ("EXECUTING", "PROMOTING"):
        raise HTTPException(status_code=409, detail="Execution or promotion already in progress for this run.")
    elif status_val == "AMBIGUOUS_PROMOTION":
        raise HTTPException(
            status_code=409,
            detail="Run state is ambiguous (PostgreSQL promotion may have succeeded, but app state update failed). Manual reconciliation is required."
        )
    elif status_val == "FAILED":
        raise HTTPException(status_code=400, detail="Run execution failed previously and cannot be re-executed.")
    elif status_val != "PENDING":
        raise HTTPException(status_code=400, detail=f"Run is not eligible for execution (status: {status_val}).")

    # Enforce strict pre-bound authority for all Silver transformations (fail closed on legacy unbound rows)
    proj_id = row["project_id"] if "project_id" in row.keys() else None
    conn_id = row["connection_id"] if "connection_id" in row.keys() else None
    lineage_id = row["silver_lineage_id"] if "silver_lineage_id" in row.keys() else None
    raw_src_ident = row["source_identity_json"] if "source_identity_json" in row.keys() else None

    if not proj_id or not conn_id or not lineage_id or not raw_src_ident:
        logger.error("Review run %s is missing pre-bound Silver authority (project_id, connection_id, silver_lineage_id, source_identity_json).", run_id)
        raise HTTPException(
            status_code=400,
            detail="Review run is missing pre-bound lineage and source authority."
        )

    try:
        source_authority = json.loads(raw_src_ident) if isinstance(raw_src_ident, str) else raw_src_ident
        source_authority = validate_promoted_identity_json(source_authority)
    except Exception as e:
        logger.error("Review run %s has invalid source_identity_json: %s", run_id, e)
        raise HTTPException(
            status_code=400,
            detail="Review run contains malformed source_identity_json authority."
        )

    if not source_authority:
        raise HTTPException(
            status_code=400,
            detail="Review run contains missing or invalid source_identity_json authority."
        )

    if not is_trusted_provenance(provenance):
        raise HTTPException(status_code=400, detail="Run is untrusted or missing valid generator provenance.")

    if not is_valid_rule_revision(run_rule_rev):
        raise HTTPException(status_code=400, detail="Run is missing a valid rule revision.")

    # Rule revision preflight comparison against current saved table rules
    rules_info = get_rules(table_name)
    current_table_rule_rev = rules_info.get("rule_revision")
    if not is_valid_rule_revision(current_table_rule_rev) or run_rule_rev != current_table_rule_rev:
        raise HTTPException(
            status_code=400,
            detail="Rules have changed since this review was generated."
        )

    # Decode planned changes JSON and validate shape
    try:
        planned_changes = json.loads(row["planned_changes_json"])
        if not isinstance(planned_changes, dict) or "rules" not in planned_changes:
            raise ValueError("planned_changes_json missing rules dictionary")
        rules = validate_rules_shape(planned_changes["rules"])
    except Exception as e:
        logger.error("Corrupt planned_changes_json for execution run %s: %s", run_id, e)
        raise HTTPException(status_code=500, detail="Internal server error.")
    if compute_rule_revision(rules) != run_rule_rev:
        raise HTTPException(
            status_code=400,
            detail="Persisted Silver rule plan is stale or malformed.",
        )

    sql_text = row["sql_text"]

    try:
        schemas = load_layer_schemas()
        bronze_schema = validate_sql_identifier(source_authority["schema"])
        bronze_table = validate_sql_identifier(source_authority["relation_name"])
        candidates_schema = validate_sql_identifier(schemas.silver_candidates)
        silver_schema = validate_sql_identifier(schemas.silver)
    except Exception as e:
        logger.error("Failed to load layer schemas: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error.")

    if provenance == SERVER_DETERMINISTIC_PROVENANCE:
        try:
            column_types = _load_exact_bronze_column_types(source_authority)
            rules = validate_deterministic_rules(
                rules,
                available_columns=column_types,
                column_types=column_types,
            )
            expected_sql = build_deterministic_silver_sql(
                candidate_schema=candidates_schema,
                candidate_name=f"{table_name}_candidate_{run_id}",
                bronze_schema=bronze_schema,
                bronze_relation=bronze_table,
                rules=rules,
            )
            if sql_text != expected_sql:
                raise SilverRuleError(
                    "Deterministic Silver SQL does not match its persisted rule plan"
                )
        except SilverRuleError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except Exception as exc:
            logger.error(
                "Failed to validate deterministic Silver rule types for run %s: %s",
                run_id,
                exc,
            )
            if is_db_connection_error(exc):
                raise HTTPException(
                    status_code=503,
                    detail="Database service is currently unavailable.",
                ) from None
            raise HTTPException(
                status_code=500,
                detail="Failed to validate Silver rule types.",
            ) from None

    step_count = (
        len(rules) + 1
        if provenance == SERVER_DETERMINISTIC_PROVENANCE
        else len(rules)
    )

    # Structural AST Preflight Validation
    try:
        validate_generated_sql(
            sql_text,
            expected_schema=candidates_schema,
            expected_table_name=table_name,
            expected_bronze_schema=bronze_schema,
            expected_bronze_table_name=bronze_table,
            run_id=run_id,
            expected_step_count=step_count,
            mode="p2_silver",
        )
    except Exception as e:
        logger.error("Preflight SQL validation failed for run %s: %s", run_id, e)
        raise HTTPException(status_code=422, detail="SQL failed structural safety validation.")

    # Build attribution count query structure before claim
    try:
        stmt = sqlglot.parse_one(sql_text, read="postgres")
        select_expr = stmt.args.get("expression")
        with_clause = select_expr.args.get("with")
        cte_names = [cte.alias for cte in with_clause.expressions]

        expected_cte_names = [f"step_{i+1}" for i in range(step_count)]
        if cte_names != expected_cte_names:
            raise ValueError(f"CTE sequence {cte_names} does not match expected {expected_cte_names}")

        selects = [f'(SELECT COUNT(*) FROM "{bronze_schema}"."{bronze_table}") as step_0_count']
        for name in cte_names:
            safe_name = validate_sql_identifier(name)
            selects.append(f"(SELECT COUNT(*) FROM {safe_name}) as {safe_name}_count")

        count_sql = f"{with_clause.sql(dialect='postgres')} SELECT {', '.join(selects)}"
    except Exception as e:
        logger.error("Failed to build attribution count query for run %s: %s", run_id, e)
        raise HTTPException(status_code=422, detail="SQL structure invalid for attribution.")

    # 2. ATOMIC CURRENT-SAVED-REVISION CLAIM
    # Single SQLite atomic statement linking run_id, status=PENDING, provenance, rule_revision, AND live table_rules match
    trusted_list = list(TRUSTED_GENERATOR_PROVENANCES)
    placeholders = ", ".join(["?"] * len(trusted_list))
    params = [run_id] + trusted_list + [run_rule_rev]

    with get_connection() as conn_db:
        cursor = conn_db.execute(
            f"""
            UPDATE generated_sql_review
            SET status = 'EXECUTING'
            WHERE run_id = ?
              AND status = 'PENDING'
              AND generator_provenance IN ({placeholders})
              AND rule_revision = ?
              AND rule_revision IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM table_rules tr
                  WHERE tr.table_name = generated_sql_review.table_name
                    AND tr.rule_revision = generated_sql_review.rule_revision
                    AND tr.rule_revision IS NOT NULL
              )
            """,
            params
        )
        conn_db.commit()
        claimed = (cursor.rowcount > 0)

    if not claimed:
        # Re-check status if atomic claim failed due to concurrent execution or state shift
        with get_connection() as conn_db:
            check_row = conn_db.execute(
                "SELECT status FROM generated_sql_review WHERE run_id = ?",
                (run_id,)
            ).fetchone()
        curr_st = check_row["status"] if check_row else "UNKNOWN"
        if curr_st in ("EXECUTING", "PROMOTING"):
            raise HTTPException(status_code=409, detail="Execution or promotion already in progress for this run.")
        raise HTTPException(
            status_code=400,
            detail="Run execution claim failed due to invalid status, untrusted provenance, or modified rules."
        )

    # 3. WINNING CLAIMER EXECUTES CANDIDATE AND MEASURES ATTRIBUTION
    attribution_results = []
    try:
        with get_generated_sql_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(count_sql)
                counts = cur.fetchone()

                initial_count = counts[0]
                attribution_results.append(f"Initial Bronze Rows: {initial_count}")

                if provenance == SERVER_DETERMINISTIC_PROVENANCE:
                    attribution_rules = [
                        (rule, index + 1)
                        for index, rule in enumerate(rules)
                    ]
                else:
                    attribution_rules = [
                        (rule, index)
                        for index, rule in enumerate(rules)
                    ]
                for rule, count_index in attribution_rules:
                    prev_count = counts[count_index]
                    curr_count = counts[count_index + 1]
                    diff = prev_count - curr_count

                    rule_label = (
                        rule_attribution_label(rule)
                        if isinstance(rule, dict)
                        else rule
                    )
                    if diff > 0:
                        attribution_results.append(f"{rule_label}: {diff} rows removed (Remaining: {curr_count})")
                    else:
                        attribution_results.append(f"{rule_label}: Transformation applied (Remaining: {curr_count})")

        candidate_name = f"{table_name}_candidate_{run_id}"

        # 1. Resolve live target relation identity in Silver schema
        live_target_ident = None
        with get_generated_sql_pool().connection() as conn:
            live_target_ident = resolve_relation_identity(conn, silver_schema, table_name)

        # 2. Derive legitimate target replacement authority strictly from exact silver_lineage_id prior PROMOTED state
        target_authority = None
        if live_target_ident is not None:
            with get_connection() as conn_db:
                row = conn_db.execute(
                    """
                    SELECT promoted_target_identity_json
                    FROM generated_sql_review
                    WHERE silver_lineage_id = ? AND table_name = ? AND status = 'PROMOTED'
                    ORDER BY rowid DESC LIMIT 1
                    """,
                    (lineage_id, table_name),
                ).fetchone()
                if row and row["promoted_target_identity_json"]:
                    target_authority = validate_promoted_identity_json(row["promoted_target_identity_json"])

            if not target_authority:
                logger.error("Target table %s.%s exists but no pre-existing promoted authority for lineage %s in SQLite (run %s)", silver_schema, table_name, lineage_id, run_id)
                _update_run_status(run_id, "FAILED")
                raise HTTPException(status_code=403, detail="Target relation overwrite unauthorized: missing pre-existing replacement authority.")

            for k in ("database_oid", "namespace_oid", "relation_oid", "schema", "relation_name", "relation_kind"):
                if target_authority.get(k) != live_target_ident.get(k):
                    logger.error("Target relation identity mismatch for run %s on key %s: live=%s vs authority=%s", run_id, k, live_target_ident.get(k), target_authority.get(k))
                    _update_run_status(run_id, "FAILED")
                    raise HTTPException(status_code=403, detail="Target relation identity mismatch: live relation does not match pre-existing replacement authority.")

        cand_identity = None
        with get_generated_sql_pool().connection() as conn:
            cand_identity = execute_candidate_sql(
                sql_text,
                conn,
                expected_schema=candidates_schema,
                run_id=run_id,
                expected_table_name=table_name,
                expected_bronze_schema=bronze_schema,
                expected_bronze_table_name=bronze_table,
                mode="p2_silver",
                expected_bronze_identity=source_authority,
            )
            conn.commit()
    except Exception as e:
        logger.error("Post-claim PostgreSQL execution failed for run %s: %s", run_id, e)
        _update_run_status(run_id, "FAILED")
        if isinstance(e, HTTPException):
            raise e
        if is_db_connection_error(e):
            raise HTTPException(status_code=503, detail="Database service is currently unavailable.")
        raise HTTPException(status_code=500, detail="Internal server error.")

    # 4. SINGLE ATOMIC SQLite TRANSITION TO PROMOTING STATE with candidate and target identities
    promoted_durable = _update_run_status(
        run_id,
        "PROMOTING",
        candidate_identity_json=json.dumps(cand_identity),
        target_identity_json=json.dumps(target_authority) if target_authority else None,
    )
    if not promoted_durable:
        logger.error("Failed to durably set run %s status to PROMOTING in SQLite", run_id)
        _update_run_status(run_id, "FAILED")
        raise HTTPException(status_code=500, detail="Internal server error.")

    # 5. RELOAD PERSISTED IDENTITIES FROM SQLite BEFORE PROMOTION
    reloaded_cand_ident = None
    reloaded_target_ident = None
    with get_connection() as conn_db:
        row = conn_db.execute(
            "SELECT candidate_identity_json, target_identity_json FROM generated_sql_review WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row:
            if row["candidate_identity_json"]:
                reloaded_cand_ident = json.loads(row["candidate_identity_json"])
            if row["target_identity_json"]:
                reloaded_target_ident = json.loads(row["target_identity_json"])

    if not reloaded_cand_ident:
        logger.error("Failed to reload persisted candidate identity for run %s", run_id)
        _update_run_status(run_id, "FAILED")
        raise HTTPException(status_code=500, detail="Internal server error.")

    # 6. PROMOTE CANDIDATE TABLE TO SILVER WITH BOUNDED POOL & EXACT IDENTITY REVALIDATION
    final_target_ident = None
    try:
        from src.promotion import SilverPromotionFailedBeforeCommit, SilverPromotionCommitUnknown
        final_target_ident, _ = promote_candidate_table(
            candidate_table=candidate_name,
            candidate_schema=candidates_schema,
            target_table=table_name,
            target_schema=silver_schema,
            promotion_conninfo=None,
            expected_candidate_identity=reloaded_cand_ident,
            expected_target_identity=reloaded_target_ident,
            run_id=run_id,
        )
    except SilverPromotionFailedBeforeCommit as e:
        logger.error("PostgreSQL promotion failed before commit for run %s: %s", run_id, e)
        _update_run_status(run_id, "FAILED")
        raise HTTPException(
            status_code=500,
            detail="Table promotion failed before commit."
        )
    except SilverPromotionCommitUnknown as e:
        logger.error("PostgreSQL promotion outcome ambiguous for run %s: %s", run_id, e)
        _update_run_status(run_id, "AMBIGUOUS_PROMOTION")
        raise HTTPException(
            status_code=500,
            detail="Promotion failed or outcome ambiguous. Manual reconciliation required."
        )
    except Exception as e:
        logger.error("Unexpected promotion error for run %s: %s", run_id, e)
        _update_run_status(run_id, "FAILED")
        raise HTTPException(
            status_code=500,
            detail="Table promotion failed before commit."
        )

    # 7. POST-PROMOTION SQLite STATUS UPDATE TO PROMOTED WITH PERSISTED FINAL TARGET IDENTITY
    if not final_target_ident or not isinstance(final_target_ident, dict):
        logger.critical("PostgreSQL promotion committed for run %s but final target identity is missing", run_id)
        _update_run_status(run_id, "AMBIGUOUS_PROMOTION")
        raise HTTPException(
            status_code=500,
            detail="Promotion committed in database, but final target identity resolution failed. Reconciliation required."
        )

    now_promoted = datetime.datetime.utcnow().isoformat()
    promoted_ok = _update_run_status(
        run_id,
        "PROMOTED",
        promoted_at=now_promoted,
        attribution_log_json=json.dumps(attribution_results),
        promoted_target_identity_json=json.dumps(final_target_ident),
    )

    if not promoted_ok:
        logger.critical("PostgreSQL promotion committed for run %s but SQLite PROMOTED update failed", run_id)
        _update_run_status(run_id, "AMBIGUOUS_PROMOTION")
        raise HTTPException(
            status_code=500,
            detail="Promotion completed in database, but run status recording encountered an internal error. Manual reconciliation required."
        )

    return {
        "status": "success",
        "run_id": run_id,
        "table_name": table_name,
        "target": final_target_ident,
        "attribution_log": attribution_results,
        "attribution_available": True,
        "message": f"Successfully executed and promoted {table_name} to Silver."
    }
