"""CSV ingestion for user-uploaded Olist-shaped raw order files."""

from __future__ import annotations

import io
from pathlib import Path
from typing import BinaryIO, Union

import pandas as pd

from src.data_loader import DataLoader
from src.report_builder import build_report

# Must match data/raw/raw_orders.csv header (Olist raw ingest shape).
RAW_ORDERS_COLUMNS: tuple[str, ...] = (
    "invoice_no",
    "stock_code",
    "description",
    "quantity",
    "invoice_date",
    "unit_price",
    "customer_id",
    "country",
)


class CsvSchemaMismatch(Exception):
    """Raised when an uploaded CSV does not match the expected raw_orders schema."""

    def __init__(self, missing_columns: list[str], extra_columns: list[str] | None = None):
        self.missing_columns = missing_columns
        self.extra_columns = extra_columns or []
        self.expected_columns = list(RAW_ORDERS_COLUMNS)
        super().__init__(
            "This file doesn't match the expected schema."
        )


def validate_raw_orders_columns(columns: list[str]) -> None:
    """Raise CsvSchemaMismatch if required columns are absent."""
    normalized = {col.strip() for col in columns}
    missing = [col for col in RAW_ORDERS_COLUMNS if col not in normalized]
    if missing:
        raise CsvSchemaMismatch(missing_columns=missing)


def parse_raw_orders_csv(source: Union[str, Path, BinaryIO, bytes]) -> pd.DataFrame:
    """Read a CSV and return a normalized raw_orders DataFrame.

  Raises CsvSchemaMismatch on shape mismatch — never falls back to demo data.
    """
    if isinstance(source, bytes):
        buffer: BinaryIO = io.BytesIO(source)
    else:
        buffer = source  # type: ignore[assignment]
    df = pd.read_csv(buffer)
    validate_raw_orders_columns(list(df.columns))
    return df[list(RAW_ORDERS_COLUMNS)].copy()


def materialize_upload_pipeline(loader: DataLoader) -> None:
    """Bronze → Silver → Gold on a loader that already has raw_orders materialized."""
    loader.conn.execute("CREATE OR REPLACE TABLE bronze_orders AS SELECT * FROM raw_orders")
    loader.build_silver()
    loader._create_reconciliation_indexes()
    loader.build_gold()


def run_validation_from_raw_orders(df: pd.DataFrame, run_id: str) -> dict:
    """Build a full validation report from an in-memory raw_orders frame."""
    loader = DataLoader.from_frames({"raw_orders": df})
    try:
        materialize_upload_pipeline(loader)
        return build_report(loader, run_id=run_id)
    finally:
        loader.close()
