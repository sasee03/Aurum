"""Learned-baseline helpers shared by the layer validators.

These compute tolerance bands from historical runs using numpy. Nothing here is
hardcoded to the demo numbers; if no history is supplied the caller falls back to
configured thresholds.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def column_stats(history: Optional[pd.DataFrame], column: str) -> Optional[dict]:
    if history is None or column not in history or len(history) == 0:
        return None
    values = history[column].astype(float).to_numpy()
    mean = float(np.mean(values))
    std = float(np.std(values))
    return {"mean": mean, "std": std, "count": int(len(values))}


def tolerance_band(stats: dict, k: float = 3.0) -> dict:
    mean = stats["mean"]
    std = stats["std"]
    return {
        "mean": mean,
        "std": std,
        "lower": mean - k * std,
        "upper": mean + k * std,
    }


def robust_iqr_band(values: np.ndarray) -> dict:
    """Median + IQR band (Tukey fences). Primary robust anomaly method."""
    arr = np.asarray(values, dtype=float)
    q1, median, q3 = np.percentile(arr, [25, 50, 75])
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    return {
        "median": float(median),
        "q1": float(q1),
        "q3": float(q3),
        "iqr": float(iqr),
        "lower": float(lower),
        "upper": float(upper),
        "method": "median + IQR (Q1 - 1.5*IQR, Q3 + 1.5*IQR)",
    }


def modified_z_score(value: float, values: np.ndarray) -> float:
    """Modified Z-score using MAD. Flag when |z| > 3.5."""
    arr = np.asarray(values, dtype=float)
    median = float(np.median(arr))
    mad = float(np.median(np.abs(arr - median)))
    if mad == 0:
        return 0.0 if value == median else float("inf")
    return 0.6745 * (value - median) / mad


def classify_robust_anomaly(
    value: float, history: np.ndarray
) -> tuple[str, dict]:
    """Return (status, evidence) using IQR primary and MAD secondary."""
    if len(history) < 3:
        return "PASS", {"detail": "Insufficient history for robust anomaly detection."}

    band = robust_iqr_band(history)
    mad_z = modified_z_score(value, history)
    evidence = {
        "value": value,
        "median": band["median"],
        "iqr_lower": band["lower"],
        "iqr_upper": band["upper"],
        "modified_z": round(mad_z, 2),
        "history_count": int(len(history)),
        "method": band["method"],
    }

    if band["lower"] <= value <= band["upper"]:
        status = "PASS"
        evidence["detail"] = "Within robust IQR band."
    elif abs(mad_z) > 3.5:
        status = "FAIL"
        evidence["detail"] = (
            f"Extreme outlier: modified Z={mad_z:.2f} (> 3.5) "
            f"and outside IQR [{band['lower']:.4g}, {band['upper']:.4g}]."
        )
    else:
        status = "WARN"
        evidence["detail"] = (
            f"Mild outlier: outside IQR [{band['lower']:.4g}, {band['upper']:.4g}] "
            f"but modified Z={mad_z:.2f}."
        )
    return status, evidence
