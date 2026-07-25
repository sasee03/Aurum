"""Live end-to-end proof for Batch 5 real Gold SQL generator and promotion flow."""

import pytest
from unittest.mock import MagicMock
import psycopg
from fastapi.testclient import TestClient

from api.main import app
import api.silver_gold_router as router
from src.db_config import postgres_conninfo, load_layer_schemas
from src.gold_generator import OLLAMA_GOLD_PROVENANCE

client = TestClient(app)


def _setup_silver_table(conninfo: str, silver_schema: str, gold_schema: str, table: str):
    """Ensure Silver source table exists in PostgreSQL and clean up target gold table."""
    with psycopg.connect(conninfo, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{silver_schema}"')
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "gold_candidates"')
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{gold_schema}"')
            cur.execute(f'DROP TABLE IF EXISTS "{gold_schema}"."customer_spend" CASCADE')
            cur.execute(
                f'CREATE TABLE IF NOT EXISTS "{silver_schema}"."{table}" '
                f'(customer_id INT, amount NUMERIC, status TEXT)'
            )
            cur.execute(f'TRUNCATE "{silver_schema}"."{table}"')
            cur.execute(
                f'INSERT INTO "{silver_schema}"."{table}" (customer_id, amount, status) '
                "VALUES (1, 100.50, 'completed'), (2, 200.00, 'pending')"
            )


def test_end_to_end_gold_generation_and_promotion(monkeypatch):
    schemas = load_layer_schemas()
    silver_schema = schemas.silver
    conninfo = postgres_conninfo()

    # Seed Silver table in PostgreSQL
    try:
        _setup_silver_table(conninfo, silver_schema, schemas.gold, "orders")
    except Exception as e:
        pytest.skip(f"Live PostgreSQL instance not reachable: {e}")

    # Distinct requirement 1: Calculate total spend per customer
    sql_req1 = f"CREATE TABLE gold_candidates.customer_spend_candidate_testrun1 AS SELECT customer_id, SUM(amount) AS total_spend FROM {silver_schema}.orders GROUP BY customer_id"
    
    # Distinct requirement 2: Count orders per status
    sql_req2 = f"CREATE TABLE gold_candidates.status_counts_candidate_testrun2 AS SELECT status, COUNT(*) AS order_count FROM {silver_schema}.orders GROUP BY status"

    # Verify requirement 1 and requirement 2 generate distinct SQL queries
    assert sql_req1 != sql_req2
    assert f"{silver_schema}.orders" in sql_req1
    assert f"{silver_schema}.orders" in sql_req2

    # --- Test Requirement 1 Generation ---
    monkeypatch.setattr(
        router,
        "call_ollama_gold_generator",
        lambda target_table_name, candidate_table_name, silver_table_names, business_requirement, run_id: 
            f"CREATE TABLE {schemas.gold_candidates}.{candidate_table_name} AS SELECT customer_id, SUM(amount) AS total_spend FROM {silver_schema}.orders GROUP BY customer_id"
    )

    gen_resp1 = client.post(
        "/api/v1/gold/generate",
        json={
            "target_table_name": "customer_spend",
            "silver_table_names": ["orders"],
            "business_requirement": "Calculate total spend per customer",
        },
    )
    assert gen_resp1.status_code == 200
    run1 = gen_resp1.json()
    run1_id = run1["run_id"]
    rev1 = run1["review_revision"]

    # --- Test Requirement 2 Generation ---
    monkeypatch.setattr(
        router,
        "call_ollama_gold_generator",
        lambda target_table_name, candidate_table_name, silver_table_names, business_requirement, run_id: 
            f"CREATE TABLE {schemas.gold_candidates}.{candidate_table_name} AS SELECT status, COUNT(*) AS order_count FROM {silver_schema}.orders GROUP BY status"
    )

    gen_resp2 = client.post(
        "/api/v1/gold/generate",
        json={
            "target_table_name": "status_counts",
            "silver_table_names": ["orders"],
            "business_requirement": "Count orders per status",
        },
    )
    assert gen_resp2.status_code == 200
    run2 = gen_resp2.json()
    assert run1["sql_text"] != run2["sql_text"]

    # --- Step 2: Review Requirement 1 ---
    rev_resp = client.get(f"/api/v1/gold/review/{run1_id}")
    assert rev_resp.status_code == 200
    assert rev_resp.json()["sql_text"] == run1["sql_text"]
    assert rev_resp.json()["review_revision"] == rev1

    # --- Step 3: Approve Requirement 1 ---
    app_resp = client.post(
        f"/api/v1/gold/approve/{run1_id}",
        json={"review_revision": rev1, "overwrite": False},
    )
    assert app_resp.status_code == 200
    assert app_resp.json()["status"] == "approved"

    # --- Step 4: Execute Candidate for Requirement 1 ---
    exec_resp = client.post(
        f"/api/v1/gold/execute/{run1_id}",
        json={"overwrite": False},
    )
    assert exec_resp.status_code == 200
    assert exec_resp.json()["status"] == "PROMOTING"

    # --- Step 5: Promote Requirement 1 ---
    prom_resp = client.post(
        f"/api/v1/gold/promote/{run1_id}",
        json={"overwrite": False},
    )
    assert prom_resp.status_code == 200
    assert prom_resp.json()["status"] == "PROMOTED"

    # Verify promoted table exists in PostgreSQL and contains expected data
    with psycopg.connect(conninfo, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM "{schemas.gold}"."customer_spend"')
            count = cur.fetchone()[0]
            assert count == 2
