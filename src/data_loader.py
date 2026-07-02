"""Load the medallion layers into Postgres and expose query helpers.

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

import re
import weakref
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import pandas as pd
import psycopg
from psycopg import sql

try:
    from .db_config import postgres_conninfo
except ImportError:  # pragma: no cover - supports `python src/data_loader.py`
    from db_config import postgres_conninfo

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


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CREATE_FROM_REGISTERED = re.compile(
    r"^\s*CREATE\s+OR\s+REPLACE\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s+AS\s+"
    r"SELECT\s+\*\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)\s*;?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CREATE_OR_REPLACE_AS = re.compile(
    r"^\s*CREATE\s+OR\s+REPLACE\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s+AS\s+",
    re.IGNORECASE | re.DOTALL,
)


def _quote_ident(name: str) -> sql.Identifier:
    if not _IDENTIFIER.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return sql.Identifier(name)


def _postgres_type(series: pd.Series) -> str:
    known_numeric = {
        "quantity",
        "unit_price",
        "customer_id",
        "net_revenue",
        "total_revenue",
        "total_orders",
        "total_customers",
        "average_order_value",
        "revenue",
        "total_quantity",
        "amount",
        "bronze_count",
        "silver_count",
        "drop_pct",
        "gold_revenue",
    }
    if series.name in known_numeric and series.dropna().empty:
        return "double precision"
    if pd.api.types.is_integer_dtype(series):
        return "bigint"
    if pd.api.types.is_float_dtype(series):
        return "double precision"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "timestamp"
    return "text"


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return pd.Timestamp(value)
    return value


def _normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df.applymap(_normalize_value) if not df.empty else df


def _translate_sql(query: str) -> str:
    """Translate the small DuckDB SQL surface used by validators to Postgres."""
    translated = query
    translated = re.sub(
        r"TRY_CAST\((.*?)\s+AS\s+DATE\)",
        r"aurum_try_date((\1)::text)",
        translated,
        flags=re.IGNORECASE | re.DOTALL,
    )
    translated = re.sub(r"::DOUBLE\b", "::double precision", translated, flags=re.IGNORECASE)
    translated = translated.replace(
        "ROUND((1 - COALESCE(sil.silver_count, 0)::double precision / "
        "seg.bronze_valid) * 100, 2)",
        "ROUND(((1 - COALESCE(sil.silver_count, 0)::double precision / "
        "seg.bronze_valid) * 100)::numeric, 2)::double precision",
    )
    translated = re.sub(
        r"CREATE\s+OR\s+REPLACE\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s+AS",
        r"DROP TABLE IF EXISTS \1; CREATE TABLE \1 AS",
        translated,
        flags=re.IGNORECASE,
    )
    translated = translated.replace("?", "%s")
    return translated


class PostgresCompatConnection:
    """Tiny DuckDB-like facade for existing bug-zoo table mutation helpers."""

    def __init__(self, pg_conn: psycopg.Connection, loader: "DataLoader") -> None:
        self._pg_conn = pg_conn
        self._loader = loader
        self._registered: dict[str, pd.DataFrame] = {}

    def execute(self, query: str, params: Optional[list[Any]] = None):
        match = _CREATE_FROM_REGISTERED.match(query)
        if match and match.group(2) in self._registered:
            table, registered_name = match.groups()
            self._loader._materialize_frame(
                table,
                self._registered[registered_name],
                temporary=False,
            )
            return None

        replace_match = _CREATE_OR_REPLACE_AS.match(query)
        if replace_match:
            return self._loader._execute_create_or_replace_as(
                replace_match.group(1), query[replace_match.end():]
            )

        cur = self._pg_conn.cursor()
        cur.execute(_translate_sql(query), params)
        return cur

    def register(self, name: str, df: pd.DataFrame) -> None:
        self._registered[name] = df.copy()

    def unregister(self, name: str) -> None:
        self._registered.pop(name, None)

    def close(self) -> None:
        self._pg_conn.close()


class DataLoader:
    _active_loaders: "weakref.WeakSet[DataLoader]" = weakref.WeakSet()

    def __init__(
        self,
        data_dir: Optional[Path] = DATA_DIR,
        conn: Optional[Any] = None,
        build: bool = True,
    ) -> None:
        pg_conn = conn or psycopg.connect(postgres_conninfo(), autocommit=True)
        self.conn = (
            pg_conn
            if isinstance(pg_conn, PostgresCompatConnection)
            else PostgresCompatConnection(pg_conn, self)
        )
        self._pg_conn = self.conn._pg_conn
        self.data_dir = Path(data_dir) if data_dir is not None else None
        self._schema = f"aurum_session_{uuid4().hex}"
        self._closed = False
        self._uses_temporary_tables = False
        # Tie schema cleanup to schema creation: if anything after the schema is
        # created fails during setup, drop it here and re-raise. Otherwise the
        # partially-built loader is never returned, run_validation's finally
        # never runs, and the session schema leaks.
        try:
            self._create_session_schema()
            self._install_helpers()
            DataLoader._active_loaders.add(self)
            if self.data_dir is not None and build:
                self._load_from_disk()
        except BaseException:
            try:
                self.close()
            except Exception:
                pass
            raise

    # ------------------------------------------------------------------ build
    def _create_session_schema(self) -> None:
        with self._pg_conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(_quote_ident(self._schema)))
            cur.execute(sql.SQL("SET search_path TO {}").format(_quote_ident(self._schema)))

    def _install_helpers(self) -> None:
        with self._pg_conn.cursor() as cur:
            cur.execute(
                """
                CREATE OR REPLACE FUNCTION aurum_try_date(value text)
                RETURNS date
                LANGUAGE plpgsql
                IMMUTABLE
                AS $$
                BEGIN
                    RETURN value::date;
                EXCEPTION WHEN others THEN
                    RETURN NULL;
                END;
                $$;
                """
            )

    def _load_from_disk(self) -> None:
        self._drop_tables(
            [
                "raw_orders",
                "bronze_orders",
                "silver_orders",
                "gold_metrics",
                "gold_country_revenue",
                "gold_product_sales",
                "historical_runs",
                "order_payments",
                "customers",
            ]
        )
        raw_path = self.data_dir / "raw" / "raw_orders.csv"
        if not raw_path.exists():
            raise FileNotFoundError(
                f"Missing {raw_path}. Run `python src/generate_data.py` first."
            )
        self._materialize_frame("raw_orders", pd.read_csv(raw_path), temporary=False)
        self.conn.execute("CREATE OR REPLACE TABLE bronze_orders AS SELECT * FROM raw_orders")
        self.build_silver()
        self._create_reconciliation_indexes()
        self.build_gold()

        hist_path = self.data_dir / "historical" / "historical_runs.csv"
        if hist_path.exists():
            self._materialize_frame(
                "historical_runs", pd.read_csv(hist_path), temporary=False
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
            loader._materialize_frame(name, df, temporary=False)
        return loader

    # --------------------------------------------------------------- helpers
    def _drop_tables(self, tables: list[str]) -> None:
        with self._pg_conn.cursor() as cur:
            for table in tables:
                cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(_quote_ident(table)))

    def _create_reconciliation_indexes(self) -> None:
        """Indexes for Silver anti-join checks S8/S10; additive, no result changes."""
        statements = [
            """
            CREATE INDEX IF NOT EXISTS idx_bronze_valid_business_key
            ON bronze_orders (invoice_no, stock_code, customer_id, invoice_date)
            INCLUDE (quantity, unit_price)
            WHERE quantity > 0
              AND unit_price > 0
              AND invoice_no IS NOT NULL
              AND stock_code IS NOT NULL
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_silver_business_key
            ON silver_orders (invoice_no, stock_code, customer_id, invoice_date)
            """,
        ]
        with self._pg_conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
            cur.execute("ANALYZE bronze_orders")
            cur.execute("ANALYZE silver_orders")

    def _execute_create_or_replace_as(self, table: str, select_sql: str):
        temporary = self._should_materialize_temporary(table, select_sql)
        drop_target = (
            sql.Identifier("pg_temp", table) if temporary else _quote_ident(table)
        )
        create_prefix = sql.SQL("{} TABLE {} AS ").format(
            sql.SQL("CREATE TEMPORARY" if temporary else "CREATE"),
            _quote_ident(table),
        )
        translated_select = _translate_sql(select_sql)
        with self._pg_conn.cursor() as cur:
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(drop_target))
            cur.execute(create_prefix.as_string(self._pg_conn) + translated_select)
            return cur

    def _should_materialize_temporary(self, table: str, select_sql: str) -> bool:
        if self._table_is_temporary(table):
            return True
        if not self._uses_temporary_tables:
            return False
        referenced_tables = [
            "raw_orders",
            "bronze_orders",
            "silver_orders",
            "gold_metrics",
            "gold_country_revenue",
            "gold_product_sales",
            "historical_runs",
            "order_payments",
            "customers",
        ]
        return any(
            re.search(rf"\b{re.escape(name)}\b", select_sql)
            and self._table_is_temporary(name)
            for name in referenced_tables
        )

    def _materialize_frame(
        self, table: str, df: pd.DataFrame, *, temporary: bool = False
    ) -> None:
        columns = list(df.columns)
        if not columns:
            raise ValueError(f"Cannot materialize table {table!r} with no columns.")

        column_defs = [
            sql.SQL("{} {}").format(_quote_ident(column), sql.SQL(_postgres_type(df[column])))
            for column in columns
        ]
        drop_target = (
            sql.Identifier("pg_temp", table) if temporary else _quote_ident(table)
        )
        create = sql.SQL("{} TABLE {} ({})").format(
            sql.SQL("CREATE TEMPORARY" if temporary else "CREATE"),
            _quote_ident(table),
            sql.SQL(", ").join(column_defs),
        )

        with self._pg_conn.cursor() as cur:
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(drop_target))
            cur.execute(create)
            if temporary:
                self._uses_temporary_tables = True
            if df.empty:
                return

            copy_sql = sql.SQL("COPY {} ({}) FROM STDIN").format(
                _quote_ident(table),
                sql.SQL(", ").join(_quote_ident(column) for column in columns),
            )
            with cur.copy(copy_sql) as copy:
                for row in df.itertuples(index=False, name=None):
                    copy.write_row([None if pd.isna(value) else value for value in row])

    def query(self, sql: str) -> pd.DataFrame:
        with self._pg_conn.cursor() as cur:
            cur.execute(_translate_sql(sql))
            rows = cur.fetchall()
            columns = [desc.name for desc in cur.description] if cur.description else []
        return _normalize_frame(pd.DataFrame(rows, columns=columns))

    def scalar(self, sql: str) -> Any:
        with self._pg_conn.cursor() as cur:
            cur.execute(_translate_sql(sql))
            row = cur.fetchone()
        return None if row is None else _normalize_value(row[0])

    def count(self, table: str) -> int:
        return int(self.scalar(f"SELECT COUNT(*) FROM {table}"))

    def table_exists(self, table: str) -> bool:
        with self._pg_conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", [table])
            found = cur.fetchone()
        return found[0] is not None

    def _table_is_temporary(self, table: str) -> bool:
        with self._pg_conn.cursor() as cur:
            cur.execute(
                """
                SELECT n.nspname LIKE 'pg_temp_%%'
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.oid = to_regclass(%s)
                """,
                [table],
            )
            row = cur.fetchone()
        return bool(row and row[0])

    def columns(self, table: str) -> list[str]:
        with self._pg_conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {table} LIMIT 0")
            return [desc.name for desc in cur.description]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            with self._pg_conn.cursor() as cur:
                cur.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        _quote_ident(self._schema)
                    )
                )
        finally:
            self.conn.close()
            DataLoader._active_loaders.discard(self)

    @classmethod
    def close_all_sessions(cls) -> None:
        for loader in list(cls._active_loaders):
            loader.close()

    def __enter__(self) -> "DataLoader":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


if __name__ == "__main__":
    loader = DataLoader()
    print("bronze:", loader.count("bronze_orders"))
    print("silver:", loader.count("silver_orders"))
    print("gold_revenue:", loader.scalar("SELECT total_revenue FROM gold_metrics"))
