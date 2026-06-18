"""Silver validator tests."""

from builders import loader_from, make_rows, to_df, to_silver

from src.contracts import FAIL, PASS
from src.silver_validator import (
    s1_drop_percentage,
    s5_quantity_positive,
    s6_unit_price_positive,
    s8_valid_records_removed,
)


def test_s1_normal_drop_passes():
    bronze = make_rows(100)
    silver = to_silver(bronze[:95])  # 5% drop, within configured tolerance
    loader = loader_from(bronze_orders=to_df(bronze), silver_orders=silver)
    assert s1_drop_percentage(loader).status == PASS


def test_s1_extreme_drop_fails():
    bronze = make_rows(100)
    silver = to_silver(bronze[:72])  # 28% drop
    loader = loader_from(bronze_orders=to_df(bronze), silver_orders=silver)
    assert s1_drop_percentage(loader).status == FAIL


def test_s8_valid_records_removed_fails():
    bronze = make_rows(100)  # all valid (quantity=1, unit_price=10)
    silver = to_silver(bronze[:76])  # 24 valid records dropped
    loader = loader_from(bronze_orders=to_df(bronze), silver_orders=silver)
    result = s8_valid_records_removed(loader)
    assert result.status == FAIL
    assert result.observed == 24


def test_s8_all_present_passes():
    bronze = make_rows(100)
    silver = to_silver(bronze)
    loader = loader_from(bronze_orders=to_df(bronze), silver_orders=silver)
    assert s8_valid_records_removed(loader).status == PASS


def test_s5_quantity_nonpositive_fails():
    silver = to_silver(make_rows(10) + make_rows(1, start=11, quantity=0))
    loader = loader_from(silver_orders=silver)
    assert s5_quantity_positive(loader).status == FAIL


def test_s5_quantity_positive_passes():
    loader = loader_from(silver_orders=to_silver(make_rows(10)))
    assert s5_quantity_positive(loader).status == PASS


def test_s6_unit_price_nonpositive_fails():
    silver = to_silver(make_rows(10) + make_rows(1, start=11, unit_price=0.0))
    loader = loader_from(silver_orders=silver)
    assert s6_unit_price_positive(loader).status == FAIL
