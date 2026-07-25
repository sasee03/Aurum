"""Tests for P1 source-to-bronze ingestion pipeline."""
import pytest
import psycopg
from fastapi.testclient import TestClient

import api.main as api_main
from src.db_config import postgres_conninfo

@pytest.fixture
def client():
    with TestClient(api_main.app) as test_client:
        yield test_client

@pytest.fixture(scope="module")
def db_conn():
    """Module-level db connection for setup/teardown."""
    conn = psycopg.connect(postgres_conninfo())
    conn.autocommit = True
    yield conn
    conn.close()

def setup_source_tables(conn):
    """Create test tables in the source schema."""
    tables = {
        "src_orders":    [("id INT", [(i,) for i in range(1, 11)]),],         # 10 rows
        "src_customers": [("cid INT, name TEXT", [(1, "Alice"), (2, "Bob"), (3, "Carol")]),],  # 3 rows
        "src_products":  [("sku TEXT, price NUMERIC", [("A", 9.99), ("B", 19.99), ("C", 29.99), ("D", 4.99), ("E", 14.99)]),],  # 5 rows
        "src_shipments": [("sid INT", [(i,) for i in range(1, 8)]),],          # 7 rows
        "src_returns":   [("rid INT, reason TEXT", [(1, "damaged"), (2, "wrong item")]),],  # 2 rows
    }
    expected_counts = {}
    with conn.cursor() as cur:
        for tname, specs in tables.items():
            cols_ddl, rows = specs[0]
            cur.execute(f"DROP TABLE IF EXISTS source.{tname}")
            cur.execute(f"DROP TABLE IF EXISTS bronze.{tname}")
            cur.execute(f"CREATE TABLE source.{tname} ({cols_ddl})")
            for row in rows:
                vals_str = "(" + ", ".join(repr(x) if isinstance(x, str) else str(x) for x in row) + ")"
                cur.execute(f"INSERT INTO source.{tname} VALUES {vals_str}")
            expected_counts[tname] = len(rows)
    return expected_counts

def test_multi_table_ingest_and_verify(client, db_conn):
    """EVIDENCE 1: Multi-table ingest and verify works natively."""
    expected_counts = setup_source_tables(db_conn)
    table_names = list(expected_counts.keys())
    
    # 1. Ingest
    resp = client.post("/api/v1/source/ingest-to-bronze", json={"tables": table_names})
    assert resp.status_code == 200, resp.text
    results = resp.json()["results"]
    for r in results:
        assert r["status"] == "success", f"Table {r['table']} failed to ingest: {r}"
        
    # 2. Verify
    resp = client.post("/api/v1/source/verify-bronze", json={"tables": table_names})
    assert resp.status_code == 200, resp.text
    for r in resp.json()["results"]:
        assert r["status"] == "success"
        assert r["match"] is True
        assert r["source_row_count"] == expected_counts[r["table"]]
        assert r["bronze_row_count"] == expected_counts[r["table"]]

def test_rollback_on_failed_create(client, db_conn, monkeypatch):
    """EVIDENCE 2: CREATE failure preserves existing bronze table (transaction works)."""
    # First ensure we have a valid bronze table
    expected_counts = setup_source_tables(db_conn)
    
    with db_conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS bronze.src_orders AS SELECT * FROM source.src_orders")
        cur.execute("ALTER TABLE bronze.src_orders OWNER TO aurum_ingestion")
    
    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM bronze.src_orders")
        old_count = cur.fetchone()[0]
    assert old_count == 10
    
    # Patch the router code AT RUNTIME to force a postgres syntax error in CREATE
    import api.source_ingest_router
    orig_ingest = api.source_ingest_router.ingest_to_bronze
    
    # We will simulate the failure by modifying the SQL string before it gets executed.
    # But wait, patching the function is hard. 
    # Let's mock the psycopg cursor execute method to raise an error specifically for CREATE TABLE.
    import psycopg.cursor
    orig_execute = psycopg.cursor.Cursor.execute
    
    def mocked_execute(self, query, *args, **kwargs):
        if hasattr(query, "as_string"):
            query_str = query.as_string(self.connection)
        else:
            query_str = str(query)
            
        if "CREATE TABLE" in query_str and "bronze" in query_str.lower() and "src_orders" in query_str.lower():
            raise psycopg.errors.DivisionByZero("Simulated failure during CREATE TABLE")
        return orig_execute(self, query, *args, **kwargs)
        
    monkeypatch.setattr(psycopg.cursor.Cursor, "execute", mocked_execute)
    
    # Call the endpoint
    resp = client.post("/api/v1/source/ingest-to-bronze", json={"tables": ["src_orders"]})
    assert resp.status_code == 200
    result = resp.json()["results"][0]
    
    assert result["status"] == "error"
    assert "Simulated failure" in result["error"] or "division by zero" in result["error"]
    
    # Verify rollback - bronze table must still exist and have 10 rows
    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM bronze.src_orders")
        new_count = cur.fetchone()[0]
        
    assert new_count == old_count, "Rollback failed! Bronze table was lost."
