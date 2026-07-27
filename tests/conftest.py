"""Pytest configuration: make the repo root importable so `import src` works."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def close_data_loader_sessions():
    yield
    from src.data_loader import DataLoader

    DataLoader.close_all_sessions()


@pytest.fixture(autouse=True)
def isolated_app_state_db(tmp_path, monkeypatch):
    """Keep SQLite app state out of the repo during tests."""
    db_path = tmp_path / "app_state.sqlite"
    monkeypatch.setenv("AURUM_APP_STATE_DB", str(db_path))
    monkeypatch.setenv("AURUM_AUTHORITY_HMAC_KEY", "test-gold-authority-key")
    yield db_path


class SchemaTracker:
    def __init__(self):
        self.schemas = set()

    def add(self, schema: str):
        if schema:
            self.schemas.add(schema)

    def track_run(self, run_id: str):
        from src.app_state.store import get_validation_run
        run = get_validation_run(run_id)
        if run and run.get("session_schema"):
            self.schemas.add(run["session_schema"])

@pytest.fixture
def schema_tracker():
    tracker = SchemaTracker()
    yield tracker
    if tracker.schemas:
        import psycopg
        from psycopg import sql
        from src.db_config import postgres_conninfo
        with psycopg.connect(postgres_conninfo(), autocommit=True) as conn:
            for s in tracker.schemas:
                conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(s)))
