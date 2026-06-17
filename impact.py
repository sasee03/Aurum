"""Business impact calculation for Gold revenue."""

from __future__ import annotations

from data_loader import DataLoader


def calculate_impact(expected_revenue_cr: float, actual_revenue_cr: float) -> dict:
    impact_cr = expected_revenue_cr - actual_revenue_cr

    if impact_cr >= 0.25:
        risk_level = "HIGH"
    elif impact_cr >= 0.05:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    return {
        "expected_revenue_cr": round(expected_revenue_cr, 2),
        "actual_revenue_cr": round(actual_revenue_cr, 2),
        "impact_cr": round(impact_cr, 2),
        "risk_level": risk_level,
    }


def calculate_impact_from_loader(loader: DataLoader) -> dict:
    expected_revenue_cr = (
        float(loader.scalar("SELECT SUM(net_amount) FROM silver_orders_correct;"))
        / 10_000_000
    )
    actual_revenue_cr = (
        float(loader.scalar("SELECT SUM(net_amount) FROM silver_orders_buggy;"))
        / 10_000_000
    )
    return calculate_impact(expected_revenue_cr, actual_revenue_cr)


if __name__ == "__main__":
    print(calculate_impact_from_loader(DataLoader()))
