"""Load the medallion layers into DuckDB and expose query helpers.

`DataLoader` owns the ETL for the demo:

    raw_orders  (CSV)
      -> bronze_orders   (raw, untouched)
      -> silver_orders   (cleaned + the planted bug)
      -> gold_* tables   (business aggregates over silver)

The planted bug lives in `SILVER_ETL_SQL`: alongside the legitimate cleaning
(`quantity > 0 AND unit_price > 0`) it also drops `quantity > 20`, which removes
valid high-quantity wholesale orders. The validators detect this from data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import duckdb
import pandas as pd

DATA_DIR = Path("data")
RAW_CSV = DATA_DIR / "raw" / "raw_orders.csv"
HISTORICAL_CSV = DATA_DIR / "historical" / "historical_runs.csv"

# The legitimate cleaning rule keeps positive quantity/price rows.
# The BUG is the extra `quantity <= 20` clause, which silently removes valid
# high-quantity orders. This is the single planted defect Aurum must catch.
SILVER_ETL_SQL = """
CREATE OR REPLACE TABLE silver_orders AS
SELECT
    invoice_no,
    stock_code,
    description,
    quantity,
    invoice_date,
    unit_price,
    customer_id,
    country,
    quantity * unit_price AS net_revenue
FROM bronze_orders
WHERE quantity > 0
  AND unit_price > 0
  AND quantity <= 20;            -- planted bug: drops valid high-quantity orders
"""


class DataLoader:
    def __init__(
        self,
        data_dir: Optional[Path] = DATA_DIR,
        conn: Optional[duckdb.DuckDBPyConnection] = None,
        build: bool = True,
    ) -> None:
        self.conn = conn or duckdb.connect(database=":memory:")
        self.data_dir = Path(data_dir) if data_dir is not None else None
        if self.data_dir is not None and build:
            self._load_from_disk()

    # ------------------------------------------------------------------ build
    def _load_from_disk(self) -> None:
        raw_path = self.data_dir / "raw" / "raw_orders.csv"
        if not raw_path.exists():
            raise FileNotFoundError(
                f"Missing {raw_path}. Run `python src/generate_data.py` first."
            )
        self.conn.execute(
            "CREATE OR REPLACE TABLE raw_orders AS SELECT * FROM read_csv_auto(?)",
            [str(raw_path)],
        )
        self.conn.execute("CREATE OR REPLACE TABLE bronze_orders AS SELECT * FROM raw_orders")
        self.build_silver()
        self.build_gold()

        hist_path = self.data_dir / "historical" / "historical_runs.csv"
        if hist_path.exists():
            self.conn.execute(
                "CREATE OR REPLACE TABLE historical_runs AS SELECT * FROM read_csv_auto(?)",
                [str(hist_path)],
            )

    def build_silver(self) -> None:
        self.conn.execute(SILVER_ETL_SQL)

    def build_gold(self) -> None:
        self.conn.execute(
            """
            CREATE OR REPLACE TABLE gold_metrics AS
            SELECT
                SUM(net_revenue) AS total_revenue,
                COUNT(DISTINCT invoice_no) AS total_orders,
                COUNT(DISTINCT customer_id) AS total_customers,
                CASE WHEN COUNT(DISTINCT invoice_no) = 0 THEN 0
                     ELSE SUM(net_revenue) / COUNT(DISTINCT invoice_no) END
                     AS average_order_value
            FROM silver_orders;
            """
        )
        self.conn.execute(
            """
            CREATE OR REPLACE TABLE gold_country_revenue AS
            SELECT country, SUM(net_revenue) AS revenue
            FROM silver_orders GROUP BY country;
            """
        )
        self.conn.execute(
            """
            CREATE OR REPLACE TABLE gold_product_sales AS
            SELECT stock_code, SUM(quantity) AS total_quantity,
                   SUM(net_revenue) AS revenue
            FROM silver_orders GROUP BY stock_code;
            """
        )

    # ------------------------------------------------------------- for tests
    @classmethod
    def from_frames(cls, frames: dict[str, pd.DataFrame]) -> "DataLoader":
        """Build a loader directly from in-memory tables (bypasses ETL).

        Used by unit tests to inject specific scenarios. `frames` maps table
        name -> DataFrame, e.g. {"bronze_orders": df, "silver_orders": df}.
        """
        loader = cls(data_dir=None, build=False)
        for name, df in frames.items():
            loader.conn.register(f"_reg_{name}", df)
            loader.conn.execute(
                f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _reg_{name}"
            )
            loader.conn.unregister(f"_reg_{name}")
        return loader

    # --------------------------------------------------------------- helpers
    def query(self, sql: str) -> pd.DataFrame:
        return self.conn.execute(sql).fetchdf()

    def scalar(self, sql: str) -> Any:
        row = self.conn.execute(sql).fetchone()
        return None if row is None else row[0]

    def count(self, table: str) -> int:
        return int(self.scalar(f"SELECT COUNT(*) FROM {table}"))

    def table_exists(self, table: str) -> bool:
        found = self.conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?",
            [table],
        ).fetchone()
        return found is not None

    def columns(self, table: str) -> list[str]:
        df = self.conn.execute(f"SELECT * FROM {table} LIMIT 0").fetchdf()
        return list(df.columns)


if __name__ == "__main__":
    loader = DataLoader()
    print("bronze:", loader.count("bronze_orders"))
    print("silver:", loader.count("silver_orders"))
    print("gold_revenue:", loader.scalar("SELECT total_revenue FROM gold_metrics"))
