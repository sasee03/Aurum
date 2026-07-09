"""Simple keyword-based intent detection for Aurum Assistant."""

from __future__ import annotations


def detect_intent(question: str) -> str:
    q = question.lower().strip()

    if any(k in q for k in ("top", "revenue", "country", "countries", "sales", "state", "states")):
        return "sample_revenue_query"

    if any(k in q for k in ("history", "previous", "past", "trend", "expected", "compare")):
        return "history_explanation"

    if any(k in q for k in ("email", "mail", "stakeholder", "draft", "alert")):
        return "email_draft"

    if any(k in q for k in ("primary key", "pk", "duplicate", "unique key")):
        return "primary_key_explanation"

    if any(k in q for k in ("date", "time", "timestamp", "freshness", "partition")):
        return "datetime_explanation"

    if any(
        k in q
        for k in (
            "custom check",
            "add validation",
            "create rule",
            "new check",
            "domain check",
            "add a custom",
            "help me add",
        )
    ):
        return "custom_check_builder"

    if any(k in q for k in ("failure", "broke", "failed", "summary", "impact", "what broke")):
        return "failure_summary"

    return "validation_explanation"
