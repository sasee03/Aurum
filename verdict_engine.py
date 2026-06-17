"""Deterministic business release verdict rules."""

from __future__ import annotations


def decide_verdict(
    profile: dict,
    baseline: dict,
    anomaly: dict,
    root_cause: dict,
    impact: dict,
) -> dict:
    reasons = []

    if anomaly["is_anomaly"]:
        reasons.append(
            "Bronze->Silver drop "
            f"{profile['drop_pct']:.0f}% vs learned normal "
            f"{baseline['normal_drop_pct']:.2f}% (+/- 3 std)"
        )

    if impact["impact_cr"] > 0:
        reasons.append(f"Gold revenue Rs {impact['impact_cr']:.2f} Cr below expected")

    if root_cause["dropped_rows"] > 0:
        reasons.append("Finance Board Dashboard impacted")

    if anomaly["severity"] == "CRITICAL" or impact["risk_level"] == "HIGH":
        decision = "BLOCK PUBLISH"
    elif anomaly["is_anomaly"] or impact["risk_level"] == "MEDIUM":
        decision = "WARN"
    else:
        decision = "ALLOW PUBLISH"

    return {
        "decision": decision,
        "reasons": reasons,
    }


if __name__ == "__main__":
    print(
        decide_verdict(
            {"drop_pct": 28.0},
            {"normal_drop_pct": 3.81},
            {"is_anomaly": True, "severity": "CRITICAL"},
            {"dropped_rows": 24_000},
            {"impact_cr": 0.48, "risk_level": "HIGH"},
        )
    )
