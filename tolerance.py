"""Tolerance comparison helpers."""

from __future__ import annotations


def compare_to_tolerance(value: float, baseline: dict) -> dict:
    normal = float(baseline["normal_drop_pct"])
    std_dev = float(baseline["std_dev"])
    lower = float(baseline["lower_bound"])
    upper = float(baseline["upper_bound"])
    deviation_sigma = 0.0 if std_dev == 0 else abs(value - normal) / std_dev

    return {
        "value": round(value, 2),
        "in_tolerance": lower <= value <= upper,
        "deviation_sigma": round(deviation_sigma, 1),
    }


if __name__ == "__main__":
    print(
        compare_to_tolerance(
            28.0,
            {
                "normal_drop_pct": 3.81,
                "std_dev": 0.032,
                "lower_bound": 3.71,
                "upper_bound": 3.91,
            },
        )
    )
