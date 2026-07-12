"""Tests for dataset config loader."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.config_loader import default_config_path, load_dataset_config


def test_default_config_path_points_to_olist_yaml():
    assert default_config_path().name == "olist.yaml"
    assert default_config_path().exists()


def test_load_olist_yaml_has_required_sections():
    cfg = load_dataset_config()
    assert cfg.dataset.name == "Olist Brazilian E-Commerce"
    assert cfg.dataset.currency == "BRL"
    assert cfg.dataset.domain == "retail"
    assert cfg.dataset.geography_label == "state"
    assert cfg.tables.bronze == "bronze_orders"
    assert cfg.tables.silver == "silver_orders"
    assert cfg.tables.gold == "gold_metrics"
    assert cfg.columns.primary_key == "invoice_no"
    assert cfg.columns.customer_id == "customer_id"
    assert cfg.columns.timestamp == "invoice_date"
    assert cfg.columns.quantity == "quantity"
    assert cfg.columns.unit_price == "unit_price"
    assert cfg.columns.geography == "country"
    assert cfg.columns.revenue == "net_revenue"
    assert cfg.columns.resolve_line_item_key() == (
        "invoice_no", "stock_code", "customer_id", "invoice_date",
    )
    assert cfg.columns.resolve_business_key() == "REGEXP_REPLACE(invoice_no, '_[0-9]+$', '')"
    assert cfg.metrics.revenue_formula == "quantity * unit_price"
    assert cfg.metrics.top_revenue_dimension == "country"
    assert cfg.metrics.top_revenue_label == "state"


def test_env_override(tmp_path, monkeypatch):
    override = tmp_path / "custom.yaml"
    override.write_text(
        textwrap.dedent(
            """
            dataset:
              name: Custom Dataset
              currency: USD
              domain: retail
              geography_label: region
            tables:
              bronze: raw_bronze
              silver: raw_silver
              gold: raw_gold
            columns:
              primary_key: id
              customer_id: cust_id
              timestamp: created_at
              quantity: qty
              unit_price: price
              geography: region
              revenue: revenue
              product_id: prod_id
              product_description: prod_desc
              order_id: ord_id
              order_id_expression: ord_id
              line_item_key: [id, prod_id, cust_id, created_at]
            metrics:
              revenue_formula: "qty * price"
              top_revenue_dimension: region
              top_revenue_label: region
              total_revenue_metric: t_rev
              total_orders_metric: t_ord
              total_customers_metric: t_cust
              average_order_value_metric: a_o_v
              aggregate_revenue_metric: a_rev
              total_quantity_metric: t_qty
            """
        ).strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("AURUM_DATASET_CONFIG", str(override))
    cfg = load_dataset_config()
    assert cfg.dataset.name == "Custom Dataset"
    assert cfg.tables.silver == "raw_silver"


def test_missing_config_raises_clear_error(tmp_path):
    missing = tmp_path / "missing.yaml"
    with pytest.raises(FileNotFoundError, match="Dataset config not found"):
        load_dataset_config(missing)


def test_missing_section_raises_clear_error(tmp_path):
    incomplete = tmp_path / "incomplete.yaml"
    incomplete.write_text(
        "dataset:\n  name: X\n  currency: BRL\n  domain: retail\n  geography_label: state\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing required section: 'tables'"):
        load_dataset_config(incomplete)


def test_missing_required_key_raises_clear_error(tmp_path):
    incomplete = tmp_path / "missing_key.yaml"
    incomplete.write_text(
        textwrap.dedent(
            """
            dataset:
              name: X
              currency: BRL
              domain: retail
            tables:
              bronze: bronze_orders
              silver: silver_orders
              gold: gold_metrics
            columns:
              primary_key: invoice_no
              customer_id: customer_id
              timestamp: invoice_date
              quantity: quantity
              unit_price: unit_price
              geography: country
              revenue: net_revenue
              product_id: stock_code
              product_description: description
              order_id: invoice_no
              order_id_expression: invoice_no
            metrics:
              revenue_formula: "quantity * unit_price"
              top_revenue_dimension: country
              top_revenue_label: state
              total_revenue_metric: total_revenue
              total_orders_metric: total_orders
              total_customers_metric: total_customers
              average_order_value_metric: average_order_value
              aggregate_revenue_metric: total_revenue
              total_quantity_metric: total_quantity
            """
        ).strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="section 'dataset' is missing required key"):
        load_dataset_config(incomplete)
