"""CSV ingestion for user-uploaded Olist-shaped raw order files."""

from __future__ import annotations

import io
from pathlib import Path
from typing import BinaryIO, Union

import pandas as pd

from src.data_loader import DataLoader
from src.report_builder import build_report
from src.config_loader import load_dataset_config, AurumDatasetConfig



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
        expected_columns: list[str] | None = None,
    ):
        self.missing_columns = missing_columns
        self.extra_columns = extra_columns or []
        if expected_columns is None:
            self.expected_columns = load_dataset_config().columns.resolve_raw_required_columns()
        else:
            self.expected_columns = expected_columns
        self.error = error or "This file doesn't match the expected schema."
        super().__init__(self.error)


def _format_byte_limit(limit: int) -> str:
    if limit >= 1024 * 1024:
        return f"{limit // (1024 * 1024)}MB"
    return f"{limit:,} bytes"


def _schema_error(message: str, expected_columns: list[str] | None = None) -> CsvSchemaMismatch:
    return CsvSchemaMismatch(missing_columns=[], error=message, expected_columns=expected_columns)


def validate_raw_orders_columns(columns: list[str], cfg: AurumDatasetConfig) -> None:
    """Raise CsvSchemaMismatch if required columns are absent."""
    normalized = {col.strip() for col in columns}
    raw_cols = cfg.columns.resolve_raw_required_columns()
    missing = [col for col in raw_cols if col not in normalized]
    if missing:
        if not normalized.intersection(raw_cols):
            raise _schema_error("file is not a valid CSV", expected_columns=raw_cols)
        raise CsvSchemaMismatch(missing_columns=missing, expected_columns=raw_cols)


def validate_row_count(df: pd.DataFrame, expected_columns: list[str] | None = None) -> None:
    """Raise CsvSchemaMismatch if the file has no data rows or exceeds the row cap."""
    if len(df) == 0:
        raise _schema_error("file contains no data rows", expected_columns=expected_columns)
    if len(df) > MAX_UPLOAD_ROWS:
        raise _schema_error(
            f"file exceeds maximum of {MAX_UPLOAD_ROWS:,} data rows",
            expected_columns=expected_columns
        )


def validate_required_non_null(df: pd.DataFrame, cfg: AurumDatasetConfig) -> None:
    """Reject uploads with blank or null values in required columns (option a)."""
    raw_cols = cfg.columns.resolve_raw_required_columns()
    for column in raw_cols:
        series = df[column]
        blank = series.isna() | series.astype(str).str.strip().eq("")
        if blank.any():
            count = int(blank.sum())
            raise _schema_error(
                f"Required column '{column}' has {count} missing or blank value(s)",
                expected_columns=raw_cols
            )


def validate_text_column(column: str, series: pd.Series, expected_columns: list[str] | None = None) -> None:
    """Raise CsvSchemaMismatch if a text column was inferred as numeric."""
    if pd.api.types.is_numeric_dtype(series):
        raise _schema_error(f"{column} must be a text/string value, not numeric", expected_columns=expected_columns)


def validate_numeric_column(column: str, series: pd.Series, expected_columns: list[str] | None = None) -> None:
    """Raise CsvSchemaMismatch if a numeric column is not numeric."""
    if pd.api.types.is_numeric_dtype(series):
        return
    coerced = pd.to_numeric(series, errors="coerce")
    if series.notna().any() and coerced.isna().any():
        raise _schema_error(f"{column} must be a numeric value", expected_columns=expected_columns)


def validate_column_dtypes(df: pd.DataFrame, cfg: AurumDatasetConfig) -> None:
    """Validate text/numeric/date dtypes for all required columns."""
    text_cols = [
        cfg.columns.primary_key,
        cfg.columns.product_id,
        cfg.columns.product_description,
        cfg.columns.geography,
    ]
    numeric_cols = [cfg.columns.quantity, cfg.columns.unit_price]
    raw_cols = cfg.columns.resolve_raw_required_columns()
    for column in text_cols:
        validate_text_column(column, df[column], expected_columns=raw_cols)
    for column in numeric_cols:
        validate_numeric_column(column, df[column], expected_columns=raw_cols)
    if pd.api.types.is_numeric_dtype(df[cfg.columns.timestamp]):
        raise _schema_error(f"{cfg.columns.timestamp} must be a date/text value, not numeric", expected_columns=raw_cols)


def validate_raw_orders_frame(df: pd.DataFrame, cfg: Optional[AurumDatasetConfig] = None) -> pd.DataFrame:
    """Apply the same Olist-shape checks used for CSV uploads to an in-memory frame.

    Raises CsvSchemaMismatch on mismatch — never falls back to demo data.
    """
    if cfg is None:
        cfg = load_dataset_config()
    raw_cols = cfg.columns.resolve_raw_required_columns()
    # Intentional broadening: accept case-insensitive/trimmed headers from CSV and connectors.
    renamed = {col: str(col).strip().lower() for col in df.columns}
    normalized = df.rename(columns=renamed)
    validate_raw_orders_columns(list(normalized.columns), cfg)
    validate_row_count(normalized, expected_columns=raw_cols)
    out = normalized[raw_cols].copy()
    validate_required_non_null(out, cfg)
    validate_column_dtypes(out, cfg)
    customer_col = cfg.columns.customer_id
    out[customer_col] = out[customer_col].astype(str)
    return out


def parse_raw_orders_csv(source: Union[str, Path, BinaryIO, bytes], cfg: Optional[AurumDatasetConfig] = None) -> pd.DataFrame:
    """Read a CSV and return a normalized raw_orders DataFrame.

    Raises CsvSchemaMismatch on shape mismatch — never falls back to demo data.
    """
    if cfg is None:
        cfg = load_dataset_config()
    raw_cols = cfg.columns.resolve_raw_required_columns()

    raw_bytes: bytes | None = None
    if isinstance(source, bytes):
        raw_bytes = source
        if len(raw_bytes) == 0:
            raise _schema_error("file is empty", expected_columns=raw_cols)
        if len(raw_bytes) > MAX_UPLOAD_BYTES:
            raise _schema_error(
                f"file exceeds maximum size of {_format_byte_limit(MAX_UPLOAD_BYTES)}",
                expected_columns=raw_cols
            )
        buffer: BinaryIO = io.BytesIO(raw_bytes)
    else:
        buffer = source  # type: ignore[assignment]

    try:
        df = pd.read_csv(buffer)
    except pd.errors.EmptyDataError:
        raise _schema_error("file is empty or not a valid CSV", expected_columns=raw_cols) from None
    except UnicodeDecodeError:
        raise _schema_error("file is not a valid CSV", expected_columns=raw_cols) from None
    except pd.errors.ParserError:
        raise _schema_error("file is not a valid CSV", expected_columns=raw_cols) from None

    return validate_raw_orders_frame(df, cfg)


def materialize_upload_pipeline(
    loader: DataLoader,
    cfg: Optional[AurumDatasetConfig] = None,
) -> None:
    """Bronze → Silver → Gold on a loader that already has raw_orders materialized."""
    if cfg is None:
        cfg = load_dataset_config()
    loader.conn.execute(f"CREATE OR REPLACE TABLE {cfg.tables.bronze} AS SELECT * FROM {cfg.tables.raw}")
    loader.build_silver(cfg)
    loader._create_reconciliation_indexes(cfg)
    loader.build_silver_assessment(cfg)
    loader.build_gold(cfg)


def run_validation_from_raw_orders(
    df: pd.DataFrame,
    run_id: str,
    cfg: Optional[AurumDatasetConfig] = None,
) -> tuple[dict, str]:
    """Build a full validation report from an in-memory raw_orders frame."""
    if cfg is None:
        cfg = load_dataset_config()
    loader = DataLoader.from_frames({cfg.tables.raw: df})
    try:
        materialize_upload_pipeline(loader, cfg)
        report = build_report(loader, run_id=run_id, cfg=cfg)
        loader.retain_schema_on_close = True
        return report, loader.session_schema
    finally:
        loader.close()
