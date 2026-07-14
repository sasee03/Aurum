"""Bronze validator tests."""

from builders import loader_from, make_rows, to_df

from src.config_loader import load_dataset_config
from src.bronze_validator import (
    b1_source_to_bronze_count,
    b3_empty_table,
    b4_required_columns,
    b8_duplicates,
    validate_bronze,
)
from src.contracts import FAIL, PASS, WARN

CFG = load_dataset_config()


def test_b1_source_and_bronze_match():
    rows = make_rows(100)
    loader = loader_from(raw_orders=to_df(rows), bronze_orders=to_df(rows))
    assert b1_source_to_bronze_count(loader, CFG).status == PASS


def test_b1_source_and_bronze_mismatch():
    raw = make_rows(100)
    bronze = make_rows(90)
    loader = loader_from(raw_orders=to_df(raw), bronze_orders=to_df(bronze))
    assert b1_source_to_bronze_count(loader, CFG).status == FAIL


def test_b3_empty_table_fails():
    empty = to_df(make_rows(0))
    loader = loader_from(bronze_orders=empty)
    assert b3_empty_table(loader, CFG).status == FAIL


def test_b4_missing_required_column_fails():
    rows = make_rows(10)
    df = to_df(rows).drop(columns=["country"])
    loader = loader_from(bronze_orders=df)
    assert b4_required_columns(loader, CFG).status == FAIL


def test_b4_all_columns_present_passes():
    loader = loader_from(bronze_orders=to_df(make_rows(10)))
    assert b4_required_columns(loader, CFG).status == PASS


def test_b8_no_duplicates_passes():
    loader = loader_from(bronze_orders=to_df(make_rows(50)))
    assert b8_duplicates(loader, CFG).status == PASS


def test_b8_duplicates_warn():
    # 50 unique rows + 1 exact duplicate of the first row -> small dup share -> WARN.
    rows = make_rows(50)
    rows.append(dict(rows[0]))
    loader = loader_from(bronze_orders=to_df(rows))
    assert b8_duplicates(loader, CFG).status == WARN


def test_validate_bronze_stops_after_required_schema_failure():
    rows = to_df(make_rows(10)).drop(columns=["quantity"])
    loader = loader_from(raw_orders=rows, bronze_orders=rows)

    results = validate_bronze(loader)
    assert [result.check_id for result in results] == ["B1", "B2", "B3", "B4"]
    assert results[-1].status == FAIL


def test_b7_dynamic_numeric_typing():
    import pandas as pd
    import yaml
    from src.bronze_validator import b7_negative_values
    from src.config_loader import _parse_raw_config
    from src.data_loader import DataLoader

    cfg_raw = yaml.safe_load('''
    dataset:
      name: Test
      currency: USD
      domain: retail
      geography_label: market
    tables:
      raw: raw_orders
      bronze: bronze_orders
      silver: silver_orders
      gold:
        metrics: gold_metrics
        country_revenue: gold_country_revenue
        product_sales: gold_product_sales
    columns:
      primary_key: pk
      order_id: ord
      order_id_expression: "{order_id}"
      product_id: pid
      product_description: desc
      customer_id: cid
      timestamp: ts
      quantity: units_custom
      unit_price: price_custom
      geography: geo
      revenue: rev
      line_item_key: [pk, pid, cid, ts]
    metrics:
      revenue_formula: "units_custom * price_custom"
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
        "units_custom": [1, -2, 3],
        "price_custom": [10.0, 20.0, -5.5]
    })
    
    loader = DataLoader(build=False)
    try:
        loader._materialize_frame("bronze_orders", df, temporary=False)
        result = b7_negative_values(loader, cfg)
        assert result.status == WARN
        assert result.observed["negative_quantity"] == 1
        assert result.observed["negative_unit_price"] == 1
    finally:
        loader.close()
