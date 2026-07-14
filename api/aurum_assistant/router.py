"""Aurum Assistant API router."""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from api.aurum_assistant.context import (
    CustomCheckConfigError,
    load_custom_checks,
    save_custom_checks,
)
from api.aurum_assistant.handlers import (
    custom_check_handler,
    email_draft_handler,
    failure_summary_handler,
    history_handler,
    sample_query_handler,
    schema_issue_explainer,
    validation_explainer,
)
from fastapi import File, Form, UploadFile

from api.aurum_assistant.handlers.custom_check_handler import next_check_id
from api.aurum_assistant.intent_router import detect_intent
from src.custom_checks import (
    DEMO_DATA_SOURCE,
    build_run_scoped_data_source,
    execute_custom_check,
    execute_custom_check_against_frame,
    run_info_for_check,
)
from src.report_safety import ReportLoadError

router = APIRouter(tags=["aurum-assistant"])


def _custom_checks_load_error(exc: CustomCheckConfigError) -> dict:
    return {
        "error": "custom_checks_invalid",
        "message": "This check configuration is invalid and could not be loaded.",
        "reason": exc.reason,
    }


def _report_load_error(exc: ReportLoadError) -> dict:
    return {
        "error": "report_load_failed",
        "message": "This report could not be loaded because the stored report data is invalid.",
        "source": exc.source,
        "reason": exc.reason,
    }


def _load_custom_checks_or_422() -> list[dict]:
    try:
        return load_custom_checks()
    except CustomCheckConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_custom_checks_load_error(exc),
        ) from None


class ChatContext(BaseModel):
    selected_check_id: Optional[str] = None
    selected_table: Optional[str] = None


class ChatRequest(BaseModel):
    page: Literal[
        "dashboard",
        "validation",
        "history",
        "query",
        "custom_checks",
        "failure",
        "bronze",
        "silver",
        "gold",
    ] = "validation"
    run_id: str = "latest"
    layer: Optional[Literal["bronze", "silver", "gold"]] = None
    question: str
    context: ChatContext = Field(default_factory=ChatContext)


class CustomCheckCreate(BaseModel):
    layer: Literal["bronze", "silver", "gold"]
    check_name: str
    rule_type: Literal[
        "not_null",
        "unique",
        "accepted_values",
        "numeric_range",
        "row_count_condition",
        "custom_sql_demo",
    ]
    column: str
    operator: str
    value: Union[str, int, float]
    severity: Literal["low", "medium", "high", "INFORMATIONAL", "WARNING", "BLOCKING"] = "WARNING"
    description: str = ""

    @classmethod
    def __get_validators__(cls):
        yield cls.validate_severity

    @classmethod
    def validate_severity(cls, v):
        if hasattr(v, "severity"):
            val = v.severity
            mapping = {"low": "INFORMATIONAL", "medium": "WARNING", "high": "BLOCKING"}
            if isinstance(val, str) and val.lower() in mapping:
                v.severity = mapping[val.lower()]
        return v


class CustomCheckRunRequest(BaseModel):
    check_id: str
    run_id: Optional[str] = None
    connection_id: Optional[str] = None  # required when targeting a connector run


def _dispatch_intent(intent: str, request: ChatRequest) -> dict:
    kwargs = {
        "question": request.question,
        "page": request.page,
        "layer": request.layer,
        "context": request.context.model_dump(),
        "run_id": request.run_id,
    }
    handlers = {
        "validation_explanation": validation_explainer.handle,
        "primary_key_explanation": schema_issue_explainer.handle_primary_key,
        "datetime_explanation": schema_issue_explainer.handle_datetime,
        "sample_revenue_query": sample_query_handler.handle,
        "history_explanation": history_handler.handle,
        "failure_summary": failure_summary_handler.handle,
        "email_draft": email_draft_handler.handle,
        "custom_check_builder": custom_check_handler.handle,
    }
    handler = handlers.get(intent, validation_explainer.handle)
    # Pass run_id only to handlers that accept it; others ignore extra kwargs via **kwargs
    import inspect
    sig = inspect.signature(handler)
    if "run_id" not in sig.parameters:
        kwargs.pop("run_id")
    return handler(**kwargs)


@router.post("/aurum-assistant/chat")
def aurum_assistant_chat(request: ChatRequest) -> dict:
    intent = detect_intent(request.question)
    try:
        return _dispatch_intent(intent, request)
    except CustomCheckConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_custom_checks_load_error(exc),
        ) from None
    except ReportLoadError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_report_load_error(exc),
        ) from None


@router.post("/assistant/chat")
def assistant_chat_alias(request: ChatRequest) -> dict:
    return aurum_assistant_chat(request)


@router.post("/custom-checks")
def create_custom_check(body: CustomCheckCreate) -> dict:
    checks = _load_custom_checks_or_422()
    check_id = next_check_id(body.layer, checks)
    record = {
        "check_id": check_id,
        **body.model_dump(),
        "value": str(body.value),
    }
    checks.append(record)
    save_custom_checks(checks)
    return {"status": "saved", "check_id": check_id}


@router.get("/custom-checks")
def list_custom_checks() -> dict:
    return {"checks": _load_custom_checks_or_422()}


@router.post("/custom-checks/run")
def run_custom_check(body: CustomCheckRunRequest) -> dict:
    """Execute a saved custom check.

    With no run_id: runs against the Olist demo session (existing behaviour).
    With run_id + mode="connector": requires a live connection_id session for the
      connector source; returns honest SKIPPED if the session has expired.
    With run_id + mode="upload": returns SKIPPED with instructions to re-supply the
      file via POST /custom-checks/run-with-file — upload data is not persisted.

    Results are additive only — never modify trust_score, final_verdict, or
    layer_status.
    """
    checks = _load_custom_checks_or_422()
    matched = next(
        (
            c
            for c in checks
            if isinstance(c, dict) and c.get("check_id") == body.check_id
        ),
        None,
    )
    if matched is None:
        return {
            "check_id": body.check_id,
            "status": "SKIPPED",
            "message": f"Check '{body.check_id}' not found.",
            "observed_value": None,
            "expected_condition": "",
        }

    # No run_id → demo session (unchanged behaviour).
    if not body.run_id:
        return execute_custom_check(matched)

    # Resolve the run.
    run = run_info_for_check(body.run_id)
    if run is None:
        return {
            "check_id": body.check_id,
            "status": "SKIPPED",
            "message": (
                f"Run '{body.run_id}' not found in history. "
                "Trigger a new validation run first."
            ),
            "observed_value": None,
            "expected_condition": "",
            "data_source": "unavailable",
            "scope_note": "No run record found.",
        }

    mode = run.get("mode", "")
    data_source = build_run_scoped_data_source(run)

    if mode == "upload":
        # Upload data is not persisted — the caller must re-supply the file.
        return {
            "check_id": body.check_id,
            "status": "SKIPPED",
            "message": (
                "Original upload data for this run is not persisted. "
                "Use 'Test against upload file' and re-select the CSV "
                "to run this check against the same data."
            ),
            "observed_value": None,
            "expected_condition": "",
            "data_source": data_source,
            "scope_note": (
                "Upload files are processed in-memory and not stored. "
                "Re-upload the file to test custom checks against it."
            ),
        }

    if mode == "connector":
        from src.postgres_connector import (
            get_session_connection,
            load_and_validate_user_table,
        )
        from src.app_state.store import get_data_connection as _get_conn

        # Prefer explicitly supplied connection_id, fall back to the run's own.
        connection_id = body.connection_id or run.get("connection_id") or ""
        if not connection_id:
            return {
                "check_id": body.check_id,
                "status": "SKIPPED",
                "message": (
                    "No connection_id for this connector run. "
                    "Re-test the connection via the Connectors page to create a session, "
                    "then include connection_id in this request."
                ),
                "observed_value": None,
                "expected_condition": "",
                "data_source": data_source,
                "scope_note": (
                    "Connector passwords are not persisted. "
                    "Re-authenticate to run checks against this data."
                ),
            }

        session = get_session_connection(connection_id)
        if session is None:
            return {
                "check_id": body.check_id,
                "status": "SKIPPED",
                "message": (
                    "Connector session has expired or is unknown. "
                    "Re-test the connection on the Connectors page (password required), "
                    "then supply the new connection_id."
                ),
                "observed_value": None,
                "expected_condition": "",
                "data_source": data_source,
                "scope_note": (
                    "Connector session TTL is 30 minutes. "
                    "Re-authenticate to run checks against this data."
                ),
            }

        # Look up which table was used for this run.
        conn_meta = _get_conn(connection_id) or _get_conn(run.get("connection_id") or "")
        if conn_meta is None:
            return {
                "check_id": body.check_id,
                "status": "SKIPPED",
                "message": (
                    "Connection metadata not found for this connector run. "
                    "Re-test the connection via the Connectors page."
                ),
                "observed_value": None,
                "expected_condition": "",
                "data_source": data_source,
                "scope_note": "Cannot load data without connection metadata.",
            }

        # Re-fetch the layer table from the live connector using coordinates
        # stored on validation_runs (not inside the 17-key report).
        layer = str(matched.get("layer", "silver")).strip().lower()
        source_schema = run.get("source_schema")
        source_table = run.get("source_table")

        if not source_table:
            return {
                "check_id": body.check_id,
                "status": "SKIPPED",
                "message": (
                    "The original source table for this connector run is not recorded. "
                    "Re-run validation via the Connectors page to re-establish the link."
                ),
                "observed_value": None,
                "expected_condition": "",
                "data_source": data_source,
                "scope_note": "Source table metadata not found on the run record.",
            }

        try:
            raw_frame = load_and_validate_user_table(
                session,
                schema=source_schema or "public",
                table=source_table,
            )
            # Build layer frames from the raw frame, then pick the right one.
            layer_df = _build_layer_frame(raw_frame, layer)
        except Exception as exc:  # noqa: BLE001
            return {
                "check_id": body.check_id,
                "status": "SKIPPED",
                "message": (
                    f"Could not re-load data from connector: {exc}. "
                    "Check the connection is still reachable."
                ),
                "observed_value": None,
                "expected_condition": "",
                "data_source": data_source,
                "scope_note": "Live re-fetch from connector failed.",
            }

        return execute_custom_check_against_frame(matched, layer_df, data_source)

    # Demo / live runs — fall through to demo session.
    return execute_custom_check(matched)


def _build_layer_frame(raw_frame, layer: str):
    """Thin wrapper — delegates to src.custom_checks so tests can monkeypatch it."""
    from src.custom_checks import build_layer_frame_from_raw

    return build_layer_frame_from_raw(raw_frame, layer)


@router.post("/custom-checks/run-with-file")
async def run_custom_check_with_file(
    check_id: str = Form(...),
    run_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    """Execute a custom check against a re-uploaded CSV for a prior upload run.

    The file is parsed in-memory and never saved. File content identity is NOT
    verified against the original upload (bytes were never persisted) — every
    response includes an honest scope_note stating this. run_id MUST exist and
    have mode="upload"; otherwise the check is SKIPPED.
    Results are additive — never modify trust_score, final_verdict, or layer_status.
    """
    from src.csv_ingest import (
        CsvSchemaMismatch,
        MAX_UPLOAD_BYTES,
        _format_byte_limit,
        parse_raw_orders_csv,
    )

    FILE_IDENTITY_SCOPE_NOTE = (
        "File identity is not verified — this checks whatever file you attach, "
        "not necessarily the original upload. Ensure you're re-uploading the same "
        "file used in the original run."
    )

    checks = _load_custom_checks_or_422()
    matched = next(
        (c for c in checks if isinstance(c, dict) and c.get("check_id") == check_id),
        None,
    )
    if matched is None:
        return {
            "check_id": check_id,
            "status": "SKIPPED",
            "message": f"Check '{check_id}' not found.",
            "observed_value": None,
            "expected_condition": "",
            "scope_note": FILE_IDENTITY_SCOPE_NOTE,
        }

    # Identity gate: run must exist and be an upload run.
    run = run_info_for_check(run_id)
    if run is None:
        return {
            "check_id": check_id,
            "status": "SKIPPED",
            "message": (
                f"Run '{run_id}' not found in history. "
                "Upload a CSV via Datasets first, then re-test against that run."
            ),
            "observed_value": None,
            "expected_condition": "",
            "data_source": "unavailable",
            "scope_note": FILE_IDENTITY_SCOPE_NOTE,
        }
    if run.get("mode") != "upload":
        return {
            "check_id": check_id,
            "status": "SKIPPED",
            "message": (
                f"Run '{run_id}' has mode '{run.get('mode')}', not 'upload'. "
                "Use POST /custom-checks/run-with-file only for upload runs."
            ),
            "observed_value": None,
            "expected_condition": "",
            "data_source": build_run_scoped_data_source(run),
            "scope_note": FILE_IDENTITY_SCOPE_NOTE,
        }

    if not file.filename or not file.filename.lower().endswith(".csv"):
        return {
            "check_id": check_id,
            "status": "SKIPPED",
            "message": "Only CSV files are supported.",
            "observed_value": None,
            "expected_condition": "",
            "data_source": f"file upload for run {run_id}",
            "scope_note": FILE_IDENTITY_SCOPE_NOTE,
        }

    # Stream-read with the same cap as the upload endpoint.
    limit = MAX_UPLOAD_BYTES
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            return {
                "check_id": check_id,
                "status": "SKIPPED",
                "message": (
                    f"File exceeds maximum size of {_format_byte_limit(limit)}. "
                    "Cannot run check."
                ),
                "observed_value": None,
                "expected_condition": "",
                "data_source": f"file upload for run {run_id}",
                "scope_note": FILE_IDENTITY_SCOPE_NOTE,
            }
        chunks.append(chunk)
    raw_bytes = b"".join(chunks)

    try:
        raw_frame = parse_raw_orders_csv(raw_bytes)
    except CsvSchemaMismatch as exc:
        return {
            "check_id": check_id,
            "status": "SKIPPED",
            "message": f"File does not match expected schema: {exc.error}",
            "observed_value": None,
            "expected_condition": "",
            "data_source": f"file upload for run {run_id}",
            "scope_note": FILE_IDENTITY_SCOPE_NOTE,
        }

    layer = str(matched.get("layer", "silver")).strip().lower()
    data_source = f"Uploaded file: {file.filename} (run {run_id})"

    try:
        layer_df = _build_layer_frame(raw_frame, layer)
    except Exception as exc:  # noqa: BLE001
        return {
            "check_id": check_id,
            "status": "SKIPPED",
            "message": f"Could not build layer data from uploaded file: {exc}",
            "observed_value": None,
            "expected_condition": "",
            "data_source": data_source,
            "scope_note": (
                f"{FILE_IDENTITY_SCOPE_NOTE} "
                "Layer build requires the Aurum Postgres database to be reachable."
            ),
        }

    result = execute_custom_check_against_frame(matched, layer_df, data_source)
    result["scope_note"] = FILE_IDENTITY_SCOPE_NOTE
    return result
