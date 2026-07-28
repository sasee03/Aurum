"""Read-only Gemini conversation endpoint backed by deterministic Aurum context."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from src.assistant_context import build_assistant_context
from src.assistant_gemini import (
    AssistantGeminiResponse,
    AssistantGeminiResponseInvalid,
    AssistantGeminiUnavailable,
    configured_assistant_gemini_model,
    explain_with_gemini,
)


router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])

_SQL_STATEMENT = re.compile(
    r"\b(?:select|insert|update|delete|create|drop|alter|truncate|merge)\s+",
    re.IGNORECASE,
)


class AssistantChatRequest(BaseModel):
    """Only UI identifiers; all pipeline facts are resolved by the backend."""

    model_config = ConfigDict(extra="forbid", strict=True)

    message: StrictStr = Field(min_length=1, max_length=4000)
    run_id: Optional[StrictStr] = Field(default=None, min_length=1, max_length=200)


def _context_value(context: Any, path: str) -> tuple[bool, Any]:
    """Resolve a dot path against server-built context, never client data."""
    current = context
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return current is not None, current


def _is_grounded(response: AssistantGeminiResponse, context: dict[str, Any]) -> bool:
    """Require provider-cited values to exactly match deterministic context."""
    if (
        response.disposition != "ANSWERED"
        or not response.evidence
        or _SQL_STATEMENT.search(response.answer)
    ):
        return False
    for item in response.evidence:
        found, actual = _context_value(context, item.path)
        if not found or actual != item.value:
            return False
        if isinstance(actual, (str, int, float, bool)) and str(actual).lower() not in response.answer.lower():
            return False
    return True


def _server_evidence(
    response: AssistantGeminiResponse, context: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return values resolved from context, never provider-supplied values."""
    return [
        {"path": item.path, "value": _context_value(context, item.path)[1]}
        for item in response.evidence
    ]


def _context_indicators(context: dict[str, Any]) -> dict[str, Any]:
    """Small non-secret provenance indicators for a client response."""
    run = context.get("run") if isinstance(context.get("run"), dict) else {}
    source = context.get("source") if isinstance(context.get("source"), dict) else {}
    gold = context.get("gold") if isinstance(context.get("gold"), dict) else {}
    return {
        "run_id": run.get("id"),
        "source": {"schema": source.get("schema"), "relation": source.get("relation")},
        "gold_status": gold.get("status"),
    }


def _insufficient_response(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "answer": "I do not have enough information in the current Aurum context to answer that.",
        "grounded": False,
        "status": "insufficient_information",
        "context": _context_indicators(context),
    }


def _readonly_response(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "answer": (
            "I can explain the current Aurum pipeline, but this assistant is read-only "
            "and cannot execute SQL, change pipeline state, approve, execute, or promote Gold."
        ),
        "grounded": False,
        "status": "read_only_refusal",
        "context": _context_indicators(context),
    }


@router.post("/chat")
def assistant_chat(request: AssistantChatRequest) -> Dict[str, Any]:
    """Explain server-built context without accepting frontend factual values."""
    context = build_assistant_context(run_id=request.run_id)
    try:
        response = explain_with_gemini(
            message=request.message,
            context=context,
            model=configured_assistant_gemini_model(),
        )
    except AssistantGeminiUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ASSISTANT_GEMINI_UNAVAILABLE",
        ) from None
    except AssistantGeminiResponseInvalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ASSISTANT_GEMINI_RESPONSE_INVALID",
        ) from None

    if response.disposition == "READ_ONLY_REFUSAL":
        return _readonly_response(context)
    if response.disposition == "INSUFFICIENT_INFORMATION" or not _is_grounded(response, context):
        return _insufficient_response(context)
    return {
        "answer": response.answer,
        "grounded": True,
        "status": "answered",
        "evidence": _server_evidence(response, context),
        "context": _context_indicators(context),
    }
