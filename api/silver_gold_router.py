"""API router for contained Gold operations and configured Silver discovery."""

from __future__ import annotations

import json
import logging
import re
import uuid
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
from src.gold_execution import (
    GOLD_CANDIDATE_CONFLICT,
    GOLD_DATABASE_UNAVAILABLE,
    GOLD_EXECUTION_FAILED,
    GOLD_SOURCE_IDENTITY_CHANGED,
    GOLD_SQL_REJECTED,
    GOLD_TARGET_IDENTITY_CHANGED,
    GoldCommitOutcomeUnknown,
    GoldExecutionRejected,
    execute_gold_candidate,
    validate_approved_gold_sql,
)
from src.gold_promotion import (
    GOLD_CANDIDATE_IDENTITY_CHANGED,
    GOLD_OVERWRITE_NOT_AUTHORIZED,
    GOLD_PROMOTION_AMBIGUOUS,
    GOLD_PROMOTION_NOT_COMMITTED,
    GOLD_PROMOTION_RECONCILIATION_REQUIRED,
    GoldPromotionOutcomeUnknown,
    GoldPromotionRejected,
    promote_gold_candidate,
    reconcile_gold_promotion,
)
from src.generator_trust import GeneratorTrustPolicy

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
GOLD_RECONCILIATION_REQUIRED = "GOLD_RECONCILIATION_REQUIRED"

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
                   status, candidate_schema, generator_provenance
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
        validated_sql = validate_approved_gold_sql(state, row["sql_text"])
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
                    validate_approved_gold_sql(state, row["sql_text"])
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
                validate_approved_gold_sql(state, row["sql_text"])
            except Exception:
                raise HTTPException(
                    status_code=422,
                    detail=GOLD_RUN_MALFORMED,
                ) from None

            try:
                catalog = resolve_gold_approval_catalog(
                    selected_sources=state.selected_sources,
                    target=state.target,
                    candidate=state.candidate,
                )
            except GoldCatalogResolutionError as exc:
                if exc.area == "database":
                    raise HTTPException(
                        status_code=503,
                        detail=GOLD_DATABASE_UNAVAILABLE,
                    ) from None
                if exc.area in {"target", "candidate_namespace"}:
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
                    candidate_namespace_identity=(
                        catalog.candidate_namespace_identity
                    ),
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
    """Atomically claim and create one approved Gold candidate."""
    execution_claim_id = f"exec_{uuid.uuid4().hex}"
    try:
        schemas = load_layer_schemas()
    except Exception:
        logger.exception("Gold execution configuration failed")
        raise HTTPException(status_code=503, detail=GOLD_UNAVAILABLE) from None

    with get_connection() as conn_db:
        try:
            conn_db.execute("BEGIN IMMEDIATE")
            row, security_row = _load_gold_rows(conn_db, run_id)
            if row is None:
                raise HTTPException(status_code=404, detail=GOLD_RUN_NOT_FOUND)
            if not GOLD_GENERATOR_TRUST.trusts_run(row["generator_provenance"]):
                raise HTTPException(
                    status_code=503,
                    detail=GOLD_EXECUTION_UNAVAILABLE,
                )
            if row["status"] in {"EXECUTING", "PROMOTING"}:
                raise HTTPException(
                    status_code=409,
                    detail=GOLD_RECONCILIATION_REQUIRED,
                )
            if row["status"] != "PENDING":
                raise HTTPException(status_code=409, detail=GOLD_STATE_CONFLICT)
            try:
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
            if state.approved_revision is None:
                raise HTTPException(
                    status_code=409,
                    detail=GOLD_APPROVAL_REQUIRED,
                )
            if payload.overwrite != state.overwrite_authorized:
                raise HTTPException(
                    status_code=409,
                    detail=GOLD_APPROVAL_STALE,
                )
            claimed_at = approval_timestamp()
            security_claim = conn_db.execute(
                """
                UPDATE gold_security_state
                SET execution_claim_id = ?,
                    execution_claimed_at = ?,
                    execution_failure_code = NULL
                WHERE run_id = ?
                  AND approved_revision = ?
                  AND execution_claim_id IS NULL
                """,
                (
                    execution_claim_id,
                    claimed_at,
                    run_id,
                    state.approved_revision,
                ),
            )
            envelope_claim = conn_db.execute(
                """
                UPDATE generated_sql_review
                SET status = 'EXECUTING'
                WHERE run_id = ?
                  AND status = 'PENDING'
                """,
                (run_id,),
            )
            if security_claim.rowcount != 1 or envelope_claim.rowcount != 1:
                raise HTTPException(
                    status_code=409,
                    detail=GOLD_STATE_CONFLICT,
                )
            conn_db.commit()
        except HTTPException:
            conn_db.rollback()
            raise

    try:
        candidate_identity = execute_gold_candidate(state, row["sql_text"])
    except GoldCommitOutcomeUnknown:
        _mark_gold_reconciliation_required(run_id, execution_claim_id)
        raise HTTPException(
            status_code=409,
            detail=GOLD_RECONCILIATION_REQUIRED,
        ) from None
    except GoldExecutionRejected as exc:
        if not _mark_gold_execution_failed(
            run_id,
            execution_claim_id,
            exc.code,
        ):
            raise HTTPException(
                status_code=409,
                detail=GOLD_RECONCILIATION_REQUIRED,
            ) from None
        status_code = (
            422
            if exc.code == GOLD_SQL_REJECTED
            else 409
            if exc.code
            in {
                GOLD_SOURCE_IDENTITY_CHANGED,
                GOLD_TARGET_IDENTITY_CHANGED,
                GOLD_CANDIDATE_CONFLICT,
            }
            else 503
            if exc.code == GOLD_DATABASE_UNAVAILABLE
            else 500
        )
        raise HTTPException(status_code=status_code, detail=exc.code) from None

    try:
        with get_connection() as conn_db:
            conn_db.execute("BEGIN IMMEDIATE")
            identity_update = conn_db.execute(
                """
                UPDATE gold_security_state
                SET candidate_identity_json = ?,
                    execution_failure_code = NULL
                WHERE run_id = ?
                  AND execution_claim_id = ?
                  AND candidate_identity_json IS NULL
                  AND EXISTS (
                      SELECT 1
                      FROM generated_sql_review
                      WHERE generated_sql_review.run_id = gold_security_state.run_id
                        AND generated_sql_review.status = 'EXECUTING'
                  )
                """,
                (
                    canonical_json(candidate_identity),
                    run_id,
                    execution_claim_id,
                ),
            )
            status_update = conn_db.execute(
                """
                UPDATE generated_sql_review
                SET status = 'PROMOTING'
                WHERE run_id = ?
                  AND status = 'EXECUTING'
                """,
                (run_id,),
            )
            if identity_update.rowcount != 1 or status_update.rowcount != 1:
                conn_db.rollback()
                raise RuntimeError("Gold candidate handoff state conflict")
            conn_db.commit()
    except Exception:
        logger.exception("Gold candidate committed but SQLite handoff failed")
        _mark_gold_reconciliation_required(run_id, execution_claim_id)
        raise HTTPException(
            status_code=409,
            detail=GOLD_RECONCILIATION_REQUIRED,
        ) from None

    return {
        "status": "PROMOTING",
        "run_id": run_id,
        "execution_claim_id": execution_claim_id,
        "candidate": {
            "schema": candidate_identity["schema"],
            "table": candidate_identity["relation_name"],
        },
    }


def _mark_gold_execution_failed(
    run_id: str,
    execution_claim_id: str,
    failure_code: str,
    backup_identity: Optional[dict[str, Any]] = None,
) -> bool:
    try:
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            security_update = conn.execute(
                """
                UPDATE gold_security_state
                SET execution_failure_code = ?
                WHERE run_id = ?
                  AND execution_claim_id = ?
                  AND candidate_identity_json IS NULL
                """,
                (failure_code, run_id, execution_claim_id),
            )
            status_update = conn.execute(
                """
                UPDATE generated_sql_review
                SET status = 'EXECUTION_FAILED'
                WHERE run_id = ?
                  AND status = 'EXECUTING'
                """,
                (run_id,),
            )
            if security_update.rowcount != 1 or status_update.rowcount != 1:
                conn.rollback()
                return False
            if backup_identity is not None:
                promoted_envelope = conn.execute(
                    "SELECT * FROM generated_sql_review WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                promoted_security = conn.execute(
                    "SELECT * FROM gold_security_state WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                promoted_state = load_persisted_gold_security_state(
                    promoted_security,
                    promoted_envelope,
                )
                cleanup_insert = conn.execute(
                    """
                    INSERT INTO gold_backup_cleanup (
                        run_id, status, backup_identity_json,
                        database_name, updated_at
                    )
                    VALUES (?, 'ELIGIBLE', ?, ?, ?)
                    ON CONFLICT(run_id) DO NOTHING
                    """,
                    (
                        run_id,
                        canonical_json(promoted_state.backup_identity),
                        promoted_state.approval_snapshot["database"]["name"],
                        proven_at,
                    ),
                )
                if cleanup_insert.rowcount != 1:
                    conn.rollback()
                    return False
            conn.commit()
            return True
    except Exception:
        logger.exception("Failed to persist deterministic Gold execution failure")
        return False


def _mark_gold_reconciliation_required(
    run_id: str,
    execution_claim_id: str,
) -> None:
    try:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE gold_security_state
                SET execution_failure_code = ?
                WHERE run_id = ?
                  AND execution_claim_id = ?
                  AND candidate_identity_json IS NULL
                  AND EXISTS (
                      SELECT 1
                      FROM generated_sql_review
                      WHERE generated_sql_review.run_id = gold_security_state.run_id
                        AND generated_sql_review.status = 'EXECUTING'
                  )
                """,
                (
                    GOLD_RECONCILIATION_REQUIRED,
                    run_id,
                    execution_claim_id,
                ),
            )
            conn.commit()
    except Exception:
        logger.exception("Failed to persist Gold reconciliation marker")


def _promotion_response(state) -> dict:
    assert state.promoted_target_identity is not None
    assert state.promotion_claim_id is not None
    return {
        "status": "PROMOTED",
        "run_id": state.run_id,
        "promotion_claim_id": state.promotion_claim_id,
        "promotion_committed_at": state.promotion_committed_at,
        "target": {
            "schema": state.promoted_target_identity["schema"],
            "table": state.promoted_target_identity["relation_name"],
            "relation_oid": state.promoted_target_identity["relation_oid"],
        },
        "backup": (
            {
                "schema": state.backup_identity["schema"],
                "table": state.backup_identity["relation_name"],
                "relation_oid": state.backup_identity["relation_oid"],
            }
            if state.backup_identity is not None
            else None
        ),
    }


def _committed_result_response(
    run_id: str,
    promotion_claim_id: str,
    *,
    final_target_identity: dict,
    backup_identity: dict | None,
) -> dict:
    """Return proven committed identities when a post-persist reload fails."""
    return {
        "status": "PROMOTED",
        "run_id": run_id,
        "promotion_claim_id": promotion_claim_id,
        "promotion_committed_at": None,
        "target": {
            "schema": final_target_identity["schema"],
            "table": final_target_identity["relation_name"],
            "relation_oid": final_target_identity["relation_oid"],
        },
        "backup": (
            {
                "schema": backup_identity["schema"],
                "table": backup_identity["relation_name"],
                "relation_oid": backup_identity["relation_oid"],
            }
            if backup_identity is not None
            else None
        ),
    }


def _load_promotion_state(run_id: str):
    with get_connection() as conn:
        row, security_row = _load_gold_rows(conn, run_id)
        if row is None:
            raise HTTPException(status_code=404, detail=GOLD_RUN_NOT_FOUND)
        try:
            state = load_persisted_gold_security_state(security_row, row)
        except (GoldStateMalformed, GoldStateStale):
            raise HTTPException(
                status_code=422,
                detail=GOLD_RUN_MALFORMED,
            ) from None
    return row, state


def _persist_gold_promoted(
    run_id: str,
    promotion_claim_id: str,
    *,
    final_target_identity: dict,
    backup_identity: dict | None,
) -> bool:
    proven_at = approval_timestamp()
    try:
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            security_update = conn.execute(
                """
                UPDATE gold_security_state
                SET promoted_target_identity_json = ?,
                    backup_identity_json = ?,
                    backup_cleanup_eligible = ?,
                    promotion_failure_code = NULL,
                    promotion_committed_at = ?
                WHERE run_id = ?
                  AND promotion_claim_id = ?
                  AND promoted_target_identity_json IS NULL
                  AND promotion_failure_code IS NULL
                  AND promotion_committed_at IS NULL
                  AND EXISTS (
                      SELECT 1
                      FROM generated_sql_review
                      WHERE generated_sql_review.run_id = gold_security_state.run_id
                        AND generated_sql_review.status
                            IN ('PROMOTING', 'AMBIGUOUS_PROMOTION')
                  )
                """,
                (
                    canonical_json(final_target_identity),
                    (
                        canonical_json(backup_identity)
                        if backup_identity is not None
                        else None
                    ),
                    0 if backup_identity is not None else None,
                    proven_at,
                    run_id,
                    promotion_claim_id,
                ),
            )
            status_update = conn.execute(
                """
                UPDATE generated_sql_review
                SET status = 'PROMOTED',
                    promoted_at = ?
                WHERE run_id = ?
                  AND status IN ('PROMOTING', 'AMBIGUOUS_PROMOTION')
                """,
                (proven_at, run_id),
            )
            if security_update.rowcount != 1 or status_update.rowcount != 1:
                conn.rollback()
                return False
            conn.commit()
            return True
    except Exception:
        logger.exception(
            "Failed to persist proven Gold promotion for run %s",
            run_id,
        )
        return False


def _persist_gold_promotion_failed(
    run_id: str,
    promotion_claim_id: str,
    failure_code: str,
) -> bool:
    try:
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            security_update = conn.execute(
                """
                UPDATE gold_security_state
                SET promotion_failure_code = ?,
                    promoted_target_identity_json = NULL,
                    backup_identity_json = NULL,
                    backup_cleanup_eligible = NULL,
                    promotion_committed_at = NULL
                WHERE run_id = ?
                  AND promotion_claim_id = ?
                  AND promotion_failure_code IS NULL
                  AND promoted_target_identity_json IS NULL
                  AND promotion_committed_at IS NULL
                  AND EXISTS (
                      SELECT 1
                      FROM generated_sql_review
                      WHERE generated_sql_review.run_id = gold_security_state.run_id
                        AND generated_sql_review.status
                            IN ('PROMOTING', 'AMBIGUOUS_PROMOTION')
                  )
                """,
                (failure_code, run_id, promotion_claim_id),
            )
            status_update = conn.execute(
                """
                UPDATE generated_sql_review
                SET status = 'PROMOTION_FAILED'
                WHERE run_id = ?
                  AND status IN ('PROMOTING', 'AMBIGUOUS_PROMOTION')
                """,
                (run_id,),
            )
            if security_update.rowcount != 1 or status_update.rowcount != 1:
                conn.rollback()
                return False
            conn.commit()
            return True
    except Exception:
        logger.exception(
            "Failed to persist deterministic Gold promotion failure"
        )
        return False


def _persist_gold_promotion_ambiguous(
    run_id: str,
    promotion_claim_id: str,
    *,
    backup_identity: dict | None = None,
) -> bool:
    try:
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            security_update = conn.execute(
                """
                UPDATE gold_security_state
                SET backup_identity_json =
                        COALESCE(backup_identity_json, ?),
                    backup_cleanup_eligible =
                        CASE
                            WHEN backup_identity_json IS NOT NULL
                                 OR ? IS NOT NULL
                            THEN 0
                            ELSE NULL
                        END,
                    promotion_failure_code = NULL,
                    promoted_target_identity_json = NULL,
                    promotion_committed_at = NULL
                WHERE run_id = ?
                  AND promotion_claim_id = ?
                  AND promotion_failure_code IS NULL
                  AND promoted_target_identity_json IS NULL
                  AND promotion_committed_at IS NULL
                  AND EXISTS (
                      SELECT 1
                      FROM generated_sql_review
                      WHERE generated_sql_review.run_id = gold_security_state.run_id
                        AND generated_sql_review.status
                            IN ('PROMOTING', 'AMBIGUOUS_PROMOTION')
                  )
                """,
                (
                    (
                        canonical_json(backup_identity)
                        if backup_identity is not None
                        else None
                    ),
                    (
                        canonical_json(backup_identity)
                        if backup_identity is not None
                        else None
                    ),
                    run_id,
                    promotion_claim_id,
                ),
            )
            status_update = conn.execute(
                """
                UPDATE generated_sql_review
                SET status = 'AMBIGUOUS_PROMOTION'
                WHERE run_id = ?
                  AND status IN ('PROMOTING', 'AMBIGUOUS_PROMOTION')
                """,
                (run_id,),
            )
            if security_update.rowcount != 1 or status_update.rowcount != 1:
                conn.rollback()
                return False
            conn.commit()
            return True
    except Exception:
        logger.exception("Failed to persist ambiguous Gold promotion")
        return False


def _promotion_failure_http_status(code: str) -> int:
    if code == GOLD_DATABASE_UNAVAILABLE:
        return 503
    if code in {
        GOLD_CANDIDATE_IDENTITY_CHANGED,
        GOLD_TARGET_IDENTITY_CHANGED,
        GOLD_OVERWRITE_NOT_AUTHORIZED,
        GOLD_PROMOTION_NOT_COMMITTED,
    }:
        return 409
    return 500


def _persisted_terminal_promotion(run_id: str) -> dict | None:
    try:
        _row, state = _load_promotion_state(run_id)
    except Exception:
        logger.exception(
            "Could not reload Gold terminal state for run %s",
            run_id,
        )
        return None
    if state.promoted_target_identity is not None:
        return _promotion_response(state)
    if state.promotion_failure_code is not None:
        raise HTTPException(
            status_code=_promotion_failure_http_status(
                state.promotion_failure_code
            ),
            detail=state.promotion_failure_code,
        )
    return None


def _reconcile_claimed_gold_promotion(run_id: str, state):
    assert state.promotion_claim_id is not None
    try:
        reconciliation = reconcile_gold_promotion(state)
    except GoldPromotionRejected as exc:
        if exc.code == GOLD_DATABASE_UNAVAILABLE:
            raise HTTPException(
                status_code=503,
                detail=GOLD_DATABASE_UNAVAILABLE,
            ) from None
        raise HTTPException(
            status_code=409,
            detail=GOLD_PROMOTION_RECONCILIATION_REQUIRED,
        ) from None

    if reconciliation.outcome == "promoted":
        assert reconciliation.final_target_identity is not None
        if _persist_gold_promoted(
            run_id,
            state.promotion_claim_id,
            final_target_identity=reconciliation.final_target_identity,
            backup_identity=reconciliation.backup_identity,
        ):
            try:
                _row, promoted_state = _load_promotion_state(run_id)
                return _promotion_response(promoted_state)
            except Exception:
                logger.exception(
                    "Proven reconciled promotion could not be reloaded"
                )
                return _committed_result_response(
                    run_id,
                    state.promotion_claim_id,
                    final_target_identity=(
                        reconciliation.final_target_identity
                    ),
                    backup_identity=reconciliation.backup_identity,
                )
    elif reconciliation.outcome == "not_committed":
        if _persist_gold_promotion_failed(
            run_id,
            state.promotion_claim_id,
            GOLD_PROMOTION_NOT_COMMITTED,
        ):
            raise HTTPException(
                status_code=409,
                detail=GOLD_PROMOTION_NOT_COMMITTED,
            )
    else:
        _persist_gold_promotion_ambiguous(
            run_id,
            state.promotion_claim_id,
            backup_identity=reconciliation.backup_identity,
        )

    terminal = _persisted_terminal_promotion(run_id)
    if terminal is not None:
        return terminal
    raise HTTPException(
        status_code=409,
        detail=GOLD_PROMOTION_RECONCILIATION_REQUIRED,
    )


@router.post("/promote/{run_id}")
def promote_gold_sql(run_id: str):
    """Claim, serialize, and promote only the exact approved Gold candidate."""
    promotion_claim_id = f"promo_{uuid.uuid4().hex}"
    reconcile_state = None
    claimed_state = None
    with get_connection() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row, security_row = _load_gold_rows(conn, run_id)
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=GOLD_RUN_NOT_FOUND,
                )
            if not GOLD_GENERATOR_TRUST.trusts_run(
                row["generator_provenance"]
            ):
                raise HTTPException(
                    status_code=503,
                    detail=GOLD_EXECUTION_UNAVAILABLE,
                )
            try:
                state = load_persisted_gold_security_state(
                    security_row,
                    row,
                )
            except (GoldStateMalformed, GoldStateStale):
                raise HTTPException(
                    status_code=422,
                    detail=GOLD_RUN_MALFORMED,
                ) from None

            if row["status"] == "PROMOTED":
                conn.rollback()
                return _promotion_response(state)
            if row["status"] == "PROMOTION_FAILED":
                assert state.promotion_failure_code is not None
                raise HTTPException(
                    status_code=_promotion_failure_http_status(
                        state.promotion_failure_code
                    ),
                    detail=state.promotion_failure_code,
                )
            if row["status"] not in {
                "PROMOTING",
                "AMBIGUOUS_PROMOTION",
            }:
                raise HTTPException(
                    status_code=409,
                    detail=GOLD_STATE_CONFLICT,
                )
            if state.promotion_claim_id is not None:
                reconcile_state = state
                conn.rollback()
            else:
                claimed_at = approval_timestamp()
                claim = conn.execute(
                    """
                    UPDATE gold_security_state
                    SET promotion_claim_id = ?,
                        promotion_claimed_at = ?,
                        promotion_failure_code = NULL
                    WHERE run_id = ?
                      AND approved_revision = ?
                      AND execution_claim_id = ?
                      AND candidate_identity_json IS NOT NULL
                      AND promotion_claim_id IS NULL
                      AND EXISTS (
                          SELECT 1
                          FROM generated_sql_review
                          WHERE generated_sql_review.run_id =
                                gold_security_state.run_id
                            AND generated_sql_review.status = 'PROMOTING'
                      )
                    """,
                    (
                        promotion_claim_id,
                        claimed_at,
                        run_id,
                        state.approved_revision,
                        state.execution_claim_id,
                    ),
                )
                if claim.rowcount != 1:
                    raise HTTPException(
                        status_code=409,
                        detail=GOLD_STATE_CONFLICT,
                    )
                refreshed_security = conn.execute(
                    "SELECT * FROM gold_security_state WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                claimed_state = load_persisted_gold_security_state(
                    refreshed_security,
                    row,
                )
                conn.commit()
        except HTTPException:
            conn.rollback()
            raise

    if reconcile_state is not None:
        return _reconcile_claimed_gold_promotion(run_id, reconcile_state)
    assert claimed_state is not None

    try:
        result = promote_gold_candidate(claimed_state)
    except GoldPromotionOutcomeUnknown as exc:
        _persist_gold_promotion_ambiguous(
            run_id,
            promotion_claim_id,
            backup_identity=exc.result.backup_identity,
        )
        raise HTTPException(
            status_code=409,
            detail=GOLD_PROMOTION_AMBIGUOUS,
        ) from None
    except GoldPromotionRejected as exc:
        if not _persist_gold_promotion_failed(
            run_id,
            promotion_claim_id,
            exc.code,
        ):
            raise HTTPException(
                status_code=409,
                detail=GOLD_PROMOTION_RECONCILIATION_REQUIRED,
            ) from None
        raise HTTPException(
            status_code=_promotion_failure_http_status(exc.code),
            detail=exc.code,
        ) from None

    if not _persist_gold_promoted(
        run_id,
        promotion_claim_id,
        final_target_identity=result.final_target_identity,
        backup_identity=result.backup_identity,
    ):
        _persist_gold_promotion_ambiguous(
            run_id,
            promotion_claim_id,
            backup_identity=result.backup_identity,
        )
        terminal = _persisted_terminal_promotion(run_id)
        if terminal is not None:
            return terminal
        raise HTTPException(
            status_code=409,
            detail=GOLD_PROMOTION_RECONCILIATION_REQUIRED,
        )

    try:
        _row, promoted_state = _load_promotion_state(run_id)
        return _promotion_response(promoted_state)
    except Exception:
        logger.exception(
            "Committed Gold promotion could not be reloaded"
        )
        return _committed_result_response(
            run_id,
            promotion_claim_id,
            final_target_identity=result.final_target_identity,
            backup_identity=result.backup_identity,
        )
