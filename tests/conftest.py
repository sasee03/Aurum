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
    yield db_path
