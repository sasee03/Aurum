"""Read-only Gemini conversation endpoint backed by deterministic Aurum context."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from src.assistant_context import build_assistant_context
from src.assistant_gemini import (
    AssistantGeminiResponseInvalid,
    AssistantGeminiUnavailable,
    configured_assistant_gemini_model,
    explain_with_gemini,
)


router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


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


def _available_fact_paths(context: Any, prefix: str = "") -> List[str]:
    """Return non-null context paths Gemini may select; no values are trusted back."""
    if not isinstance(context, dict):
        return []
    paths: List[str] = []
    for key, value in context.items():
        path = f"{prefix}.{key}" if prefix else key
        if value is None:
            continue
        paths.append(path)
        if isinstance(value, dict):
            paths.extend(_available_fact_paths(value, path))
    return paths


def _server_facts(fact_paths: List[str], context: dict[str, Any]) -> List[Dict[str, Any]]:
    """Resolve selected paths from server context, rejecting unknown values."""
    facts: List[Dict[str, Any]] = []
    for path in fact_paths:
        found, value = _context_value(context, path)
        if not found:
            return []
        facts.append({"path": path, "value": value})
    return facts


def _fact_label(path: str) -> str:
    return path.replace("_", " ").replace(".", " ").capitalize()


def _render_factual_answer(facts: List[Dict[str, Any]]) -> str:
    """Render only server-resolved values; Gemini prose is never returned."""
    lines = []
    for fact in facts:
        value = fact["value"]
        rendered = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
        lines.append(f"- {_fact_label(fact['path'])}: {rendered}.")
    return "Verified Aurum facts:\n" + "\n".join(lines)


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
    available_fact_paths = _available_fact_paths(context)
    try:
        response = explain_with_gemini(
            message=request.message,
            context=context,
            available_fact_paths=available_fact_paths,
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
    if response.disposition == "INSUFFICIENT_INFORMATION":
        return _insufficient_response(context)
    facts = _server_facts(response.fact_paths, context)
    if not facts:
        return _insufficient_response(context)
    return {
        "answer": _render_factual_answer(facts),
        "grounded": True,
        "status": "answered",
        "evidence": facts,
        "context": _context_indicators(context),
    }
