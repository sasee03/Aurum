"""Dataset upload endpoints — user CSV ingestion (Phase 2 Unit 1)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

import api.main as api_main
from src.app_state.store import save_validation_report, save_validation_run
from src.csv_ingest import (
    RAW_ORDERS_COLUMNS,
    CsvSchemaMismatch,
    parse_raw_orders_csv,
    run_validation_from_raw_orders,
)
from src.db_config import postgres_target_info
from src.report_builder import attach_trust_narrative

router = APIRouter(tags=["datasets"])


@router.post("/datasets/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    project_id: str = Form(default=""),
) -> dict:
    """Accept an Olist-shaped raw_orders CSV, validate, run engine, return 17-key report."""
    if not api_main._database_reachable():
        target = postgres_target_info()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "live_validation_unavailable",
                "message": (
                    "CSV validation is unavailable: the database is unreachable. "
                    "Start PostgreSQL and check /health."
                ),
                "database_target": target,
            },
        )

    if not file.filename or not file.filename.lower().endswith(".csv"):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "schema_match": False,
                "error": "Only CSV uploads are supported.",
                "expected_columns": list(RAW_ORDERS_COLUMNS),
                "missing_columns": [],
            },
        )

    raw_bytes = await file.read()
    try:
        frame = parse_raw_orders_csv(raw_bytes)
    except CsvSchemaMismatch as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "schema_match": False,
                "error": exc.error,
                "expected_columns": exc.expected_columns,
                "missing_columns": exc.missing_columns,
            },
        )

    run_id = f"upload_{uuid.uuid4().hex[:12]}"
    report = attach_trust_narrative(run_validation_from_raw_orders(frame, run_id=run_id))
    persisted_run_id = report.get("run_id", run_id)
    save_validation_run(
        persisted_run_id,
        status="completed",
        mode="upload",
        project_id=project_id or None,
    )
    save_validation_report(persisted_run_id, report)
    return report
