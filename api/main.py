"""FastAPI transport layer for Aurum (Ring 3 — API only).

This is a thin HTTP layer over the existing engine. It performs NO reshaping:
every report is returned exactly as ``build_report()`` produces it (the 14
top-level keys and the ``CheckResult`` shape), so the Streamlit UI can later
swap file-reads for API calls with no field remapping.

Run it (port 8000 avoids clashing with Streamlit's 8501):

    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import json
from typing import Optional

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.db_config import postgres_conninfo
from src.report_builder import REPORT_PATH
from src.run_demo import run_validation

app = FastAPI(title="Aurum API", version="1.0.0")

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


@app.get("/health")
def health() -> dict:
    """Liveness plus a quick Postgres reachability probe. Never runs the engine."""
    try:
        with psycopg.connect(postgres_conninfo(), connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        database = "ok"
    except Exception:
        database = "unreachable"
    return {"status": "ok", "database": database}


@app.post("/runs")
def trigger_run(request: Optional[RunRequest] = None) -> dict:
    """Run a synchronous validation (~5s) and return the full report dict."""
    global _last_report
    run_id = request.run_id if request is not None else "demo_run_001"
    report = run_validation(run_id=run_id)
    _last_report = report
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
    """Fetch a report by id.

    v1 limitation: there is no per-run persistence yet (that is Ring 5's Quality
    Store). Only the latest report is retrievable, so this returns it when the id
    matches and a clean 404 otherwise.
    """
    report = _load_latest_report()
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="No report available yet. Trigger a run via POST /runs.",
        )
    if report.get("run_id") != run_id:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Report '{run_id}' not found. Per-run history arrives in Ring 5; "
                "only the latest run is currently retrievable."
            ),
        )
    return report
