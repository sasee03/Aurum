"""Aurum Assistant API router."""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.aurum_assistant.context import (
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
from api.aurum_assistant.handlers.custom_check_handler import next_check_id
from api.aurum_assistant.intent_router import detect_intent

router = APIRouter(tags=["aurum-assistant"])


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
    severity: Literal["low", "medium", "high"] = "medium"
    description: str = ""


class CustomCheckRunRequest(BaseModel):
    check_id: str


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
    return _dispatch_intent(intent, request)


@router.post("/assistant/chat")
def assistant_chat_alias(request: ChatRequest) -> dict:
    return aurum_assistant_chat(request)


@router.post("/custom-checks")
def create_custom_check(body: CustomCheckCreate) -> dict:
    checks = load_custom_checks()
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
    return {"checks": load_custom_checks()}


def _preview_run(check: dict) -> dict:
    """Demo preview — does not replace the validation engine."""
    rule_type = check.get("rule_type", "")
    column = check.get("column", "")
    operator = check.get("operator", "")
    value = check.get("value", "")
    layer = check.get("layer", "silver")

    if rule_type == "row_count_condition":
        observed = 1240
        passed = observed > 0 if operator == ">" and str(value) == "0" else True
        return {
            "check_id": check["check_id"],
            "status": "PASS" if passed else "FAIL",
            "message": f"Row count condition on {column} satisfied for {layer} layer (demo preview — not yet connected to validation engine).",
            "observed_value": observed,
            "expected_condition": f"{column} count {operator} {value}",
        }
    if rule_type == "not_null":
        return {
            "check_id": check["check_id"],
            "status": "PASS",
            "message": f"No null values found in {column} (demo preview).",
            "observed_value": 0,
            "expected_condition": f"{column} is not null",
        }
    if rule_type == "numeric_range":
        return {
            "check_id": check["check_id"],
            "status": "PASS",
            "message": f"{column} values within expected range (demo preview).",
            "observed_value": 0,
            "expected_condition": f"{column} {operator} {value}",
        }
    return {
        "check_id": check["check_id"],
        "status": "PASS",
        "message": f"Custom rule '{check.get('check_name')}' preview completed (demo).",
        "observed_value": "demo",
        "expected_condition": f"{rule_type} on {column}",
    }


@router.post("/custom-checks/run")
def run_custom_check(body: CustomCheckRunRequest) -> dict:
    checks = load_custom_checks()
    matched = next((c for c in checks if c.get("check_id") == body.check_id), None)
    if matched is None:
        return {
            "check_id": body.check_id,
            "status": "SKIPPED",
            "message": f"Check '{body.check_id}' not found.",
            "observed_value": None,
            "expected_condition": "",
        }
    return _preview_run(matched)
