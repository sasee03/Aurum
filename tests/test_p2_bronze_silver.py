import json
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from api.main import app
from src.app_state.db import get_connection

@pytest.fixture
def temp_sqlite_db(monkeypatch):
    """Isolated temporary SQLite database for app state testing."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    monkeypatch.setenv("AURUM_APP_STATE_DB", str(tmp_path))
    yield tmp_path
    if tmp_path.exists():
        try:
            tmp_path.unlink()
        except OSError:
            pass

def test_p2_rules_validation_and_persistence(temp_sqlite_db):
    client = TestClient(app)
    base_url = "/api/v1/transform"
    table_name = "src_orders_test"

    # 1. Reject empty rules
    resp = client.post(f"{base_url}/rules", json={"table_name": table_name, "rules": []})
    assert resp.status_code == 400
    assert "Rules must not be empty" in resp.json()["detail"]

    # 2. Reject whitespace-only rules
    resp = client.post(f"{base_url}/rules", json={"table_name": table_name, "rules": ["   "]})
    assert resp.status_code == 400
    assert "whitespace-only" in resp.json()["detail"]

    # 3. Reject duplicate rules
    resp = client.post(f"{base_url}/rules", json={"table_name": table_name, "rules": ["Remove nulls", "Remove nulls"]})
    assert resp.status_code == 400
    assert "Duplicate rules" in resp.json()["detail"]

    # 4. Save valid rules
    rules = ["Filter invalid amounts", "Trim string fields"]
    resp = client.post(f"{base_url}/rules", json={"table_name": table_name, "rules": rules})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # 5. Retrieve saved rules
    resp = client.get(f"{base_url}/rules/{table_name}")
    assert resp.status_code == 200
    assert resp.json()["rules"] == rules

def test_p2_generator_unavailable_behavior(temp_sqlite_db, monkeypatch):
    client = TestClient(app)
    base_url = "/api/v1/transform"
    table_name = "src_orders_test"

    # Seed rules first
    client.post(f"{base_url}/rules", json={"table_name": table_name, "rules": ["Rule 1"]})

    # Mock get_table_schema so schema check passes without requiring Postgres
    monkeypatch.setattr("api.bronze_silver_router.get_table_schema", lambda t: "- col1 (text)")

    resp = client.post(f"{base_url}/generate", json={"table_name": table_name})
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()

def test_p2_review_executed_mapping(temp_sqlite_db):
    client = TestClient(app)
    base_url = "/api/v1/transform"
    run_id = "run_test_review_1"
    table_name = "src_orders_test"

    valid_sql = (
        f"CREATE TABLE silver_candidates.{table_name}_candidate_{run_id} AS "
        f"WITH step_1 AS (SELECT * FROM bronze.{table_name}) SELECT * FROM step_1;"
    )

    # Seed a pending review record directly into isolated SQLite
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status)
            VALUES (?, ?, ?, ?, ?, 'PENDING')
            """,
            (
                run_id,
                table_name,
                valid_sql,
                json.dumps({"summary": "1 step", "rules": ["Step 1: test rule"]}),
                "2026-07-23T00:00:00Z"
            )
        )
        conn.commit()

    # Review pending run -> executed must be False
    resp = client.get(f"{base_url}/review/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["executed"] is False
    assert data["status"] == "PENDING"

    # Update status to PROMOTED and set valid target identity
    promoted_ident = json.dumps({
        "database_oid": 12345,
        "namespace_oid": 10,
        "relation_oid": 100,
        "schema": "silver",
        "relation_name": table_name,
        "relation_kind": "r",
    })
    with get_connection() as conn:
        conn.execute("UPDATE generated_sql_review SET status = 'PROMOTED', promoted_target_identity_json = ? WHERE run_id = ?", (promoted_ident, run_id))
        conn.commit()

    # Review promoted run -> executed must be True
    resp = client.get(f"{base_url}/review/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["executed"] is True
    assert data["status"] == "PROMOTED"

def test_p2_execute_idempotency_and_safety_checks(temp_sqlite_db):
    client = TestClient(app)
    base_url = "/api/v1/transform"

    # 1. Non-existent run_id returns 404
    resp = client.post(f"{base_url}/execute/run_nonexistent")
    assert resp.status_code == 404

    valid_sql = (
        "CREATE TABLE silver_candidates.src_orders_test_candidate_run_promoted_1 AS "
        "WITH step_1 AS (SELECT * FROM bronze.src_orders_test) SELECT * FROM step_1;"
    )

    # 2. Already PROMOTED run returns stored result idempotently
    promoted_run_id = "run_promoted_1"
    attr_log = ["Initial Bronze Rows: 100", "Step 1: 10 rows removed"]
    promoted_ident = json.dumps({
        "database_oid": 12345,
        "namespace_oid": 10,
        "relation_oid": 100,
        "schema": "silver",
        "relation_name": "src_orders_test",
        "relation_kind": "r",
    })
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status, attribution_log_json, promoted_target_identity_json)
            VALUES (?, ?, ?, ?, ?, 'PROMOTED', ?, ?)
            """,
            (
                promoted_run_id,
                "src_orders_test",
                valid_sql,
                json.dumps({"summary": "1 step", "rules": ["Step 1: test rule"]}),
                "2026-07-23T00:00:00Z",
                json.dumps(attr_log),
                promoted_ident,
            )
        )
        conn.commit()

    resp = client.post(f"{base_url}/execute/{promoted_run_id}")
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["status"] == "success"
    assert res_data["attribution_log"] == attr_log
    assert "already executed" in res_data["message"]

    # 3. EXECUTING status returns 409 Conflict
    executing_run_id = "run_executing_1"
    valid_exec_sql = (
        "CREATE TABLE silver_candidates.src_orders_test_candidate_run_executing_1 AS "
        "WITH step_1 AS (SELECT * FROM bronze.src_orders_test) SELECT * FROM step_1;"
    )
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status)
            VALUES (?, ?, ?, ?, ?, 'EXECUTING')
            """,
            (
                executing_run_id,
                "src_orders_test",
                valid_exec_sql,
                json.dumps({"summary": "1 step", "rules": ["Step 1: test rule"]}),
                "2026-07-23T00:00:00Z"
            )
        )
        conn.commit()

    resp = client.post(f"{base_url}/execute/{executing_run_id}")
    assert resp.status_code == 409
    assert "already in progress" in resp.json()["detail"]
