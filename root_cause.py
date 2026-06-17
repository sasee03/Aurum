"""Root-cause analysis for the Silver transformation regression."""

from __future__ import annotations

from data_loader import DataLoader


def find_root_cause(loader: DataLoader) -> dict:
    dropped_discounted_orders = int(
        loader.scalar(
            """
            SELECT COUNT(*)
            FROM silver_orders_correct correct
            LEFT JOIN silver_orders_buggy buggy
                ON correct.order_id = buggy.order_id
            WHERE buggy.order_id IS NULL
                AND correct.has_discount = TRUE;
            """
        )
    )

    return {
        "cause": "Silver transformation wrongly filtered valid discounted orders",
        "dropped_rows": dropped_discounted_orders,
        "evidence_ref": "missing_discounted_orders",
    }


if __name__ == "__main__":
    print(find_root_cause(DataLoader()))
