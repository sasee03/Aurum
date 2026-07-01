"""Postgres connection configuration for Aurum.

Configuration is intentionally environment-driven so the validation engine can
run locally against Docker without hardcoded credentials.
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
    return load_postgres_config().conninfo()
