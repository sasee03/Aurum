"""Load dataset schema configuration from YAML."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

REQUIRED_SECTIONS = ("dataset", "tables", "columns", "metrics")

_DATASET_FIELDS = ("name", "currency", "domain", "geography_label")
_TABLE_FIELDS = ("raw", "bronze", "silver", "gold")
_GOLD_TABLE_FIELDS = ("metrics", "country_revenue", "product_sales")
_COLUMN_FIELDS = (
    "primary_key",
    "customer_id",
    "timestamp",
    "quantity",
    "unit_price",
    "geography",
    "revenue",
    "product_id",
    "product_description",
    "order_id",
    "order_id_expression",
    "line_item_key",
)
_METRIC_FIELDS = (
    "revenue_formula",
    "top_revenue_dimension",
    "top_revenue_label",
    "total_revenue_metric",
    "total_orders_metric",
    "total_customers_metric",
    "average_order_value_metric",
    "aggregate_revenue_metric",
    "total_quantity_metric",
)


@dataclass(frozen=True)
class DatasetInfo:
    name: str
    currency: str
    domain: str
    geography_label: str


@dataclass(frozen=True)
class GoldTablesInfo:
    metrics: str
    country_revenue: str
    product_sales: str


@dataclass(frozen=True)
class TablesInfo:
    raw: str
    bronze: str
    silver: str
    gold: GoldTablesInfo


@dataclass(frozen=True)
class ColumnsInfo:
    primary_key: str
    customer_id: str
    timestamp: str
    quantity: str
    unit_price: str
    geography: str
    revenue: str
    product_id: str
    product_description: str
    order_id: str
    order_id_expression: str
    line_item_key: tuple[str, str, str, str]
    price_ceiling: Optional[float] = None

    def resolve_identifier(self) -> str:
        return self.primary_key

    def resolve_business_key(self) -> str:
        return self.order_id_expression if self.order_id_expression else self.order_id

    def resolve_line_item_key(self) -> tuple[str, str, str, str]:
        return self.line_item_key

    def resolve_raw_required_columns(self) -> list[str]:
        cols = [
            self.primary_key,
            self.product_id,
            self.product_description,
            self.quantity,
            self.timestamp,
            self.unit_price,
            self.customer_id,
            self.geography,
        ]
        if self.order_id not in cols:
            cols.append(self.order_id)
        return cols


@dataclass(frozen=True)
class MetricsInfo:
    revenue_formula: str
    order_id_expression: str
    top_revenue_dimension: str
    top_revenue_label: str
    total_revenue_metric: str
    total_orders_metric: str
    total_customers_metric: str
    average_order_value_metric: str
    aggregate_revenue_metric: str
    total_quantity_metric: str


@dataclass(frozen=True)
class AurumDatasetConfig:
    dataset: DatasetInfo
    tables: TablesInfo
    columns: ColumnsInfo
    metrics: MetricsInfo


class ConfigResolutionError(RuntimeError):
    """Raised when a custom dataset config cannot be resolved safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
    gold_raw = _require_mapping(tables_raw["gold"], "tables.gold")
    _require_fields("tables.gold", gold_raw, _GOLD_TABLE_FIELDS)
    
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
            raw=str(tables_raw["raw"]),
            bronze=str(tables_raw["bronze"]),
            silver=str(tables_raw["silver"]),
            gold=GoldTablesInfo(
                metrics=str(gold_raw["metrics"]),
                country_revenue=str(gold_raw["country_revenue"]),
                product_sales=str(gold_raw["product_sales"]),
            ),
        ),
        columns=ColumnsInfo(
            primary_key=str(columns_raw["primary_key"]),
            customer_id=str(columns_raw["customer_id"]),
            timestamp=str(columns_raw["timestamp"]),
            quantity=str(columns_raw["quantity"]),
            unit_price=str(columns_raw["unit_price"]),
            geography=str(columns_raw["geography"]),
            revenue=str(columns_raw["revenue"]),
            product_id=str(columns_raw["product_id"]),
            product_description=str(columns_raw["product_description"]),
            order_id=str(columns_raw["order_id"]),
            order_id_expression=str(columns_raw.get("order_id_expression", columns_raw["order_id"])),
            line_item_key=tuple(str(column) for column in columns_raw["line_item_key"]),
            price_ceiling=float(columns_raw["price_ceiling"]) if columns_raw.get("price_ceiling") is not None else None,
        ),
        metrics=MetricsInfo(
            revenue_formula=str(metrics_raw["revenue_formula"]),
            order_id_expression=str(columns_raw.get("order_id_expression", columns_raw["order_id"])),
            top_revenue_dimension=str(metrics_raw["top_revenue_dimension"]),
            top_revenue_label=str(metrics_raw["top_revenue_label"]),
            total_revenue_metric=str(metrics_raw["total_revenue_metric"]),
            total_orders_metric=str(metrics_raw["total_orders_metric"]),
            total_customers_metric=str(metrics_raw["total_customers_metric"]),
            average_order_value_metric=str(metrics_raw["average_order_value_metric"]),
            aggregate_revenue_metric=str(metrics_raw["aggregate_revenue_metric"]),
            total_quantity_metric=str(metrics_raw["total_quantity_metric"]),
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


def resolve_config_by_name(name: Optional[str]) -> Optional[AurumDatasetConfig]:
    """Load the named config, returning None only when no matching file exists."""
    if not name:
        return None

    normalized_name = str(name).strip().casefold()
    try:
        path = next(
            (
                candidate
                for candidate in default_config_path().parent.glob("*.yaml")
                if candidate.stem.casefold() == normalized_name
            ),
            None,
        )
    except Exception as exc:  # noqa: BLE001 - directory lookup failures must be loud
        raise ConfigResolutionError(
            "dataset_config_lookup_failed",
            f"Could not search for dataset config '{name}': {exc}",
        ) from exc
    if path is None:
        return None
    try:
        return load_dataset_config(path)
    except Exception as exc:  # noqa: BLE001 - every matching-file failure must be loud
        raise ConfigResolutionError(
            "dataset_config_invalid",
            f"Dataset config '{path}' exists but could not be loaded: {exc}",
        ) from exc


def resolve_config_for_project_or_table(
    project_id: Optional[str],
    table_or_file_name: Optional[str] = None,
) -> AurumDatasetConfig:
    """Resolve a required config for custom data; never fall back to Olist."""
    if table_or_file_name:
        config = resolve_config_by_name(Path(table_or_file_name).stem)
        if config is not None:
            return config

    project = None
    project_name = None
    if project_id:
        try:
            from src.app_state.store import get_project

            project = get_project(project_id)
            project_name = project.get("name") if project is not None else None
        except Exception as exc:  # noqa: BLE001 - store failures must not become Olist runs
            raise ConfigResolutionError(
                "project_store_lookup_failed",
                f"Could not look up project '{project_id}' while resolving its dataset config: {exc}",
            ) from exc

        if project is None:
            raise ConfigResolutionError(
                "project_not_found",
                f"Project '{project_id}' was not found while resolving its dataset config.",
            )

        config = resolve_config_by_name(project_name)
        if config is not None:
            return config

    targets = []
    if table_or_file_name:
        targets.append(f"table/file '{table_or_file_name}'")
    if project is not None:
        targets.append(f"project '{project_name}'")
    target = " or ".join(targets) or "the selected custom data"
    raise ConfigResolutionError(
        "dataset_config_not_found",
        f"No dataset config exists for {target}; refusing to substitute the default Olist config.",
    )
