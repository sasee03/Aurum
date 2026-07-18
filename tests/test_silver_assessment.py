from __future__ import annotations

from fastapi.testclient import TestClient

import api.main as api_main
from src.config_loader import load_dataset_config


class _FakeCursor:
    def __init__(self, excluded_reason: str) -> None:
        self._queries: list[str] = []
        self._fetchone_results = [
            {"to_regclass": "silver_row_assessment"},
            {"total": 4, "retained": 1, "invalid": 2, "excluded": 1},
        ]
        self._fetchall_result = [
            {
                "invoice_no": "INV002",
                "quantity": -5,
                "unit_price": 10.0,
                "row_status": "INVALID",
                "reason": "quantity <= 0",
            },
            {
                "invoice_no": None,
                "quantity": 1,
                "unit_price": 10.0,
                "row_status": "INVALID",
                "reason": "invoice_no is null",
            },
            {
                "invoice_no": "INV003",
                "quantity": 1,
                "unit_price": 100.0,
                "row_status": "EXCLUDED",
                "reason": excluded_reason,
            },
        ]

    @property
    def queries(self) -> list[str]:
        return self._queries

    def execute(self, query) -> None:
        self._queries.append(str(query))

    def fetchone(self):
        return self._fetchone_results.pop(0)

    def fetchall(self):
        return self._fetchall_result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self, row_factory=None):  # noqa: ARG002 - matches psycopg signature
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_silver_assessment_missing_run_returns_404(monkeypatch):
    monkeypatch.setattr("src.app_state.store.get_validation_run", lambda _run_id: None)

    with TestClient(api_main.app) as client:
        response = client.get("/runs/missing_run_12345/silver-assessment")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found."


def test_silver_assessment_requires_retained_session_schema(monkeypatch):
    monkeypatch.setattr(
        "src.app_state.store.get_validation_run",
        lambda _run_id: {
            "run_id": "silver_run_001",
            "session_schema": None,
            "dataset_config": "olist",
        },
    )

    with TestClient(api_main.app) as client:
        response = client.get("/runs/silver_run_001/silver-assessment")

    assert response.status_code == 422
    assert response.json()["detail"] == "No session schema retained for this run."


def test_silver_assessment_requires_retained_dataset_config(monkeypatch):
    monkeypatch.setattr(
        "src.app_state.store.get_validation_run",
        lambda _run_id: {
            "run_id": "silver_run_001",
            "session_schema": "aurum_session_123",
            "dataset_config": None,
        },
    )

    with TestClient(api_main.app) as client:
        response = client.get("/runs/silver_run_001/silver-assessment")

    assert response.status_code == 422
    assert response.json()["detail"] == "No dataset_config retained for this run."


def test_silver_assessment_returns_flagged_rows_without_schema_leak(monkeypatch):
    cfg = load_dataset_config()
    assert cfg.columns.price_ceiling is not None
    ceiling = float(cfg.columns.price_ceiling)
    cursor = _FakeCursor(f"unit_price > {ceiling}")
    connection = _FakeConnection(cursor)

    monkeypatch.setattr(
        "src.app_state.store.get_validation_run",
        lambda _run_id: {
            "run_id": "silver_run_001",
            "session_schema": "aurum_session_123",
            "dataset_config": cfg.config_name,
        },
    )
    monkeypatch.setattr("src.config_loader.resolve_config_by_name", lambda _name: cfg)
    monkeypatch.setattr(api_main.psycopg, "connect", lambda *args, **kwargs: connection)

    with TestClient(api_main.app) as client:
        response = client.get("/runs/silver_run_001/silver-assessment")

    assert response.status_code == 200
    body = response.json()
    assert "session_schema" not in body
    assert body["summary"] == {
        "total": 4,
        "retained": 1,
        "invalid": 2,
        "excluded": 1,
    }
    assert [row["row_status"] for row in body["flagged_rows"]] == [
        "INVALID",
        "INVALID",
        "EXCLUDED",
    ]
    assert body["flagged_rows"][1]["reason"] == "invoice_no is null"
    assert body["flagged_rows"][2]["reason"] == f"unit_price > {ceiling}"

    sql_text = "\n".join(cursor.queries)
    assert "invoice_no is null" in sql_text
    assert "stock_code is null" in sql_text
    assert "quantity <= 0" in sql_text
    assert "unit_price <= 0" in sql_text
    assert f"unit_price > {ceiling}" in sql_text
