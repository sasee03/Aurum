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

POSTGRES_PROMOTION_ROLE = "aurum_promotion"
POSTGRES_GENERATED_SQL_ROLE = "aurum_generated_sql"


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
        f"user={POSTGRES_PROMOTION_ROLE} "
        f"password={POSTGRES_PROMOTION_ROLE}"
    )

def postgres_generated_sql_conninfo() -> str:
    """Return the connection string for aurum_generated_sql role."""
    cfg = load_postgres_config()
    return (
        f"host={cfg.host} "
        f"port={cfg.port} "
        f"dbname={cfg.dbname} "
        f"user={POSTGRES_GENERATED_SQL_ROLE} "
        f"password={POSTGRES_GENERATED_SQL_ROLE}"
    )



def apply_role_setup(
    conn_or_conninfo: Any | None = None,
    schemas: LayerSchemas | None = None,
) -> None:
    """Apply config-driven layer schema creation and role permissions.

    Dynamically resolves physical schema names from authoritative deployment
    configuration (load_layer_schemas()) and executes structural identifier-quoted
    schema creation and role grants.
    """
    if schemas is None:
        schemas = load_layer_schemas()

    from psycopg import sql

    def _execute_grants(conn: Any) -> None:
        with conn.cursor() as cur:
            for s in (
                schemas.source,
                schemas.bronze,
                schemas.silver,
                schemas.gold,
                schemas.silver_candidates,
                schemas.gold_candidates,
            ):
                cur.execute(
                    sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                        sql.Identifier(s)
                    )
                )

            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'aurum_ingestion') THEN
                        CREATE ROLE aurum_ingestion WITH LOGIN PASSWORD 'aurum_ingestion';
                    END IF;
                    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'aurum_generated_sql') THEN
                        CREATE ROLE aurum_generated_sql WITH LOGIN PASSWORD 'aurum_generated_sql' NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS NOINHERIT;
                    END IF;
                    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'aurum_promotion') THEN
                        CREATE ROLE aurum_promotion WITH LOGIN PASSWORD 'aurum_promotion' NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS INHERIT;
                    END IF;
                    ALTER ROLE aurum_generated_sql NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS NOINHERIT;
                    ALTER ROLE aurum_promotion NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS INHERIT;
                END
                $$;
            """)

            # Ingestion grants
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO aurum_ingestion").format(sql.Identifier(schemas.source)))
            cur.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO aurum_ingestion").format(sql.Identifier(schemas.source)))
            cur.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO aurum_ingestion").format(sql.Identifier(schemas.bronze)))

            # Generated SQL grants: USAGE on execution read layers, CREATE ONLY on candidates
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO aurum_generated_sql").format(sql.Identifier(schemas.bronze)))
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO aurum_generated_sql").format(sql.Identifier(schemas.silver)))
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO aurum_generated_sql").format(sql.Identifier(schemas.gold)))
            cur.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO aurum_generated_sql").format(sql.Identifier(schemas.silver_candidates)))
            cur.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO aurum_generated_sql").format(sql.Identifier(schemas.gold_candidates)))

            # Generated SQL SELECT on existing tables in read layers (Bronze and Silver)
            for s in (schemas.bronze, schemas.silver):
                cur.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO aurum_generated_sql").format(sql.Identifier(s)))

            # Creator-role-specific default privileges derived from actual production creators
            for creator in ("aurum_ingestion", "aurum"):
                cur.execute(
                    sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} GRANT SELECT ON TABLES TO aurum_generated_sql").format(
                        sql.Identifier(creator), sql.Identifier(schemas.bronze)
                    )
                )
            cur.execute(
                sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE aurum IN SCHEMA {} GRANT SELECT ON TABLES TO aurum_generated_sql").format(
                    sql.Identifier(schemas.silver)
                )
            )

            # Promotion grants: USAGE and CREATE for metadata movements/handoffs
            cur.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO aurum_promotion").format(sql.Identifier(schemas.silver)))
            cur.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO aurum_promotion").format(sql.Identifier(schemas.gold)))
            cur.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO aurum_promotion").format(sql.Identifier(schemas.silver_candidates)))
            cur.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO aurum_promotion").format(sql.Identifier(schemas.gold_candidates)))

            # Database connect grants
            cur.execute("SELECT current_database()")
            curr_db = cur.fetchone()[0]
            cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO aurum_ingestion, aurum_generated_sql, aurum_promotion").format(sql.Identifier(curr_db)))

            # Role hierarchy invariant: aurum_promotion holds membership in aurum_generated_sql
            cur.execute("REVOKE aurum_promotion FROM aurum_generated_sql;")
            cur.execute("REVOKE aurum_generated_sql FROM aurum_promotion;")
            cur.execute("GRANT aurum_generated_sql TO aurum_promotion WITH INHERIT TRUE, SET TRUE;")

        conn.commit()

    if conn_or_conninfo is None or isinstance(conn_or_conninfo, str):
        target = conn_or_conninfo or postgres_conninfo()
        import psycopg
        with psycopg.connect(target) as conn:
            _execute_grants(conn)
    else:
        _execute_grants(conn_or_conninfo)


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
        _conninfo_for(POSTGRES_PROMOTION_ROLE, POSTGRES_PROMOTION_ROLE),
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


def close_pools():
    global _ingestion_pool, _generated_sql_pool, _promotion_pool
    if _ingestion_pool is not None:
        try:
            _ingestion_pool.close(timeout=2.0)
        except Exception:
            pass
        _ingestion_pool = None
    if _generated_sql_pool is not None:
        try:
            _generated_sql_pool.close(timeout=2.0)
        except Exception:
            pass
        _generated_sql_pool = None
    if _promotion_pool is not None:
        try:
            _promotion_pool.close(timeout=2.0)
        except Exception:
            pass
        _promotion_pool = None


import atexit
atexit.register(close_pools)


if __name__ == "__main__":
    apply_role_setup()
    print("Idempotent Aurum role and schema setup completed successfully.")
