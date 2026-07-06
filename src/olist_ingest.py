"""Ingest the Brazilian Olist e-commerce dataset into Aurum's retail column model.

Source: Olist Brazilian E-Commerce Public Dataset (Kaggle / CC BY-NC-SA 4.0).
Raw CSVs live under ``data/olist/``. Use :func:`ensure_olist_csvs` to download
from a public GitHub mirror when files are missing locally.

Bronze grain: one row per ``order_item`` (line item), mapped to the existing
Aurum medallion column names so validators stay stable:

    invoice_no   <- order_id
    stock_code   <- product_id
    description  <- product_category_name (English when available)
    quantity     <- 1 (Olist order_items are one unit per row)
    invoice_date <- order_purchase_timestamp (date)
    unit_price   <- price
    customer_id  <- customer_id
    country      <- customer_state (Brazilian state code)
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import pandas as pd

DATA_DIR = Path("data")
OLIST_DIR = DATA_DIR / "olist"

# Public mirror of the Kaggle CSV bundle (individual files).
OLIST_MIRROR_BASE = (
    "https://raw.githubusercontent.com/0PeterAdel/Brazilian-ECommerce/master/0.DataSet"
)

REQUIRED_CSVS = (
    "olist_orders_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_customers_dataset.csv",
    "olist_products_dataset.csv",
    "product_category_name_translation.csv",
)


def ensure_olist_csvs(olist_dir: Path = OLIST_DIR) -> Path:
    """Download missing Olist CSVs into *olist_dir*; return the directory path."""
    olist_dir.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_CSVS:
        dest = olist_dir / name
        if dest.exists() and dest.stat().st_size > 0:
            continue
        url = f"{OLIST_MIRROR_BASE}/{name}"
        print(f"Downloading {name} ...")
        urllib.request.urlretrieve(url, dest)
    return olist_dir


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False)


def build_raw_orders_from_olist(olist_dir: Path = OLIST_DIR) -> pd.DataFrame:
    """Join Olist tables into Aurum's ``raw_orders`` shape."""
    ensure_olist_csvs(olist_dir)

    items = _read_csv(olist_dir / "olist_order_items_dataset.csv")
    orders = _read_csv(olist_dir / "olist_orders_dataset.csv")
    customers = _read_csv(olist_dir / "olist_customers_dataset.csv")
    products = _read_csv(olist_dir / "olist_products_dataset.csv")
    translation = _read_csv(olist_dir / "product_category_name_translation.csv")

    df = (
        items.merge(orders[["order_id", "customer_id", "order_purchase_timestamp"]], on="order_id")
        .merge(customers[["customer_id", "customer_state"]], on="customer_id")
        .merge(
            products[["product_id", "product_category_name"]],
            on="product_id",
            how="left",
        )
        .merge(translation, on="product_category_name", how="left")
    )

    purchase_ts = pd.to_datetime(df["order_purchase_timestamp"], errors="coerce")
    description = df["product_category_name_english"].fillna(df["product_category_name"])
    # Unique line key: order_id + order_item_id (Olist grain). Gold order counts
    # strip the trailing _<item_id> suffix in build_gold().
    line_id = df["order_id"].astype(str) + "_" + df["order_item_id"].astype(str)

    out = pd.DataFrame(
        {
            "invoice_no": line_id,
            "stock_code": df["product_id"].astype(str),
            "description": description.fillna("UNKNOWN").astype(str),
            "quantity": 1,
            "invoice_date": purchase_ts.dt.strftime("%Y-%m-%d"),
            "unit_price": pd.to_numeric(df["price"], errors="coerce"),
            "customer_id": df["customer_id"].astype(str),
            "country": df["customer_state"].astype(str),
        }
    )
    out = out.dropna(subset=["invoice_no", "unit_price", "invoice_date", "customer_id"])
    return out.reset_index(drop=True)


def olist_summary(raw: pd.DataFrame) -> dict:
    """Quick stats for logging and historical bootstrap."""
    valid = raw[(raw["quantity"] > 0) & (raw["unit_price"] > 0)]
    return {
        "raw_rows": len(raw),
        "valid_rows": len(valid),
        "expected_revenue": float((valid["quantity"] * valid["unit_price"]).sum()),
        "distinct_orders": int(
            raw["invoice_no"].str.replace(r"_[0-9]+$", "", regex=True).nunique()
        ),
        "distinct_customers": int(raw["customer_id"].nunique()),
        "high_price_rows": int((valid["unit_price"] > 20).sum()),
    }
