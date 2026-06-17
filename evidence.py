"""Evidence rows shown in the demo and dashboard."""

from __future__ import annotations

from data_loader import DataLoader


def money_cr(value: float) -> str:
    return f"Rs {value / 10_000_000:.2f} Cr"


def build_evidence(loader: DataLoader, impact: dict) -> list[dict]:
    bronze_sql = "SELECT COUNT(*) FROM bronze_orders;"
    silver_sql = "SELECT COUNT(*) FROM silver_orders_buggy;"
    revenue_sql = "SELECT SUM(net_amount) FROM silver_orders_buggy;"

    bronze_count = int(loader.scalar(bronze_sql))
    silver_count = int(loader.scalar(silver_sql))
    actual_revenue = float(loader.scalar(revenue_sql))

    return [
        {
            "name": "Bronze order count",
            "sql": bronze_sql,
            "result": f"{bronze_count:,} rows",
            "meaning": "Total orders ingested in the raw layer.",
        },
        {
            "name": "Silver valid count (today)",
            "sql": silver_sql,
            "result": f"{silver_count:,} rows",
            "meaning": "Valid orders surviving the Silver transformation today.",
        },
        {
            "name": "Gold revenue delta",
            "sql": revenue_sql,
            "result": money_cr(actual_revenue),
            "meaning": (
                "Today's Gold revenue vs "
                f"Rs {impact['expected_revenue_cr']:.2f} Cr expected = "
                f"Rs {impact['impact_cr']:.2f} Cr short."
            ),
        },
    ]


if __name__ == "__main__":
    from impact import calculate_impact_from_loader

    loader = DataLoader()
    print(build_evidence(loader, calculate_impact_from_loader(loader)))
