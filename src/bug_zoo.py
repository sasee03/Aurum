"""Bug zoo — plant unanticipated defects and verify Pain-1 layers catch them.

Each scenario introduces a bug type WITHOUT a bug-specific check. Detection must
come from Layer 1 rules, Layer 2 reconciliation, or Layer 3 robust anomaly.
"""

from __future__ import annotations

import random
from typing import Iterable, Optional

import pandas as pd

from .contracts import DETECTION_LAYER_1, DETECTION_LAYER_2, DETECTION_LAYER_3
from .data_loader import DataLoader
from .detection_stack import DetectionStackResult, run_detection_stack


def rebuild_gold(loader: DataLoader) -> None:
    loader.build_gold()


def flagged_checks(
    result: DetectionStackResult,
    *,
    detection_layer: Optional[str] = None,
    dimension: Optional[str] = None,
    check_id_prefix: Optional[str] = None,
) -> list:
    """Return non-PASS checks, optionally filtered by layer/dimension/id."""
    out = [c for c in result.all_checks if c.status in ("FAIL", "WARN", "IMPACTED")]
    if detection_layer:
        out = [c for c in out if c.extra.get("detection_layer") == detection_layer]
    if dimension:
        out = [c for c in out if c.extra.get("dimension") == dimension]
    if check_id_prefix:
        out = [c for c in out if c.check_id.startswith(check_id_prefix)]
    return out


def assert_caught(
    result: DetectionStackResult,
    *,
    detection_layer: str,
    description: str,
    check_id_prefix: Optional[str] = None,
) -> None:
    hits = flagged_checks(result, detection_layer=detection_layer, check_id_prefix=check_id_prefix)
    assert hits, (
        f"Bug zoo failure: {description} — expected detection from {detection_layer}, "
        f"but no FAIL/WARN/IMPACTED checks found."
    )


# --- Planters ----------------------------------------------------------------

def plant_random_row_drop(loader: DataLoader, fraction: float = 0.25) -> DataLoader:
    silver = loader.query("SELECT * FROM silver_orders")
    keep = max(1, int(len(silver) * (1 - fraction)))
    silver = silver.sample(n=keep, random_state=42)
    loader.conn.register("_silver", silver)
    loader.conn.execute("CREATE OR REPLACE TABLE silver_orders AS SELECT * FROM _silver")
    loader.conn.unregister("_silver")
    rebuild_gold(loader)
    return loader


def plant_duplicate_batch(loader: DataLoader, n_dup: int = 10) -> DataLoader:
    silver = loader.query("SELECT * FROM silver_orders")
    extra = silver.head(n_dup).copy()
    silver = pd.concat([silver, extra], ignore_index=True)
    loader.conn.register("_silver", silver)
    loader.conn.execute("CREATE OR REPLACE TABLE silver_orders AS SELECT * FROM _silver")
    loader.conn.unregister("_silver")
    rebuild_gold(loader)
    return loader


def plant_orphan_payments(loader: DataLoader) -> DataLoader:
    payments = pd.DataFrame(
        [{"payment_id": "PAY000001", "invoice_no": "INV999999", "amount": 500.0}]
    )
    loader.conn.register("_pay", payments)
    loader.conn.execute("CREATE OR REPLACE TABLE order_payments AS SELECT * FROM _pay")
    loader.conn.unregister("_pay")
    return loader


def plant_inflate_price(loader: DataLoader, factor: float = 2.0) -> DataLoader:
    silver = loader.query("SELECT * FROM silver_orders")
    silver["unit_price"] = silver["unit_price"] * factor
    silver["net_revenue"] = silver["quantity"] * silver["unit_price"]
    loader.conn.register("_silver", silver)
    loader.conn.execute("CREATE OR REPLACE TABLE silver_orders AS SELECT * FROM _silver")
    loader.conn.unregister("_silver")
    # Deliberately do NOT rebuild Gold — simulates stale Gold after Silver corruption.
    return loader


def plant_null_keys(loader: DataLoader, n: int = 5) -> DataLoader:
    silver = loader.query("SELECT * FROM silver_orders")
    silver.loc[: n - 1, "invoice_no"] = None
    loader.conn.register("_silver", silver)
    loader.conn.execute("CREATE OR REPLACE TABLE silver_orders AS SELECT * FROM _silver")
    loader.conn.unregister("_silver")
    rebuild_gold(loader)
    return loader


def plant_scale_quantities(loader: DataLoader, factor: float = 2.0) -> DataLoader:
    silver = loader.query("SELECT * FROM silver_orders")
    silver["quantity"] = (silver["quantity"] * factor).astype(int)
    silver["net_revenue"] = silver["quantity"] * silver["unit_price"]
    loader.conn.register("_silver", silver)
    loader.conn.execute("CREATE OR REPLACE TABLE silver_orders AS SELECT * FROM _silver")
    loader.conn.unregister("_silver")
    rebuild_gold(loader)
    return loader


def run_zoo_case(loader: DataLoader) -> DetectionStackResult:
    return run_detection_stack(loader)
