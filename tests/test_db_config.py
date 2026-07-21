"""Postgres connection config: local defaults, DB_* env vars, and DATABASE_URL precedence."""

import os

from src.db_config import (
    db_connect_timeout,
    load_layer_schemas,
    load_postgres_config,
    postgres_conninfo,
    postgres_target_info,
)


def test_postgres_conninfo_local_defaults_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for key in (
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "AURUM_POSTGRES_HOST",
        "AURUM_POSTGRES_PORT",
        "AURUM_POSTGRES_DB",
        "AURUM_POSTGRES_USER",
        "AURUM_POSTGRES_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)

    info = postgres_conninfo()
    assert info == (
        "host=localhost port=5433 dbname=aurum user=aurum password=aurum"
    )
    assert "sslmode" not in info


def test_postgres_conninfo_prefers_database_url(monkeypatch):
    url = "postgresql://cloud:secret@db.example.com:5432/mydb?sslmode=require"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DB_HOST", "should-not-be-used")

    assert postgres_conninfo() == url


def test_db_env_vars_take_precedence_over_legacy(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_HOST", "office-host")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "office_db")
    monkeypatch.setenv("DB_USER", "postgres")
    monkeypatch.setenv("DB_PASSWORD", "office_pw")
    monkeypatch.setenv("AURUM_POSTGRES_HOST", "legacy-host")

    info = postgres_conninfo()
    assert "host=office-host" in info
    assert "port=5432" in info
    assert "dbname=office_db" in info
    assert "user=postgres" in info
    assert "password=office_pw" in info


def test_load_postgres_config_unchanged_when_database_url_set(monkeypatch):
    """Individual env vars still load for callers that need host/port breakdown."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x@y/z")
    monkeypatch.setenv("DB_HOST", "custom-host")
    monkeypatch.setenv("DB_PORT", "9999")

    cfg = load_postgres_config()
    assert cfg.host == "custom-host"
    assert cfg.port == 9999


def test_db_connect_timeout_defaults_to_three(monkeypatch):
    monkeypatch.delenv("DB_CONNECT_TIMEOUT", raising=False)
    assert db_connect_timeout() == 3


def test_db_connect_timeout_reads_env(monkeypatch):
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "2")
    assert db_connect_timeout() == 2


def test_postgres_target_info_excludes_password(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "5433")
    monkeypatch.setenv("DB_NAME", "aurum")
    monkeypatch.setenv("DB_PASSWORD", "super_secret")

    target = postgres_target_info()
    assert target == {"host": "localhost", "port": 5433, "database": "aurum"}
    assert "password" not in str(target).lower()


def test_postgres_target_info_from_database_url(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:secret@neon.example.com:5432/aurum_db?sslmode=require",
    )
    target = postgres_target_info()
    assert target["host"] == "neon.example.com"
    assert target["port"] == 5432
    assert target["database"] == "aurum_db"
    assert "secret" not in str(target)


def test_layer_schema_defaults_to_demo_topology(monkeypatch):
    for key in (
        "AURUM_SCHEMA_SOURCE",
        "AURUM_SCHEMA_BRONZE",
        "AURUM_SCHEMA_SILVER",
        "AURUM_SCHEMA_GOLD",
    ):
        monkeypatch.delenv(key, raising=False)

    schemas = load_layer_schemas()
    assert schemas.source == "source"
    assert schemas.bronze == "bronze"
    assert schemas.silver == "silver"
    assert schemas.gold == "gold"
    assert schemas.silver_candidates == "silver_candidates"


def test_layer_schema_env_redirects_without_code_change(monkeypatch):
    monkeypatch.setenv("AURUM_SCHEMA_SILVER", "silver_demo_2")
    schemas = load_layer_schemas()
    assert schemas.silver == "silver_demo_2"
