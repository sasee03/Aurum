"""Tests for Codex QA fixes: revenue tolerance honesty, freshness, orphan FK."""

from datetime import date, timedelta

import pandas as pd

from builders import loader_from, make_rows, to_df, to_silver

from src.contracts import FAIL, WARN
from src.rule_library import _check_consistency_fk, _check_freshness
from src.table_specs import TABLE_SPECS


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
