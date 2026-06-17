"""Anomaly decision logic for pipeline profile metrics."""

from __future__ import annotations

from tolerance import compare_to_tolerance


def detect_anomaly(profile: dict, baseline: dict) -> dict:
    drop_today = float(profile["drop_pct"])
    tolerance = compare_to_tolerance(drop_today, baseline)
    deviation_sigma = tolerance["deviation_sigma"]

    if deviation_sigma >= 10:
        severity = "CRITICAL"
    elif deviation_sigma >= 3:
        severity = "HIGH"
    elif not tolerance["in_tolerance"]:
        severity = "MEDIUM"
    else:
        severity = "LOW"

    return {
        "is_anomaly": not tolerance["in_tolerance"],
        "drop_today": round(drop_today, 2),
        "deviation_sigma": deviation_sigma,
        "severity": severity,
    }


if __name__ == "__main__":
    print(
        detect_anomaly(
            {"drop_pct": 28.0},
            {
                "normal_drop_pct": 3.81,
                "std_dev": 0.032,
                "lower_bound": 3.71,
                "upper_bound": 3.91,
            },
        )
    )
