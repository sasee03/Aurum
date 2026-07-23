"""API router for contained Gold operations and configured Silver discovery."""

from __future__ import annotations

import json
import logging
import re
from typing import List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr
import psycopg

try:
    from psycopg_pool import PoolClosed, PoolTimeout
except ImportError:  # pragma: no cover - dependency is required in production
    PoolClosed = PoolTimeout = ()

from src.app_state.db import get_connection
from src.db_config import (
    get_generated_sql_pool,
    load_layer_schemas,
)
from src.gold_catalog import (
    GoldCatalogResolutionError,
    resolve_gold_approval_catalog,
)
from src.gold_security import (
    GoldStateMalformed,
    GoldStateStale,
    approval_timestamp,
    build_approval_snapshot,
    canonical_json,
    load_gold_security_state,
    load_persisted_gold_security_state,
    revision_for,
)
from src.generator_trust import GeneratorTrustPolicy
from src.sql_safety import validate_generated_sql

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
GOLD_UNAVAILABLE = "GOLD_UNAVAILABLE"
GOLD_RUN_NOT_FOUND = "GOLD_RUN_NOT_FOUND"
GOLD_RUN_MALFORMED = "GOLD_RUN_MALFORMED"
GOLD_APPROVAL_REQUIRED = "GOLD_APPROVAL_REQUIRED"
GOLD_APPROVAL_STALE = "GOLD_APPROVAL_STALE"
GOLD_STATE_CONFLICT = "GOLD_STATE_CONFLICT"
GOLD_SOURCE_IDENTITY_CHANGED = "GOLD_SOURCE_IDENTITY_CHANGED"
GOLD_TARGET_IDENTITY_CHANGED = "GOLD_TARGET_IDENTITY_CHANGED"
GOLD_DATABASE_UNAVAILABLE = "GOLD_DATABASE_UNAVAILABLE"

class GenerateGoldPayload(BaseModel):
    target_table_name: str
    silver_table_names: List[str]
    business_requirement: str

class ExecuteGoldPayload(BaseModel):
    overwrite: bool = False


class ApproveGoldPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_revision: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    overwrite: StrictBool

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
            SELECT run_id, table_name, sql_text, planned_changes_json,
                   candidate_schema, generator_provenance
            FROM generated_sql_review
            WHERE run_id = ?
            """,
            (run_id,)
        ).fetchone()
        security_row = conn.execute(
            "SELECT * FROM gold_security_state WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        
    if not row:
        raise HTTPException(status_code=404, detail="Run ID not found.")

    if not GOLD_GENERATOR_TRUST.trusts_run(row["generator_provenance"]):
        raise HTTPException(status_code=503, detail=GOLD_REVIEW_UNAVAILABLE)

    try:
        schemas = load_layer_schemas()
        state = load_gold_security_state(
            security_row,
            row,
            configured_silver_schema=schemas.silver,
            configured_gold_schema=schemas.gold,
            configured_candidate_schema=schemas.gold_candidates,
        )
        validated_sql = validate_generated_sql(
            row["sql_text"],
            expected_schema=schemas.gold_candidates,
            expected_table_name=state.target["table"],
            run_id=run_id,
            expected_step_count=None,
        )
        planned_changes = json.loads(row["planned_changes_json"])
    except (GoldStateMalformed, GoldStateStale, TypeError, ValueError):
        raise HTTPException(status_code=422, detail=GOLD_RUN_MALFORMED) from None
    except Exception:
        logger.exception("Gold review validation failed for run %s", run_id)
        raise HTTPException(status_code=422, detail=GOLD_RUN_MALFORMED) from None

    return {
        "run_id": run_id,
        "table_name": row["table_name"],
        "planned_changes": planned_changes,
        "sql_text": validated_sql,
        "review_revision": state.review_revision,
        "approved_revision": state.approved_revision,
        "executed": False,
        "message": (
            "Gold plan is approved but production execution remains unavailable."
            if state.approved_revision
            else "Gold plan is ready for explicit approval."
        ),
    }



def _load_gold_rows(conn, run_id: str):
    envelope = conn.execute(
        """
        SELECT run_id, table_name, sql_text, planned_changes_json, status,
               candidate_schema, generator_provenance
        FROM generated_sql_review
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    security = conn.execute(
        "SELECT * FROM gold_security_state WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return envelope, security


def _approval_response(state, *, idempotent: bool) -> dict:
    assert state.approved_revision is not None
    assert state.approval_snapshot is not None
    assert state.overwrite_authorized is not None
    return {
        "status": "unchanged" if idempotent else "approved",
        "run_id": state.run_id,
        "review_revision": state.review_revision,
        "approved_revision": state.approved_revision,
        "approved_at": state.approved_at,
        "overwrite_authorized": state.overwrite_authorized,
        "target_state": state.approval_snapshot["target_identity"]["state"],
    }


@router.post("/approve/{run_id}")
def approve_gold_sql(run_id: str, payload: ApproveGoldPayload):
    """Persist one immutable execution authorization for the reviewed Gold plan."""
    with get_connection() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row, security_row = _load_gold_rows(conn, run_id)
            if row is None:
                raise HTTPException(status_code=404, detail=GOLD_RUN_NOT_FOUND)
            if row["status"] != "PENDING":
                raise HTTPException(status_code=409, detail=GOLD_STATE_CONFLICT)
            if not GOLD_GENERATOR_TRUST.trusts_run(row["generator_provenance"]):
                raise HTTPException(status_code=503, detail=GOLD_UNAVAILABLE)
            if (
                security_row is not None
                and security_row["approved_revision"] is not None
            ):
                try:
                    state = load_persisted_gold_security_state(
                        security_row,
                        row,
                    )
                    validate_generated_sql(
                        row["sql_text"],
                        expected_schema=state.candidate["schema"],
                        expected_table_name=state.target["table"],
                        run_id=run_id,
                        expected_step_count=None,
                    )
                except GoldStateStale:
                    raise HTTPException(
                        status_code=409,
                        detail=GOLD_APPROVAL_STALE,
                    ) from None
                except GoldStateMalformed:
                    raise HTTPException(
                        status_code=422,
                        detail=GOLD_RUN_MALFORMED,
                    ) from None
                except Exception:
                    raise HTTPException(
                        status_code=422,
                        detail=GOLD_RUN_MALFORMED,
                    ) from None
                if payload.review_revision != state.review_revision:
                    raise HTTPException(
                        status_code=409,
                        detail=GOLD_APPROVAL_STALE,
                    )
                if state.overwrite_authorized != payload.overwrite:
                    raise HTTPException(
                        status_code=409,
                        detail=GOLD_STATE_CONFLICT,
                    )
                conn.rollback()
                return _approval_response(state, idempotent=True)
            try:
                schemas = load_layer_schemas()
                state = load_gold_security_state(
                    security_row,
                    row,
                    configured_silver_schema=schemas.silver,
                    configured_gold_schema=schemas.gold,
                    configured_candidate_schema=schemas.gold_candidates,
                )
            except GoldStateStale:
                raise HTTPException(
                    status_code=409,
                    detail=GOLD_APPROVAL_STALE,
                ) from None
            except GoldStateMalformed:
                raise HTTPException(
                    status_code=422,
                    detail=GOLD_RUN_MALFORMED,
                ) from None
            except Exception:
                logger.exception("Gold approval configuration failed")
                raise HTTPException(
                    status_code=503,
                    detail=GOLD_UNAVAILABLE,
                ) from None
            if payload.review_revision != state.review_revision:
                raise HTTPException(status_code=409, detail=GOLD_APPROVAL_STALE)
            try:
                validate_generated_sql(
                    row["sql_text"],
                    expected_schema=schemas.gold_candidates,
                    expected_table_name=state.target["table"],
                    run_id=run_id,
                    expected_step_count=None,
                )
            except Exception:
                raise HTTPException(
                    status_code=422,
                    detail=GOLD_RUN_MALFORMED,
                ) from None

            try:
                catalog = resolve_gold_approval_catalog(
                    selected_sources=state.selected_sources,
                    target=state.target,
                )
            except GoldCatalogResolutionError as exc:
                if exc.area == "database":
                    raise HTTPException(
                        status_code=503,
                        detail=GOLD_DATABASE_UNAVAILABLE,
                    ) from None
                if exc.area == "target":
                    raise HTTPException(
                        status_code=409,
                        detail=GOLD_TARGET_IDENTITY_CHANGED,
                    ) from None
                if exc.area == "source":
                    raise HTTPException(
                        status_code=409,
                        detail=GOLD_SOURCE_IDENTITY_CHANGED,
                    ) from None
                raise HTTPException(
                    status_code=503,
                    detail=GOLD_DATABASE_UNAVAILABLE,
                ) from None
            except Exception as exc:
                if _is_connectivity_error(exc):
                    logger.warning(
                        "Gold approval database unavailable: %s",
                        type(exc).__name__,
                    )
                else:
                    logger.exception("Gold approval catalog resolution failed")
                raise HTTPException(
                    status_code=503,
                    detail=GOLD_DATABASE_UNAVAILABLE,
                ) from None

            target_state = catalog.target_identity.get("state")
            if (
                target_state == "existing" and not payload.overwrite
            ) or (
                target_state == "absent" and payload.overwrite
            ):
                raise HTTPException(status_code=409, detail=GOLD_STATE_CONFLICT)
            try:
                approval_snapshot = build_approval_snapshot(
                    review_snapshot=state.review_snapshot,
                    review_revision=state.review_revision,
                    database_oid=catalog.database_oid,
                    database_name=catalog.database_name,
                    source_identities=catalog.source_identities,
                    target_identity=catalog.target_identity,
                    overwrite_authorized=payload.overwrite,
                )
            except GoldStateMalformed:
                raise HTTPException(
                    status_code=422,
                    detail=GOLD_RUN_MALFORMED,
                ) from None

            approved_revision = revision_for(approval_snapshot)
            approved_at = approval_timestamp()
            cursor = conn.execute(
                """
                UPDATE gold_security_state
                SET approval_snapshot_json = ?,
                    approved_revision = ?,
                    approved_at = ?,
                    overwrite_authorized = ?,
                    source_identities_json = ?,
                    target_identity_json = ?
                WHERE run_id = ?
                  AND review_revision = ?
                  AND approved_revision IS NULL
                """,
                (
                    canonical_json(approval_snapshot),
                    approved_revision,
                    approved_at,
                    int(payload.overwrite),
                    canonical_json(list(catalog.source_identities)),
                    canonical_json(catalog.target_identity),
                    run_id,
                    state.review_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=409, detail=GOLD_STATE_CONFLICT)
            refreshed_security = conn.execute(
                "SELECT * FROM gold_security_state WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            approved_state = load_gold_security_state(
                refreshed_security,
                row,
                configured_silver_schema=schemas.silver,
                configured_gold_schema=schemas.gold,
                configured_candidate_schema=schemas.gold_candidates,
            )
            conn.commit()
            return _approval_response(approved_state, idempotent=False)
        except HTTPException:
            conn.rollback()
            raise


@router.post("/execute/{run_id}")
def execute_gold_sql(run_id: str, payload: ExecuteGoldPayload):
    """Fail closed before PostgreSQL until later execution controls exist."""
    with get_connection() as conn_db:
        row, security_row = _load_gold_rows(conn_db, run_id)

    if row is None:
        raise HTTPException(status_code=404, detail=GOLD_RUN_NOT_FOUND)
    if not GOLD_GENERATOR_TRUST.trusts_run(row["generator_provenance"]):
        raise HTTPException(status_code=503, detail=GOLD_EXECUTION_UNAVAILABLE)
    if row["status"] != "PENDING":
        raise HTTPException(status_code=409, detail=GOLD_APPROVAL_STALE)

    try:
        schemas = load_layer_schemas()
        state = load_gold_security_state(
            security_row,
            row,
            configured_silver_schema=schemas.silver,
            configured_gold_schema=schemas.gold,
            configured_candidate_schema=schemas.gold_candidates,
        )
    except GoldStateStale:
        raise HTTPException(status_code=409, detail=GOLD_APPROVAL_STALE) from None
    except GoldStateMalformed:
        raise HTTPException(status_code=422, detail=GOLD_RUN_MALFORMED) from None
    except Exception:
        logger.exception("Gold execution preflight configuration failed")
        raise HTTPException(status_code=503, detail=GOLD_UNAVAILABLE) from None
    if state.approved_revision is None:
        raise HTTPException(status_code=409, detail=GOLD_APPROVAL_REQUIRED)
    if payload.overwrite != state.overwrite_authorized:
        raise HTTPException(status_code=409, detail=GOLD_APPROVAL_STALE)
    raise HTTPException(status_code=503, detail=GOLD_EXECUTION_UNAVAILABLE)
