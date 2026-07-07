"""Shared data loading for Aurum Assistant handlers."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Optional, Union

from src.config_loader import load_dataset_config

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "reports" / "report.json"
HISTORICAL_CSV_PATH = ROOT / "data" / "historical" / "historical_runs.csv"
HISTORY_PATH = ROOT / "data" / "history" / "history_records.json"
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


def _history_from_csv() -> list[dict]:
    if not HISTORICAL_CSV_PATH.exists():
        return []
    records: list[dict] = []
    with HISTORICAL_CSV_PATH.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            records.append(
                {
                    "run_id": row["run_id"],
                    "bronze_rows": int(float(row["bronze_count"])),
                    "silver_rows": int(float(row["silver_count"])),
                    "drop_pct": float(row.get("drop_pct", 0)),
                    "gold_revenue": float(row["gold_revenue"]),
                    # Engine bootstrap history represents normal retained runs.
                    "final_verdict": "TRUSTED",
                }
            )
    return records


def load_history_records() -> list[dict]:
    """Prefer engine history CSV; fall back to JSON snapshot."""
    csv_records = _history_from_csv()
    if csv_records:
        return csv_records
    records = load_json_file(HISTORY_PATH, default=None)
    if records is not None:
        return records
    return []


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
