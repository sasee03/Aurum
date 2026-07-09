"""User Postgres connector endpoints — separate from the app's own DATABASE_URL."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import api.main as api_main
from src.app_state.store import (
    get_data_connection,
    get_project,
    save_data_connection,
    save_validation_report,
    save_validation_run,
)
from src.csv_ingest import CsvSchemaMismatch, run_validation_from_raw_orders
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
from src.report_builder import attach_trust_narrative

router = APIRouter(tags=["connectors"])


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

    try:
        frame = load_and_validate_user_table(
            session,
            schema=body.schema_name.strip(),
            table=body.table.strip(),
        )
    except CsvSchemaMismatch as exc:
        return _schema_mismatch_response(exc)

    run_id = f"connector_{uuid.uuid4().hex[:12]}"
    report = attach_trust_narrative(run_validation_from_raw_orders(frame, run_id=run_id))
    persisted_run_id = report.get("run_id", run_id)
    project_id = body.project_id or session.project_id
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
    )
    save_validation_report(persisted_run_id, report)
    return report
