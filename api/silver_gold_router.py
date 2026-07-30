"""API router for contained Gold operations and configured Silver discovery."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import List, Literal, Union

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr
import psycopg
from typing_extensions import Annotated

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
    resolve_structured_gold_source,
)
from src.gold_security import (
    GoldAuthorityConfigurationError,
    GoldStateMalformed,
    GoldStateStale,
    approval_authority_mac,
    approval_timestamp,
    build_approval_snapshot,
    canonical_json,
    load_gold_security_state,
    load_persisted_gold_security_state,
    new_gold_security_record,
    insert_gold_run_origin,
    insert_gold_security_state,
    revision_for,
    new_gold_run_origin,
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
from src.gold_ai import (
    GoldAIAmbiguousInterpretation,
    GoldAIProposalInvalid,
    GoldAISupportedInterpretation,
    GoldAIUnavailable,
    GoldAIUnsupportedInterpretation,
    configured_gold_ai_model,
    interpret_gold_requirement,
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
from src.sql_safety import SqlSafetyViolation, validate_generated_sql
from src.structured_gold import (
    StructuredGoldDefinitionError,
    compile_structured_gold_sql,
    validate_structured_gold_definition,
)

router = APIRouter(prefix="/api/v1/gold", tags=["gold"])
logger = logging.getLogger(__name__)

MANUAL_CONTROLLED_GOLD_PROVENANCE = "manual_controlled_gold_v1"
STRUCTURED_DETERMINISTIC_GOLD_PROVENANCE = "structured_deterministic_gold_v1"
GOLD_GENERATOR_TRUST = GeneratorTrustPolicy(
    pipeline="gold",
    trusted_hardened_provenances=frozenset(
        {
            MANUAL_CONTROLLED_GOLD_PROVENANCE,
            STRUCTURED_DETERMINISTIC_GOLD_PROVENANCE,
        }
    ),
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


def _log_gold_authority_failure(run_id: str, stage: str, event: str) -> None:
    logger.warning(
        "gold_authority_event event=%s run_id=%s stage=%s",
        event,
        run_id,
        stage,
    )

class GenerateGoldPayload(BaseModel):
    target_table_name: str
    silver_table_names: List[str]
    business_requirement: str


class StructuredGoldSourcePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_name: StrictStr = Field(
        alias="schema",
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        max_length=63,
    )
    table: StrictStr = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=63)


class StructuredGoldDimensionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: StrictStr = Field(min_length=1, max_length=63)


class StructuredGoldColumnExpressionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["column"]
    column: StrictStr = Field(min_length=1, max_length=63)


class StructuredGoldBinaryExpressionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["binary"]
    operator: Literal["add", "subtract", "multiply"]
    left_column: StrictStr = Field(min_length=1, max_length=63)
    right_column: StrictStr = Field(min_length=1, max_length=63)


StructuredGoldExpressionPayload = Annotated[
    Union[
        StructuredGoldColumnExpressionPayload,
        StructuredGoldBinaryExpressionPayload,
    ],
    Field(discriminator="type"),
]


class StructuredGoldMetricPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aggregation: Literal["sum", "count", "avg", "min", "max"]
    expression: StructuredGoldExpressionPayload
    alias: StrictStr = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        max_length=63,
    )


class GenerateStructuredGoldPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: StructuredGoldSourcePayload
    dimension: StructuredGoldDimensionPayload
    metric: StructuredGoldMetricPayload
    target_table_name: StrictStr = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        max_length=63,
    )
    business_purpose: StrictStr = Field(min_length=1, max_length=4000)


class GenerateAIGoldPayload(BaseModel):
    """Natural-language producer input for the existing Structured Gold kernel."""

    model_config = ConfigDict(extra="forbid")

    source: StructuredGoldSourcePayload
    target_table_name: StrictStr = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        max_length=63,
    )
    business_requirement: StrictStr = Field(min_length=1, max_length=4000)


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

    return {"tables": [{"name": row[0], "schema": silver_schema} for row in rows]}


@router.get("/gold-tables")
def list_gold_tables():
    """List only real tables in the server-configured Gold schema."""
    schemas = load_layer_schemas()
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
                    (schemas.gold,),
                )
                rows = cur.fetchall()
    except Exception as exc:
        if _is_connectivity_error(exc):
            raise HTTPException(
                status_code=503,
                detail="Gold table discovery is currently unavailable.",
            ) from None
        raise HTTPException(
            status_code=500,
            detail="Gold table discovery failed.",
        ) from None

    return {"tables": [{"name": row[0]} for row in rows]}


def _persist_gold_proposal(
    *,
    run_id: str,
    target_name: str,
    sql_text: str,
    planned_changes: dict,
    business_requirement: str,
    provenance: str,
    generator_version: str,
    selected_sources: list[dict[str, str]],
    target_schema: str,
    candidate_schema: str,
    generation_database_identity: dict | None = None,
    generation_source_identities: list[dict] | None = None,
    origin_database_identity: dict | None = None,
    origin_source_identities: list[dict] | None = None,
    generator_family: str = "structured_manual",
    generator_model: str | None = None,
) -> dict:
    """Persist the existing review envelope and Gold security companion state."""
    try:
        security_record = new_gold_security_record(
            run_id=run_id,
            sql_text=sql_text,
            business_requirement=business_requirement,
            generator_provenance=provenance,
            generator_version=generator_version,
            selected_sources=selected_sources,
            target_schema=target_schema,
            target_name=target_name,
            candidate_schema=candidate_schema,
            generation_database_identity=generation_database_identity,
            generation_source_identities=generation_source_identities,
        )
    except GoldAuthorityConfigurationError:
        raise HTTPException(status_code=503, detail=GOLD_UNAVAILABLE) from None
    except Exception as exc:
        logger.exception("Failed to build Gold security record")
        raise HTTPException(
            status_code=422,
            detail=f"Invalid Gold security payload: {exc}",
        ) from None

    created_at = approval_timestamp()
    try:
        origin_record = new_gold_run_origin(
            run_id=run_id,
            origin_provenance=provenance,
            generator_family=generator_family,
            generator_model=generator_model,
            generation_database_identity=(
                origin_database_identity or generation_database_identity or {}
            ),
            generation_source_identities=(
                origin_source_identities or generation_source_identities or []
            ),
            selected_sources=selected_sources,
            created_at=created_at,
        )
    except GoldAuthorityConfigurationError:
        raise HTTPException(status_code=503, detail=GOLD_UNAVAILABLE) from None
    except GoldStateMalformed:
        raise HTTPException(status_code=422, detail=GOLD_RUN_MALFORMED) from None
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO generated_sql_review (
                run_id, table_name, sql_text, planned_changes_json,
                created_at, status, candidate_schema, generator_provenance,
                project_id, connection_id
            )
            VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?, 'default_project', 'default_connection')
            """,
            (
                run_id,
                target_name,
                sql_text,
                canonical_json(planned_changes),
                created_at,
                candidate_schema,
                provenance,
            ),
        )
        insert_gold_security_state(conn, security_record)
        insert_gold_run_origin(conn, origin_record)
        conn.commit()

    return {
        "run_id": run_id,
        "table_name": target_name,
        "sql_text": sql_text,
        "planned_changes": planned_changes,
        "status": "PENDING",
        "review_revision": security_record["review_revision"],
        "generator_provenance": provenance,
    }


@router.post("/generate")
def generate_gold_sql(payload: GenerateGoldPayload):
    """Controlled non-LLM Gold proposal path using trusted controlled provenance."""
    if not GOLD_GENERATOR_TRUST.trusts_run(MANUAL_CONTROLLED_GOLD_PROVENANCE):
        raise HTTPException(status_code=503, detail=GOLD_GENERATION_UNAVAILABLE)

    target_name = payload.target_table_name.strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", target_name):
        raise HTTPException(status_code=400, detail="Invalid target table name identifier.")

    if not payload.silver_table_names:
        raise HTTPException(status_code=400, detail="At least one silver table is required.")

    schemas = load_layer_schemas()
    for s_table in payload.silver_table_names:
        if not check_table_exists(schemas.silver, s_table):
            raise HTTPException(status_code=404, detail=f"Silver table '{s_table}' not found.")

    provenance = MANUAL_CONTROLLED_GOLD_PROVENANCE
    generator_version = "v1.0.0"
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    candidate_schema = schemas.gold_candidates
    candidate_name = f"{target_name}_candidate_{run_id}"
    primary_silver = payload.silver_table_names[0]

    sql_text = (
        f'CREATE TABLE "{candidate_schema}"."{candidate_name}" AS '
        f'WITH step_1 AS (SELECT * FROM "{schemas.silver}"."{primary_silver}") '
        f'SELECT * FROM step_1'
    )

    selected_sources = [
        {"schema": schemas.silver, "table": s_table}
        for s_table in payload.silver_table_names
    ]
    planned_changes = {
        "summary": f"Controlled Gold projection from silver.{primary_silver}",
        "sources": payload.silver_table_names,
        "target": target_name,
        "business_requirement": payload.business_requirement,
    }
    try:
        generation_catalog = resolve_gold_approval_catalog(
            selected_sources=selected_sources,
            target={"schema": schemas.gold, "table": target_name},
            candidate={"schema": candidate_schema, "table": candidate_name},
        )
    except GoldCatalogResolutionError as exc:
        status_code = 404 if exc.area == "source" else 503
        raise HTTPException(status_code=status_code, detail=GOLD_GENERATION_UNAVAILABLE) from None
    except Exception:
        logger.exception("Controlled Gold generation catalog resolution failed")
        raise HTTPException(status_code=503, detail=GOLD_GENERATION_UNAVAILABLE) from None

    return _persist_gold_proposal(
        run_id=run_id,
        target_name=target_name,
        sql_text=sql_text,
        planned_changes=planned_changes,
        business_requirement=(
            payload.business_requirement or "Controlled Gold Projection"
        ),
        provenance=provenance,
        generator_version=generator_version,
        selected_sources=selected_sources,
        target_schema=schemas.gold,
        candidate_schema=candidate_schema,
        origin_database_identity={
            "oid": generation_catalog.database_oid,
            "name": generation_catalog.database_name,
        },
        origin_source_identities=list(generation_catalog.source_identities),
    )


def _resolve_structured_gold_source_or_error(
    source: StructuredGoldSourcePayload,
):
    schemas = load_layer_schemas()
    if source.schema_name != schemas.silver:
        raise HTTPException(
            status_code=422,
            detail="Structured Gold source must use the configured Silver schema.",
        )

    try:
        source_catalog = resolve_structured_gold_source(
            schema=schemas.silver,
            relation_name=source.table,
        )
    except Exception as exc:
        if _is_connectivity_error(exc):
            logger.warning(
                "Structured Gold source catalog unavailable: %s",
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=503,
                detail="Structured Gold source validation is currently unavailable.",
            ) from None
        if isinstance(exc, GoldCatalogResolutionError):
            raise HTTPException(
                status_code=404,
                detail="Structured Gold Silver source is unavailable.",
            ) from None
        logger.exception("Structured Gold source catalog resolution failed")
        raise HTTPException(
            status_code=500,
            detail="Structured Gold source validation failed.",
        ) from None
    return schemas, source_catalog


def _generate_structured_gold_proposal(
    payload: GenerateStructuredGoldPayload,
    *,
    source_catalog=None,
    generator_family: str = "structured_manual",
    generator_model: str | None = None,
):
    """Compile and persist one validated definition through the shared Gold path."""
    if not GOLD_GENERATOR_TRUST.trusts_run(
        STRUCTURED_DETERMINISTIC_GOLD_PROVENANCE
    ):
        raise HTTPException(status_code=503, detail=GOLD_GENERATION_UNAVAILABLE)

    schemas = load_layer_schemas()
    if source_catalog is None:
        _, source_catalog = _resolve_structured_gold_source_or_error(payload.source)

    columns = {column.name: column for column in source_catalog.columns}
    expression = payload.metric.expression.model_dump()
    try:
        definition = validate_structured_gold_definition(
            dimension=payload.dimension.column,
            aggregation=payload.metric.aggregation,
            expression=expression,
            alias=payload.metric.alias,
            columns=columns,
        )
    except StructuredGoldDefinitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    target_name = payload.target_table_name
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    candidate_schema = schemas.gold_candidates
    candidate_name = f"{target_name}_candidate_{run_id}"
    source_identity = source_catalog.source_identity
    selected_sources = [
        {
            "schema": source_identity["schema"],
            "table": source_identity["relation_name"],
        }
    ]
    try:
        sql_text = compile_structured_gold_sql(
            candidate_schema=candidate_schema,
            candidate_name=candidate_name,
            source_schema=source_identity["schema"],
            source_relation=source_identity["relation_name"],
            definition=definition,
        )
        sql_text = validate_generated_sql(
            sql_text,
            expected_schema=candidate_schema,
            expected_table_name=target_name,
            run_id=run_id,
            mode="gold_ctas",
            selected_sources=(
                (
                    source_identity["schema"],
                    source_identity["relation_name"],
                ),
            ),
            expected_candidate_name=candidate_name,
        )
    except (StructuredGoldDefinitionError, SqlSafetyViolation):
        logger.exception("Structured Gold deterministic SQL was rejected")
        raise HTTPException(
            status_code=422,
            detail="Structured Gold definition could not produce safe SQL.",
        ) from None

    planned_changes = {
        "summary": (
            "Structured Gold aggregation from "
            f"{source_identity['schema']}.{source_identity['relation_name']}"
        ),
        "source": selected_sources[0],
        "dimension": definition["dimension"],
        "metric": {
            "aggregation": definition["aggregation"],
            "expression": definition["expression"],
            "alias": definition["alias"],
        },
        "target": target_name,
        "business_purpose": payload.business_purpose,
    }
    return _persist_gold_proposal(
        run_id=run_id,
        target_name=target_name,
        sql_text=sql_text,
        planned_changes=planned_changes,
        business_requirement=payload.business_purpose,
        provenance=STRUCTURED_DETERMINISTIC_GOLD_PROVENANCE,
        generator_version="v1.0.0",
        selected_sources=selected_sources,
        target_schema=schemas.gold,
        candidate_schema=candidate_schema,
        generation_database_identity={
            "oid": source_catalog.database_oid,
            "name": source_catalog.database_name,
        },
        generation_source_identities=[source_identity],
        generator_family=generator_family,
        generator_model=generator_model,
    )


@router.post("/generate-structured")
def generate_structured_gold_sql(payload: GenerateStructuredGoldPayload):
    """Compile one exact structured aggregation into the existing Gold review flow."""
    return _generate_structured_gold_proposal(payload)


@router.post("/ai/generate")
def generate_ai_structured_gold(payload: GenerateAIGoldPayload):
    """Translate intent once, then reuse the deterministic Structured Gold kernel."""
    schemas, source_catalog = _resolve_structured_gold_source_or_error(payload.source)
    model = configured_gold_ai_model()
    try:
        interpretation = interpret_gold_requirement(
            source_schema=schemas.silver,
            source_relation=source_catalog.source_identity["relation_name"],
            columns=source_catalog.columns,
            business_requirement=payload.business_requirement,
            model=model,
        )
    except GoldAIUnavailable:
        raise HTTPException(status_code=503, detail="GOLD_AI_UNAVAILABLE") from None
    except GoldAIProposalInvalid:
        raise HTTPException(status_code=422, detail="GOLD_AI_PROPOSAL_INVALID") from None

    if isinstance(interpretation, GoldAIAmbiguousInterpretation):
        return interpretation.model_dump()
    if isinstance(interpretation, GoldAIUnsupportedInterpretation):
        return interpretation.model_dump()
    if not isinstance(interpretation, GoldAISupportedInterpretation):
        raise HTTPException(status_code=422, detail="GOLD_AI_PROPOSAL_INVALID")

    definition = interpretation.definition
    structured_payload = GenerateStructuredGoldPayload(
        source=payload.source,
        dimension=StructuredGoldDimensionPayload(column=definition.dimension),
        metric=StructuredGoldMetricPayload(
            aggregation=definition.aggregation,
            expression=definition.expression.model_dump(),
            alias=definition.alias,
        ),
        target_table_name=payload.target_table_name,
        business_purpose=payload.business_requirement,
    )
    try:
        response = _generate_structured_gold_proposal(
            structured_payload,
            source_catalog=source_catalog,
            generator_family="gemini",
            generator_model=model,
        )
    except HTTPException as exc:
        if exc.status_code == 422:
            raise HTTPException(
                status_code=422,
                detail="GOLD_AI_PROPOSAL_INVALID",
            ) from None
        raise

    response["verdict"] = "SUPPORTED"
    response["ai_interpretation"] = interpretation.model_dump()
    response["generator_family"] = "gemini"
    response["generator_model"] = model
    return response

@router.get("/review/{run_id}")
def review_gold_sql(run_id: str):
    """Review only runs produced by a trusted, hardened Gold generator."""
    with get_connection() as conn:
        row, security_row = _load_gold_rows(conn, run_id)
        
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
    except GoldAuthorityConfigurationError:
        _log_gold_authority_failure(run_id, "review", "authority_key_missing")
        raise HTTPException(status_code=503, detail=GOLD_UNAVAILABLE) from None
    except (GoldStateMalformed, GoldStateStale, TypeError, ValueError):
        _log_gold_authority_failure(run_id, "review", "persisted_authority_invalid")
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
        "executed": row["status"] not in {"PENDING", "EXECUTING"},
        "executable": row["status"] == "PENDING",
        "status": row["status"],
        "generator_provenance": row["generator_provenance"],
        "message": (
            "Gold plan has explicit approval."
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
    origin = conn.execute(
        "SELECT * FROM gold_run_origin WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if security is not None:
        security = {
            **dict(security),
            "__gold_run_origin": dict(origin) if origin is not None else None,
        }
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
            except GoldAuthorityConfigurationError:
                _log_gold_authority_failure(run_id, "approval", "authority_key_missing")
                raise HTTPException(status_code=503, detail=GOLD_UNAVAILABLE) from None
            except GoldStateStale:
                raise HTTPException(
                    status_code=409,
                    detail=GOLD_APPROVAL_STALE,
                ) from None
            except GoldStateMalformed:
                _log_gold_authority_failure(run_id, "approval", "persisted_authority_invalid")
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

            if (
                state.generation_source_identities is not None
                and (
                    state.generation_database_identity is None
                    or catalog.database_oid
                    != state.generation_database_identity["oid"]
                    or catalog.database_name
                    != state.generation_database_identity["name"]
                    or tuple(catalog.source_identities)
                    != state.generation_source_identities
                )
            ):
                raise HTTPException(
                    status_code=409,
                    detail=GOLD_SOURCE_IDENTITY_CHANGED,
                )

            origin_database = state.origin["generation_database"]
            origin_sources = tuple(state.origin["generation_source_identities"])
            if (
                catalog.database_oid != origin_database["oid"]
                or catalog.database_name != origin_database["name"]
                or tuple(catalog.source_identities) != origin_sources
            ):
                _log_gold_authority_failure(
                    run_id,
                    "approval",
                    "origin_source_identity_mismatch",
                )
                raise HTTPException(
                    status_code=409,
                    detail=GOLD_SOURCE_IDENTITY_CHANGED,
                )

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
            try:
                approval_mac = approval_authority_mac(
                    run_id=run_id,
                    origin=state.origin,
                    review_revision=state.review_revision,
                    approved_revision=approved_revision,
                    approved_at=approved_at,
                    approval_snapshot=approval_snapshot,
                )
            except GoldAuthorityConfigurationError:
                raise HTTPException(
                    status_code=503,
                    detail=GOLD_UNAVAILABLE,
                ) from None
            cursor = conn.execute(
                """
                UPDATE gold_security_state
                SET approval_snapshot_json = ?,
                    approved_revision = ?,
                    approved_at = ?,
                    approval_mac_key_id = 'gold-authority-hmac-v1',
                    approval_mac = ?,
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
                    approval_mac,
                    int(payload.overwrite),
                    canonical_json(list(catalog.source_identities)),
                    canonical_json(catalog.target_identity),
                    run_id,
                    state.review_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=409, detail=GOLD_STATE_CONFLICT)
            _refreshed_row, refreshed_security = _load_gold_rows(conn, run_id)
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
            except GoldAuthorityConfigurationError:
                _log_gold_authority_failure(run_id, "execution", "authority_key_missing")
                raise HTTPException(
                    status_code=503,
                    detail=GOLD_UNAVAILABLE,
                ) from None
            except GoldStateStale:
                raise HTTPException(
                    status_code=409,
                    detail=GOLD_APPROVAL_STALE,
                ) from None
            except GoldStateMalformed:
                _log_gold_authority_failure(run_id, "execution", "persisted_authority_invalid")
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
            except GoldAuthorityConfigurationError:
                _log_gold_authority_failure(run_id, "promotion", "authority_key_missing")
                raise HTTPException(
                    status_code=503,
                    detail=GOLD_UNAVAILABLE,
                ) from None
            except (GoldStateMalformed, GoldStateStale):
                _log_gold_authority_failure(run_id, "promotion", "persisted_authority_invalid")
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
                _refreshed_row, refreshed_security = _load_gold_rows(
                    conn, run_id
                )
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
