"""Load dataset schema configuration from YAML."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

REQUIRED_SECTIONS = ("dataset", "tables", "columns", "metrics")

_DATASET_FIELDS = ("name", "currency", "domain", "geography_label")
_TABLE_FIELDS = ("bronze", "silver", "gold")
_COLUMN_FIELDS = (
    "primary_key",
    "customer_id",
    "timestamp",
    "quantity",
    "unit_price",
    "geography",
    "revenue",
)
_METRIC_FIELDS = ("revenue_formula", "top_revenue_dimension", "top_revenue_label")


@dataclass(frozen=True)
class DatasetInfo:
    name: str
    currency: str
    domain: str
    geography_label: str


@dataclass(frozen=True)
class TablesInfo:
    bronze: str
    silver: str
    gold: str


@dataclass(frozen=True)
class ColumnsInfo:
    primary_key: str
    customer_id: str
    timestamp: str
    quantity: str
    unit_price: str
    geography: str
    revenue: str


@dataclass(frozen=True)
class MetricsInfo:
    revenue_formula: str
    top_revenue_dimension: str
    top_revenue_label: str


@dataclass(frozen=True)
class AurumDatasetConfig:
    dataset: DatasetInfo
    tables: TablesInfo
    columns: ColumnsInfo
    metrics: MetricsInfo


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "configs" / "olist.yaml"


def _require_mapping(raw: Any, section: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(
            f"Dataset config section '{section}' must be a mapping; got {type(raw).__name__}."
        )
    return raw


def _require_fields(section: str, mapping: Mapping[str, Any], fields: tuple[str, ...]) -> None:
    missing = [field for field in fields if field not in mapping]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(
            f"Dataset config section '{section}' is missing required key(s): {joined}."
        )


def _parse_raw_config(raw: Any, source: str) -> AurumDatasetConfig:
    if not isinstance(raw, Mapping):
        raise ValueError(f"Dataset config at {source} must be a YAML mapping at the top level.")

    for section in REQUIRED_SECTIONS:
        if section not in raw:
            raise ValueError(
                f"Dataset config at {source} is missing required section: '{section}'."
            )

    dataset_raw = _require_mapping(raw["dataset"], "dataset")
    tables_raw = _require_mapping(raw["tables"], "tables")
    columns_raw = _require_mapping(raw["columns"], "columns")
    metrics_raw = _require_mapping(raw["metrics"], "metrics")

    _require_fields("dataset", dataset_raw, _DATASET_FIELDS)
    _require_fields("tables", tables_raw, _TABLE_FIELDS)
    _require_fields("columns", columns_raw, _COLUMN_FIELDS)
    _require_fields("metrics", metrics_raw, _METRIC_FIELDS)

    return AurumDatasetConfig(
        dataset=DatasetInfo(
            name=str(dataset_raw["name"]),
            currency=str(dataset_raw["currency"]),
            domain=str(dataset_raw["domain"]),
            geography_label=str(dataset_raw["geography_label"]),
        ),
        tables=TablesInfo(
            bronze=str(tables_raw["bronze"]),
            silver=str(tables_raw["silver"]),
            gold=str(tables_raw["gold"]),
        ),
        columns=ColumnsInfo(
            primary_key=str(columns_raw["primary_key"]),
            customer_id=str(columns_raw["customer_id"]),
            timestamp=str(columns_raw["timestamp"]),
            quantity=str(columns_raw["quantity"]),
            unit_price=str(columns_raw["unit_price"]),
            geography=str(columns_raw["geography"]),
            revenue=str(columns_raw["revenue"]),
        ),
        metrics=MetricsInfo(
            revenue_formula=str(metrics_raw["revenue_formula"]),
            top_revenue_dimension=str(metrics_raw["top_revenue_dimension"]),
            top_revenue_label=str(metrics_raw["top_revenue_label"]),
        ),
    )


def load_dataset_config(path: Optional[os.PathLike[str] | str] = None) -> AurumDatasetConfig:
    """Load dataset config from YAML.

    Defaults to ``configs/olist.yaml`` relative to the repo root.
    Override path with the ``AURUM_DATASET_CONFIG`` environment variable.
    """
    if path is None:
        env_path = os.environ.get("AURUM_DATASET_CONFIG")
        path = Path(env_path) if env_path else default_config_path()
    else:
        path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Dataset config not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Dataset config at {path} is not valid YAML: {exc}") from exc

    return _parse_raw_config(raw, str(path))
