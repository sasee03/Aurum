"""Shared runtime assertions for Aurum performance and stress harnesses."""

from __future__ import annotations

import json
import math
from typing import Any, Iterable, Tuple


EXPECTED_REPORT_KEYS = frozenset(
    {
        "project",
        "description",
        "pipeline",
        "dataset",
        "run_id",
        "layer_status",
        "final_verdict",
        "severity",
        "first_failed_layer",
        "root_cause",
        "business_impact",
        "suggested_action",
        "trust_score",
        "trust_narrative",
        "coverage",
        "detection_layers",
        "checks",
    }
)
EXPECTED_DATASET = "Olist Brazilian E-Commerce"
EXPECTED_VERDICT = "NOT TRUSTED"
EXPECTED_LAYER_STATUS = {
    "bronze": "PASS",
    "silver": "FAIL",
    "gold": "IMPACTED",
}
EXPECTED_LOSS_BRL = 13_447_000.57
STALE_TERMS = ("INR", "Rs", "\u20b9", "Online Retail", "synthetic")


def walk_values(value: Any, path: str = "") -> Iterable[Tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            yield from walk_values(item, next_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_values(item, f"{path}[{index}]")
    else:
        yield path, value


def validate_report_contract(
    report: dict,
    runtime_text: str = "",
    expected_loss_multiplier: float = 1.0,
) -> Tuple[bool, list]:
    failures = []

    actual_keys = set(report.keys())
    if actual_keys != set(EXPECTED_REPORT_KEYS):
        missing = sorted(EXPECTED_REPORT_KEYS - actual_keys)
        extra = sorted(actual_keys - EXPECTED_REPORT_KEYS)
        failures.append(
            "Report keys changed: "
            f"expected {len(EXPECTED_REPORT_KEYS)}, got {len(actual_keys)}, "
            f"missing={missing}, extra={extra}."
        )

    if report.get("dataset") != EXPECTED_DATASET:
        failures.append(
            f"dataset={report.get('dataset')!r}; expected {EXPECTED_DATASET!r}."
        )

    if report.get("final_verdict") != EXPECTED_VERDICT:
        failures.append(
            f"final_verdict={report.get('final_verdict')!r}; "
            f"expected {EXPECTED_VERDICT!r}."
        )

    layer_status = report.get("layer_status", {})
    for layer, expected in EXPECTED_LAYER_STATUS.items():
        actual = layer_status.get(layer)
        if actual != expected:
            failures.append(f"layer_status.{layer}={actual!r}; expected {expected!r}.")

    impact = report.get("business_impact", {})
    estimated_loss = impact.get("estimated_loss")
    expected_loss = EXPECTED_LOSS_BRL * expected_loss_multiplier
    if not isinstance(estimated_loss, (int, float)):
        failures.append("business_impact.estimated_loss is missing or non-numeric.")
    elif not math.isclose(float(estimated_loss), expected_loss, rel_tol=0.01, abs_tol=1):
        failures.append(
            "business_impact.estimated_loss="
            f"{estimated_loss!r}; expected around {expected_loss:,.2f} BRL."
        )

    combined_text = json.dumps(report, ensure_ascii=False) + "\n" + runtime_text
    for term in STALE_TERMS:
        if term in combined_text:
            failures.append(f"Stale runtime reference found: {term!r}.")

    return not failures, failures


def patch_llm_narrative() -> None:
    """Keep benchmarks on the deterministic path without external Ollama calls."""
    from src import report_builder

    report_builder.trust_engine.generate_trust_narrative = (
        lambda **_: "LLM narrative skipped for deterministic benchmark/stress run."
    )
