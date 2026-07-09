"""SQLite app-state store for Aurum platform metadata (projects, runs, reports)."""

from .db import app_state_path, get_connection, init_schema
from .store import (
    create_project,
    get_project,
    get_report_by_run_id,
    list_projects,
    save_validation_report,
    save_validation_run,
)

__all__ = [
    "app_state_path",
    "get_connection",
    "init_schema",
    "create_project",
    "list_projects",
    "get_project",
    "save_validation_run",
    "save_validation_report",
    "get_report_by_run_id",
]
