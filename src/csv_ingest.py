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

TEXT_COLUMNS: tuple[str, ...] = ("invoice_no", "stock_code", "description", "country")
NUMERIC_COLUMNS: tuple[str, ...] = ("quantity", "unit_price")

# Upload limits — reject before parsing huge payloads into memory.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_UPLOAD_ROWS = 500_000


class CsvSchemaMismatch(Exception):
    """Raised when an uploaded CSV does not match the expected raw_orders schema."""

    def __init__(
        self,
        missing_columns: list[str],
        extra_columns: list[str] | None = None,
        *,
        error: str | None = None,
    ):
        self.missing_columns = missing_columns
        self.extra_columns = extra_columns or []
        self.expected_columns = list(RAW_ORDERS_COLUMNS)
        self.error = error or "This file doesn't match the expected schema."
        super().__init__(self.error)


def _format_byte_limit(limit: int) -> str:
    if limit >= 1024 * 1024:
        return f"{limit // (1024 * 1024)}MB"
    return f"{limit:,} bytes"


def _schema_error(message: str) -> CsvSchemaMismatch:
    return CsvSchemaMismatch(missing_columns=[], error=message)


def validate_raw_orders_columns(columns: list[str]) -> None:
    """Raise CsvSchemaMismatch if required columns are absent."""
    normalized = {col.strip() for col in columns}
    missing = [col for col in RAW_ORDERS_COLUMNS if col not in normalized]
    if missing:
        if not normalized.intersection(RAW_ORDERS_COLUMNS):
            raise _schema_error("file is not a valid CSV")
        raise CsvSchemaMismatch(missing_columns=missing)


def validate_row_count(df: pd.DataFrame) -> None:
    """Raise CsvSchemaMismatch if the file has no data rows or exceeds the row cap."""
    if len(df) == 0:
        raise _schema_error("file contains no data rows")
    if len(df) > MAX_UPLOAD_ROWS:
        raise _schema_error(
            f"file exceeds maximum of {MAX_UPLOAD_ROWS:,} data rows"
        )


def validate_required_non_null(df: pd.DataFrame) -> None:
    """Reject uploads with blank or null values in required columns (option a)."""
    for column in RAW_ORDERS_COLUMNS:
        series = df[column]
        blank = series.isna() | series.astype(str).str.strip().eq("")
        if blank.any():
            count = int(blank.sum())
            raise _schema_error(
                f"Required column '{column}' has {count} missing or blank value(s)"
            )


def validate_text_column(column: str, series: pd.Series) -> None:
    """Raise CsvSchemaMismatch if a text column was inferred as numeric."""
    if pd.api.types.is_numeric_dtype(series):
        raise _schema_error(f"{column} must be a text/string value, not numeric")


def validate_numeric_column(column: str, series: pd.Series) -> None:
    """Raise CsvSchemaMismatch if a numeric column is not numeric."""
    if pd.api.types.is_numeric_dtype(series):
        return
    coerced = pd.to_numeric(series, errors="coerce")
    if series.notna().any() and coerced.isna().any():
        raise _schema_error(f"{column} must be a numeric value")


def validate_invoice_no_text(series: pd.Series) -> None:
    """Raise CsvSchemaMismatch if invoice_no was inferred as numeric (Olist uses text ids)."""
    validate_text_column("invoice_no", series)


def validate_column_dtypes(df: pd.DataFrame) -> None:
    """Validate text/numeric/date dtypes for all required columns."""
    for column in TEXT_COLUMNS:
        validate_text_column(column, df[column])
    for column in NUMERIC_COLUMNS:
        validate_numeric_column(column, df[column])
    if pd.api.types.is_numeric_dtype(df["invoice_date"]):
        raise _schema_error("invoice_date must be a date/text value, not numeric")


def validate_raw_orders_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the same Olist-shape checks used for CSV uploads to an in-memory frame.

    Raises CsvSchemaMismatch on mismatch — never falls back to demo data.
    """
    # Intentional broadening: accept case-insensitive/trimmed headers from CSV and connectors.
    renamed = {col: str(col).strip().lower() for col in df.columns}
    normalized = df.rename(columns=renamed)
    validate_raw_orders_columns(list(normalized.columns))
    validate_row_count(normalized)
    out = normalized[list(RAW_ORDERS_COLUMNS)].copy()
    validate_required_non_null(out)
    validate_column_dtypes(out)
    out["customer_id"] = out["customer_id"].astype(str)
    return out


def parse_raw_orders_csv(source: Union[str, Path, BinaryIO, bytes]) -> pd.DataFrame:
    """Read a CSV and return a normalized raw_orders DataFrame.

    Raises CsvSchemaMismatch on shape mismatch — never falls back to demo data.
    """
    raw_bytes: bytes | None = None
    if isinstance(source, bytes):
        raw_bytes = source
        if len(raw_bytes) == 0:
            raise _schema_error("file is empty")
        if len(raw_bytes) > MAX_UPLOAD_BYTES:
            raise _schema_error(
                f"file exceeds maximum size of {_format_byte_limit(MAX_UPLOAD_BYTES)}"
            )
        buffer: BinaryIO = io.BytesIO(raw_bytes)
    else:
        buffer = source  # type: ignore[assignment]

    try:
        df = pd.read_csv(buffer)
    except pd.errors.EmptyDataError:
        raise _schema_error("file is empty or not a valid CSV") from None
    except UnicodeDecodeError:
        raise _schema_error("file is not a valid CSV") from None
    except pd.errors.ParserError:
        raise _schema_error("file is not a valid CSV") from None

    return validate_raw_orders_frame(df)


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
