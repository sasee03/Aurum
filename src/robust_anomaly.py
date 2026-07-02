"""Layer 3 — Robust Anomaly Detection (Median + IQR, Modified Z/MAD).

Does NOT use mean ± 3σ as the primary method. Baselines are computed from
historical_runs — never hardcoded.

TODO: STL seasonal decomposition when customer data has clear seasonality.
TODO: PSI for distribution-shift monitoring.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .baseline import classify_robust_anomaly
from .contracts import (
    ACCURACY,
    BRONZE,
    COMPLETENESS,
    DETECTION_LAYER_3,
    GOLD,
    SILVER,
    CheckResult,
)
from .data_loader import DataLoader
from .resilience import (
    MIN_HISTORY_FOR_ANOMALY,
    Check,
    run_checks,
    skipped_result,
)

# Metrics monitored for robust anomaly detection.
METRICS = [
    {"id": "bronze_count", "name": "Bronze Row Count", "dimension": COMPLETENESS,
     "layer": BRONZE, "history_col": "bronze_count",
     "current_sql": "SELECT COUNT(*) FROM bronze_orders"},
    {"id": "silver_count", "name": "Silver Row Count", "dimension": COMPLETENESS,
     "layer": SILVER, "history_col": "silver_count",
     "current_sql": "SELECT COUNT(*) FROM silver_orders"},
    {"id": "drop_pct", "name": "Bronze-to-Silver Drop %", "dimension": COMPLETENESS,
     "layer": SILVER, "history_col": "drop_pct",
     "current_sql": (
         "SELECT (1 - (SELECT COUNT(*) FROM silver_orders)::DOUBLE "
         "/ NULLIF((SELECT COUNT(*) FROM bronze_orders), 0)) * 100"
     )},
    {"id": "gold_revenue", "name": "Gold Revenue", "dimension": ACCURACY,
     "layer": GOLD, "history_col": "gold_revenue",
     "current_sql": "SELECT total_revenue FROM gold_metrics"},
]


def _history(loader: DataLoader) -> Optional[pd.DataFrame]:
    if loader.table_exists("historical_runs"):
        return loader.query("SELECT * FROM historical_runs")
    return None


def _result(
    metric: dict, status: str, value: float, evidence: dict
) -> CheckResult:
    return CheckResult(
        check_id=f"L3-ANO-{metric['id'].upper()[:6]}",
        check_name=f"Robust Anomaly: {metric['name']}",
        layer=metric["layer"],
        status=status,
        observed={"value": value, **evidence},
        expected="within robust IQR band",
        detail=evidence.get("detail", ""),
        evidence_query=metric["current_sql"],
        extra={
            "dimension": metric["dimension"],
            "detection_layer": DETECTION_LAYER_3,
            "metric": metric["id"],
            "method": "median + IQR; modified Z (MAD)",
        },
    )


def _anomaly_id(metric: dict) -> str:
    return f"L3-ANO-{metric['id'].upper()[:6]}"


def _anomaly_metric(loader: DataLoader, metric: dict, history: pd.DataFrame):
    """Score a single metric; returns a CheckResult, or None if not applicable."""
    hist_col = metric["history_col"]
    if hist_col not in history.columns:
        return None  # metric absent from history schema -- nothing to score
    raw = loader.scalar(metric["current_sql"])
    if raw is None:
        return skipped_result(
            _anomaly_id(metric),
            f"Robust Anomaly: {metric['name']}",
            metric["layer"],
            (
                f"current value for '{metric['id']}' is NULL "
                "(empty/degenerate upstream) -- cannot score anomaly."
            ),
            evidence_query=metric["current_sql"],
        )
    value = float(raw)
    hist_values = history[hist_col].astype(float).to_numpy()
    status, evidence = classify_robust_anomaly(value, hist_values)
    return _result(metric, status, value, evidence)


def run_robust_anomaly_layer(loader: DataLoader) -> list[CheckResult]:
    history = _history(loader)
    n = 0 if history is None else len(history)
    if history is None or n < MIN_HISTORY_FOR_ANOMALY:
        # No baseline yet (normal for a new customer's first runs): SKIP each
        # anomaly check with a specific reason -- never a false WARN/FAIL.
        reason = (
            f"no baseline yet (n={n}, need {MIN_HISTORY_FOR_ANOMALY}) "
            "-- will learn from this run"
        )
        return [
            skipped_result(
                _anomaly_id(metric),
                f"Robust Anomaly: {metric['name']}",
                metric["layer"],
                reason,
                evidence_query=metric["current_sql"],
            )
            for metric in METRICS
        ]

    return run_checks(
        [
            Check(
                (lambda metric=metric: _anomaly_metric(loader, metric, history)),
                _anomaly_id(metric),
                f"Robust Anomaly: {metric['name']}",
                metric["layer"],
            )
            for metric in METRICS
        ]
    )
