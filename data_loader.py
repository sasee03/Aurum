"""DuckDB loading and query helpers for Aurum CSV data."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Union

import duckdb
import pandas as pd


DATA_DIR = Path("data")


class DataLoader:
    def __init__(self, data_dir: Union[str, Path] = DATA_DIR) -> None:
        self.data_dir = Path(data_dir)
        self.conn = duckdb.connect(database=":memory:")
        self.load()

    def load(self) -> None:
        csv_tables = {
            "bronze_orders": "bronze_orders.csv",
            "silver_orders_correct": "silver_orders_correct.csv",
            "silver_orders_buggy": "silver_orders_buggy.csv",
            "historical_runs": "historical_runs.csv",
        }
        for table_name, csv_name in csv_tables.items():
            path = self.data_dir / csv_name
            if not path.exists():
                raise FileNotFoundError(
                    f"Missing {path}. Run `python generate_data.py` first."
                )
            self.conn.execute(
                f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM read_csv_auto(?)",
                [str(path)],
            )

    def query(self, sql: str) -> pd.DataFrame:
        return self.conn.execute(sql).fetchdf()

    def scalar(self, sql: str) -> Any:
        return self.conn.execute(sql).fetchone()[0]


def query(sql: str) -> pd.DataFrame:
    return DataLoader().query(sql)


if __name__ == "__main__":
    loader = DataLoader()
    print(loader.query("SELECT COUNT(*) AS bronze_count FROM bronze_orders;"))
