"""Pain-1 detection stack: orchestrates Layers 1, 2, and 3."""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import BRONZE, CROSS_LAYER, GOLD, SILVER, CheckResult
from .data_loader import DataLoader
from .reconciliation_layer import run_reconciliation_layer
from .robust_anomaly import run_robust_anomaly_layer
from .rule_library import run_rule_library


@dataclass
class DetectionStackResult:
    layer_1_rules: list[CheckResult] = field(default_factory=list)
    layer_2_reconciliation: list[CheckResult] = field(default_factory=list)
    layer_3_robust_anomaly: list[CheckResult] = field(default_factory=list)

    @property
    def all_checks(self) -> list[CheckResult]:
        return (
            self.layer_1_rules
            + self.layer_2_reconciliation
            + self.layer_3_robust_anomaly
        )

    def for_pipeline_layer(self, layer: str) -> list[CheckResult]:
        return [c for c in self.all_checks if c.layer == layer]


def run_detection_stack(loader: DataLoader) -> DetectionStackResult:
    """Run all three Pain-1 detection layers in order (cheapest first)."""
    return DetectionStackResult(
        layer_1_rules=run_rule_library(loader),
        layer_2_reconciliation=run_reconciliation_layer(loader),
        layer_3_robust_anomaly=run_robust_anomaly_layer(loader),
    )


def merge_checks(*groups: list[CheckResult]) -> list[CheckResult]:
    """Concatenate check result lists preserving order."""
    out: list[CheckResult] = []
    for group in groups:
        out.extend(group)
    return out
