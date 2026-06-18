"""Assemble the final Aurum report from all validators and write report.json."""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import TRUSTED
from .cross_layer_validator import (
    build_business_impact,
    build_root_cause,
    first_failed_layer,
    validate_cross_layer,
)
from .bronze_validator import validate_bronze
from .data_loader import DataLoader
from .gold_validator import validate_gold
from .silver_validator import validate_silver
from .verdict_engine import compute_final_verdict, compute_layer_status

REPORT_PATH = Path("reports/report.json")
PIPELINE = "Raw \u2192 Bronze \u2192 Silver \u2192 Gold"


def _suggested_action(final_verdict: str, layer_status: dict, root_cause: dict) -> str:
    if final_verdict == TRUSTED:
        return "No action required. Pipeline output is trustworthy."
    if layer_status.get("silver") == "FAIL":
        suspected = root_cause.get("suspected_filter")
        if suspected:
            return (
                f"Fix the Silver transformation rule ({suspected}) and rerun the ETL."
            )
        return "Fix the Silver transformation rule and rerun the ETL."
    if layer_status.get("bronze") == "FAIL":
        return "Fix ingestion into Bronze and rerun the pipeline."
    if layer_status.get("gold") == "FAIL":
        return "Fix the Gold aggregation logic and recompute metrics."
    return "Review flagged layers before publishing Gold outputs."


def build_report(loader: DataLoader, run_id: str = "demo_run_001") -> dict:
    bronze_results = validate_bronze(loader)
    silver_results = validate_silver(loader)
    gold_results = validate_gold(loader)

    layer_status = {
        "bronze": compute_layer_status(bronze_results),
        "silver": compute_layer_status(silver_results),
        "gold": compute_layer_status(gold_results),
    }

    cross_results = validate_cross_layer(
        bronze_results, silver_results, gold_results, layer_status
    )

    verdict = compute_final_verdict(layer_status)
    root_cause = build_root_cause(silver_results)
    business_impact = build_business_impact(loader)
    suggested_action = _suggested_action(
        verdict["final_verdict"], layer_status, root_cause
    )

    return {
        "project": "Aurum",
        "description": "Cross-layer data quality validation framework",
        "pipeline": PIPELINE,
        "dataset": "Retail Orders",
        "run_id": run_id,
        "layer_status": layer_status,
        "final_verdict": verdict["final_verdict"],
        "severity": verdict["severity"],
        "first_failed_layer": first_failed_layer(layer_status),
        "root_cause": root_cause,
        "business_impact": business_impact,
        "suggested_action": suggested_action,
        "checks": {
            "bronze": [r.to_dict() for r in bronze_results],
            "silver": [r.to_dict() for r in silver_results],
            "gold": [r.to_dict() for r in gold_results],
            "cross_layer": [r.to_dict() for r in cross_results],
        },
    }


def write_report(report: dict, path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path
