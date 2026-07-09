"""Stakeholder email draft handler (draft only — no sending)."""

from __future__ import annotations

from typing import Any, Optional

from api.aurum_assistant.context import fallback_response, format_response, load_latest_report, load_report_for_run


def handle(
    question: str,
    page: str = "failure",
    layer: Optional[str] = None,
    context: Optional[dict] = None,
    run_id: str = "latest",
) -> dict:
    report = load_report_for_run(run_id)
    if report is None:
        return fallback_response(
            "I could not find the latest report context. Please run the pipeline once and try again.",
            ["Run validation pipeline"],
        )

    layer_status = report.get("layer_status", {})
    root_cause = report.get("root_cause", {})
    business_impact = report.get("business_impact", {})
    suggested_action = report.get("suggested_action", "")
    final_verdict = report.get("final_verdict", "NOT TRUSTED")

    failed_layer = "Silver"
    for name, status in layer_status.items():
        if status == "FAIL":
            failed_layer = name.capitalize()
            break

    subject = f"Aurum Alert: {failed_layer} Layer Validation Failure Impacting Gold Revenue"
    root_text = root_cause.get("summary", "A validation issue was detected.")
    suspected = root_cause.get("suspected_filter")
    impact_text = business_impact.get("detail", "Downstream metrics may be affected.")
    loss = business_impact.get("estimated_loss")

    body_lines = [
        "Hi team,",
        "",
        "Aurum detected a validation failure in the current pipeline run.",
        "",
        f"The issue was identified in the {failed_layer} layer. Bronze data arrived successfully, "
        f"but the Bronze-to-Silver transformation removed more records than expected. "
        "Because Gold revenue is calculated from Silver data, the Gold output is currently "
        f"impacted and should not be treated as fully trusted (verdict: {final_verdict}).",
        "",
        "Root cause:",
        root_text,
    ]
    if suspected:
        body_lines.append(f"Suspected filter: {suspected}")
    body_lines.extend([
        "",
        "Business impact:",
        impact_text,
    ])
    if loss is not None:
        body_lines.append(f"Estimated revenue gap: {loss:,.2f}.")
    body_lines.extend([
        "",
        "Recommended action:",
        suggested_action or "Review the transformation logic and rerun the pipeline.",
        "",
        "Thanks.",
    ])
    body = "\n".join(body_lines)
    copy_text = f"Subject: {subject}\n\n{body}"
    summary = f"{failed_layer} validation failure — Gold revenue impacted. Draft only; not sent."

    return format_response(
        "email_draft",
        summary,
        data={
            "email_draft": {
                "subject": subject,
                "body": body,
                "summary": summary,
                "copy_text": copy_text,
            }
        },
        confidence="high",
    )
