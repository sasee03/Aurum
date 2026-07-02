import pandas as pd
import psycopg
import pytest

from src.data_loader import DataLoader
from src.db_config import postgres_conninfo


def _schema_exists(schema: str) -> bool:
    conn = psycopg.connect(postgres_conninfo(), autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
                [schema],
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def test_construction_failure_leaves_no_orphaned_schema(monkeypatch):
    captured = {}
    original_install = DataLoader._install_helpers

    def boom(self):
        # Fail after the session schema has been created but before full init.
        captured["schema"] = self._schema
        raise RuntimeError("forced failure during DataLoader setup")

    monkeypatch.setattr(DataLoader, "_install_helpers", boom)

    with pytest.raises(RuntimeError, match="forced failure during DataLoader setup"):
        DataLoader(data_dir=None, build=False)

    assert "schema" in captured, "failure did not occur after schema creation"
    assert not _schema_exists(captured["schema"]), "orphaned schema left behind"

    monkeypatch.setattr(DataLoader, "_install_helpers", original_install)


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
