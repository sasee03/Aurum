from __future__ import annotations

from src.app_state.store import get_data_connection, get_project
from src.bronze_authority import (
    BRONZE_INGEST_COMMIT_IN_PROGRESS,
    BRONZE_INGEST_RECONCILIATION_REQUIRED,
    BronzeAuthorityError,
    claim_bronze_ingest_operation,
    finalize_bronze_ingest_ready,
    find_ready_bronze_authority,
    get_bronze_ingest_operation,
    mark_bronze_ingest_commit_in_progress,
    mark_bronze_ingest_creating,
    mark_bronze_ingest_outcome,
)

from src.promotion import resolve_relation_identity
from typing import List, Optional, Any, Dict
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import psycopg
from psycopg import sql

from src.db_config import get_ingestion_pool, load_layer_schemas
from src.metadata_discovery import discover_from_connection, discover_table_metadata, AmbiguousTableError

router = APIRouter(tags=["Source Ingestion"])

class ConnectRequest(BaseModel):
    host: str
    port: int
    database: str
    user: str
    password: str

class IngestRequest(BaseModel):
    tables: List[str]

@router.post("/api/v1/source/connect")
def source_connect(req: ConnectRequest):
    """P1.1: Verify connection to the source database with honest error messages."""
    conninfo = (
        f"host={req.host} port={req.port} dbname={req.database} "
        f"user={req.user} password={req.password}"
    )
    try:
        # We use a short connection timeout just to test
        with psycopg.connect(conninfo, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return {"connected": True, "message": "Connection successful."}
    except psycopg.OperationalError as e:
        error_str = str(e).lower()
        if "authentication failed" in error_str or "password authentication failed" in error_str:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "Authentication failed", "message": f"Authentication failed for user '{req.user}'."}
            )
        elif "does not exist" in error_str and "database" in error_str:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "Database not found", "message": f"Database '{req.database}' does not exist on server."}
            )
        else:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"error": "Host unreachable", "message": f"Host/port unreachable at '{req.host}:{req.port}'."}
            )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Unknown error", "message": str(e)}
        )

@router.get("/api/v1/source/tables")
def source_tables(schema: Optional[str] = None):
    """P1.2 & P1.3: Discover tables and their row counts from the source schema."""
    schemas = load_layer_schemas()
    target_schema = schema or schemas.source

    pool = get_ingestion_pool()
    try:
        with pool.connection() as conn:
            # We enforce use of aurum_ingestion for these queries
            response = discover_from_connection(conn, schema=target_schema, source="live", lightweight=False)
            response["schema"] = target_schema
            return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



def _database_identity(conn: Any) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT database.oid, database.datname
            FROM pg_catalog.pg_database AS database
            WHERE database.datname = pg_catalog.current_database()
            """
        )
        row = cur.fetchone()
    if row is None or type(row[0]) is not int or row[0] <= 0:
        raise RuntimeError("PostgreSQL current database identity is unavailable")
    return {
        "database_oid": int(row[0]),
        "database_name": str(row[1]),
    }


def _namespace_oid(conn: Any, schema: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT oid
            FROM pg_catalog.pg_namespace
            WHERE nspname = %s
            """,
            (schema,),
        )
        row = cur.fetchone()
    if row is None or type(row[0]) is not int or row[0] <= 0:
        raise RuntimeError(f"PostgreSQL schema {schema!r} is unavailable")
    return int(row[0])


def _resolve_ingest_connection_authority(connection_id: str) -> tuple[str, Any]:
    conn = get_data_connection(connection_id)
    if conn is None or conn.get("status") != "active":
        raise HTTPException(
            status_code=409,
            detail=f"Data connection '{connection_id}' is not active or does not exist.",
        )
    project_id = conn.get("project_id", "")
    project = get_project(project_id)
    if project is None:
        raise HTTPException(
            status_code=409,
            detail=f"Project '{project_id}' does not exist.",
        )
    return project_id, conn


def _require_same_live_database(session: Any, conn: Any) -> dict[str, Any]:
    live = _database_identity(conn)
    session_db = session.get("database_name")
    if session_db and session_db != live["database_name"]:
        raise HTTPException(
            status_code=409,
            detail="Active session database name does not match live connection",
        )
    return live


@router.post("/api/v1/source/ingest-to-bronze")
def ingest_to_bronze(req: IngestRequest):
    """P1.4: Atomically copy selected tables from source to bronze (1:1 data copy)."""
    if not req.tables:
        raise HTTPException(status_code=400, detail="No tables selected for ingestion.")

    schemas = load_layer_schemas()
    source_schema = schemas.source
    bronze_schema = schemas.bronze

    pool = get_ingestion_pool()
    results = []

    try:
        with pool.connection() as conn:
            # Step 1: Validate client-provided tables against an allow-list
            discovered = discover_from_connection(conn, schema=source_schema, lightweight=True)
            allowed_tables = {t["table"] for t in discovered.get("tables", [])}

            for table_name in req.tables:
                if table_name not in allowed_tables:
                    results.append({
                        "table": table_name,
                        "status": "error",
                        "error": f"Table '{table_name}' not found in source schema '{source_schema}'."
                    })
                    continue

                ingest_id = None
                ingest_id = None
                try:
                    # Execute DROP and CREATE TABLE AS in a transaction
                    with conn.transaction():
                        with conn.cursor() as cur:
                            qualified_source = sql.SQL("{}.{}").format(sql.Identifier(source_schema), sql.Identifier(table_name))
                            qualified_bronze = sql.SQL("{}.{}").format(sql.Identifier(bronze_schema), sql.Identifier(table_name))

                            # Drop existing bronze table if it exists
                            cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(qualified_bronze))

                            # Create new bronze table as a 1:1 data copy
                            cur.execute(
                                sql.SQL("CREATE TABLE {} AS SELECT * FROM {}").format(
                                    qualified_bronze, qualified_source
                                )
                            )
                    results.append({
                        "table": table_name,
                        "status": "success",
                        "message": "Ingested to bronze successfully."
                    })
                except Exception as e:
                    operation_status = None
                    operation_id = ingest_id
                    if operation_id:
                        try:
                            operation_status = get_bronze_ingest_operation(
                                operation_id
                            )["status"]
                        except Exception:
                            operation_status = None
                    results.append({
                        "table": table_name,
                        "status": "error",
                        "error": f"Failed to ingest: {str(e)}",
                        "ingest_id": operation_id,
                        "operation_status": operation_status,
                    })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Connection pool error: {str(e)}")

    return {"results": results}


@router.post("/api/v1/source/verify-bronze")
def verify_bronze(req: IngestRequest):
    """P1.5: Verify ingested tables and return a sample."""
    if not req.tables:
        raise HTTPException(status_code=400, detail="No tables specified.")

    schemas = load_layer_schemas()
    source_schema = schemas.source
    bronze_schema = schemas.bronze

    pool = get_ingestion_pool()
    results = []

    try:
        with pool.connection() as conn:
            for table_name in req.tables:
                try:
                    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                        qual_source = sql.SQL("{}.{}").format(sql.Identifier(source_schema), sql.Identifier(table_name))
                        qual_bronze = sql.SQL("{}.{}").format(sql.Identifier(bronze_schema), sql.Identifier(table_name))

                        # Check source count
                        cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(qual_source))
                        row = cur.fetchone()
                        source_count = row["count"] if row else 0

                        # Check bronze count
                        cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(qual_bronze))
                        row = cur.fetchone()
                        bronze_count = row["count"] if row else 0

                        # Get preview
                        cur.execute(sql.SQL("SELECT * FROM {} LIMIT 50").format(qual_bronze))
                        preview = cur.fetchall()

                        results.append({
                            "table": table_name,
                            "status": "success",
                            "source_row_count": source_count,
                            "bronze_row_count": bronze_count,
                            "match": source_count == bronze_count,
                            "preview_sample": preview
                        })
                except Exception as e:
                    results.append({
                        "table": table_name,
                        "status": "error",
                        "error": str(e)
                    })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"results": results}



@router.post("/api/v1/source/ingest-reconcile/{ingest_id}")
def reconcile_bronze_ingest(ingest_id: str):
    """Read-first exact-OID reconciliation for an unresolved Bronze commit."""
    try:
        operation = get_bronze_ingest_operation(ingest_id)
    except BronzeAuthorityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if operation["status"] == "READY":
        authority = finalize_bronze_ingest_ready(ingest_id)
        return {
            "status": "READY",
            "ingest_id": ingest_id,
            "bronze_identity": authority["bronze_identity"],
        }
    if operation["status"] not in {
        BRONZE_INGEST_COMMIT_IN_PROGRESS,
        BRONZE_INGEST_RECONCILIATION_REQUIRED,
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "Bronze ingest is not in a commit-reconciliation state "
                f"({operation['status']})."
            ),
        )
    expected = operation["provisional_bronze_identity"]
    if expected is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "No exact provisional Bronze identity was persisted; "
                "manual reconciliation is required."
            ),
        )
    connection = get_data_connection(operation["connection_id"])
    if (
        connection is None
        or connection.get("project_id") != operation["project_id"]
        or connection.get("status") != "active"
        or get_project(operation["project_id"]) is None
    ):
        raise HTTPException(
            status_code=409,
            detail="Persisted Bronze project/connection authority is inactive.",
        )
    try:
        with get_ingestion_pool().connection() as conn:
            database = _database_identity(conn)
            if (
                database["database_name"] != operation["database_name"]
                or database["database_oid"] != expected["database_oid"]
            ):
                raise BronzeAuthorityError(
                    "Reconciliation database identity does not match authority"
                )
            with conn.transaction():
                live = resolve_relation_identity(
                    conn,
                    operation["bronze_schema"],
                    operation["bronze_relation"],
                )
                if live == expected:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            sql.SQL(
                                "LOCK TABLE {}.{} IN ACCESS SHARE MODE"
                            ).format(
                                sql.Identifier(operation["bronze_schema"]),
                                sql.Identifier(operation["bronze_relation"]),
                            )
                        )
                    locked = resolve_relation_identity(
                        conn,
                        operation["bronze_schema"],
                        operation["bronze_relation"],
                    )
                    if locked != expected:
                        live = locked
    except BronzeAuthorityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Bronze reconciliation database is unavailable.",
        ) from exc

    if live == expected:
        authority = finalize_bronze_ingest_ready(ingest_id)
        return {
            "status": "READY",
            "ingest_id": ingest_id,
            "bronze_identity": authority["bronze_identity"],
            "reconciled": True,
        }
    if live is None:
        mark_bronze_ingest_outcome(
            ingest_id,
            status="FAILED_RETRYABLE",
            failure_code="EXACT_PROVISIONAL_RELATION_ABSENT",
        )
        return {
            "status": "FAILED_RETRYABLE",
            "ingest_id": ingest_id,
            "reconciled": True,
        }
    mark_bronze_ingest_outcome(
        ingest_id,
        status=BRONZE_INGEST_RECONCILIATION_REQUIRED,
        failure_code="SAME_NAME_DIFFERENT_IDENTITY",
    )
    return {
        "status": BRONZE_INGEST_RECONCILIATION_REQUIRED,
        "ingest_id": ingest_id,
        "replacement_preserved": True,
    }



def verify_bronze(req: IngestRequest):
    """P1.5: Verify ingested tables and return a sample."""
    if not req.tables:
        raise HTTPException(status_code=400, detail="No tables specified.")

    schemas = load_layer_schemas()
    source_schema = schemas.source
    bronze_schema = schemas.bronze

    pool = get_ingestion_pool()
    results = []

    try:
        with pool.connection() as conn:
            for table_name in req.tables:
                try:
                    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                        qual_source = sql.SQL("{}.{}").format(sql.Identifier(source_schema), sql.Identifier(table_name))
                        qual_bronze = sql.SQL("{}.{}").format(sql.Identifier(bronze_schema), sql.Identifier(table_name))

                        # Check source count
                        cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(qual_source))
                        row = cur.fetchone()
                        source_count = row["count"] if row else 0

                        # Check bronze count
                        cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(qual_bronze))
                        row = cur.fetchone()
                        bronze_count = row["count"] if row else 0

                        # Get preview
                        cur.execute(sql.SQL("SELECT * FROM {} LIMIT 50").format(qual_bronze))
                        preview = cur.fetchall()

                        results.append({
                            "table": table_name,
                            "status": "success",
                            "source_row_count": source_count,
                            "bronze_row_count": bronze_count,
                            "match": source_count == bronze_count,
                            "preview_sample": preview
                        })
                except Exception as e:
                    results.append({
                        "table": table_name,
                        "status": "error",
                        "error": str(e)
                    })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"results": results}
