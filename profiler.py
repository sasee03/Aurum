"""Profile current pipeline health from DuckDB tables."""

from __future__ import annotations

from data_loader import DataLoader


def build_profile(loader: DataLoader) -> dict:
    bronze_count = int(loader.scalar("SELECT COUNT(*) FROM bronze_orders;"))
    silver_count = int(loader.scalar("SELECT COUNT(*) FROM silver_orders_buggy;"))
    drop_pct = (bronze_count - silver_count) / bronze_count * 100

    return {
        "bronze_count": bronze_count,
        "silver_count": silver_count,
        "drop_pct": round(drop_pct, 2),
    }


def layer_quality(loader: DataLoader) -> dict:
    return {
        "bronze_null_order_ids": int(
            loader.scalar("SELECT COUNT(*) FROM bronze_orders WHERE order_id IS NULL;")
        ),
        "bronze_duplicate_order_ids": int(
            loader.scalar(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT order_id
                    FROM bronze_orders
                    GROUP BY order_id
                    HAVING COUNT(*) > 1
                );
                """
            )
        ),
    }


if __name__ == "__main__":
    print(build_profile(DataLoader()))
