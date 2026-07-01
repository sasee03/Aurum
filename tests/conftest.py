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
