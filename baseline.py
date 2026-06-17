"""Compute learned normal Bronze-to-Silver tolerance from historical runs."""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import List, Dict, Union


def compute_baseline(historical_runs: Union[pd.DataFrame, List[Dict]]) -> dict:
    runs = pd.DataFrame(historical_runs)
    if "drop_pct" not in runs:
        runs = runs.assign(
            drop_pct=(runs["bronze_count"] - runs["silver_count"])
            / runs["bronze_count"]
            * 100
        )

    drop_pcts = runs["drop_pct"].astype(float).to_numpy()
    normal_drop_pct = float(np.mean(drop_pcts))
    std_dev = float(np.std(drop_pcts))

    return {
        "normal_drop_pct": round(normal_drop_pct, 2),
        "std_dev": round(std_dev, 3),
        "lower_bound": round(normal_drop_pct - 3 * std_dev, 2),
        "upper_bound": round(normal_drop_pct + 3 * std_dev, 2),
        "method": "mean +/- 3 std",
    }


if __name__ == "__main__":
    sample = [{"drop_pct": pct} for pct in [3.77, 3.85, 3.81]]
    print(compute_baseline(sample))
