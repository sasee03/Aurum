import pandas as pd

from src.data_loader import DataLoader


def test_data_loader_instances_use_isolated_schemas():
    left = DataLoader.from_frames(
        {
            "bronze_orders": pd.DataFrame(
                [
                    {"invoice_no": "L1", "stock_code": "A", "quantity": 1},
                    {"invoice_no": "L2", "stock_code": "A", "quantity": 1},
                ]
            )
        }
    )
    right = DataLoader.from_frames(
        {
            "bronze_orders": pd.DataFrame(
                [{"invoice_no": "R1", "stock_code": "B", "quantity": 1}]
            )
        }
    )

    try:
        assert left.count("bronze_orders") == 2
        assert right.count("bronze_orders") == 1

        right.close()

        assert left.count("bronze_orders") == 2
    finally:
        left.close()
        right.close()


def test_is_not_distinct_from_keeps_native_boolean_semantics():
    loader = DataLoader.from_frames(
        {
            "null_pairs": pd.DataFrame(
                [
                    {"label": "one_sided_null", "a": None, "b": 1.0},
                    {"label": "both_null", "a": None, "b": None},
                    {"label": "type_anchor", "a": 1.0, "b": 1.0},
                ]
            )
        }
    )

    try:
        result = loader.query(
            """
            SELECT label, v.a IS NOT DISTINCT FROM v.b AS same
            FROM null_pairs v
            ORDER BY label
            """
        )
        values = dict(zip(result["label"], result["same"]))
        assert values["one_sided_null"] is False
        assert values["both_null"] is True
    finally:
        loader.close()
