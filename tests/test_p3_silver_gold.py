import pytest
from fastapi.testclient import TestClient
from api.main import app
import api.silver_gold_router as router
from src.db_config import load_layer_schemas
import sqlite3

client = TestClient(app)

@pytest.fixture(autouse=True)
def mock_db_and_llm(monkeypatch, tmp_path):
    schemas = load_layer_schemas()
    
    # Mock LLM to return standard response without sleeping
    def fast_llm_stubbed(prompt):
        import re
        run_id_match = re.search(r"_candidate_(run_[a-f0-9]+)", prompt)
        run_id = run_id_match.group(1) if run_id_match else "run_mock"
        table_match = re.search(r"Candidate Table Name: ([a-zA-Z0-9_]+)_candidate_", prompt)
        table_name = table_match.group(1) if table_match else "daily_sales"
        return f"```sql\nCREATE TABLE {schemas.gold_candidates}.{table_name}_candidate_{run_id} AS\nSELECT 1;\n```"
    monkeypatch.setattr(router, "call_llm_stubbed", fast_llm_stubbed)
    
    # Mock schema fetcher
    def mock_get_schemas(schema_name, table_names):
        return f"Table: {table_names[0]}\nColumns:\n  - id (int)"
    monkeypatch.setattr(router, "get_multiple_table_schemas", mock_get_schemas)
    
    # Mock table existence checker
    fake_tables = set()
    def mock_check_exists(schema_name, table_name):
        return table_name in fake_tables
    monkeypatch.setattr(router, "check_table_exists", mock_check_exists)
    
    yield {"fake_tables": fake_tables}

def test_check_name(mock_db_and_llm):
    # Valid and available
    resp = client.get("/api/v1/gold/check-name?name=daily_sales")
    assert resp.status_code == 200
    assert resp.json()["status"] == "available"
    assert resp.json()["is_available"] is True
    
    # Invalid identifier
    resp = client.get("/api/v1/gold/check-name?name=DROP TABLE")
    assert resp.status_code == 200
    assert resp.json()["status"] == "invalid"
    
    # Taken
    mock_db_and_llm["fake_tables"].add("taken_table")
    resp = client.get("/api/v1/gold/check-name?name=taken_table")
    assert resp.status_code == 200
    assert resp.json()["status"] == "taken"
    assert len(resp.json()["resolution_options"]) == 2
    assert resp.json()["resolution_options"][0]["action"] == "overwrite"

def test_structural_extraction():
    sql = '''
    CREATE TABLE gold_candidates.candidate AS 
    SELECT 
        DATE(order_date) as order_day, 
        COUNT(order_id) as total_orders 
    FROM silver.orders 
    JOIN silver.customers ON silver.orders.customer_id = silver.customers.id
    WHERE order_date > '2023-01-01'
    GROUP BY DATE(order_date)
    '''
    summary = router.summarize_sql_structure(sql)
    assert 'DATE(order_date)' in summary['dimensions']
    assert 'total_orders' in summary['metrics']
    assert summary['filters_applied'] is True
    assert 'orders' in summary['summary']
    assert 'customers' in summary['summary']

def test_generate_and_review():
    payload = {
        "target_table_name": "daily_sales",
        "silver_table_names": ["orders"],
        "business_requirement": "Count orders by day"
    }
    
    # Generate
    resp = client.post("/api/v1/gold/generate", json=payload)
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    
    # Review
    resp = client.get(f"/api/v1/gold/review/{run_id}")
    assert resp.status_code == 200
    assert "SELECT 1" in resp.json()["sql_text"]
    assert "message" in resp.json()

def test_execute_toctou_safety(mock_db_and_llm, monkeypatch):
    # Mock out execution
    monkeypatch.setattr(router, "execute_candidate_sql", lambda sql, conn, run_id: None)
    monkeypatch.setattr(router, "promote_candidate_table", lambda **kwargs: None)
    
    # Mock pool connection for preview
    class MockCursor:
        def execute(self, *args): pass
        def fetchone(self): return [10]
        def fetchall(self): return [(1,)]
        @property
        def description(self): return [("col1",)]
        def __enter__(self): return self
        def __exit__(self, *args): pass
    
    class MockConn:
        def cursor(self): return MockCursor()
        def commit(self): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        
    class MockPool:
        def connection(self): return MockConn()
        
    monkeypatch.setattr(router, "get_generated_sql_pool", lambda: MockPool())
    
    payload = {
        "target_table_name": "conflict_test",
        "silver_table_names": ["orders"],
        "business_requirement": "test"
    }
    resp = client.post("/api/v1/gold/generate", json=payload)
    run_id = resp.json()["run_id"]
    
    # TOCTOU: table gets created by someone else
    mock_db_and_llm["fake_tables"].add("conflict_test")
    
    # Execute without overwrite flag
    resp = client.post(f"/api/v1/gold/execute/{run_id}", json={"overwrite": False})
    assert resp.status_code == 409
    assert "overwrite=True" in resp.json()["detail"]
    
    # Execute WITH overwrite flag
    resp = client.post(f"/api/v1/gold/execute/{run_id}", json={"overwrite": True})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert resp.json()["total_rows"] == 10
