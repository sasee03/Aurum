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
    WARN,
)
from .data_loader import DataLoader

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


def run_robust_anomaly_layer(loader: DataLoader) -> list[CheckResult]:
    history = _history(loader)
    if history is None or len(history) < 3:
        return [
            CheckResult(
                "L3-ANO-NOHIST",
                "Robust Anomaly: Insufficient History",
                SILVER, WARN,
                observed=0, expected=">= 3 historical runs",
                detail="Not enough history for robust anomaly baselines.",
                evidence_query="SELECT COUNT(*) FROM historical_runs",
                extra={"detection_layer": DETECTION_LAYER_3, "dimension": ACCURACY},
            )
        ]

    results = []
    for metric in METRICS:
        hist_col = metric["history_col"]
        if hist_col not in history.columns:
            continue
        try:
            value = float(loader.scalar(metric["current_sql"]) or 0)
        except Exception:
            continue
        hist_values = history[hist_col].astype(float).to_numpy()
        status, evidence = classify_robust_anomaly(value, hist_values)
        results.append(_result(metric, status, value, evidence))
    return results
