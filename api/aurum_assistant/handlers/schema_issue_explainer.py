"""Primary key and schema issue explanation handler."""

from __future__ import annotations

from typing import Any, Optional

from api.aurum_assistant.context import (
    DEMO_PK_ISSUE,
    format_response,
    load_latest_report,
    load_report_for_run,
)


def _find_pk_checks(report: dict) -> list[dict]:
    found: list[dict] = []
    for layer_checks in report.get("checks", {}).values():
        for check in layer_checks:
            name = (check.get("check_name") or "").lower()
            cid = (check.get("check_id") or "").upper()
            if "primary key" in name or "duplicate" in name or "UNIQ-PK" in cid or "B8" == cid:
                found.append(check)
    for layer_checks in report.get("detection_layers", {}).values():
        for check in layer_checks:
            name = (check.get("check_name") or "").lower()
            cid = (check.get("check_id") or "").upper()
            if "primary key" in name or "UNIQ-PK" in cid:
                found.append(check)
    return found


def handle_primary_key(
    question: str,
    page: str = "validation",
    layer: Optional[str] = None,
    context: Optional[dict] = None,
    run_id: str = "latest",
) -> dict:
    report = load_report_for_run(run_id)
    pk_checks = _find_pk_checks(report) if report else []
    failed_pk = [c for c in pk_checks if c.get("status") in ("FAIL", "WARN")]

    parts: list[str] = []
    if failed_pk:
        check = failed_pk[0]
        parts.append(
            f"The primary key check ({check.get('check_id')}) failed: {check.get('detail', '')}."
        )
        parts.append(
            "Duplicate or missing keys break join reliability and can cause incorrect deduplication."
        )
        parts.append("Downstream aggregation risk: revenue and order counts may be inflated or dropped.")
        confidence = "high"
    else:
        parts.append(DEMO_PK_ISSUE["summary"])
        parts.append(" ".join(DEMO_PK_ISSUE["details"]))
        parts.append(f"Why this matters: {DEMO_PK_ISSUE['downstream_risk']}")
        parts.append("(Demo issue explanation — not a new verdict.)")
        confidence = "medium"

    return format_response(
        "primary_key_explanation",
        " ".join(parts),
        data={
            "suggested_actions": [
                "Review duplicate key queries in failed checks",
                "Validate composite key columns across Bronze and Silver",
                "Confirm deduplication logic in Silver ETL",
            ]
        },
        confidence=confidence,
    )


def handle_datetime(
    question: str,
    page: str = "validation",
    layer: Optional[str] = None,
    context: Optional[dict] = None,
    run_id: str = "latest",
) -> dict:
    from api.aurum_assistant.context import DEMO_DATETIME_ISSUE

    report = load_report_for_run(run_id)
    time_checks: list[dict] = []
    if report:
        for layer_checks in report.get("checks", {}).values():
            for check in layer_checks:
                name = (check.get("check_name") or "").lower()
                cid = (check.get("check_id") or "").upper()
                if any(k in name for k in ("fresh", "time", "date")) or "TIME" in cid:
                    time_checks.append(check)

    failed_time = [c for c in time_checks if c.get("status") in ("FAIL", "WARN")]
    parts: list[str] = []

    if failed_time:
        check = failed_time[0]
        parts.append(
            f"Date/time check ({check.get('check_id')}) flagged: {check.get('detail', '')}."
        )
        confidence = "high"
    else:
        parts.append(DEMO_DATETIME_ISSUE["summary"])
        parts.append(" ".join(DEMO_DATETIME_ISSUE["details"]))
        parts.append(f"Why this matters: {DEMO_DATETIME_ISSUE['downstream_risk']}")
        parts.append("(Demo issue explanation — not a new verdict.)")
        confidence = "medium"

    if report:
        for check in time_checks:
            obs = check.get("observed")
            if isinstance(obs, dict) and "max_date" in obs:
                parts.append(
                    f"Latest observed max_date: {obs.get('max_date')}; "
                    f"run_date: {obs.get('run_date', 'N/A')}."
                )
                break

    return format_response(
        "datetime_explanation",
        " ".join(parts),
        data={
            "suggested_actions": [
                "Verify timestamp format in source data",
                "Check partition completeness for the current run",
                "Compare max invoice_date against expected run date",
            ]
        },
        confidence=confidence,
    )
