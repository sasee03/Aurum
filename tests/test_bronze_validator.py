"""Bronze validator tests."""

from builders import loader_from, make_rows, to_df

from src.bronze_validator import (
    b1_source_to_bronze_count,
    b3_empty_table,
    b4_required_columns,
    b8_duplicates,
)
from src.contracts import FAIL, PASS, WARN


def test_b1_source_and_bronze_match():
    rows = make_rows(100)
    loader = loader_from(raw_orders=to_df(rows), bronze_orders=to_df(rows))
    assert b1_source_to_bronze_count(loader).status == PASS


def test_b1_source_and_bronze_mismatch():
    raw = make_rows(100)
    bronze = make_rows(90)
    loader = loader_from(raw_orders=to_df(raw), bronze_orders=to_df(bronze))
    assert b1_source_to_bronze_count(loader).status == FAIL


def test_b3_empty_table_fails():
    empty = to_df(make_rows(0))
    loader = loader_from(bronze_orders=empty)
    assert b3_empty_table(loader).status == FAIL


def test_b4_missing_required_column_fails():
    rows = make_rows(10)
    df = to_df(rows).drop(columns=["country"])
    loader = loader_from(bronze_orders=df)
    assert b4_required_columns(loader).status == FAIL


def test_b4_all_columns_present_passes():
    loader = loader_from(bronze_orders=to_df(make_rows(10)))
    assert b4_required_columns(loader).status == PASS


def test_b8_no_duplicates_passes():
    loader = loader_from(bronze_orders=to_df(make_rows(50)))
    assert b8_duplicates(loader).status == PASS


def test_b8_duplicates_warn():
    # 50 unique rows + 1 exact duplicate of the first row -> small dup share -> WARN.
    rows = make_rows(50)
    rows.append(dict(rows[0]))
    loader = loader_from(bronze_orders=to_df(rows))
    assert b8_duplicates(loader).status == WARN
