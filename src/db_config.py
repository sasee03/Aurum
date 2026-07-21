"""Postgres connection configuration for Aurum.

Configuration is environment-driven so the validation engine can run locally
against pgAdmin-managed PostgreSQL, Docker, or a remote cloud host when
``DATABASE_URL`` is set.

Precedence for individual fields:
  1. ``DB_*`` — canonical env names for office/local setups.
  2. ``AURUM_POSTGRES_*`` — legacy aliases (Docker compose defaults).
  3. Built-in defaults.

Connection string precedence:
  1. ``DATABASE_URL`` — full URI (supports ``sslmode=require`` for remote SSL).
  2. Libpq keyword string built from resolved host/port/db/user/password.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse
from typing import Optional

from dotenv import load_dotenv
import psycopg_pool

load_dotenv()


@dataclass(frozen=True)
class PostgresConfig:
    host: str = "localhost"
    port: int = 5433
    dbname: str = "aurum"
    user: str = "aurum"
    password: str = "aurum"

    def conninfo(self) -> str:
        return (
            f"host={self.host} "
            f"port={self.port} "
            f"dbname={self.dbname} "
            f"user={self.user} "
            f"password={self.password}"
        )





@dataclass(frozen=True)
class LayerSchemas:
    source: str = "source"
    bronze: str = "bronze"
    silver: str = "silver"
    gold: str = "gold"
    silver_candidates: str = "silver_candidates"
    gold_candidates: str = "gold_candidates"


def _env(primary: str, legacy: str, default: str) -> str:
    return os.getenv(primary) or os.getenv(legacy) or default


def load_layer_schemas() -> LayerSchemas:
    return LayerSchemas(
        source=os.getenv("AURUM_SCHEMA_SOURCE", "source"),
        bronze=os.getenv("AURUM_SCHEMA_BRONZE", "bronze"),
        silver=os.getenv("AURUM_SCHEMA_SILVER", "silver"),
        gold=os.getenv("AURUM_SCHEMA_GOLD", "gold"),
        silver_candidates=os.getenv("AURUM_SCHEMA_SILVER_CANDIDATES", "silver_candidates"),
        gold_candidates=os.getenv("AURUM_SCHEMA_GOLD_CANDIDATES", "gold_candidates"),
    )


def load_postgres_config() -> PostgresConfig:
    return PostgresConfig(
        host=_env("DB_HOST", "AURUM_POSTGRES_HOST", "localhost"),
        port=int(_env("DB_PORT", "AURUM_POSTGRES_PORT", "5433")),
        dbname=_env("DB_NAME", "AURUM_POSTGRES_DB", "aurum"),
        user=_env("DB_USER", "AURUM_POSTGRES_USER", "aurum"),
        password=_env("DB_PASSWORD", "AURUM_POSTGRES_PASSWORD", "aurum"),
    )


def db_connect_timeout() -> int:
    """Seconds to wait for a Postgres TCP handshake (health probes, fast fail)."""
    raw = os.getenv("DB_CONNECT_TIMEOUT", "3").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 3


def postgres_conninfo() -> str:
    """Return the connection string passed to ``psycopg.connect()``."""
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return database_url
    return load_postgres_config().conninfo()

def postgres_promotion_conninfo() -> str:
    """Return the connection string for aurum_promotion role."""
    cfg = load_postgres_config()
    return (
        f"host={cfg.host} "
        f"port={cfg.port} "
        f"dbname={cfg.dbname} "
        f"user=aurum_promotion "
        f"password=aurum_promotion"
    )


def postgres_target_info() -> dict[str, str | int]:
    """Non-sensitive connection target for health/debug responses (no password)."""
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        parsed = urlparse(database_url)
        host = parsed.hostname or "unknown"
        port = parsed.port or 5432
        dbname = (parsed.path or "").lstrip("/") or "unknown"
        return {"host": host, "port": port, "database": dbname}
    cfg = load_postgres_config()
    return {"host": cfg.host, "port": cfg.port, "database": cfg.dbname}

_ingestion_pool: Optional[psycopg_pool.ConnectionPool] = None
_generated_sql_pool: Optional[psycopg_pool.ConnectionPool] = None
_promotion_pool: Optional[psycopg_pool.ConnectionPool] = None


def _configure_pool_conn(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('statement_timeout', %s, false)", (os.getenv("DB_STATEMENT_TIMEOUT", "10s"),))


def init_pools():
    global _ingestion_pool, _generated_sql_pool, _promotion_pool
    if _ingestion_pool is not None:
        return

    cfg = load_postgres_config()

    def _conninfo_for(user: str, password: str) -> str:
        return (
            f"host={cfg.host} "
            f"port={cfg.port} "
            f"dbname={cfg.dbname} "
            f"user={user} "
            f"password={password}"
        )

    _ingestion_pool = psycopg_pool.ConnectionPool(
        _conninfo_for("aurum_ingestion", "aurum_ingestion"),
        kwargs={"autocommit": True},
        configure=_configure_pool_conn,
        min_size=1,
        max_size=5,
        open=True
    )
    _generated_sql_pool = psycopg_pool.ConnectionPool(
        _conninfo_for("aurum_generated_sql", "aurum_generated_sql"),
        kwargs={"autocommit": True},
        configure=_configure_pool_conn,
        min_size=1,
        max_size=5,
        open=True
    )
    _promotion_pool = psycopg_pool.ConnectionPool(
        _conninfo_for("aurum_promotion", "aurum_promotion"),
        kwargs={"autocommit": True},
        configure=_configure_pool_conn,
        min_size=1,
        max_size=5,
        open=True
    )

def get_ingestion_pool() -> psycopg_pool.ConnectionPool:
    if _ingestion_pool is None:
        init_pools()
    assert _ingestion_pool is not None
    return _ingestion_pool


def get_generated_sql_pool() -> psycopg_pool.ConnectionPool:
    if _generated_sql_pool is None:
        init_pools()
    assert _generated_sql_pool is not None
    return _generated_sql_pool


def get_promotion_pool() -> psycopg_pool.ConnectionPool:
    if _promotion_pool is None:
        init_pools()
    assert _promotion_pool is not None
    return _promotion_pool
