"""Local history comparison handler."""

from __future__ import annotations

from typing import Any, Optional

from api.aurum_assistant.context import (
    fallback_response,
    format_response,
    load_history_records,
    load_latest_report,
    load_report_for_run,
)


def _retention_pct(bronze: int, silver: int) -> float:
    if bronze <= 0:
        return 0.0
    return round(silver / bronze * 100, 1)


def handle(
    question: str,
    page: str = "history",
    layer: Optional[str] = None,
    context: Optional[dict] = None,
    run_id: str = "latest",
) -> dict:
    history = load_history_records()
    report = load_report_for_run(run_id)

    if not history:
        return fallback_response(
            "No validation run history found yet. Run validation via POST /runs to populate history.",
            ["Run validation", "Check Run History after a completed run"],
        )

    retentions = [_retention_pct(h["bronze_rows"], h["silver_rows"]) for h in history]
    avg_retention = sum(retentions) / len(retentions)
    min_ret, max_ret = min(retentions), max(retentions)

    current_bronze = None
    current_silver = None
    current_verdict = None
    if report:
        checks = report.get("checks", {})
        bronze_checks = checks.get("bronze", [])
        silver_checks = checks.get("silver", [])
        for c in bronze_checks:
            if c.get("check_id") == "B1":
                current_bronze = c.get("observed")
                break
        for c in silver_checks:
            if c.get("check_id") == "S1" and isinstance(c.get("extra"), dict):
                current_silver = c["extra"].get("silver")
                if current_bronze is None:
                    current_bronze = c["extra"].get("bronze")
                break
        current_verdict = report.get("final_verdict")

    parts: list[str] = [
        f"Historically, Silver retained around {min_ret:.0f}–{max_ret:.0f}% of Bronze records "
        f"(average {avg_retention:.1f}%)."
    ]

    if current_bronze and current_silver:
        current_ret = _retention_pct(int(current_bronze), int(current_silver))
        parts.append(
            f"In the current run, Silver retained only around {current_ret:.0f}%, "
            f"which is much lower than expected."
        )
        if current_ret < min_ret - 5:
            parts.append(
                "This indicates abnormal record loss during Bronze-to-Silver transformation."
            )
    elif report:
        root = report.get("root_cause", {}).get("summary", "")
        parts.append(f"Current run: {root}")

    if current_verdict:
        parts.append(f"Current verdict: {current_verdict}.")

    trusted = sum(1 for h in history if h.get("final_verdict") == "TRUSTED")
    parts.append(f"History shows {trusted}/{len(history)} trusted runs.")

    return format_response(
        "history_explanation",
        " ".join(parts),
        data={
            "table": history[-5:],
            "suggested_actions": [
                "Compare Silver row counts against historical median",
                "Review transformation filters introduced in this run",
            ],
        },
        confidence="high" if current_bronze else "medium",
    )
