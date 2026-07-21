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
                    results.append({
                        "table": table_name,
                        "status": "error",
                        "error": f"Failed to ingest: {str(e)}"
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
