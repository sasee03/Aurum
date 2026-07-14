"""Assemble the final Aurum report from all validators and write report.json."""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import TRUSTED, WARNING
from .config_loader import load_dataset_config, AurumDatasetConfig
from .cross_layer_validator import (
    build_business_impact,
    build_root_cause,
    first_failed_layer,
    validate_cross_layer,
)
from .bronze_validator import validate_bronze
from .data_loader import DataLoader
from .detection_stack import run_detection_stack
from .gold_validator import validate_gold
from .silver_validator import validate_silver
from .resilience import build_coverage
from .verdict_engine import compute_final_verdict, compute_layer_status
from .engines.trust_engine import TrustScoringEngine
from .contracts import CheckResult, PASS, FAIL, WARN, SKIPPED

trust_engine = TrustScoringEngine()

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


def build_report(
    loader: DataLoader,
    run_id: str = "demo_run_001",
    cfg: AurumDatasetConfig | None = None,
) -> dict:
    cfg = cfg or load_dataset_config()
    detection = run_detection_stack(loader, cfg)

    bronze_results = validate_bronze(loader, cfg)
    silver_results = validate_silver(loader, cfg)
    bronze_status = compute_layer_status(bronze_results)
    silver_status = compute_layer_status(silver_results)
    gold_results = validate_gold(loader, upstream_status=silver_status, cfg=cfg)

    layer_status = {
        "bronze": bronze_status,
        "silver": silver_status,
        "gold": compute_layer_status(gold_results),
    }

    # Custom checks execution
    custom_results = []
    try:
        from api.aurum_assistant.context import load_custom_checks
        custom_checks_cfg = load_custom_checks()
    except Exception:
        custom_checks_cfg = []

    if custom_checks_cfg:
        import pandas as pd
        from src.custom_checks import evaluate_check_on_frame, LAYER_TABLES

        for c in custom_checks_cfg:
            layer = str(c.get("layer", "silver")).strip().lower()
            table_name = LAYER_TABLES.get(layer)
            df = loader.query(f"SELECT * FROM {table_name}") if table_name and loader.table_exists(table_name) else pd.DataFrame()
            
            res_dict = evaluate_check_on_frame(c, df)
            
            # Map severity
            raw_severity = str(c.get("severity", "WARNING")).upper()
            if raw_severity == "HIGH": severity = "BLOCKING"
            elif raw_severity == "MEDIUM": severity = "WARNING"
            elif raw_severity == "LOW": severity = "INFORMATIONAL"
            else: severity = raw_severity

            # Determine CheckResult status based on execution status and severity
            exec_status = res_dict.get("status", SKIPPED)
            final_status = exec_status
            if exec_status == "FAIL":
                if severity == "BLOCKING":
                    final_status = FAIL
                elif severity == "WARNING":
                    final_status = WARN
                else: # INFORMATIONAL
                    final_status = PASS # or WARN? Let's use PASS but detail it. 

            custom_results.append(
                CheckResult(
                    check_id=res_dict.get("check_id", ""),
                    check_name=c.get("check_name", "Custom Check"),
                    layer="Custom",
                    status=final_status,
                    observed=res_dict.get("observed_value"),
                    expected=res_dict.get("expected_condition"),
                    detail=res_dict.get("message", ""),
                    extra={"severity": severity, "original_status": exec_status}
                )
            )

    if custom_results:
        layer_status["custom"] = compute_layer_status(custom_results)

    cross_results = validate_cross_layer(
        bronze_results, silver_results, gold_results, layer_status, cfg
    )

    verdict = compute_final_verdict(layer_status)
    final_verdict = verdict["final_verdict"]
    severity = verdict["severity"]

    coverage = build_coverage(
        bronze_results
        + silver_results
        + gold_results
        + cross_results
        + custom_results
        + detection.all_checks
    )
    # Skips must never buy a clean bill of health: a TRUSTED verdict with
    # incomplete coverage is downgraded to a caveated WARNING so no reader
    # mistakes "we couldn't check everything" for "everything is fine".
    if final_verdict == TRUSTED and not coverage["full_coverage"]:
        final_verdict = WARNING
        severity = "MEDIUM"
        coverage["verdict_caveat"] = (
            f"Coverage incomplete: {coverage['skipped']} check(s) skipped; "
            "verdict downgraded from TRUSTED."
        )

    root_cause = build_root_cause(silver_results)
    business_impact = build_business_impact(loader, cfg)
    suggested_action = _suggested_action(
        final_verdict, layer_status, root_cause
    )

    trust_score = verdict.get("trust_score", 0)

    return {
        "project": "Aurum",
        "description": "Cross-layer data quality validation framework",
        "pipeline": PIPELINE,
        "dataset": cfg.dataset.name,
        "run_id": run_id,
        "layer_status": layer_status,
        "final_verdict": final_verdict,
        "severity": severity,
        "first_failed_layer": first_failed_layer(layer_status),
        "root_cause": root_cause,
        "business_impact": business_impact,
        "suggested_action": suggested_action,
        "trust_score": trust_score,
        "trust_narrative": "",
        "coverage": coverage,
        "detection_layers": {
            "layer_1_rules": [r.to_dict() for r in detection.layer_1_rules],
            "layer_2_reconciliation": [
                r.to_dict() for r in detection.layer_2_reconciliation
            ],
            "layer_3_robust_anomaly": [
                r.to_dict() for r in detection.layer_3_robust_anomaly
            ],
        },
        "checks": {
            "bronze": [r.to_dict() for r in bronze_results],
            "silver": [r.to_dict() for r in silver_results],
            "gold": [r.to_dict() for r in gold_results],
            "cross_layer": [r.to_dict() for r in cross_results],
            "custom": [r.to_dict() for r in custom_results] if custom_results else [],
        },
    }


def attach_trust_narrative(
    report: dict,
    *,
    timeout_seconds: float = 180,
) -> dict:
    """Post-build seam: Ollama narration only, after deterministic verdict is fixed."""
    report["trust_narrative"] = trust_engine.generate_trust_narrative(
        score=report.get("trust_score", 0),
        business_impact=report.get("business_impact", {}),
        root_cause=report.get("root_cause", {}),
        timeout_seconds=timeout_seconds,
    )
    return report


def write_report(report: dict, path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path
