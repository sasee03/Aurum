"""Pipeline failure summary handler."""

from __future__ import annotations

from typing import Any, Optional

from api.aurum_assistant.context import fallback_response, format_response, load_latest_report


def handle(
    question: str,
    page: str = "failure",
    layer: Optional[str] = None,
    context: Optional[dict] = None,
) -> dict:
    report = load_latest_report()
    if report is None:
        return fallback_response(
            "I could not find the latest report context. Please run the pipeline once and try again.",
            ["Run validation pipeline", "Check report.json availability"],
        )

    layer_status = report.get("layer_status", {})
    first_failed = report.get("first_failed_layer", "Unknown")
    severity = report.get("severity", "HIGH")
    root_cause = report.get("root_cause", {})
    business_impact = report.get("business_impact", {})
    suggested_action = report.get("suggested_action", "")

    failed_stage = first_failed or "Unknown stage"
    for name, status in layer_status.items():
        if status == "FAIL":
            failed_stage = f"{name.capitalize()} validation"
            break

    root_summary = root_cause.get("summary", "Root cause not specified in report.")
    impact_detail = business_impact.get("detail", "Business impact details unavailable.")
    loss = business_impact.get("estimated_loss")

    answer_parts = [
        f"The pipeline failed at the {failed_stage} stage.",
        root_summary,
    ]
    if loss is not None:
        answer_parts.append(f"Business impact: estimated loss {loss:,.2f}.")
    else:
        answer_parts.append(impact_detail)
    answer_parts.append("This should be reviewed by the data engineering team.")
    if suggested_action:
        answer_parts.append(f"The next action is: {suggested_action}")

    return format_response(
        "failure_summary",
        " ".join(answer_parts),
        data={
            "suggested_actions": [
                suggested_action or "Review failed checks in the validation report",
                "Assign owner: data engineering team",
                "Rerun pipeline after fix",
            ],
            "table": [
                {"field": "Failed stage", "value": failed_stage},
                {"field": "Severity", "value": severity},
                {"field": "Root cause", "value": root_summary},
                {"field": "Suggested owner", "value": "Data engineering team"},
                {"field": "Next action", "value": suggested_action or "Investigate and fix"},
            ],
        },
        confidence="high",
    )
