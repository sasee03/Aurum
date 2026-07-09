"""Shared data loading for Aurum Assistant handlers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union

from src.config_loader import load_dataset_config

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "reports" / "report.json"
CUSTOM_CHECKS_PATH = ROOT / "data" / "custom_checks" / "custom_checks.json"
SAMPLE_ORDERS_PATH = ROOT / "data" / "sample" / "sample_orders.json"

# Demo-safe schema issue payloads when report lacks detail.
def _demo_datetime_issue() -> dict:
    timestamp_col = load_dataset_config().columns.timestamp
    return {
        "issue_type": "datetime",
        "summary": "Timestamp freshness and partition completeness concern.",
        "details": [
            f"Max {timestamp_col} may lag expected run date (freshness).",
            "Late-arriving data can leave partitions incomplete.",
            "Time-based aggregations may exclude recent records.",
        ],
        "downstream_risk": "Daily revenue rollups may undercount recent orders.",
    }


DEMO_PK_ISSUE = {
    "issue_type": "primary_key",
    "summary": "Composite business key integrity risk detected during reconciliation.",
    "details": [
        "Duplicate keys can inflate downstream aggregations.",
        "Missing keys break join reliability between Bronze and Silver.",
        "Changed key structure causes deduplication gaps.",
    ],
    "downstream_risk": "Revenue and order counts may be wrong if keys are not unique.",
}

DEMO_DATETIME_ISSUE = _demo_datetime_issue()


def load_json_file(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def load_latest_report() -> Optional[dict]:
    """Load report from in-memory API cache or disk."""
    try:
        import api.main as api_main

        if api_main._last_report is not None:
            return api_main._last_report
    except Exception:
        pass
    return load_json_file(REPORT_PATH)


def load_report_for_run(run_id: Optional[str]) -> Optional[dict]:
    """Load report by run_id from SQLite store, falling back to latest."""
    if run_id and run_id not in ("latest", "demo_run_001", ""):
        try:
            from src.app_state.store import get_report_by_run_id
            stored = get_report_by_run_id(run_id)
            if stored is not None:
                return stored
        except Exception:
            pass
    return load_latest_report()


def _row_counts_from_report(report: dict) -> tuple[int, int]:
    """Extract bronze/silver row counts from a validation report when present."""
    bronze_rows = 0
    silver_rows = 0
    checks = report.get("checks", {})
    for check in checks.get("bronze", []):
        if check.get("check_id") == "B1" and check.get("observed") is not None:
            bronze_rows = int(check["observed"])
            break
    for check in checks.get("silver", []):
        extra = check.get("extra")
        if check.get("check_id") == "S1" and isinstance(extra, dict):
            if extra.get("silver") is not None:
                silver_rows = int(extra["silver"])
            if bronze_rows == 0 and extra.get("bronze") is not None:
                bronze_rows = int(extra["bronze"])
            break
    return bronze_rows, silver_rows


def load_history_records() -> list[dict]:
    """Load run history from SQLite only (same source as GET /runs)."""
    from src.app_state.store import get_report_by_run_id, list_validation_runs

    records: list[dict] = []
    for run in list_validation_runs():
        report = get_report_by_run_id(run["run_id"])
        bronze_rows = 0
        silver_rows = 0
        gold_revenue = 0.0
        if report:
            bronze_rows, silver_rows = _row_counts_from_report(report)
            impact = report.get("business_impact", {})
            gold_revenue = float(
                impact.get("actual_revenue") or impact.get("expected_revenue") or 0
            )

        drop_pct = 0.0
        if bronze_rows > 0:
            drop_pct = round((1 - silver_rows / bronze_rows) * 100, 1)

        records.append(
            {
                "run_id": run["run_id"],
                "bronze_rows": bronze_rows,
                "silver_rows": silver_rows,
                "drop_pct": drop_pct,
                "gold_revenue": gold_revenue,
                "final_verdict": run.get("final_verdict") or "UNKNOWN",
                "trust_score": run.get("trust_score"),
                "started_at": run.get("started_at"),
                "status": run.get("status"),
            }
        )
    return records


def load_custom_checks() -> list[dict]:
    checks = load_json_file(CUSTOM_CHECKS_PATH, default=None)
    if checks is not None:
        return checks
    return []


def save_custom_checks(checks: list[dict]) -> None:
    CUSTOM_CHECKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CUSTOM_CHECKS_PATH.write_text(
        json.dumps(checks, indent=2, default=str), encoding="utf-8"
    )


def load_sample_orders() -> list[dict]:
    orders = load_json_file(SAMPLE_ORDERS_PATH, default=None)
    if orders is not None:
        return orders
    return []


def fallback_response(answer: str, suggested_actions: Optional[list] = None) -> dict:
    return {
        "intent": "validation_explanation",
        "answer": answer,
        "data": {"suggested_actions": suggested_actions or []},
        "confidence": "low",
    }


def format_response(
    intent: str,
    answer: str,
    data: Optional[dict] = None,
    confidence: str = "high",
) -> dict:
    return {
        "intent": intent,
        "answer": answer,
        "data": data or {},
        "confidence": confidence,
    }
