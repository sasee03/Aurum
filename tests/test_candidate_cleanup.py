"""Tests for candidate table retry collision fix and bulk hygiene cleanup utility."""

import datetime
import uuid
import psycopg
import pytest

from src.db_config import load_layer_schemas, postgres_promotion_conninfo, get_generated_sql_pool
from src.sql_safety import execute_candidate_sql
from src.promotion import discard_candidate_table
from src.app_state.db import get_connection, init_schema
from src.candidate_cleanup import cleanup_orphaned_candidate_tables


def test_retry_collision_recovery():
    """Verify execute_candidate_sql safely removes stale leftovers before re-creating candidate table."""
    schemas = load_layer_schemas()
    run_id = f"test_retry_{uuid.uuid4().hex[:8]}"
    target_table = f"orders_retry_{run_id}"
    candidate_table = f"{target_table}_candidate_{run_id}"
    
    # 1. Simulate a mid-execution leftover table owned by aurum_promotion
    with get_generated_sql_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f'CREATE TABLE "{schemas.silver_candidates}"."{candidate_table}" (id int)')
            cur.execute(f'ALTER TABLE "{schemas.silver_candidates}"."{candidate_table}" OWNER TO aurum_promotion')
            conn.commit()

    # Verify stale table exists
    with get_generated_sql_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT to_regclass(\'"{schemas.silver_candidates}"."{candidate_table}"\')')
            assert cur.fetchone()[0] is not None

    # 2. Retry execution using execute_candidate_sql
    sql = f'CREATE TABLE {schemas.silver_candidates}.{candidate_table} AS SELECT 1 AS id'
    with get_generated_sql_pool().connection() as conn:
        execute_candidate_sql(sql, conn, expected_schema=schemas.silver_candidates, run_id=run_id)
        conn.commit()

    # 3. Confirm execution succeeded without collision error
    with get_generated_sql_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM "{schemas.silver_candidates}"."{candidate_table}"')
            assert cur.fetchone()[0] == 1

    # Cleanup after test
    discard_candidate_table(candidate_table, schemas.silver_candidates, postgres_promotion_conninfo())


def test_bulk_cleanup_utility_differentiation():
    """Test cleanup utility accurately segregates orphaned, in-flight, and untracked candidate tables."""
    schemas = load_layer_schemas()
    
    run_stale = f"run_stale_{uuid.uuid4().hex[:8]}"
    run_fresh = f"run_fresh_{uuid.uuid4().hex[:8]}"
    
    tbl_stale = f"stale_test_candidate_{run_stale}"
    tbl_fresh = f"fresh_test_candidate_{run_fresh}"
    tbl_untracked = f"untracked_test_candidate_run_{uuid.uuid4().hex[:8]}"
    
    # Seed SQLite metadata with candidate_schema
    stale_time = (datetime.datetime.utcnow() - datetime.timedelta(hours=2)).isoformat()
    fresh_time = datetime.datetime.utcnow().isoformat()
    
    with get_connection() as conn:
        init_schema(conn)
        conn.execute(
            "INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status, candidate_schema) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_stale, "stale_test", f"CREATE TABLE {schemas.silver_candidates}.{tbl_stale} AS SELECT 1", "{}", stale_time, "PENDING", schemas.silver_candidates)
        )
        conn.execute(
            "INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status, candidate_schema) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_fresh, "fresh_test", f"CREATE TABLE {schemas.silver_candidates}.{tbl_fresh} AS SELECT 1", "{}", fresh_time, "PENDING", schemas.silver_candidates)
        )
        conn.commit()
        
    # Create candidate tables in Postgres via aurum_promotion
    with psycopg.connect(postgres_promotion_conninfo()) as p_conn:
        with p_conn.cursor() as cur:
            cur.execute(f'CREATE TABLE "{schemas.silver_candidates}"."{tbl_stale}" (id int)')
            cur.execute(f'CREATE TABLE "{schemas.silver_candidates}"."{tbl_fresh}" (id int)')
            cur.execute(f'CREATE TABLE "{schemas.silver_candidates}"."{tbl_untracked}" (id int)')
        p_conn.commit()

    # Run cleanup utility (1 hour threshold)
    res = cleanup_orphaned_candidate_tables(age_threshold_seconds=3600)
    
    removed_tables = [r["table"] for r in res["removed_candidates"]]
    in_flight_tables = [r["table"] for r in res["in_flight_candidates"]]
    untracked_tables = [r["table"] for r in res["untracked_candidates"]]
    
    assert tbl_stale in removed_tables
    assert tbl_fresh in in_flight_tables
    assert tbl_untracked in untracked_tables
    
    # Confirm in Postgres that ONLY stale table was dropped
    with get_generated_sql_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT to_regclass(\'"{schemas.silver_candidates}"."{tbl_stale}"\')')
            assert cur.fetchone()[0] is None
            
            cur.execute(f'SELECT to_regclass(\'"{schemas.silver_candidates}"."{tbl_fresh}"\')')
            assert cur.fetchone()[0] is not None
            
            cur.execute(f'SELECT to_regclass(\'"{schemas.silver_candidates}"."{tbl_untracked}"\')')
            assert cur.fetchone()[0] is not None

    # Final cleanup of remaining test tables
    discard_candidate_table(tbl_fresh, schemas.silver_candidates, postgres_promotion_conninfo())
    discard_candidate_table(tbl_untracked, schemas.silver_candidates, postgres_promotion_conninfo())


def test_table_name_mismatch_untracked_safety():
    """Regression test: A candidate table with matching run_id but mismatched target table_name is treated as UNTRACKED and NOT deleted."""
    schemas = load_layer_schemas()
    run_id = f"run_shadow_{uuid.uuid4().hex[:8]}"

    tracked_target = "tracked_table_A"
    shadow_target = "shadow_table_B"
    shadow_candidate_table = f"{shadow_target}_candidate_{run_id}"

    # 1. Seed SQLite metadata for tracked_target
    stale_time = (datetime.datetime.utcnow() - datetime.timedelta(hours=2)).isoformat()
    with get_connection() as conn:
        init_schema(conn)
        conn.execute(
            "INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status, candidate_schema) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, tracked_target, f"CREATE TABLE {schemas.silver_candidates}.{tracked_target}_candidate_{run_id} AS SELECT 1", "{}", stale_time, "PENDING", schemas.silver_candidates)
        )
        conn.commit()

    # 2. Create shadow candidate table (shadow_target != tracked_target) in Postgres
    with psycopg.connect(postgres_promotion_conninfo()) as p_conn:
        with p_conn.cursor() as cur:
            cur.execute(f'CREATE TABLE "{schemas.silver_candidates}"."{shadow_candidate_table}" (id int)')
        p_conn.commit()

    # 3. Run cleanup utility
    res = cleanup_orphaned_candidate_tables(age_threshold_seconds=3600)
    untracked_tables = [r["table"] for r in res["untracked_candidates"]]
    removed_tables = [r["table"] for r in res["removed_candidates"]]

    # Assert it is classified as UNTRACKED and NOT in removed_candidates
    assert shadow_candidate_table in untracked_tables
    assert shadow_candidate_table not in removed_tables

    # 4. Verify candidate STILL EXISTS in Postgres
    with psycopg.connect(postgres_promotion_conninfo()) as p_conn:
        with p_conn.cursor() as cur:
            cur.execute(f'SELECT to_regclass(\'"{schemas.silver_candidates}"."{shadow_candidate_table}"\')')
            assert cur.fetchone()[0] is not None

    # Cleanup test table
    discard_candidate_table(shadow_candidate_table, schemas.silver_candidates, postgres_promotion_conninfo())


def test_admin_cleanup_endpoint_guard():
    """Verify POST /api/v1/admin/candidate-cleanup requires confirm=true."""
    from fastapi.testclient import TestClient
    from api.main import app

    client = TestClient(app)

    # Call without confirm=true -> HTTP 400
    resp_no_confirm = client.post("/api/v1/admin/candidate-cleanup")
    assert resp_no_confirm.status_code == 400
    assert "explicit confirmation" in resp_no_confirm.json()["detail"]

    # Call with confirm=true -> HTTP 200
    resp_confirm = client.post("/api/v1/admin/candidate-cleanup?confirm=true")
    assert resp_confirm.status_code == 200
    assert resp_confirm.json()["status"] == "success"
