"""User Postgres connector endpoints — separate from the app's own DATABASE_URL."""

from __future__ import annotations

import uuid
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import api.main as api_main
import psycopg
from psycopg import sql

from src.app_state.store import (
    get_data_connection,
    get_project,
    save_data_connection,
    save_validation_report,
    save_validation_run,
)
from src.csv_ingest import (
    CsvSchemaMismatch,
    run_connector_validation_from_raw_orders as _run_connector_validation,
)
from src.config_loader import ConfigResolutionError, resolve_config_for_project_or_table
from src.db_config import postgres_target_info
from src.postgres_connector import (
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
from src.report_builder import attach_trust_narrative

router = APIRouter(tags=["connectors"])
logger = logging.getLogger(__name__)

CONNECTOR_NARRATIVE_TIMEOUT_SECONDS = 15


def run_validation_from_raw_orders(*args, **kwargs):
    """Compatibility seam delegating to authority-producing connector ETL."""
    return _run_connector_validation(*args, **kwargs)


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
        (
            report,
            session_schema,
            bronze_identity,
        ) = run_validation_from_raw_orders(
            frame,
            run_id=run_id,
            cfg=cfg,
        )
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
            bronze_identity=bronze_identity,
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
