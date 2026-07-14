"""Pain-1 detection stack: orchestrates rule and anomaly detection."""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import CheckResult
from .config_loader import AurumDatasetConfig
from .data_loader import DataLoader
from .robust_anomaly import run_robust_anomaly_layer
from .rule_library import run_rule_library


@dataclass
class DetectionStackResult:
    layer_1_rules: list[CheckResult] = field(default_factory=list)
    # Retained as an empty compatibility slot in the nested report contract.
    layer_2_reconciliation: list[CheckResult] = field(default_factory=list)
    layer_3_robust_anomaly: list[CheckResult] = field(default_factory=list)

    @property
    def all_checks(self) -> list[CheckResult]:
        return (
            self.layer_1_rules
            + self.layer_3_robust_anomaly
        )

    def for_pipeline_layer(self, layer: str) -> list[CheckResult]:
        return [c for c in self.all_checks if c.layer == layer]


def run_detection_stack(
    loader: DataLoader,
    cfg: AurumDatasetConfig | None = None,
) -> DetectionStackResult:
    """Run the active Pain-1 detection layers in order (cheapest first)."""
    return DetectionStackResult(
        layer_1_rules=run_rule_library(loader, cfg),
        layer_3_robust_anomaly=run_robust_anomaly_layer(loader),
    )


def merge_checks(*groups: list[CheckResult]) -> list[CheckResult]:
    """Concatenate check result lists preserving order."""
    out: list[CheckResult] = []
    for group in groups:
        out.extend(group)
    return out
