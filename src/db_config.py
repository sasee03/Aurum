"""Postgres connection configuration for Aurum.

Configuration is intentionally environment-driven so the validation engine can
run locally against Docker without hardcoded credentials, or remotely against a
cloud Postgres (e.g. Neon) when ``DATABASE_URL`` is set.

Precedence:
  1. ``DATABASE_URL`` — a full connection string/URI (supports ``sslmode=require``
     and other libpq params for remote SSL hosts).
  2. Individual ``AURUM_POSTGRES_*`` env vars — the original local Docker path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


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


def load_postgres_config() -> PostgresConfig:
    return PostgresConfig(
        host=os.getenv("AURUM_POSTGRES_HOST", "localhost"),
        port=int(os.getenv("AURUM_POSTGRES_PORT", "5433")),
        dbname=os.getenv("AURUM_POSTGRES_DB", "aurum"),
        user=os.getenv("AURUM_POSTGRES_USER", "aurum"),
        password=os.getenv("AURUM_POSTGRES_PASSWORD", "aurum"),
    )


def postgres_conninfo() -> str:
    """Return the connection string passed to ``psycopg.connect()``.

    When ``DATABASE_URL`` is set it is returned as-is (psycopg accepts PostgreSQL
    URIs including ``?sslmode=require`` for remote SSL). When absent, the existing
    local libpq keyword string is built from ``AURUM_POSTGRES_*`` — no SSL forced.
    """
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return database_url
    return load_postgres_config().conninfo()
