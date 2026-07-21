"""FastAPI transport layer for Aurum (Ring 3 — API only).

This is a thin HTTP layer over the existing engine. It performs NO reshaping:
every report is returned exactly as ``build_report()`` produces it (the 17
top-level keys and the ``CheckResult`` shape), so a React UI can call these
endpoints with no field remapping.

Run it (port 8000 avoids clashing with Streamlit's 8501):

    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from typing import Optional

import psycopg
from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.db_config import db_connect_timeout, postgres_conninfo, postgres_target_info
from src.metadata_discovery import (
    AmbiguousTableError,
    discover_demo_session_metadata,
    discover_live_metadata,
    discover_live_table_detail,
    discover_live_tables_lightweight,
)
from src.report_builder import REPORT_PATH
from src.run_demo import run_validation
from src.report_builder import attach_trust_narrative
from src.report_safety import ReportLoadError, load_report_file, validate_report_shape
from src.app_state.store import (
    get_report_by_run_id,
    list_validation_runs,
    save_validation_report,
    save_validation_run,
)

from api.aurum_assistant.router import router as aurum_assistant_router
from api.connectors_router import router as connectors_router
from api.datasets_router import router as datasets_router
from api.projects_router import router as projects_router
from api.source_ingest_router import router as source_ingest_router
from api.bronze_silver_router import router as bronze_silver_router

REACT_DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app = FastAPI(title="Aurum API", version="1.0.0")

app.include_router(aurum_assistant_router)
app.include_router(connectors_router)
app.include_router(datasets_router)
app.include_router(projects_router)
app.include_router(source_ingest_router)
app.include_router(bronze_silver_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=REACT_DEV_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory cache of the most recent report produced in THIS process. The
# trigger endpoint uses the side-effect-free core (no file write), so this is
# the primary "latest" source; we fall back to the on-disk report.json that the
# demo script produces so `latest` still works right after `python src/run_demo.py`.
_last_report: Optional[dict] = None
logger = logging.getLogger(__name__)


def _report_load_detail(exc: ReportLoadError) -> dict:
    return {
        "error": "report_load_failed",
        "message": "This report could not be loaded because the stored report data is invalid.",
        "source": exc.source,
        "reason": exc.reason,
    }


class RunRequest(BaseModel):
    run_id: str = "demo_run_001"


def _load_latest_report() -> Optional[dict]:
    if _last_report is not None:
        return validate_report_shape(_last_report, source="in-memory latest report")
    return load_report_file(REPORT_PATH, source=str(REPORT_PATH))


def _database_reachable() -> bool:
    """Fast, side-effect-free Postgres reachability probe.

    Uses ``DB_CONNECT_TIMEOUT`` so a degraded/absent DB fails fast instead of
    hanging. Shared by ``/health`` and the ``POST /runs`` guard so both agree on
    what "live" means (a 200 elsewhere is never treated as proof of a live DB).
    """
    try:
        with psycopg.connect(
            postgres_conninfo(), connect_timeout=db_connect_timeout()
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception:
        return False


@app.get("/health")
def health(response: Response) -> dict:
    """Liveness plus a quick Postgres reachability probe. Never runs the engine.

    ``status`` reflects ``database``: if the DB probe fails the top-level status
    is ``"degraded"`` (never ``"ok"``) and the HTTP code is 503, so both the body
    and the HTTP layer tell the truth to load balancers / liveness probes.

    ``database_target`` exposes host/port/database for debugging — never passwords.
    """
    target = postgres_target_info()
    database = "ok" if _database_reachable() else "unreachable"

    body = {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "database_target": target,
    }
    if database == "ok":
        return body
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return body


@app.get("/runs")
def list_runs() -> dict:
    """List validation runs from SQLite app state only (sparse-but-real)."""
    try:
        return {"runs": list_validation_runs()}
    except ReportLoadError as exc:
        logger.warning("Invalid report while listing runs: %s: %s", exc.source, exc.reason)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_report_load_detail(exc),
        ) from None


@app.post("/runs")
def trigger_run(request: Optional[RunRequest] = None) -> dict:
    """Run a synchronous validation (~5s) and return the full report dict.

    API-layer live guard: this endpoint is structurally UNCALLABLE unless the
    database is actually reachable. A disabled UI button is only a suggestion;
    this server-side probe is the guarantee. A degraded DB is refused FAST (via
    ``DB_CONNECT_TIMEOUT``) with a clear 503 — the engine / DataLoader is never
    constructed, so a stale click, re-enabled button, or direct call cannot hang
    against a degraded backend.
    """
    if not _database_reachable():
        target = postgres_target_info()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "live_validation_unavailable",
                "message": (
                    "Live validation is unavailable: the database is unreachable. "
                    "The API refuses to run validation against a degraded backend "
                    "(verified snapshot mode). Start PostgreSQL and check /health."
                ),
                "database_target": target,
            },
        )

    global _last_report
    run_id = request.run_id if request is not None else "demo_run_001"
    report, session_schema = run_validation(run_id=run_id)
    report = attach_trust_narrative(report)
    _last_report = report
    persisted_run_id = report.get("run_id", run_id)
    save_validation_run(persisted_run_id, status="completed", mode="demo", session_schema=session_schema, dataset_config="olist")
    save_validation_report(persisted_run_id, report)
    return report

@app.get("/runs/{run_id}/silver-assessment")
def get_silver_assessment(run_id: str) -> dict:
    from src.app_state.store import get_validation_run
    from psycopg.rows import dict_row
    from psycopg import sql
    from src.config_loader import resolve_config_by_name

    run = get_validation_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")

    schema = run.get("session_schema")
    if not schema:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No session schema retained for this run."
        )

    config_name = run.get("dataset_config")
    if not config_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No dataset_config retained for this run."
        )

    cfg = resolve_config_by_name(config_name)
    if not cfg:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not resolve dataset config '{config_name}'."
        )

    unit_price_col = cfg.columns.unit_price
    quantity_col = cfg.columns.quantity
    primary_key_col = cfg.columns.primary_key
    product_id_col = cfg.columns.product_id
    price_ceiling = cfg.columns.price_ceiling
    excluded_reason = (
        f"{unit_price_col} > {price_ceiling}"
        if price_ceiling is not None
        else "Valid Bronze row is missing from Silver"
    )

    try:
        with psycopg.connect(postgres_conninfo(), connect_timeout=db_connect_timeout()) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))

                cur.execute("SELECT to_regclass('silver_row_assessment')")
                if cur.fetchone()["to_regclass"] is None:
                    raise HTTPException(
                        status_code=404,
                        detail="silver_row_assessment view not found in session schema."
                    )

                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        COALESCE(SUM(CASE WHEN is_valid AND is_in_silver THEN 1 ELSE 0 END), 0) as retained,
                        COALESCE(SUM(CASE WHEN NOT is_valid THEN 1 ELSE 0 END), 0) as invalid,
                        COALESCE(SUM(CASE WHEN is_valid AND NOT is_in_silver THEN 1 ELSE 0 END), 0) as excluded
                    FROM silver_row_assessment
                """)
                counts = cur.fetchone()

                query = f"""
                    SELECT *,
                    CASE
                        WHEN NOT is_valid THEN 'INVALID'
                        WHEN is_valid AND NOT is_in_silver THEN 'EXCLUDED'
                    END AS row_status,
                    CASE
                        WHEN {primary_key_col} IS NULL THEN '{primary_key_col} is null'
                        WHEN {product_id_col} IS NULL THEN '{product_id_col} is null'
                        WHEN {quantity_col} <= 0 AND {unit_price_col} <= 0 THEN '{quantity_col} <= 0 and {unit_price_col} <= 0'
                        WHEN {quantity_col} <= 0 THEN '{quantity_col} <= 0'
                        WHEN {unit_price_col} <= 0 THEN '{unit_price_col} <= 0'
                        WHEN is_valid AND NOT is_in_silver THEN '{excluded_reason}'
                    END AS reason
                    FROM silver_row_assessment
                    WHERE (NOT is_valid) OR (is_valid AND NOT is_in_silver)
                    LIMIT 20
                """
                cur.execute(query)
                flagged_rows = cur.fetchall()

                return {
                    "summary": counts,
                    "flagged_rows": flagged_rows
                }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to query silver_row_assessment: {e}")
        raise HTTPException(status_code=500, detail="Failed to query assessment view.")


@app.get("/reports/latest")
def latest_report() -> dict:
    """Return the most recent report (in-memory cache, else on-disk report.json)."""
    try:
        report = _load_latest_report()
    except ReportLoadError as exc:
        logger.warning("Invalid latest report: %s: %s", exc.source, exc.reason)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_report_load_detail(exc),
        ) from None
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="No report available yet. Trigger a run via POST /runs.",
        )
    return report


@app.get("/reports/{run_id}")
def report_by_id(run_id: str) -> dict:
    """Fetch a report by id from SQLite app state, else latest in-memory/disk."""
    try:
        stored = get_report_by_run_id(run_id)
    except ReportLoadError as exc:
        logger.warning("Invalid stored report: %s: %s", exc.source, exc.reason)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_report_load_detail(exc),
        ) from None
    if stored is not None:
        return stored

    try:
        report = _load_latest_report()
    except ReportLoadError as exc:
        logger.warning("Invalid fallback report: %s: %s", exc.source, exc.reason)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_report_load_detail(exc),
        ) from None
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="No report available yet. Trigger a run via POST /runs.",
        )
    if report.get("run_id") != run_id:
        raise HTTPException(
            status_code=404,
            detail=f"Report '{run_id}' not found.",
        )
    return report


@app.get("/metadata/health")
def metadata_health(response: Response) -> dict:
    """Read-only metadata subsystem health (Postgres reachability)."""
    try:
        with psycopg.connect(postgres_conninfo(), connect_timeout=db_connect_timeout()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return {"status": "ok"}
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "detail": "Database unavailable"}


@app.get("/metadata")
def metadata_overview(
    schema: Optional[str] = None,
    table_name: Optional[str] = None,
    sample_limit: int = Query(5, ge=1, le=100),
) -> dict:
    """Read-only live metadata discovery (no DataLoader, no schema creation)."""
    try:
        return discover_live_metadata(
            schema=schema,
            table_name=table_name,
            sample_limit=sample_limit,
        )
    except psycopg.Error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Metadata discovery failed",
        ) from None


@app.get("/metadata/tables")
def metadata_tables(schema: Optional[str] = None) -> dict:
    """Lightweight live table list (no column profiling or candidate keys)."""
    try:
        return discover_live_tables_lightweight(schema=schema)
    except psycopg.Error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Metadata discovery failed",
        ) from None


@app.get("/metadata/tables/{table_name}")
def metadata_table_detail(
    table_name: str,
    schema: Optional[str] = None,
    sample_limit: int = Query(5, ge=1, le=100),
) -> dict:
    """Read-only full metadata for one live table."""
    try:
        return discover_live_table_detail(
            table_name=table_name,
            schema=schema,
            sample_limit=sample_limit,
        )
    except AmbiguousTableError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Table '{table_name}' not found.",
        ) from None
    except psycopg.Error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Metadata discovery failed",
        ) from None


@app.post("/metadata/demo-session")
def metadata_demo_session(
    sample_limit: int = Query(5, ge=1, le=100),
) -> dict:
    """Side-effectful demo metadata: materializes DataLoader session, then cleans up."""
    try:
        return discover_demo_session_metadata(sample_limit=sample_limit)
    except psycopg.Error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from None
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo data files are missing. Run python src/generate_data.py first.",
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Metadata discovery failed",
        ) from None
