"""Tests for Codex QA fixes: revenue tolerance honesty, freshness, orphan FK."""

from datetime import date, timedelta

import pandas as pd

from builders import loader_from, make_rows, to_df, to_silver

from src.contracts import FAIL, WARN
from src.config_loader import (
    AurumDatasetConfig,
    ColumnsInfo,
    DatasetInfo,
    MetricsInfo,
    TablesInfo,
)
from src.detection_stack import run_detection_stack
from src.rule_library import _check_consistency_fk, _check_freshness
from src.table_specs import TABLE_SPECS, build_table_specs


def test_future_date_shift_fails_freshness_check():
    rows = make_rows(20)
    df = to_df(rows)
    future = (date.today() + timedelta(days=30)).isoformat()
    df["invoice_date"] = future
    loader = loader_from(bronze_orders=df)
    spec = dict(TABLE_SPECS["bronze_orders"])
    results = _check_freshness(loader, "bronze_orders", spec)
    assert len(results) == 1
    assert results[0].check_id == "L1-BRO-TIME-FRESH"
    assert results[0].status == FAIL
    assert "future" in results[0].detail.lower()


def test_stale_dates_warn_freshness_check():
    rows = make_rows(20)
    df = to_df(rows)
    stale = (date.today() - timedelta(days=10)).isoformat()
    df["invoice_date"] = stale
    loader = loader_from(bronze_orders=df)
    spec = dict(TABLE_SPECS["bronze_orders"])
    spec["expected_freshness_days"] = 3
    results = _check_freshness(loader, "bronze_orders", spec)
    assert len(results) == 1
    assert results[0].status == WARN
    assert "stale" in results[0].detail.lower()


def test_orphan_customer_fk_fails_when_dimension_exists():
    bronze = make_rows(10)
    silver = to_silver(bronze)
    silver.loc[0, "customer_id"] = 999999
    customers = pd.DataFrame(
        {"customer_id": [r["customer_id"] for r in bronze], "country": ["UK"] * 10}
    )
    loader = loader_from(
        bronze_orders=to_df(bronze),
        silver_orders=silver,
        customers=customers,
    )
    spec = dict(TABLE_SPECS["silver_orders"])
    results = _check_consistency_fk(loader, "silver_orders", spec)
    fk_hits = [r for r in results if r.check_id == "L1-SIL-CONS-FK-CUST"]
    assert len(fk_hits) == 1
    assert fk_hits[0].status == FAIL
    assert fk_hits[0].observed == 1


def test_detection_stack_layer_1_uses_custom_dataset_config_specs():
    cfg = AurumDatasetConfig(
        dataset=DatasetInfo(
            name="Custom Orders",
            currency="USD",
            domain="retail",
            geography_label="market",
        ),
        tables=TablesInfo(bronze="bronze_orders", silver="silver_orders", gold="gold_metrics"),
        columns=ColumnsInfo(
            primary_key="SaleLineId",
            customer_id="BuyerRef",
            timestamp="SoldAt",
            quantity="Units",
            unit_price="PriceEach",
            geography="Market",
            revenue="LineRevenue",
            product_id="Sku",
            product_description="ItemName",
            order_id="OrderRef",
            order_id_expression="{order_id}",
            line_item_key=("SaleLineId", "Sku", "BuyerRef", "SoldAt"),
        ),
        metrics=MetricsInfo(
            revenue_formula="Units * PriceEach",
            order_id_expression="{order_id}",
            top_revenue_dimension="Market",
            top_revenue_label="Market",
            total_revenue_metric="total_revenue",
            total_orders_metric="total_orders",
            total_customers_metric="total_customers",
            average_order_value_metric="average_order_value",
            aggregate_revenue_metric="LineRevenue",
            total_quantity_metric="total_quantity",
        ),
    )

    specs = build_table_specs(cfg)
    spec_text = str(specs)
    assert "SaleLineId" in specs["bronze_orders"]["primary_key"]
    assert "OrderRef" in specs["bronze_orders"]["mandatory_columns"]
    assert "Sku" in specs["silver_orders"]["business_key"]
    assert "LineRevenue" in specs["silver_orders"]["mandatory_columns"]
    assert "invoice_no" not in spec_text
    assert "stock_code" not in spec_text

    raw = pd.DataFrame(
        {
            "SaleLineId": ["L1", "L2"],
            "OrderRef": ["O1", "O2"],
            "Sku": ["A", "B"],
            "ItemName": ["Alpha", "Beta"],
            "BuyerRef": ["C1", "C2"],
            "SoldAt": ["2026-01-01", "2026-01-02"],
            "Units": [2, 3],
            "PriceEach": [10.0, 30.0],
            "Market": ["US", "CA"],
        }
    )
    silver = raw.copy()
    silver["LineRevenue"] = silver["Units"] * silver["PriceEach"]
    gold = pd.DataFrame(
        [
            {
                "total_revenue": 110.0,
                "total_orders": 2,
                "total_customers": 2,
                "average_order_value": 55.0,
            }
        ]
    )
    loader = loader_from(raw_orders=raw, bronze_orders=raw, silver_orders=silver, gold_metrics=gold)

    results = run_detection_stack(loader, cfg).layer_1_rules
    assert results
    assert {result.check_id for result in results} >= {
        "L1-RAW-COMP-NULL",
        "L1-BRO-COMP-NULL",
        "L1-SIL-COMP-NULL",
        "L1-GOL-COMP-NULL",
    }
    assert all(result.status != "SKIPPED" for result in results)
    assert "invoice_no" not in str([result.to_dict() for result in results])
    assert "stock_code" not in str([result.to_dict() for result in results])
