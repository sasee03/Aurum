"""API router for contained Gold operations and configured Silver discovery."""

from __future__ import annotations

import json
import logging
import re
import datetime
from typing import List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
import psycopg

try:
    from psycopg_pool import PoolClosed, PoolTimeout
except ImportError:  # pragma: no cover - dependency is required in production
    PoolClosed = PoolTimeout = ()

from src.app_state.db import get_connection
from src.db_config import (
    get_generated_sql_pool,
    postgres_promotion_conninfo,
    load_layer_schemas,
)
from src.generator_trust import GeneratorTrustPolicy
from src.sql_safety import validate_generated_sql, execute_candidate_sql
from src.promotion import promote_candidate_table

router = APIRouter(prefix="/api/v1/gold", tags=["gold"])
logger = logging.getLogger(__name__)

GOLD_GENERATOR_TRUST = GeneratorTrustPolicy(
    pipeline="gold",
    trusted_hardened_provenances=frozenset(),
)

GOLD_GENERATION_UNAVAILABLE = "Gold SQL generation is currently unavailable."
GOLD_EXECUTION_UNAVAILABLE = (
    "Gold execution is unavailable until the run is produced by a trusted, "
    "hardened generator."
)
GOLD_REVIEW_UNAVAILABLE = (
    "Gold review is unavailable because this run was not produced by a trusted, "
    "hardened generator."
)

class GenerateGoldPayload(BaseModel):
    target_table_name: str
    silver_table_names: List[str]
    business_requirement: str

class ExecuteGoldPayload(BaseModel):
    overwrite: bool = False

def check_table_exists(schema_name: str, table_name: str) -> bool:
    """Check if a table exists in the given schema."""
    with get_generated_sql_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT to_regclass(%s)",
                (f'"{schema_name}"."{table_name}"',)
            )
            return cur.fetchone()[0] is not None

@router.get("/check-name")
def check_name(name: str = Query(..., description="The proposed name for the gold table")):
    """P3.1A: Synchronous check for gold table name collision."""
    schemas = load_layer_schemas()
    
    # Pre-flight identifier validation
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        return {
            "name": name,
            "is_valid_identifier": False,
            "is_available": False,
            "status": "invalid",
            "resolution_options": [],
            "message": f"'{name}' is not a valid PostgreSQL identifier."
        }
        
    try:
        exists = check_table_exists(schemas.gold, name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check table existence: {e}")

    if exists:
        return {
            "name": name,
            "is_valid_identifier": True,
            "is_available": False,
            "status": "taken",
            "resolution_options": [
                {
                    "action": "overwrite",
                    "description": f"Replace the existing '{name}' table in the gold schema."
                },
                {
                    "action": "rename",
                    "description": "Choose a different name."
                }
            ],
            "message": f"The table '{name}' already exists in the Gold layer."
        }
    else:
        return {
            "name": name,
            "is_valid_identifier": True,
            "is_available": True,
            "status": "available",
            "resolution_options": [],
            "message": "Name is available."
        }

def _configured_silver_schema() -> str:
    """Resolve and validate the physical Silver schema from server configuration."""
    schema_name = load_layer_schemas().silver
    if not isinstance(schema_name, str) or not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*", schema_name
    ):
        raise ValueError("Invalid configured Silver schema")
    return schema_name


def _is_connectivity_error(exc: Exception) -> bool:
    pool_errors = tuple(
        error_type
        for error_type in (PoolClosed, PoolTimeout)
        if isinstance(error_type, type)
    )
    return isinstance(exc, (psycopg.OperationalError, *pool_errors))


@router.get("/silver-tables")
def list_silver_tables():
    """List only real tables in the server-configured Silver schema."""
    try:
        silver_schema = _configured_silver_schema()
    except Exception:
        logger.exception("Invalid Silver layer configuration")
        raise HTTPException(
            status_code=500,
            detail="Invalid Silver layer configuration.",
        ) from None

    try:
        with get_generated_sql_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = %s
                      AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                    """,
                    (silver_schema,),
                )
                rows = cur.fetchall()
    except Exception as exc:
        if _is_connectivity_error(exc):
            logger.warning("Silver discovery database unavailable: %s", type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail="Silver table discovery is currently unavailable.",
            ) from None
        logger.exception("Silver table discovery failed")
        raise HTTPException(
            status_code=500,
            detail="Silver table discovery failed.",
        ) from None

    return {"tables": [{"name": row[0]} for row in rows]}


@router.post("/generate")
def generate_gold_sql(payload: GenerateGoldPayload):
    """Fail closed until a trusted, hardened Gold generator is registered."""
    if not GOLD_GENERATOR_TRUST.generation_available:
        raise HTTPException(status_code=503, detail=GOLD_GENERATION_UNAVAILABLE)
    raise HTTPException(status_code=503, detail=GOLD_GENERATION_UNAVAILABLE)

@router.get("/review/{run_id}")
def review_gold_sql(run_id: str):
    """Review only runs produced by a trusted, hardened Gold generator."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT table_name, sql_text, planned_changes_json, generator_provenance
            FROM generated_sql_review
            WHERE run_id = ?
            """,
            (run_id,)
        ).fetchone()
        
    if not row:
        raise HTTPException(status_code=404, detail="Run ID not found.")

    if not GOLD_GENERATOR_TRUST.trusts_run(row["generator_provenance"]):
        raise HTTPException(status_code=503, detail=GOLD_REVIEW_UNAVAILABLE)
        
    sql_text = row["sql_text"]
    
    try:
        schemas = load_layer_schemas()
        validated_sql = validate_generated_sql(sql_text, expected_schema=schemas.gold_candidates, run_id=run_id, expected_step_count=None)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"SQL failed structural validation: {e}")

    return {
        "run_id": run_id,
        "table_name": row["table_name"],
        "planned_changes": json.loads(row["planned_changes_json"]),
        "sql_text": validated_sql,
        "executed": False,
        "message": "SQL is validated and ready for execution."
    }

@router.post("/execute/{run_id}")
def execute_gold_sql(run_id: str, payload: ExecuteGoldPayload):
    """Execute only runs produced by a trusted, hardened Gold generator."""
    with get_connection() as conn_db:
        row = conn_db.execute(
            """
            SELECT table_name, sql_text, generator_provenance
            FROM generated_sql_review
            WHERE run_id = ?
            """,
            (run_id,)
        ).fetchone()
        
    if not row:
        raise HTTPException(status_code=404, detail="Run ID not found or already executed.")

    if not GOLD_GENERATOR_TRUST.trusts_run(row["generator_provenance"]):
        raise HTTPException(status_code=503, detail=GOLD_EXECUTION_UNAVAILABLE)
        
    table_name = row["table_name"]
    sql_text = row["sql_text"]
    
    schemas = load_layer_schemas()
    
    # 1. TOCTOU Check: Ensure overwrite is respected at execution time
    exists = check_table_exists(schemas.gold, table_name)
    if exists and not payload.overwrite:
        raise HTTPException(
            status_code=409, 
            detail=f"Table '{table_name}' exists in the gold schema. Provide overwrite=True to replace it."
        )

    # 2. Execution and Ownership Transfer (aurum_generated_sql -> aurum_promotion)
    try:
        with get_generated_sql_pool().connection() as conn:
            execute_candidate_sql(sql_text, conn, expected_schema=schemas.gold_candidates, run_id=run_id)
            conn.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute candidate SQL: {e}")

    candidate_name = f"{table_name}_candidate_{run_id}"

    # 3. P3.5: Gold preview via LIMIT from the candidate table
    preview_rows = []
    total_rows = 0
    try:
        with get_generated_sql_pool().connection() as conn:
            with conn.cursor() as cur:
                # Count
                cur.execute(f'SELECT COUNT(*) FROM "{schemas.gold_candidates}"."{candidate_name}"')
                total_rows = cur.fetchone()[0]
                
                # Preview
                cur.execute(f'SELECT * FROM "{schemas.gold_candidates}"."{candidate_name}" LIMIT 5')
                cols = [desc[0] for desc in cur.description] if cur.description else []
                preview_rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to preview gold candidate table: {e}")

    # 4. Promotion to Gold (aurum_promotion)
    try:
        promote_candidate_table(
            candidate_table=candidate_name,
            candidate_schema=schemas.gold_candidates,
            target_table=table_name,
            target_schema=schemas.gold,
            promotion_conninfo=postgres_promotion_conninfo()
        )
        now_promoted = datetime.datetime.utcnow().isoformat()
        with get_connection() as conn_db:
            conn_db.execute(
                "UPDATE generated_sql_review SET status = 'PROMOTED', promoted_at = ? WHERE run_id = ?",
                (now_promoted, run_id)
            )
            conn_db.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to promote candidate to gold: {e}")
        
    return {
        "status": "success",
        "run_id": run_id,
        "table_name": table_name,
        "total_rows": total_rows,
        "preview_rows": preview_rows,
        "message": f"Successfully executed and promoted {table_name} to Gold."
    }
