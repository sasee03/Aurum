"""User Postgres connector endpoints — separate from the app's own DATABASE_URL."""

from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr

import api.main as api_main
import psycopg
from psycopg import sql

from src.app_state.db import get_connection
from src.app_state.store import (
    get_data_connection,
    get_project,
    save_data_connection,
    save_validation_report,
    save_validation_run,
)
from src.csv_ingest import CsvSchemaMismatch, run_validation_from_raw_orders
from src.config_loader import ConfigResolutionError, resolve_config_for_project_or_table
from src.bronze_authority import (
    BronzeAuthorityError,
    claim_bronze_ingest_operation,
    finalize_bronze_ingest_ready,
    find_ready_bronze_authority,
    mark_bronze_ingest_commit_in_progress,
    mark_bronze_ingest_creating,
    mark_bronze_ingest_outcome,
    BRONZE_INGEST_FAILED_RETRYABLE,
    BRONZE_INGEST_RECONCILIATION_REQUIRED,
)
from src.db_config import load_layer_schemas, postgres_target_info
from src.postgres_connector import (
    SessionConnection,
    UserPostgresTarget,
    classify_connect_error,
    get_session_connection,
    list_user_schemas,
    list_user_tables,
    load_and_validate_user_table,
    open_session_connection,
    session_public_view,
    store_session_connection,
    test_user_postgres,
)
from src.metadata_discovery import discover_table_metadata
from src.promotion import resolve_relation_identity
from src.report_builder import attach_trust_narrative

router = APIRouter(tags=["connectors"])
logger = logging.getLogger(__name__)

CONNECTOR_NARRATIVE_TIMEOUT_SECONDS = 15


class PostgresTestRequest(BaseModel):
    host: str = Field(..., min_length=1)
    port: int = Field(..., ge=1, le=65535)
    database: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1)
    password: str = Field(...)
    project_id: Optional[str] = None
    name: Optional[str] = None


class PostgresValidateRequest(BaseModel):
    connection_id: str = Field(..., min_length=1)
    schema_name: str = Field(..., min_length=1, alias="schema")
    table: str = Field(..., min_length=1)
    project_id: Optional[str] = None

    model_config = {"populate_by_name": True}


class ConnectorRelationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_name: StrictStr = Field(
        alias="schema",
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        max_length=63,
    )
    table: StrictStr = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        max_length=63,
    )


class ConnectorBronzeIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: StrictStr = Field(min_length=1, max_length=200)
    relations: List[ConnectorRelationPayload] = Field(min_length=1, max_length=20)


def _schema_mismatch_response(exc: CsvSchemaMismatch) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "schema_match": False,
            "error": exc.error,
            "expected_columns": exc.expected_columns,
            "missing_columns": exc.missing_columns,
        },
    )


def _config_resolution_response(exc: ConfigResolutionError) -> JSONResponse:
    status_code = {
        "project_store_lookup_failed": status.HTTP_500_INTERNAL_SERVER_ERROR,
        "dataset_config_lookup_failed": status.HTTP_500_INTERNAL_SERVER_ERROR,
        "project_not_found": status.HTTP_404_NOT_FOUND,
    }.get(exc.code, status.HTTP_422_UNPROCESSABLE_ENTITY)
    return JSONResponse(
        status_code=status_code,
        content={"error": exc.code, "message": str(exc)},
    )


def _require_app_db() -> None:
    if not api_main._database_reachable():
        target = postgres_target_info()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "live_validation_unavailable",
                "message": (
                    "Live validation is unavailable: the Aurum database is unreachable. "
                    "Start PostgreSQL and check /health."
                ),
                "database_target": target,
            },
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_connector_state_metadata(session: SessionConnection) -> str:
    """Persist non-secret session metadata so Bronze authority FKs can bind it."""
    project_id = session.project_id if session.project_id and get_project(session.project_id) else None
    if project_id is None:
        project_id = "connector_session_project"
        now = _utc_now()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO projects (
                    id, name, description, environment, created_at, updated_at,
                    status
                )
                VALUES (?, 'Connector Sessions', '', 'Development', ?, ?, 'active')
                """,
                (project_id, now, now),
            )
            conn.commit()

    if get_data_connection(session.connection_id) is None:
        save_data_connection(
            connection_id=session.connection_id,
            project_id=project_id,
            name=session.name,
            host=session.host,
            port=session.port,
            database_name=session.database,
            username=session.username,
        )
    return project_id


def _database_identity(conn: Any) -> tuple[int, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT oid, datname
            FROM pg_catalog.pg_database
            WHERE datname = pg_catalog.current_database()
            """
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "database_identity_unresolved",
                "message": "The connector database identity could not be resolved.",
            },
        )
    return int(row[0]), str(row[1])


def _namespace_oid(conn: Any, schema_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT oid FROM pg_catalog.pg_namespace WHERE nspname = %s",
            (schema_name,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "bronze_schema_unavailable",
                "message": (
                    f"Configured Bronze schema '{schema_name}' is not available "
                    "in this connector database."
                ),
            },
        )
    return int(row[0])


def _relation_payload(relation: ConnectorRelationPayload) -> dict[str, str]:
    return {
        "schema": relation.schema_name.strip(),
        "table": relation.table.strip(),
    }


def _validate_selected_relation(
    conn: Any,
    *,
    database_oid: int,
    relation: dict[str, str],
) -> dict[str, Any]:
    discovered = list_user_tables(conn, schema=relation["schema"])
    if not any(
        item.get("schema") == relation["schema"] and item.get("table") == relation["table"]
        for item in discovered
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "source_relation_not_found",
                "message": (
                    f"Source relation '{relation['schema']}.{relation['table']}' "
                    "was not found in this connector session."
                ),
                "source": relation,
            },
        )
    try:
        source_identity = resolve_relation_identity(
            conn,
            relation["schema"],
            relation["table"],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "source_relation_invalid",
                "message": classify_connect_error(exc),
                "source": relation,
            },
        ) from None
    if source_identity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "source_relation_not_found",
                "message": (
                    f"Source relation '{relation['schema']}.{relation['table']}' "
                    "could not be resolved in this connector database."
                ),
                "source": relation,
            },
        )
    if source_identity["database_oid"] != database_oid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "source_database_identity_mismatch",
                "message": "Source relation identity does not belong to the selected connector database.",
                "source": relation,
            },
        )
    if source_identity["relation_kind"] not in {"r", "p"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "unsupported_source_relation_kind",
                "message": "Only ordinary and partitioned PostgreSQL tables can be ingested to Bronze.",
                "source": relation,
            },
        )
    return source_identity


def _assert_bronze_target_available(
    conn: Any,
    *,
    source: dict[str, str],
    bronze_schema: str,
    bronze_relation: str,
) -> None:
    ready = find_ready_bronze_authority(
        bronze_schema=bronze_schema,
        bronze_relation=bronze_relation,
    )
    if ready is not None and (
        ready["source_schema"] != source["schema"]
        or ready["source_relation"] != source["table"]
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "bronze_target_source_conflict",
                "message": (
                    f"Bronze target '{bronze_schema}.{bronze_relation}' is already "
                    f"bound to source '{ready['source_schema']}.{ready['source_relation']}'."
                ),
                "source": source,
                "bronze": {"schema": bronze_schema, "table": bronze_relation},
            },
        )
    existing = resolve_relation_identity(conn, bronze_schema, bronze_relation)
    if existing is not None and ready is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "bronze_target_untracked_conflict",
                "message": (
                    f"Bronze target '{bronze_schema}.{bronze_relation}' already "
                    "exists without connector-bound authority."
                ),
                "source": source,
                "bronze": {"schema": bronze_schema, "table": bronze_relation},
            },
        )


def _copy_relation_to_bronze(
    conn: Any,
    *,
    source_schema: str,
    source_table: str,
    bronze_schema: str,
    bronze_table: str,
) -> dict[str, Any]:
    """Create one Bronze 1:1 copy using identifier-quoted PostgreSQL SQL."""
    with conn.transaction():
        with conn.cursor() as cur:
            qualified_source = sql.SQL("{}.{}").format(
                sql.Identifier(source_schema),
                sql.Identifier(source_table),
            )
            qualified_bronze = sql.SQL("{}.{}").format(
                sql.Identifier(bronze_schema),
                sql.Identifier(bronze_table),
            )
            cur.execute(sql.SQL("LOCK TABLE {} IN ACCESS SHARE MODE").format(qualified_source))
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(qualified_source))
            source_row_count = int(cur.fetchone()[0])
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(qualified_bronze))
            cur.execute(
                sql.SQL("CREATE TABLE {} AS SELECT * FROM {}").format(
                    qualified_bronze,
                    qualified_source,
                )
            )
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(qualified_bronze))
            bronze_row_count = int(cur.fetchone()[0])
    bronze_identity = resolve_relation_identity(conn, bronze_schema, bronze_table)
    if bronze_identity is None:
        raise RuntimeError("Bronze relation was not created")
    return {
        "source_row_count": source_row_count,
        "bronze_row_count": bronze_row_count,
        "match": source_row_count == bronze_row_count,
        "bronze_identity": bronze_identity,
    }


def _connector_bronze_result(
    *,
    connection_id: str,
    authority: dict[str, Any],
    source_row_count: int,
    bronze_row_count: int,
    match: bool,
) -> dict[str, Any]:
    return {
        "connection_id": connection_id,
        "ingest_id": authority["ingest_id"],
        "status": "success" if match else "error",
        "source": {
            "schema": authority["source_schema"],
            "table": authority["source_relation"],
        },
        "bronze": {
            "schema": authority["bronze_schema"],
            "table": authority["bronze_relation"],
        },
        "source_row_count": source_row_count,
        "bronze_row_count": bronze_row_count,
        "row_count": bronze_row_count if match else None,
        "match": match,
    }


@router.post("/connectors/postgres/test")
def test_postgres_connector(body: PostgresTestRequest) -> dict:
    """Test a user-supplied Postgres target. Never echoes the password."""
    target = UserPostgresTarget(
        host=body.host.strip(),
        port=int(body.port),
        database=body.database.strip(),
        username=body.username.strip(),
        password=body.password,
    )
    result = test_user_postgres(target)
    if not result["connected"]:
        return result

    try:
        session = store_session_connection(
            target,
            project_id=body.project_id,
            name=body.name,
        )
        if body.project_id and get_project(body.project_id):
            save_data_connection(
                connection_id=session.connection_id,
                project_id=body.project_id,
                name=session.name,
                host=session.host,
                port=session.port,
                database_name=session.database,
                username=session.username,
            )
    except Exception:
        return {
            "connected": False,
            "error": "Connection succeeded, but saving connection metadata failed. Please retry.",
            "host": target.host,
            "port": int(target.port),
            "database": target.database,
            "username": target.username,
        }

    public = session_public_view(session)
    return {
        "connected": True,
        "connection_id": public["connection_id"],
        "host": public["host"],
        "port": public["port"],
        "database": public["database"],
        "username": public["username"],
        "name": public["name"],
    }


@router.get("/connectors/postgres/schemas")
def postgres_schemas(connection_id: str = Query(...)) -> dict:
    session = get_session_connection(connection_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "connection_not_found",
                "message": (
                    "Connection session expired or unknown. "
                    "Re-test the connection (password is not persisted)."
                ),
            },
        )
    try:
        with open_session_connection(session) as conn:
            schemas = list_user_schemas(conn)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"connected": False, "error": classify_connect_error(exc)},
        )
    return {"connection_id": connection_id, "schemas": schemas}


@router.get("/connectors/postgres/tables")
def postgres_tables(
    connection_id: str = Query(...),
    schema: Optional[str] = Query(None),
) -> dict:
    session = get_session_connection(connection_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "connection_not_found",
                "message": (
                    "Connection session expired or unknown. "
                    "Re-test the connection (password is not persisted)."
                ),
            },
        )
    try:
        with open_session_connection(session) as conn:
            tables = list_user_tables(conn, schema=schema)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"connected": False, "error": classify_connect_error(exc)},
        )
    return {"connection_id": connection_id, "schema": schema, "tables": tables}


@router.get("/connectors/postgres/tables/{table}/preview")
def preview_postgres_table(
    table: str,
    connection_id: str = Query(...),
    schema: Optional[str] = Query(None),
) -> dict:
    """Preview a user table directly from the remote Postgres instance, before validation."""
    session = get_session_connection(connection_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "connection_not_found",
                "message": (
                    "Connection session expired or unknown. "
                    "Re-test the connection (password is not persisted)."
                ),
            },
        )
    try:
        with open_session_connection(session) as conn:
            # 1. Gather rich metadata (columns, types, row count, nullability)
            metadata = discover_table_metadata(conn, schema_name=schema or "public", table_name=table)

            # 2. Fetch a real sample of rows
            # Using dict_row to match column names to values cleanly
            with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                # Default schema to 'public' if not provided to avoid ambiguity errors
                qualified_name = sql.SQL("{}.{}").format(
                    sql.Identifier(schema or "public"),
                    sql.Identifier(table)
                )
                cur.execute(sql.SQL("SELECT * FROM {} LIMIT 50").format(qualified_name))
                sample_data = cur.fetchall()

    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"connected": False, "error": classify_connect_error(exc)},
        )

    return {
        "connection_id": connection_id,
        "schema": schema,
        "table": table,
        "metadata": metadata,
        "data": sample_data
    }


@router.post("/connectors/postgres/bronze/ingest")
def ingest_connector_relations_to_bronze(body: ConnectorBronzeIngestRequest) -> dict:
    """Connector-bound Bronze handoff for exact discovered schema.table relations."""
    session = get_session_connection(body.connection_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "connection_not_found",
                "message": (
                    "Connection session expired or unknown. "
                    "Re-test the connection (password is not persisted)."
                ),
            },
        )

    relations = [_relation_payload(relation) for relation in body.relations]
    source_keys = [(relation["schema"], relation["table"]) for relation in relations]
    if len(set(source_keys)) != len(source_keys):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_source_relation",
                "message": "Each connector-bound Bronze source relation must be unique.",
            },
        )
    target_keys: dict[str, dict[str, str]] = {}
    for relation in relations:
        previous = target_keys.get(relation["table"])
        if previous is not None and previous["schema"] != relation["schema"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "bronze_target_name_collision",
                    "message": (
                        f"Selected sources '{previous['schema']}.{previous['table']}' "
                        f"and '{relation['schema']}.{relation['table']}' would both "
                        f"target Bronze table '{relation['table']}'. Select one source "
                        "or rename upstream before ingesting both."
                    ),
                    "bronze": {"table": relation["table"]},
                },
            )
        target_keys[relation["table"]] = relation

    project_id = _ensure_connector_state_metadata(session)
    schemas = load_layer_schemas()
    results: list[dict[str, Any]] = []

    try:
        with open_session_connection(session) as conn:
            database_oid, database_name = _database_identity(conn)
            bronze_namespace_oid = _namespace_oid(conn, schemas.bronze)
            for relation in relations:
                source_identity = _validate_selected_relation(
                    conn,
                    database_oid=database_oid,
                    relation=relation,
                )
                bronze_relation = relation["table"]
                _assert_bronze_target_available(
                    conn,
                    source=relation,
                    bronze_schema=schemas.bronze,
                    bronze_relation=bronze_relation,
                )
                ingest_id = f"bronze_{uuid.uuid4().hex}"
                operation = claim_bronze_ingest_operation(
                    ingest_id=ingest_id,
                    project_id=project_id,
                    connection_id=session.connection_id,
                    database_name=database_name,
                    database_oid=database_oid,
                    source_schema=relation["schema"],
                    source_namespace_oid=source_identity["namespace_oid"],
                    source_relation=relation["table"],
                    bronze_schema=schemas.bronze,
                    bronze_namespace_oid=bronze_namespace_oid,
                    bronze_relation=bronze_relation,
                )
                try:
                    mark_bronze_ingest_creating(
                        operation["ingest_id"],
                        source_identity=source_identity,
                    )
                    copied = _copy_relation_to_bronze(
                        conn,
                        source_schema=relation["schema"],
                        source_table=relation["table"],
                        bronze_schema=schemas.bronze,
                        bronze_table=bronze_relation,
                    )
                    if not copied["match"]:
                        raise BronzeAuthorityError(
                            "Bronze row count did not match the selected source relation"
                        )
                    mark_bronze_ingest_commit_in_progress(
                        operation["ingest_id"],
                        bronze_identity=copied["bronze_identity"],
                    )
                    authority = finalize_bronze_ingest_ready(operation["ingest_id"])
                    results.append(
                        _connector_bronze_result(
                            connection_id=session.connection_id,
                            authority=authority,
                            source_row_count=copied["source_row_count"],
                            bronze_row_count=copied["bronze_row_count"],
                            match=copied["match"],
                        )
                    )
                except Exception as exc:
                    status_code = (
                        BRONZE_INGEST_RECONCILIATION_REQUIRED
                        if isinstance(exc, BronzeAuthorityError)
                        else BRONZE_INGEST_FAILED_RETRYABLE
                    )
                    try:
                        mark_bronze_ingest_outcome(
                            operation["ingest_id"],
                            status=status_code,
                            failure_code=exc.__class__.__name__,
                        )
                    except BronzeAuthorityError:
                        logger.exception("Failed to mark connector Bronze ingest outcome")
                    results.append(
                        {
                            "connection_id": session.connection_id,
                            "ingest_id": operation["ingest_id"],
                            "status": "error",
                            "source": relation,
                            "bronze": {
                                "schema": schemas.bronze,
                                "table": bronze_relation,
                            },
                            "error": classify_connect_error(exc),
                        }
                    )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "connector_bronze_ingest_failed",
                "message": classify_connect_error(exc),
            },
        ) from None

    return {"connection_id": session.connection_id, "results": results}


@router.post("/connectors/postgres/validate")
def validate_postgres_table(body: PostgresValidateRequest) -> dict:
    """Read a user table into memory, validate Olist shape, run the upload pipeline."""
    _require_app_db()

    session = get_session_connection(body.connection_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "connection_not_found",
                "message": (
                    "Connection session expired or unknown. "
                    "Re-test the connection (password is not persisted)."
                ),
            },
        )

    project_id = body.project_id or session.project_id
    try:
        cfg = resolve_config_for_project_or_table(project_id, body.table.strip())
    except ConfigResolutionError as exc:
        return _config_resolution_response(exc)

    try:
        frame = load_and_validate_user_table(
            session,
            schema=body.schema_name.strip(),
            table=body.table.strip(),
            cfg=cfg,
        )
    except CsvSchemaMismatch as exc:
        return _schema_mismatch_response(exc)

    run_id = f"connector_{uuid.uuid4().hex[:12]}"
    source_schema = body.schema_name.strip()
    source_table = body.table.strip()
    try:
        report, session_schema = run_validation_from_raw_orders(frame, run_id=run_id, cfg=cfg)
        report = attach_trust_narrative(
            report,
            timeout_seconds=CONNECTOR_NARRATIVE_TIMEOUT_SECONDS,
        )
        # Source coordinates live on validation_runs — never inside the 17-key report.
        persisted_run_id = report.get("run_id", run_id)
        # Only attach connection_id when metadata was persisted (FK-safe).
        connection_id_for_run = (
            session.connection_id if get_data_connection(session.connection_id) else None
        )
        save_validation_run(
            persisted_run_id,
            status="completed",
            mode="connector",
            project_id=project_id if project_id and get_project(project_id) else None,
            connection_id=connection_id_for_run,
            source_schema=source_schema,
            source_table=source_table,
            session_schema=session_schema,
            dataset_config=cfg.config_name,
        )
        save_validation_report(persisted_run_id, report)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Connector table parsed but validation execution failed for %s.%s",
            source_schema,
            source_table,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "connector_validation_failed",
                "message": (
                    "Connector data matched the expected schema, but Aurum could "
                    "not complete validation. No report was persisted for this run."
                ),
            },
        )
    return report
