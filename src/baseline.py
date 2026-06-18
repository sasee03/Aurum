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
