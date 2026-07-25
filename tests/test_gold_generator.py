"""Tests for real Ollama Gold SQL generator and router integration."""

from unittest.mock import patch, MagicMock
import pytest
import requests
from fastapi.testclient import TestClient

from api.main import app
import api.silver_gold_router as router
from src.gold_generator import (
    strip_markdown_code_fences,
    build_gold_prompt,
    call_ollama_gold_generator,
    OLLAMA_GOLD_PROVENANCE,
)
from src.sql_safety import SqlSafetyViolation

client = TestClient(app)


def test_strip_markdown_code_fences():
    raw_sql = "```sql\nCREATE TABLE gold_candidates.test_candidate_123 AS SELECT 1 AS id\n```"
    assert strip_markdown_code_fences(raw_sql) == "CREATE TABLE gold_candidates.test_candidate_123 AS SELECT 1 AS id"

    raw_plain = "CREATE TABLE gold_candidates.test_candidate_123 AS SELECT 1 AS id"
    assert strip_markdown_code_fences(raw_plain) == "CREATE TABLE gold_candidates.test_candidate_123 AS SELECT 1 AS id"

    raw_whitespace = "  ```\nSELECT 1\n```  "
    assert strip_markdown_code_fences(raw_whitespace) == "SELECT 1"


def test_build_gold_prompt():
    meta = {"clean_orders": [("order_id", "integer"), ("amount", "numeric")]}
    prompt = build_gold_prompt(
        silver_tables_meta=meta,
        target_table_name="order_summary",
        candidate_table_name="order_summary_candidate_run123",
        candidate_schema="gold_candidates",
        silver_schema="tenant_curated",
        business_requirement="Sum amounts by order ID",
    )
    assert "tenant_curated.clean_orders" in prompt
    assert "order_id (integer)" in prompt
    assert "gold_candidates.order_summary_candidate_run123" in prompt
    assert "Sum amounts by order ID" in prompt


from src.db_config import load_layer_schemas

def test_call_ollama_gold_generator_happy_path(monkeypatch):
    silver_schema = load_layer_schemas().silver
    valid_sql = f"CREATE TABLE gold_candidates.order_summary_candidate_run123 AS SELECT order_id, SUM(amount) AS total FROM {silver_schema}.clean_orders GROUP BY order_id"

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"response": f"```sql\n{valid_sql}\n```"}
    mock_resp.raise_for_status.return_value = None

    monkeypatch.setattr(
        "src.gold_generator.fetch_silver_table_columns",
        lambda silver_tables: {"clean_orders": [("order_id", "integer"), ("amount", "numeric")]},
    )
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: mock_resp)

    res = call_ollama_gold_generator(
        target_table_name="order_summary",
        candidate_table_name="order_summary_candidate_run123",
        silver_table_names=["clean_orders"],
        business_requirement="Sum amounts by order ID",
        run_id="run123",
    )
    assert res == valid_sql


def test_call_ollama_gold_generator_timeout_fails_fast(monkeypatch):
    monkeypatch.setattr(
        "src.gold_generator.fetch_silver_table_columns",
        lambda silver_tables: {"clean_orders": [("order_id", "integer")]},
    )

    def timeout_post(*args, **kwargs):
        raise requests.exceptions.Timeout("Connection timed out")

    monkeypatch.setattr(requests, "post", timeout_post)

    with pytest.raises(TimeoutError) as exc_info:
        call_ollama_gold_generator(
            target_table_name="order_summary",
            candidate_table_name="order_summary_candidate_run123",
            silver_table_names=["clean_orders"],
            business_requirement="Sum amounts",
            run_id="run123",
        )
    assert "timed out" in str(exc_info.value)


def test_call_ollama_gold_generator_retry_once_on_validation_failure(monkeypatch):
    silver_schema = load_layer_schemas().silver
    invalid_sql = f"SELECT * FROM {silver_schema}.clean_orders"  # Not a CTAS
    valid_sql = f"CREATE TABLE gold_candidates.order_summary_candidate_run123 AS SELECT order_id FROM {silver_schema}.clean_orders"

    responses = [
        {"response": invalid_sql},
        {"response": f"```sql\n{valid_sql}\n```"},
    ]

    def mock_post(*args, **kwargs):
        resp_data = responses.pop(0)
        m = MagicMock()
        m.json.return_value = resp_data
        m.raise_for_status.return_value = None
        return m

    monkeypatch.setattr(
        "src.gold_generator.fetch_silver_table_columns",
        lambda silver_tables: {"clean_orders": [("order_id", "integer")]},
    )
    monkeypatch.setattr(requests, "post", mock_post)

    res = call_ollama_gold_generator(
        target_table_name="order_summary",
        candidate_table_name="order_summary_candidate_run123",
        silver_table_names=["clean_orders"],
        business_requirement="Get order IDs",
        run_id="run123",
    )
    assert res == valid_sql


def test_generate_gold_sql_endpoint_success(monkeypatch):
    monkeypatch.setattr(
        router,
        "GOLD_GENERATOR_TRUST",
        router.GeneratorTrustPolicy(
            pipeline="gold",
            trusted_hardened_provenances=frozenset({OLLAMA_GOLD_PROVENANCE}),
        ),
    )
    silver_schema = load_layer_schemas().silver
    valid_sql = f"CREATE TABLE gold_candidates.revenue_report_candidate_testrun AS SELECT customer_id, SUM(price) AS revenue FROM {silver_schema}.orders GROUP BY customer_id"

    def mock_generator(*args, **kwargs):
        return valid_sql

    monkeypatch.setattr(router, "call_ollama_gold_generator", mock_generator)

    response = client.post(
        "/api/v1/gold/generate",
        json={
            "target_table_name": "revenue_report",
            "silver_table_names": ["orders"],
            "business_requirement": "Calculate revenue per customer",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["table_name"] == "revenue_report"
    assert data["status"] == "PENDING"
    assert data["generator_provenance"] == OLLAMA_GOLD_PROVENANCE
    assert data["sql_text"] == valid_sql
    assert "run_id" in data
    assert "review_revision" in data
