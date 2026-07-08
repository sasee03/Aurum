"""FastAPI transport layer for Aurum (Ring 3 — API only).

This is a thin HTTP layer over the existing engine. It performs NO reshaping:
every report is returned exactly as ``build_report()`` produces it (the 17
top-level keys and the ``CheckResult`` shape), so a React UI can call these
endpoints with no field remapping.

Run it (port 8000 avoids clashing with Streamlit's 8501):

    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import json
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
from src.app_state.store import (
    get_report_by_run_id,
    list_validation_runs,
    save_validation_report,
    save_validation_run,
)

from api.aurum_assistant.router import router as aurum_assistant_router
from api.projects_router import router as projects_router

REACT_DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app = FastAPI(title="Aurum API", version="1.0.0")

app.include_router(aurum_assistant_router)
app.include_router(projects_router)

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


class RunRequest(BaseModel):
    run_id: str = "demo_run_001"


def _load_latest_report() -> Optional[dict]:
    if _last_report is not None:
        return _last_report
    if REPORT_PATH.exists():
        return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    return None


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
    return {"runs": list_validation_runs()}


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
    report = attach_trust_narrative(run_validation(run_id=run_id))
    _last_report = report
    persisted_run_id = report.get("run_id", run_id)
    save_validation_run(persisted_run_id, status="completed", mode="live")
    save_validation_report(persisted_run_id, report)
    return report


@app.get("/reports/latest")
def latest_report() -> dict:
    """Return the most recent report (in-memory cache, else on-disk report.json)."""
    report = _load_latest_report()
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="No report available yet. Trigger a run via POST /runs.",
        )
    return report


@app.get("/reports/{run_id}")
def report_by_id(run_id: str) -> dict:
    """Fetch a report by id from SQLite app state, else latest in-memory/disk."""
    stored = get_report_by_run_id(run_id)
    if stored is not None:
        return stored

    report = _load_latest_report()
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
