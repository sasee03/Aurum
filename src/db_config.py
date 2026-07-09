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
from urllib.parse import urlparse

from dotenv import load_dotenv

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


def _env(primary: str, legacy: str, default: str) -> str:
    return os.getenv(primary) or os.getenv(legacy) or default


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
