"""Unit tests for atomic table promotion."""

import psycopg
import pytest

from src.db_config import postgres_conninfo
from src.promotion import PromotionError, candidate_table_name, promote_candidate_table

@pytest.fixture
def promotion_conn():
    # Use superuser for testing setup
    return postgres_conninfo()

def test_promotion_rollback_on_failure(promotion_conn):
    # Setup schemas and dummy tables
    with psycopg.connect(promotion_conn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS test_candidate;")
            cur.execute("CREATE SCHEMA IF NOT EXISTS test_active;")
            cur.execute("DROP TABLE IF EXISTS test_active.real_table;")
            cur.execute("CREATE TABLE test_active.real_table AS SELECT 1 AS v;")
            
            cur.execute("DROP TABLE IF EXISTS test_candidate.cand_table;")
            cur.execute("CREATE TABLE test_candidate.cand_table AS SELECT 2 AS v;")
            
    with pytest.raises(PromotionError, match="Candidate table does not exist"):
        promote_candidate_table(
            "missing_cand_table",
            "test_candidate",
            "real_table",
            "test_active",
            promotion_conn
        )
        
    # Verify rollback protected the old active table
    with psycopg.connect(promotion_conn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT v FROM test_active.real_table;")
            res = cur.fetchone()
            assert res[0] == 1, "The active table should not have been dropped or replaced"
            
            # Verify candidate table also still exists
            cur.execute("SELECT v FROM test_candidate.cand_table;")
            res2 = cur.fetchone()
            assert res2[0] == 2, "Candidate table should not have been lost"


def test_promotion_swaps_candidate_and_removes_superseded(promotion_conn):
    with psycopg.connect(promotion_conn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS test_candidate;")
            cur.execute("CREATE SCHEMA IF NOT EXISTS test_active;")
            cur.execute("DROP TABLE IF EXISTS test_active.real_table__superseded;")
            cur.execute("DROP TABLE IF EXISTS test_active.real_table;")
            cur.execute("DROP TABLE IF EXISTS test_candidate.real_table_candidate_run_1;")
            cur.execute("CREATE TABLE test_active.real_table AS SELECT 1 AS v;")
            cur.execute("CREATE TABLE test_candidate.real_table_candidate_run_1 AS SELECT 2 AS v;")

    promote_candidate_table(
        "real_table_candidate_run_1",
        "test_candidate",
        "real_table",
        "test_active",
        promotion_conn,
    )

    with psycopg.connect(promotion_conn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT v FROM test_active.real_table;")
            assert cur.fetchone()[0] == 2
            cur.execute("SELECT to_regclass('test_active.real_table__superseded');")
            assert cur.fetchone()[0] is None
            cur.execute("SELECT to_regclass('test_candidate.real_table_candidate_run_1');")
            assert cur.fetchone()[0] is None


def test_promotion_allows_first_active_table(promotion_conn):
    with psycopg.connect(promotion_conn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS test_candidate;")
            cur.execute("CREATE SCHEMA IF NOT EXISTS test_active;")
            cur.execute("DROP TABLE IF EXISTS test_active.first_table;")
            cur.execute("DROP TABLE IF EXISTS test_candidate.first_table_candidate_run_1;")
            cur.execute("CREATE TABLE test_candidate.first_table_candidate_run_1 AS SELECT 3 AS v;")

    promote_candidate_table(
        "first_table_candidate_run_1",
        "test_candidate",
        "first_table",
        "test_active",
        promotion_conn,
    )

    with psycopg.connect(promotion_conn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT v FROM test_active.first_table;")
            assert cur.fetchone()[0] == 3


def test_candidate_table_name_includes_unique_run_id():
    assert candidate_table_name("orders", "run_20260721") == "orders_candidate_run_20260721"


def test_candidate_table_name_rejects_unsafe_identifiers():
    with pytest.raises(PromotionError, match="Unsafe target table"):
        candidate_table_name("orders;drop", "run_1")
    with pytest.raises(PromotionError, match="Unsafe run id"):
        candidate_table_name("orders", "run-1")


def test_promotion_rejects_unsafe_owner(promotion_conn):
    with pytest.raises(PromotionError, match="Unsafe promoted owner"):
        promote_candidate_table(
            "candidate_table",
            "candidate_schema",
            "target_table",
            "target_schema",
            promotion_conn,
            promoted_owner="bad-owner",
        )
