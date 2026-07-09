"""Validation result explanation handler."""

from __future__ import annotations

from typing import Any, Optional

from api.aurum_assistant.context import fallback_response, format_response, load_latest_report, load_report_for_run


def _layer_from_context(page: str, layer: Optional[str]) -> Optional[str]:
    if layer:
        return layer.lower()
    if page in ("bronze", "silver", "gold"):
        return page
    return None


def _failed_checks_for_layer(report: dict, layer: str) -> list[dict]:
    checks = report.get("checks", {}).get(layer, [])
    return [c for c in checks if c.get("status") in ("FAIL", "WARN", "IMPACTED")]


def handle(
    question: str,
    page: str = "validation",
    layer: Optional[str] = None,
    run_id: str = "latest",
    context: Optional[dict] = None,
) -> dict:
    report = load_report_for_run(run_id)
    if report is None:
        return fallback_response(
            "I could not find the latest report context. Please run the pipeline once and try again.",
            ["Run validation pipeline", "Check report.json availability"],
        )

    target_layer = _layer_from_context(page, layer)
    layer_status = report.get("layer_status", {})
    final_verdict = report.get("final_verdict", "UNKNOWN")
    root_cause = report.get("root_cause", {})
    business_impact = report.get("business_impact", {})
    suggested_action = report.get("suggested_action", "")
    first_failed = report.get("first_failed_layer")
    coverage = report.get("coverage", {})
    verdict_caveat = coverage.get("verdict_caveat", "")

    ctx = context or {}
    selected_check_id = ctx.get("selected_check_id")

    parts: list[str] = []

    if target_layer:
        status = layer_status.get(target_layer, "UNKNOWN")
        layer_name = target_layer.capitalize()
        if status == "PASS":
            parts.append(f"{layer_name} passed validation in the latest report.")
        elif status == "FAIL":
            parts.append(
                f"{layer_name} failed because {root_cause.get('summary', 'validation checks did not pass')}."
            )
        elif status == "IMPACTED":
            parts.append(
                f"{layer_name} is impacted by an upstream failure. "
                f"{business_impact.get('detail', 'Downstream metrics may be incomplete.')}"
            )
        else:
            parts.append(f"{layer_name} status is {status}.")

        failed = _failed_checks_for_layer(report, target_layer)
        if selected_check_id:
            matched = [c for c in failed if c.get("check_id") == selected_check_id]
            if matched:
                parts.append(f"Check {selected_check_id}: {matched[0].get('detail', '')}")
        elif failed:
            top = failed[0]
            parts.append(
                f"Primary failed check: {top.get('check_id')} — {top.get('detail', '')}"
            )
    else:
        if "not trusted" in question.lower() or "verdict" in question.lower():
            parts.append(
                f"The final verdict is {final_verdict}. "
                f"{root_cause.get('summary', '')}"
            )
        elif "fix first" in question.lower() or "should i fix" in question.lower():
            parts.append(f"Start with: {suggested_action}")
        else:
            silver_status = layer_status.get("silver", "UNKNOWN")
            gold_status = layer_status.get("gold", "UNKNOWN")
            parts.append(
                f"Silver is {silver_status} and Gold is {gold_status}. "
                f"{root_cause.get('summary', '')}"
            )

    if first_failed:
        parts.append(f"First failed layer: {first_failed}.")

    if business_impact and business_impact.get("status") != "NOT_AVAILABLE":
        loss = business_impact.get("estimated_loss")
        if loss is not None:
            parts.append(
                f"Business impact: estimated loss of {loss:,.2f} "
                f"({business_impact.get('loss_percent', 0):.1f}% gap)."
            )

    if gold_status := layer_status.get("gold"):
        if gold_status == "IMPACTED" and "gold" in question.lower():
            parts.append(
                "Gold is impacted because it depends on Silver data that failed validation."
            )

    if verdict_caveat:
        parts.append(f"Note: {verdict_caveat}")

    if suggested_action:
        parts.append(f"Suggested action: {suggested_action}")

    answer = " ".join(parts)
    suggested_actions = [suggested_action] if suggested_action else []
    if first_failed:
        suggested_actions.append(f"Investigate {first_failed}")

    return format_response(
        "validation_explanation",
        answer,
        data={"suggested_actions": [a for a in suggested_actions if a]},
        confidence="high",
    )
