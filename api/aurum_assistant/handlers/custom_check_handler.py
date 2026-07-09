"""Custom validation check builder handler."""

from __future__ import annotations

import re
from typing import Any, Optional

from api.aurum_assistant.context import format_response, load_custom_checks
from src.config_loader import load_dataset_config


RULE_TYPES = (
    "not_null",
    "unique",
    "accepted_values",
    "numeric_range",
    "row_count_condition",
    "custom_sql_demo",
)

def _layer_defaults() -> dict[str, dict]:
    cfg = load_dataset_config()
    pk = cfg.columns.primary_key
    return {
        "silver": {
            "check_name": "Discounted orders should not be removed",
            "rule_type": "row_count_condition",
            "column": "discount_applied",
            "operator": ">",
            "value": "0",
            "severity": "high",
            "description": "Ensures discounted orders are still present after Silver transformation.",
        },
        "bronze": {
            "check_name": "Bronze mandatory columns not null",
            "rule_type": "not_null",
            "column": pk,
            "operator": "is",
            "value": "not null",
            "severity": "high",
            "description": f"Ensures {pk} is populated in Bronze.",
        },
        "gold": {
            "check_name": "Revenue should not be negative",
            "rule_type": "numeric_range",
            "column": "total_revenue",
            "operator": ">=",
            "value": "0",
            "severity": "high",
            "description": "Ensures Gold total_revenue is non-negative.",
        },
    }


def _infer_layer(question: str, page: str, layer: Optional[str]) -> str:
    q = question.lower()
    if layer:
        return layer.lower()
    if page in ("bronze", "silver", "gold"):
        return page
    for name in ("silver", "bronze", "gold"):
        if name in q:
            return name
    return "silver"


def handle(
    question: str,
    page: str = "custom_checks",
    layer: Optional[str] = None,
    context: Optional[dict] = None,
) -> dict:
    target_layer = _infer_layer(question, page, layer)
    defaults = _layer_defaults()
    template = defaults.get(target_layer, defaults["silver"])
    existing = load_custom_checks()
    layer_checks = [c for c in existing if c.get("layer") == target_layer]

    answer = (
        f"I can help you add a custom {target_layer.capitalize()} validation check. "
        "Data engineers can add domain-specific validation rules instead of relying only on fixed checks. "
        "Use the form on the Custom Checks page to configure layer, rule type, column, and severity, "
        "then Save Check and Test Check. Non-SQL checks currently run against the Olist demo "
        "validation session; uploaded and connector-run scoped checks are coming soon. "
        "SQL-based checks are not yet supported."
    )

    if "negative" in question.lower() and "revenue" in question.lower():
        template = defaults["gold"].copy()
        target_layer = "gold"

    return format_response(
        "custom_check_builder",
        answer,
        data={
            "custom_check": {
                **template,
                "layer": target_layer,
                "existing_count": len(layer_checks),
                "supported_rule_types": list(RULE_TYPES),
            },
            "suggested_actions": [
                "Open Custom Checks page",
                f"Configure a {target_layer} rule",
                "Save Check",
                "Test Check",
            ],
        },
        confidence="high",
    )


def next_check_id(layer: str, checks: list[dict]) -> str:
    prefix = f"custom_{layer}_"
    nums = []
    for c in checks:
        cid = c.get("check_id", "")
        m = re.match(rf"{re.escape(prefix)}(\d+)$", cid)
        if m:
            nums.append(int(m.group(1)))
    n = max(nums, default=0) + 1
    return f"{prefix}{n:03d}"
