"""Dataset upload endpoints — user CSV ingestion (Phase 2 Unit 1)."""

from __future__ import annotations

import uuid
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

import api.main as api_main
from src.app_state.store import save_validation_report, save_validation_run
from src.config_loader import ConfigResolutionError, resolve_config_for_project_or_table
from src.csv_ingest import (
    RAW_ORDERS_COLUMNS,
    CsvSchemaMismatch,
    parse_raw_orders_csv,
    run_validation_from_raw_orders,
)
import src.csv_ingest as csv_ingest
from src.db_config import postgres_target_info
from src.report_builder import attach_trust_narrative

router = APIRouter(tags=["datasets"])
logger = logging.getLogger(__name__)

_READ_CHUNK_BYTES = 1024 * 1024


def _config_resolution_response(
    exc: ConfigResolutionError,
    project_id: str,
) -> JSONResponse:
    if exc.code == "project_not_found":
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "Project not found", "project_id": project_id},
        )
    status_code = (
        status.HTTP_500_INTERNAL_SERVER_ERROR
        if exc.code in {"project_store_lookup_failed", "dataset_config_lookup_failed"}
        else status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    return JSONResponse(
        status_code=status_code,
        content={"error": exc.code, "message": str(exc)},
    )


async def _read_upload_bytes_capped(file: UploadFile) -> bytes:
    """Read upload body in chunks; reject before buffering more than MAX_UPLOAD_BYTES."""
    limit = csv_ingest.MAX_UPLOAD_BYTES
    if file.size is not None and file.size > limit:
        raise csv_ingest._schema_error(
            f"file exceeds maximum size of {csv_ingest._format_byte_limit(limit)}"
        )

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise csv_ingest._schema_error(
                f"file exceeds maximum size of {csv_ingest._format_byte_limit(limit)}"
            )
        chunks.append(chunk)
    return b"".join(chunks)


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

    try:
        cfg = resolve_config_for_project_or_table(project_id or None, file.filename)
    except ConfigResolutionError as exc:
        return _config_resolution_response(exc, project_id)

    try:
        raw_bytes = await _read_upload_bytes_capped(file)
        frame = parse_raw_orders_csv(raw_bytes, cfg=cfg)
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
    try:
        report, session_schema = run_validation_from_raw_orders(frame, run_id=run_id, cfg=cfg)
        report = attach_trust_narrative(report)
        persisted_run_id = report.get("run_id", run_id)
        save_validation_run(
            persisted_run_id,
            status="completed",
            mode="upload",
            project_id=project_id or None,
            display_name=file.filename,
            session_schema=session_schema,
            dataset_config=cfg.config_name,
        )
        save_validation_report(persisted_run_id, report)
    except Exception:  # noqa: BLE001
        logger.exception("CSV upload parsed but validation execution failed")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "upload_validation_failed",
                "message": (
                    "CSV upload parsed successfully, but Aurum could not complete "
                    "validation. No report was persisted for this upload."
                ),
            },
        )
    return report
