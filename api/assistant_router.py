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


def _has_available_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return any(_has_available_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_available_value(item) for item in value)
    return True


def _available_fact_paths(context: Any, prefix: str = "") -> List[str]:
    """Return non-null context paths Gemini may select; no values are trusted back."""
    if not isinstance(context, dict):
        return []
    paths: List[str] = []
    for key, value in context.items():
        path = f"{prefix}.{key}" if prefix else key
        if not _has_available_value(value):
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
        if not found or not _has_available_value(value):
            return []
        facts.append({"path": path, "value": value})
    return facts


def _fact_label(path: str) -> str:
    return path.replace("_", " ").replace(".", " ").capitalize()


def _facts_by_path(facts: List[Dict[str, Any]]) -> dict[str, Any]:
    return {fact["path"]: fact["value"] for fact in facts}


def _format_relation(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    schema = value.get("schema")
    relation = value.get("relation") or value.get("table")
    if isinstance(schema, str) and isinstance(relation, str):
        return f"{schema}.{relation}"
    if isinstance(relation, str):
        return relation
    return None


def _format_scalar(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,}"
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value, sort_keys=True)


def _format_rule(rule: Any) -> str | None:
    if not isinstance(rule, dict):
        return None
    rule_type = rule.get("type") or rule.get("kind")
    if rule_type == "compare":
        column = rule.get("column")
        operator = rule.get("operator")
        value = rule.get("value")
        if isinstance(column, str) and isinstance(operator, str) and value is not None:
            return f"keep rows where {column} {operator} {_format_scalar(value)}"
    if rule_type == "distinct":
        return "remove duplicate rows"
    if rule_type == "filter":
        column = rule.get("column")
        if isinstance(column, str):
            return f"apply a filter on {column}"
    return json.dumps(rule, sort_keys=True)


def _format_rules(value: Any) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    rendered = [_format_rule(rule) for rule in value]
    rendered = [item for item in rendered if item]
    if not rendered:
        return None
    if len(rendered) == 1:
        return rendered[0]
    return ", ".join(rendered[:-1]) + f", and {rendered[-1]}"


def _render_human_summary(facts: List[Dict[str, Any]]) -> str | None:
    by_path = _facts_by_path(facts)
    sentences: list[str] = []

    source_relation = _format_relation(by_path.get("dataset.source"))
    if not source_relation:
        source_schema = by_path.get("source.schema")
        source_table = by_path.get("source.relation")
        if isinstance(source_schema, str) and isinstance(source_table, str):
            source_relation = f"{source_schema}.{source_table}"
    if source_relation:
        sentences.append(f"This dataset is currently represented by {source_relation}.")

    layers = by_path.get("dataset.available_layers")
    if isinstance(layers, list) and layers:
        layer_text = ", ".join(str(layer).title() for layer in layers)
        sentences.append(f"Aurum has grounded context for these layers: {layer_text}.")

    row_counts = by_path.get("dataset.row_counts")
    if isinstance(row_counts, dict):
        row_parts = [
            f"{layer} {_format_scalar(count)} rows"
            for layer, count in row_counts.items()
            if count is not None
        ]
        if row_parts:
            sentences.append("Current row counts are " + " and ".join(row_parts) + ".")

    layer_relations = by_path.get("dataset.layer_relations")
    bronze_relation = (
        _format_relation(layer_relations.get("bronze"))
        if isinstance(layer_relations, dict)
        else None
    )
    if not bronze_relation:
        bronze_schema = by_path.get("bronze.schema")
        bronze_table = by_path.get("bronze.relation")
        if isinstance(bronze_schema, str) and isinstance(bronze_table, str):
            bronze_relation = f"{bronze_schema}.{bronze_table}"
    if bronze_relation and bronze_relation != source_relation:
        sentences.append(f"The Bronze relation is {bronze_relation}.")

    rules = _format_rules(by_path.get("silver.transformation.rules"))
    if rules:
        sentences.append(f"Silver currently applies these transformation rules: {rules}.")

    silver_status = by_path.get("silver.validation_status")
    if isinstance(silver_status, str):
        sentences.append(f"Silver validation status is {silver_status}.")

    gold_status = by_path.get("gold.status")
    if isinstance(gold_status, str):
        sentences.append(f"Gold status is {gold_status}.")

    gold_target = _format_relation(by_path.get("gold.target"))
    if not gold_target and isinstance(layer_relations, dict):
        gold_target = _format_relation(layer_relations.get("gold"))
    if gold_target:
        sentences.append(f"The Gold target is {gold_target}.")

    root_cause = by_path.get("quality.root_cause")
    if isinstance(root_cause, dict) and isinstance(root_cause.get("summary"), str):
        sentences.append(f"Recorded root cause: {root_cause['summary']}")

    if sentences:
        return " ".join(sentences)
    return None


def _render_factual_answer(facts: List[Dict[str, Any]]) -> str:
    """Render only server-resolved values; Gemini prose is never returned."""
    summary = _render_human_summary(facts)
    if summary:
        return summary
    lines = []
    for fact in facts:
        value = fact["value"]
        rendered = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
        lines.append(f"- {_fact_label(fact['path'])}: {rendered}.")
    return "Verified Aurum facts:\n" + "\n".join(lines)


def _select_available(paths: List[str], requested: List[str]) -> List[str]:
    available = set(paths)
    return [path for path in requested if path in available]


def _looks_like_readonly_refusal(message: str) -> bool:
    lowered = message.lower()
    action_terms = (
        "approve",
        "promote",
        "execute",
        "delete",
        "drop",
        "insert",
        "update",
        "create",
        "modify",
        "run silver",
        "run gold",
        "reveal",
        "credential",
        "password",
        "api key",
        "token",
        "secret",
    )
    return any(term in lowered for term in action_terms)


def _fallback_fact_paths(message: str, available_fact_paths: List[str]) -> List[str]:
    lowered = message.lower()
    requested: list[str] = []
    wants_dataset = any(
        term in lowered
        for term in ("dataset", "table", "source", "what is this", "tell me about")
    )
    wants_bronze = any(term in lowered for term in ("bronze", "raw", "ingest"))
    wants_silver = any(
        term in lowered
        for term in ("silver", "clean", "rule", "filter", "duplicate", "record")
    )
    wants_gold = any(term in lowered for term in ("gold", "metric", "calculate", "target"))
    wants_quality = any(
        term in lowered
        for term in ("quality", "trust", "fail", "failure", "impact", "root cause", "summary")
    )
    wants_overview = not any((wants_bronze, wants_silver, wants_gold, wants_quality))

    if wants_dataset or wants_overview:
        requested.extend(
            [
                "dataset.source",
                "dataset.available_layers",
                "dataset.layer_relations",
                "dataset.row_counts",
                "source.schema",
                "source.relation",
            ]
        )
    if wants_bronze or wants_overview:
        requested.extend(
            [
                "bronze.schema",
                "bronze.relation",
                "bronze.authority_status",
                "bronze.row_count",
            ]
        )
    if wants_silver or wants_dataset or wants_overview:
        requested.extend(
            [
                "silver.validation_status",
                "silver.row_count",
                "silver.removed_count",
                "silver.transformation.summary",
                "silver.transformation.rules",
            ]
        )
    if wants_gold or wants_overview:
        requested.extend(["gold.status", "gold.business_requirement", "gold.target"])
    if wants_quality or wants_overview:
        requested.extend(["quality.layer_status", "quality.root_cause", "quality.failed_checks"])

    return _select_available(available_fact_paths, list(dict.fromkeys(requested)))


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
    effective_run_id = request.run_id
    if not effective_run_id:
        try:
            from src.app_state.db import get_readonly_connection
            with get_readonly_connection() as conn:
                row = conn.execute("SELECT run_id FROM generated_sql_review ORDER BY created_at DESC LIMIT 1").fetchone()
                if not row:
                    row = conn.execute("SELECT run_id FROM validation_runs ORDER BY started_at DESC LIMIT 1").fetchone()
                if row:
                    effective_run_id = row["run_id"]
        except Exception:
            effective_run_id = None
    context = build_assistant_context(run_id=effective_run_id)
    available_fact_paths = _available_fact_paths(context)
    try:
        response = explain_with_gemini(
            message=request.message,
            context=context,
            available_fact_paths=available_fact_paths,
            model=configured_assistant_gemini_model(),
        )
    except AssistantGeminiUnavailable:
        if _looks_like_readonly_refusal(request.message):
            return _readonly_response(context)
        fallback_paths = _fallback_fact_paths(request.message, available_fact_paths)
        facts = _server_facts(fallback_paths, context)
        if facts:
            return {
                "answer": _render_factual_answer(facts),
                "grounded": True,
                "status": "answered",
                "evidence": facts,
                "context": _context_indicators(context),
            }
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
