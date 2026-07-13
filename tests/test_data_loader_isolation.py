import time
from pathlib import Path

import pandas as pd
import psycopg
import pytest

from src.config_loader import load_dataset_config
from src.bronze_validator import validate_bronze
from src.contracts import PASS
from src.cross_layer_validator import validate_cross_layer
from src.data_loader import DataLoader
from src.db_config import postgres_conninfo
from src.gold_validator import validate_gold
from src.silver_validator import validate_silver
from src.verdict_engine import compute_layer_status


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


def test_data_loader_connects_with_timeout_and_fails_fast(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_PORT", "1")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "1")

    start = time.monotonic()
    with pytest.raises(psycopg.OperationalError):
        DataLoader(data_dir=None, build=False)
    elapsed = time.monotonic() - start

    assert elapsed < 3


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


def test_build_silver_custom_config():
    import yaml
    from src.config_loader import _parse_raw_config

    cfg_raw = yaml.safe_load('''
    dataset:
      name: Test
      currency: USD
      domain: retail
      geography_label: market
    tables:
      bronze: bronze_orders
      silver: silver_orders
      gold: gold_metrics
    columns:
      primary_key: pk
      order_id: ord
      order_id_expression: "{order_id}"
      product_id: pid
      product_description: desc
      customer_id: cid
      timestamp: ts
      quantity: qty_col
      unit_price: price_col
      geography: geo
      revenue: rev
      line_item_key: [pk, pid, cid, ts]
      price_ceiling: 20
    metrics:
      revenue_formula: "qty_col * price_col"
      order_id_expression: "{order_id}"
      top_revenue_dimension: geo
      top_revenue_label: geo
      total_revenue_metric: total_revenue
      total_orders_metric: total_orders
      total_customers_metric: total_customers
      average_order_value_metric: average_order_value
      aggregate_revenue_metric: rev
      total_quantity_metric: total_quantity
    ''')
    cfg = _parse_raw_config(cfg_raw, "test")

    df = pd.DataFrame({
        "pk": ["L1", "L2", "L3"],
        "pid": ["A", "B", "C"],
        "desc": ["da", "db", "dc"],
        "qty_col": [5, -2, 10],
        "ts": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "price_col": [15.0, 10.0, 25.0],
        "cid": ["C1", "C2", "C3"],
        "geo": ["US", "US", "CA"],
        "ord": ["O1", "O2", "O3"]
    })

    loader = DataLoader(build=False)
    try:
        loader._materialize_frame("bronze_orders", df, temporary=False)
        loader.build_silver(cfg)

        res = loader.query("SELECT * FROM silver_orders")
        assert len(res) == 1
        assert res.iloc[0]["pk"] == "L1"
        assert res.iloc[0]["rev"] == 75.0
    finally:
        loader.close()


def test_generic_revenue_column_flows_through_full_validator_chain(monkeypatch):
    config_path = Path(__file__).resolve().parents[1] / "configs" / "generic_orders.yaml"
    monkeypatch.setenv("AURUM_DATASET_CONFIG", str(config_path))
    cfg = load_dataset_config()
    df = pd.DataFrame({
        "sale_line_id": ["L1", "L2"],
        "order_ref": ["O1", "O2"],
        "sku": ["A", "B"],
        "item_name": ["Alpha", "Beta"],
        "buyer_ref": ["C1", "C2"],
        "sold_at": ["2026-01-01", "2026-01-02"],
        "units": [2, 3],
        "price_each": [10.0, 30.0],
        "market": ["US", "CA"],
    })

    loader = DataLoader(build=False)
    try:
        loader._materialize_frame("raw_orders", df, temporary=False)
        loader.conn.execute(
            "CREATE OR REPLACE TABLE bronze_orders AS SELECT * FROM raw_orders"
        )
        loader.build_silver(cfg)
        loader.build_gold(cfg)

        silver = loader.query("SELECT * FROM silver_orders ORDER BY sale_line_id")
        assert silver["line_revenue"].tolist() == [20.0, 90.0]
        assert "net_revenue" not in silver.columns

        assert loader.scalar("SELECT total_revenue FROM gold_metrics") == 110.0
        assert loader.query(
            "SELECT market, revenue FROM gold_country_revenue ORDER BY market"
        ).to_dict("records") == [
            {"market": "CA", "revenue": 90.0},
            {"market": "US", "revenue": 20.0},
        ]
        assert loader.query(
            "SELECT sku, total_quantity, revenue FROM gold_product_sales ORDER BY sku"
        ).to_dict("records") == [
            {"sku": "A", "total_quantity": 2.0, "revenue": 20.0},
            {"sku": "B", "total_quantity": 3.0, "revenue": 90.0},
        ]

        bronze_results = {result.check_id: result for result in validate_bronze(loader)}
        silver_results = {result.check_id: result for result in validate_silver(loader)}
        bronze_status = compute_layer_status(bronze_results.values())
        silver_status = compute_layer_status(silver_results.values())
        gold_results = {
            result.check_id: result
            for result in validate_gold(loader, upstream_status=silver_status)
        }
        gold_status = compute_layer_status(gold_results.values())
        cross_results = {
            result.check_id: result
            for result in validate_cross_layer(
                list(bronze_results.values()),
                list(silver_results.values()),
                list(gold_results.values()),
                {"bronze": bronze_status, "silver": silver_status, "gold": gold_status},
            )
        }

        assert set(bronze_results) == {f"B{i}" for i in range(1, 11)}
        assert set(silver_results) == {f"S{i}" for i in range(1, 11)}
        assert set(gold_results) == {f"G{i}" for i in range(1, 11)}
        assert set(cross_results) == {f"X{i}" for i in range(1, 5)}
        assert silver_results["S7"].status == PASS
        assert gold_results["G1"].status == PASS
        assert gold_results["G2"].status == PASS
        assert gold_results["G6"].status == PASS
        assert gold_results["G9"].status == PASS
        assert cross_results["X3"].status == PASS
    finally:
        loader.close()


def test_build_gold_custom_config():
    import yaml
    from src.config_loader import _parse_raw_config

    cfg_raw = yaml.safe_load('''
    dataset:
      name: Test
      currency: USD
      domain: retail
      geography_label: market
    tables:
      bronze: bronze_orders
      silver: silver_orders
      gold: gold_metrics
    columns:
      primary_key: pk
      order_id: ord
      order_id_expression: "{order_id}"
      product_id: pid
      product_description: desc
      customer_id: cid
      timestamp: ts
      quantity: qty_col
      unit_price: price_col
      geography: geo
      revenue: rev
      line_item_key: [pk, pid, cid, ts]
      price_ceiling: 20
    metrics:
      revenue_formula: "qty_col * price_col"
      order_id_expression: "{order_id}"
      top_revenue_dimension: geo
      top_revenue_label: geo
      total_revenue_metric: custom_total_revenue
      total_orders_metric: custom_total_orders
      total_customers_metric: custom_total_customers
      average_order_value_metric: custom_average_order_value
      aggregate_revenue_metric: rev
      total_quantity_metric: total_quantity
    ''')
    cfg = _parse_raw_config(cfg_raw, "test")

    df = pd.DataFrame({
        "pk": ["L1", "L2", "L3"],
        "pid": ["A", "B", "C"],
        "desc": ["da", "db", "dc"],
        "qty_col": [5, -2, 10],
        "ts": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "price_col": [15.0, 10.0, 25.0],
        "cid": ["C1", "C2", "C3"],
        "geo": ["US", "US", "CA"],
        "ord": ["O1", "O2", "O3"]
    })

    loader = DataLoader(build=False)
    try:
        loader._materialize_frame("bronze_orders", df, temporary=False)
        loader.build_silver(cfg)

        loader.build_gold(cfg)

        res = loader.query("SELECT * FROM gold_metrics")
        assert len(res) == 1
        assert res.iloc[0]["custom_total_revenue"] == 75.0
        assert res.iloc[0]["custom_total_orders"] == 1
        assert res.iloc[0]["custom_total_customers"] == 1
        assert res.iloc[0]["custom_average_order_value"] == 75.0

        # Assert country revenue
        country_df = loader.query("SELECT * FROM gold_country_revenue")
        assert len(country_df) == 1
        assert country_df.iloc[0]["geo"] == "US"
        assert country_df.iloc[0]["rev"] == 75.0

        # Assert product sales
        product_df = loader.query("SELECT * FROM gold_product_sales")
        assert len(product_df) == 1
        assert product_df.iloc[0]["pid"] == "A"
        assert product_df.iloc[0]["total_quantity"] == 5
        assert product_df.iloc[0]["rev"] == 75.0
    finally:
        loader.close()
