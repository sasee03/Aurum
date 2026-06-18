"""Pytest configuration: make the repo root importable so `import src` works."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
