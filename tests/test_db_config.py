"""Postgres connection config: local defaults and DATABASE_URL precedence."""

import os

from src.db_config import load_postgres_config, postgres_conninfo


def test_postgres_conninfo_local_defaults_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AURUM_POSTGRES_HOST", raising=False)
    monkeypatch.delenv("AURUM_POSTGRES_PORT", raising=False)
    monkeypatch.delenv("AURUM_POSTGRES_DB", raising=False)
    monkeypatch.delenv("AURUM_POSTGRES_USER", raising=False)
    monkeypatch.delenv("AURUM_POSTGRES_PASSWORD", raising=False)

    info = postgres_conninfo()
    assert info == (
        "host=localhost port=5433 dbname=aurum user=aurum password=aurum"
    )
    assert "sslmode" not in info


def test_postgres_conninfo_prefers_database_url(monkeypatch):
    url = "postgresql://cloud:secret@db.example.com:5432/mydb?sslmode=require"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("AURUM_POSTGRES_HOST", "should-not-be-used")

    assert postgres_conninfo() == url


def test_load_postgres_config_unchanged_when_database_url_set(monkeypatch):
    """Individual env vars still load for callers that need host/port breakdown."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x@y/z")
    monkeypatch.setenv("AURUM_POSTGRES_HOST", "custom-host")
    monkeypatch.setenv("AURUM_POSTGRES_PORT", "9999")

    cfg = load_postgres_config()
    assert cfg.host == "custom-host"
    assert cfg.port == 9999
