import json
import sqlite3
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from api.main import app
import api.bronze_silver_router as bronze_silver_router
from api.bronze_silver_router import parse_attribution_log, is_trusted_provenance
from src.app_state.db import get_connection, init_schema, _SCHEMA_SQL
from src.sql_safety import SqlSafetyViolation, validate_generated_sql

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

def test_parse_attribution_log_structural_validation():
    # Valid list[str]
    log, avail = parse_attribution_log(json.dumps(["Initial Bronze Rows: 100", "Step 1: 5 removed"]))
    assert avail is True
    assert log == ["Initial Bronze Rows: 100", "Step 1: 5 removed"]

    # None / empty / missing
    log, avail = parse_attribution_log(None)
    assert avail is False and log is None

    log, avail = parse_attribution_log("")
    assert avail is False and log is None

    # Malformed JSON
    log, avail = parse_attribution_log("{bad json")
    assert avail is False and log is None

    # JSON Object (dict)
    log, avail = parse_attribution_log(json.dumps({"key": "val"}))
    assert avail is False and log is None

    # JSON Scalar (int/string)
    log, avail = parse_attribution_log(json.dumps(123))
    assert avail is False and log is None

    log, avail = parse_attribution_log(json.dumps("single string"))
    assert avail is False and log is None

    # Mixed-type array
    log, avail = parse_attribution_log(json.dumps(["valid", 123, None]))
    assert avail is False and log is None

def test_migration_idempotency_and_legacy_quarantine(temp_sqlite_db):
    conn = get_connection()

    # Verify column exists
    info = conn.execute("PRAGMA table_info(generated_sql_review)").fetchall()
    col_names = {row[1] for row in info}
    assert "generator_provenance" in col_names

    # Seed legacy row without provenance
    conn.execute(
        """
        INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status, generator_provenance)
        VALUES ('legacy_run_1', 'src_orders', 'SELECT 1;', '{}', '2026-07-23T00:00:00Z', 'PENDING', NULL)
        """
    )
    conn.commit()

    # Re-run init_schema to simulate repeated startup
    init_schema(conn)

    # Legacy row must be quarantined to 'untrusted_legacy'
    row = conn.execute("SELECT generator_provenance FROM generated_sql_review WHERE run_id = 'legacy_run_1'").fetchone()
    assert row["generator_provenance"] == "untrusted_legacy"
    assert is_trusted_provenance(row["generator_provenance"]) is False

def test_real_execute_handler_exact_once_and_untrusted_rejection(temp_sqlite_db, monkeypatch):
    client = TestClient(app)
    base_url = "/api/v1/transform"

    exec_counts = {"execute_candidate": 0, "promote": 0}

    # Mock external PostgreSQL DB boundaries safely
    class MockCursor:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def execute(self, sql, params=None):
            pass
        def fetchone(self):
            return (100, 95)  # 100 bronze rows, 95 step_1 rows

    class MockConnection:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def cursor(self):
            return MockCursor()
        def commit(self):
            pass

    class MockPool:
        def connection(self):
            return MockConnection()

    def mock_execute_candidate_sql(sql_text, conn, expected_schema, run_id=None, *args, **kwargs):
        exec_counts["execute_candidate"] += 1

    def mock_promote_candidate_table(candidate_table, candidate_schema, target_table, target_schema, promotion_conninfo):
        exec_counts["promote"] += 1

    monkeypatch.setattr("api.bronze_silver_router.get_generated_sql_pool", lambda: MockPool())
    monkeypatch.setattr("api.bronze_silver_router.execute_candidate_sql", mock_execute_candidate_sql)
    monkeypatch.setattr("api.bronze_silver_router.promote_candidate_table", mock_promote_candidate_table)
    monkeypatch.setattr("api.bronze_silver_router.postgres_promotion_conninfo", lambda: "dbname=mock")
    monkeypatch.setattr("api.bronze_silver_router.load_layer_schemas", lambda: type("Schemas", (), {"bronze": "bronze", "silver_candidates": "silver_candidates", "silver": "silver"})())

    # 1. Legacy PENDING run rejection
    legacy_run_id = "run_legacy_pending"
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status, generator_provenance)
            VALUES (?, 'src_orders_test', 'SELECT 1;', '{}', '2026-07-23T00:00:00Z', 'PENDING', 'untrusted_legacy')
            """,
            (legacy_run_id,)
        )
        conn.commit()

    resp = client.post(f"{base_url}/execute/{legacy_run_id}")
    assert resp.status_code == 400
    assert "untrusted or missing valid generator provenance" in resp.json()["detail"]
    assert exec_counts["execute_candidate"] == 0
    assert exec_counts["promote"] == 0

    # 2. Trusted PENDING run execution (Exact-once)
    trusted_run_id = "run_trusted_pending_1"
    valid_sql = (
        f"CREATE TABLE silver_candidates.src_orders_test_candidate_{trusted_run_id} AS "
        f"WITH step_1 AS (SELECT * FROM bronze.src_orders_test) SELECT * FROM step_1;"
    )
    rules_payload = ["Step 1: filter nulls"]
    client.post(f"{base_url}/rules", json={"table_name": "src_orders_test", "rules": rules_payload})
    rules_info = client.get(f"{base_url}/rules/src_orders_test").json()
    rule_rev = rules_info["rule_revision"]

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status, generator_provenance, rule_revision)
            VALUES (?, 'src_orders_test', ?, ?, '2026-07-23T00:00:00Z', 'PENDING', 'ollama_v1_generic', ?)
            """,
            (
                trusted_run_id,
                valid_sql,
                json.dumps({"summary": "1 step", "rules": rules_payload}),
                rule_rev
            )
        )
        conn.commit()

    # First execution attempt
    resp = client.post(f"{base_url}/execute/{trusted_run_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert exec_counts["execute_candidate"] == 1
    assert exec_counts["promote"] == 1

    # 3. Double-execution attempt returns existing promoted result idempotently
    resp_retry = client.post(f"{base_url}/execute/{trusted_run_id}")
    assert resp_retry.status_code == 200
    res_json = resp_retry.json()
    assert res_json["status"] == "success"
    assert res_json["run_id"] == trusted_run_id
    assert res_json["attribution_available"] is True
    assert exec_counts["execute_candidate"] == 1
    assert exec_counts["promote"] == 1


def test_ast_candidate_identity_and_cte_sequence_validation():
    # Scenario A: Correct run ID, candidate target belongs to another table -> REJECTED
    sql_a = (
        "CREATE TABLE silver_candidates.other_table_candidate_run1 AS "
        "WITH step_1 AS (SELECT * FROM bronze.src_orders) SELECT * FROM step_1;"
    )
    with pytest.raises(SqlSafetyViolation, match="Candidate table target must be EXACTLY"):
        validate_generated_sql(
            sql_a,
            expected_schema="silver_candidates",
            expected_table_name="src_orders",
            expected_bronze_schema="bronze",
            run_id="run1",
            expected_step_count=1,
            mode="p2_silver",
        )

    # Scenario B: Correct candidate, source references another Bronze table -> REJECTED
    sql_b = (
        "CREATE TABLE silver_candidates.src_orders_candidate_run1 AS "
        "WITH step_1 AS (SELECT * FROM bronze.other_table) SELECT * FROM step_1;"
    )
    with pytest.raises(SqlSafetyViolation, match="step_1 must read from permitted Bronze table"):
        validate_generated_sql(
            sql_b,
            expected_schema="silver_candidates",
            expected_table_name="src_orders",
            expected_bronze_schema="bronze",
            run_id="run1",
            expected_step_count=1,
            mode="p2_silver",
        )

    # Scenario C: step_2 reads directly from Bronze instead of step_1 -> REJECTED
    sql_c = (
        "CREATE TABLE silver_candidates.src_orders_candidate_run1 AS "
        "WITH step_1 AS (SELECT * FROM bronze.src_orders), "
        "step_2 AS (SELECT * FROM bronze.src_orders) SELECT * FROM step_2;"
    )
    with pytest.raises(SqlSafetyViolation, match=r"step_2 must (read from|reference unqualified) 'step_1'"):
        validate_generated_sql(
            sql_c,
            expected_schema="silver_candidates",
            expected_table_name="src_orders",
            expected_bronze_schema="bronze",
            run_id="run1",
            expected_step_count=2,
            mode="p2_silver",
        )

    # Scenario D: step_3 skips step_2 -> REJECTED
    sql_d = (
        "CREATE TABLE silver_candidates.src_orders_candidate_run1 AS "
        "WITH step_1 AS (SELECT * FROM bronze.src_orders), "
        "step_2 AS (SELECT * FROM step_1), "
        "step_3 AS (SELECT * FROM step_1) SELECT * FROM step_3;"
    )
    with pytest.raises(SqlSafetyViolation, match="step_3 must read from step_2"):
        validate_generated_sql(
            sql_d,
            expected_schema="silver_candidates",
            expected_table_name="src_orders",
            expected_bronze_schema="bronze",
            run_id="run1",
            expected_step_count=3,
            mode="p2_silver",
        )

    # Scenario E: final SELECT reads from step_1 instead of final step -> REJECTED
    sql_e = (
        "CREATE TABLE silver_candidates.src_orders_candidate_run1 AS "
        "WITH step_1 AS (SELECT * FROM bronze.src_orders), "
        "step_2 AS (SELECT * FROM step_1) SELECT * FROM step_1;"
    )
    with pytest.raises(SqlSafetyViolation, match="Final SELECT must read from final step 'step_2'"):
        validate_generated_sql(
            sql_e,
            expected_schema="silver_candidates",
            expected_table_name="src_orders",
            expected_bronze_schema="bronze",
            run_id="run1",
            expected_step_count=2,
            mode="p2_silver",
        )

    # Scenario F: extra unrelated CTE -> REJECTED
    sql_f = (
        "CREATE TABLE silver_candidates.src_orders_candidate_run1 AS "
        "WITH step_1 AS (SELECT * FROM bronze.src_orders), "
        "extra_cte AS (SELECT * FROM step_1) SELECT * FROM extra_cte;"
    )
    with pytest.raises(SqlSafetyViolation):
        validate_generated_sql(
            sql_f,
            expected_schema="silver_candidates",
            expected_table_name="src_orders",
            expected_bronze_schema="bronze",
            run_id="run1",
            expected_step_count=2,
            mode="p2_silver",
        )

    # Scenario G: Valid cumulative pipeline -> PASSED in p2_silver mode
    sql_g = (
        "CREATE TABLE silver_candidates.src_orders_candidate_run1 AS "
        "WITH step_1 AS (SELECT * FROM bronze.src_orders), "
        "step_2 AS (SELECT * FROM step_1) SELECT * FROM step_2;"
    )
    validated = validate_generated_sql(
        sql_g,
        expected_schema="silver_candidates",
        expected_table_name="src_orders",
        expected_bronze_schema="bronze",
        run_id="run1",
        expected_step_count=2,
        mode="p2_silver",
    )
    assert "step_1" in validated and "step_2" in validated

    # Scenario H: Unqualified physical table in step_1 -> REJECTED in p2_silver mode
    sql_h = (
        "CREATE TABLE silver_candidates.src_orders_candidate_run1 AS "
        "WITH step_1 AS (SELECT * FROM src_orders) SELECT * FROM step_1;"
    )
    with pytest.raises(SqlSafetyViolation, match="step_1 must read from schema-qualified Bronze table"):
        validate_generated_sql(
            sql_h,
            expected_schema="silver_candidates",
            expected_table_name="src_orders",
            expected_bronze_schema="bronze",
            run_id="run1",
            mode="p2_silver",
        )

    # Scenario I: Schema-qualified fake CTE reference -> REJECTED in p2_silver mode
    sql_i = (
        "CREATE TABLE silver_candidates.src_orders_candidate_run1 AS "
        "WITH step_1 AS (SELECT * FROM bronze.src_orders), "
        "step_2 AS (SELECT * FROM hostile.step_1) SELECT * FROM step_2;"
    )
    with pytest.raises(SqlSafetyViolation, match="step_2 must reference unqualified"):
        validate_generated_sql(
            sql_i,
            expected_schema="silver_candidates",
            expected_table_name="src_orders",
            expected_bronze_schema="bronze",
            run_id="run1",
            mode="p2_silver",
        )

    # Scenario J: Constant SELECT with no table -> REJECTED in p2_silver mode
    sql_j = "CREATE TABLE silver_candidates.src_orders_candidate_run1 AS SELECT 1;"
    with pytest.raises(SqlSafetyViolation):
        validate_generated_sql(
            sql_j,
            expected_schema="silver_candidates",
            expected_table_name="src_orders",
            expected_bronze_schema="bronze",
            run_id="run1",
            mode="p2_silver",
        )


def test_p3_gold_compatibility_with_generic_mode():
    """Prove P3 Gold queries pass generic mode validation without being subjected to P2 sequential step rules."""
    p3_sql = (
        "CREATE TABLE gold_candidates.daily_sales_candidate_run_p3 AS "
        "WITH aggregated AS ("
        "    SELECT customer_id, SUM(amount) AS total FROM silver.orders GROUP BY customer_id"
        ") "
        "SELECT * FROM aggregated;"
    )
    validated = validate_generated_sql(
        p3_sql,
        expected_schema="gold_candidates",
        expected_table_name="daily_sales",
        run_id="run_p3",
        mode="generic"
    )
    assert "aggregated" in validated


def test_server_side_rule_revision_and_execute_gating(temp_sqlite_db, monkeypatch):
    client = TestClient(app)
    base_url = "/api/v1/transform"
    exec_counts = {"execute_candidate": 0, "promote": 0}

    def mock_execute_candidate_sql(sql_text, conn, expected_schema, run_id=None, *args, **kwargs):
        exec_counts["execute_candidate"] += 1

    def mock_promote_candidate_table(candidate_table, candidate_schema, target_table, target_schema, promotion_conninfo):
        exec_counts["promote"] += 1

    class MockCursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): pass
        def fetchone(self): return (100, 90)

    class MockConnection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def cursor(self): return MockCursor()
        def commit(self): pass

    class MockPool:
        def connection(self): return MockConnection()

    monkeypatch.setattr("api.bronze_silver_router.get_generated_sql_pool", lambda: MockPool())
    monkeypatch.setattr("api.bronze_silver_router.execute_candidate_sql", mock_execute_candidate_sql)
    monkeypatch.setattr("api.bronze_silver_router.promote_candidate_table", mock_promote_candidate_table)
    monkeypatch.setattr("api.bronze_silver_router.postgres_promotion_conninfo", lambda: "dbname=mock")
    monkeypatch.setattr("api.bronze_silver_router.load_layer_schemas", lambda: type("Schemas", (), {"bronze": "bronze", "silver_candidates": "silver_candidates", "silver": "silver"})())

    # Save initial rules -> Revision R1
    save_resp = client.post(f"{base_url}/rules", json={"table_name": "tbl_rev_test", "rules": ["Filter price > 0"]})
    assert save_resp.status_code == 200
    r1_rev = save_resp.json()["rule_revision"]

    # Seed run created with R1 revision
    run_id = "run_rev_1"
    valid_sql = (
        f"CREATE TABLE silver_candidates.tbl_rev_test_candidate_{run_id} AS "
        f"WITH step_1 AS (SELECT * FROM bronze.tbl_rev_test) SELECT * FROM step_1;"
    )
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status, generator_provenance, rule_revision)
            VALUES (?, 'tbl_rev_test', ?, ?, '2026-07-23T00:00:00Z', 'PENDING', 'ollama_v1_generic', ?)
            """,
            (run_id, valid_sql, json.dumps({"summary": "1 step", "rules": ["Filter price > 0"]}), r1_rev)
        )
        conn.commit()

    # Review run when rules match R1 -> executable = True
    rev_resp = client.get(f"{base_url}/review/{run_id}")
    assert rev_resp.status_code == 200
    assert rev_resp.json()["executable"] is True

    # Save new rules -> Revision R2
    client.post(f"{base_url}/rules", json={"table_name": "tbl_rev_test", "rules": ["Filter price > 0", "Remove nulls"]})

    # Review run when rules changed to R2 -> executable = False
    rev_resp_stale = client.get(f"{base_url}/review/{run_id}")
    assert rev_resp_stale.status_code == 200
    assert rev_resp_stale.json()["executable"] is False

    # Execute stale run -> Rejected 400, 0 DB mutations
    exec_stale = client.post(f"{base_url}/execute/{run_id}")
    assert exec_stale.status_code == 400
    assert "Rules have changed since this review was generated" in exec_stale.json()["detail"]
    assert exec_counts["execute_candidate"] == 0
    assert exec_counts["promote"] == 0


def test_post_claim_failure_state_transition(temp_sqlite_db, monkeypatch):
    """Prove that if post-claim execution fails, run status transitions to FAILED instead of staying EXECUTING."""
    client = TestClient(app)
    base_url = "/api/v1/transform"
    run_id = "run_fail_post_claim"

    def mock_failing_execute_candidate_sql(*args, **kwargs):
        raise Exception("PostgreSQL execution error")

    class MockCursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): pass
        def fetchone(self): return (100, 90)

    class MockConnection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def cursor(self): return MockCursor()
        def commit(self): pass

    class MockPool:
        def connection(self): return MockConnection()

    monkeypatch.setattr("api.bronze_silver_router.get_generated_sql_pool", lambda: MockPool())
    monkeypatch.setattr("api.bronze_silver_router.execute_candidate_sql", mock_failing_execute_candidate_sql)
    monkeypatch.setattr("api.bronze_silver_router.postgres_promotion_conninfo", lambda: "dbname=mock")
    monkeypatch.setattr("api.bronze_silver_router.load_layer_schemas", lambda: type("Schemas", (), {"bronze": "bronze", "silver_candidates": "silver_candidates", "silver": "silver"})())

    # Save rules
    save_resp = client.post(f"{base_url}/rules", json={"table_name": "tbl_fail_test", "rules": ["Step 1"]})
    r_rev = save_resp.json()["rule_revision"]

    valid_sql = (
        f"CREATE TABLE silver_candidates.tbl_fail_test_candidate_{run_id} AS "
        f"WITH step_1 AS (SELECT * FROM bronze.tbl_fail_test) SELECT * FROM step_1;"
    )
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status, generator_provenance, rule_revision)
            VALUES (?, 'tbl_fail_test', ?, ?, '2026-07-23T00:00:00Z', 'PENDING', 'ollama_v1_generic', ?)
            """,
            (run_id, valid_sql, json.dumps({"summary": "1 step", "rules": ["Step 1"]}), r_rev)
        )
        conn.commit()

    resp = client.post(f"{base_url}/execute/{run_id}")
    assert resp.status_code == 500

    # Verify status in SQLite transitioned to FAILED (not EXECUTING)
    with get_connection() as conn:
        row = conn.execute("SELECT status FROM generated_sql_review WHERE run_id = ?", (run_id,)).fetchone()
        assert row["status"] == "FAILED"


def test_router_schema_error_contracts(monkeypatch):
    client = TestClient(app)

    # Test 404 missing table contract
    class EmptyCursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): pass
        def fetchall(self): return []

    class MockIngestionPoolEmpty:
        def connection(self):
            return type("Conn", (), {"__enter__": lambda s: s, "__exit__": lambda s, *a: None, "cursor": lambda s: EmptyCursor()})()

    monkeypatch.setattr("api.bronze_silver_router.get_ingestion_pool", lambda: MockIngestionPoolEmpty())
    monkeypatch.setattr("api.bronze_silver_router.get_rules", lambda t: {"rules": ["rule 1"]})

    resp = client.post("/api/v1/transform/generate", json={"table_name": "non_existent_table"})
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]

    # Test 503 database connection error contract
    class OperationallyFailingPool:
        def connection(self):
            raise bronze_silver_router.PsycopgOperationalError("database unavailable")

    monkeypatch.setattr("api.bronze_silver_router.get_ingestion_pool", lambda: OperationallyFailingPool())
    resp = client.post("/api/v1/transform/generate", json={"table_name": "src_orders"})
    assert resp.status_code == 503
    assert "Database service is currently unavailable" in resp.json()["detail"]

    # Test sanitized 500 for non-connectivity failures
    class UnexpectedlyFailingPool:
        def connection(self):
            raise Exception("internal query secret")

    monkeypatch.setattr("api.bronze_silver_router.get_ingestion_pool", lambda: UnexpectedlyFailingPool())
    resp = client.post("/api/v1/transform/generate", json={"table_name": "src_orders"})
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Internal server error."
    assert "internal query secret" not in resp.text

def test_ambiguous_promotion_recovery_rejection(temp_sqlite_db):
    client = TestClient(app)
    base_url = "/api/v1/transform"
    ambiguous_run_id = "run_ambiguous_1"

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status, generator_provenance)
            VALUES (?, 'src_orders_test', 'SELECT 1;', '{}', '2026-07-23T00:00:00Z', 'AMBIGUOUS_PROMOTION', 'ollama_v1_generic')
            """,
            (ambiguous_run_id,)
        )
        conn.commit()

    resp = client.post(f"{base_url}/execute/{ambiguous_run_id}")
    assert resp.status_code == 409
    assert "ambiguous" in resp.json()["detail"].lower()


def test_full_sha256_revision_and_legacy_backfill_migration(temp_sqlite_db):
    """Verify compute_rule_revision returns 64 hex chars and init_schema backfills legacy table_rules idempotently."""
    from src.app_state.db import compute_rule_revision

    normalized_rules = ["rule one", "rule two"]
    rev = compute_rule_revision(normalized_rules)
    assert isinstance(rev, str)
    assert len(rev) == 64
    assert rev == rev.lower()
    assert compute_rule_revision(["rule one", "rule two"]) == rev
    assert compute_rule_revision(["rule two", "rule one"]) != rev
    assert compute_rule_revision(["  rule one  ", "rule two"]) == rev

    conn = get_connection()
    conn.execute("INSERT INTO table_rules (table_name, rules_json, rule_revision, updated_at) VALUES ('legacy_valid', '[\"r1\", \"r2\"]', NULL, '2026-07-23T00:00:00Z')")
    conn.execute("INSERT INTO table_rules (table_name, rules_json, rule_revision, updated_at) VALUES ('legacy_corrupt', '{\"not\": \"a list\"}', NULL, '2026-07-23T00:00:00Z')")
    conn.commit()

    init_schema(conn)

    row_valid = conn.execute("SELECT rule_revision FROM table_rules WHERE table_name = 'legacy_valid'").fetchone()
    assert row_valid["rule_revision"] is not None
    assert len(row_valid["rule_revision"]) == 64

    row_corrupt = conn.execute("SELECT rule_revision FROM table_rules WHERE table_name = 'legacy_corrupt'").fetchone()
    assert row_corrupt["rule_revision"] is None


def test_atomic_revision_race_rejection(temp_sqlite_db, monkeypatch):
    """Prove that if table_rules changes right before atomic claim, execute claim fails atomically."""
    client = TestClient(app)
    base_url = "/api/v1/transform"
    exec_counts = {"execute_candidate": 0, "promote": 0}

    def mock_execute_candidate_sql(*args, **kwargs):
        exec_counts["execute_candidate"] += 1

    def mock_promote_candidate_table(*args, **kwargs):
        exec_counts["promote"] += 1

    class MockCursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): pass
        def fetchone(self): return (100, 90)

    class MockConnection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def cursor(self): return MockCursor()
        def commit(self): pass

    class MockPool:
        def connection(self): return MockConnection()

    monkeypatch.setattr("api.bronze_silver_router.get_generated_sql_pool", lambda: MockPool())
    monkeypatch.setattr("api.bronze_silver_router.execute_candidate_sql", mock_execute_candidate_sql)
    monkeypatch.setattr("api.bronze_silver_router.promote_candidate_table", mock_promote_candidate_table)
    monkeypatch.setattr("api.bronze_silver_router.postgres_promotion_conninfo", lambda: "dbname=mock")
    monkeypatch.setattr("api.bronze_silver_router.load_layer_schemas", lambda: type("Schemas", (), {"bronze": "bronze", "silver_candidates": "silver_candidates", "silver": "silver"})())

    rules_a = ["Rule A"]
    rules_b = ["Rule B"]
    revision_a = bronze_silver_router.compute_rule_revision(rules_a)
    revision_b = bronze_silver_router.compute_rule_revision(rules_b)
    assert revision_a and revision_b and revision_a != revision_b

    # Save initial rules -> canonical A
    save_resp = client.post(f"{base_url}/rules", json={"table_name": "tbl_race_test", "rules": rules_a})
    assert save_resp.status_code == 200
    assert save_resp.json()["rule_revision"] == revision_a

    run_id = "run_race_1"
    valid_sql = (
        f"CREATE TABLE silver_candidates.tbl_race_test_candidate_{run_id} AS "
        f"WITH step_1 AS (SELECT * FROM bronze.tbl_race_test) SELECT * FROM step_1;"
    )
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status, generator_provenance, rule_revision)
            VALUES (?, 'tbl_race_test', ?, ?, '2026-07-23T00:00:00Z', 'PENDING', 'ollama_v1_generic', ?)
            """,
            (run_id, valid_sql, json.dumps({"summary": "1 step", "rules": rules_a}), revision_a)
        )
        conn.commit()

    real_get_connection = bronze_silver_router.get_connection
    real_get_rules = bronze_silver_router.get_rules
    race = {"preflight_revision": None, "injected": False}

    def observe_preflight_rules(table_name):
        result = real_get_rules(table_name)
        race["preflight_revision"] = result["rule_revision"]
        return result

    class ClaimBoundaryConnection:
        def __init__(self, conn):
            self._conn = conn

        def __enter__(self):
            self._conn.__enter__()
            return self

        def __exit__(self, *args):
            return self._conn.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def execute(self, sql, parameters=()):
            is_atomic_claim = (
                "UPDATE generated_sql_review" in sql
                and "SET status = 'EXECUTING'" in sql
                and "EXISTS (" in sql
            )
            if is_atomic_claim and not race["injected"]:
                assert race["preflight_revision"] == revision_a
                race["injected"] = True
                save_result = bronze_silver_router.save_rules(
                    bronze_silver_router.RulesPayload(
                        table_name="tbl_race_test",
                        rules=rules_b,
                    )
                )
                assert save_result["rule_revision"] == revision_b
            return self._conn.execute(sql, parameters)

    def claim_boundary_get_connection():
        return ClaimBoundaryConnection(real_get_connection())

    monkeypatch.setattr(bronze_silver_router, "get_rules", observe_preflight_rules)
    monkeypatch.setattr(bronze_silver_router, "get_connection", claim_boundary_get_connection)

    # Execute attempt must fail atomically at claim step
    resp = client.post(f"{base_url}/execute/{run_id}")
    assert race["injected"] is True
    assert resp.status_code == 400
    assert exec_counts["execute_candidate"] == 0
    assert exec_counts["promote"] == 0


def test_promotion_failure_transitions_to_ambiguous_promotion(temp_sqlite_db, monkeypatch):
    """Prove that if promote_candidate_table fails after PROMOTING transition, status is AMBIGUOUS_PROMOTION."""
    client = TestClient(app)
    base_url = "/api/v1/transform"
    run_id = "run_promo_fail_1"

    def mock_execute_candidate_sql(*args, **kwargs):
        pass

    def mock_failing_promote_candidate_table(*args, **kwargs):
        raise Exception("PostgreSQL promotion deadlock/failure")

    class MockCursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): pass
        def fetchone(self): return (100, 90)

    class MockConnection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def cursor(self): return MockCursor()
        def commit(self): pass

    class MockPool:
        def connection(self): return MockConnection()

    monkeypatch.setattr("api.bronze_silver_router.get_generated_sql_pool", lambda: MockPool())
    monkeypatch.setattr("api.bronze_silver_router.execute_candidate_sql", mock_execute_candidate_sql)
    monkeypatch.setattr("api.bronze_silver_router.promote_candidate_table", mock_failing_promote_candidate_table)
    monkeypatch.setattr("api.bronze_silver_router.postgres_promotion_conninfo", lambda: "dbname=mock")
    monkeypatch.setattr("api.bronze_silver_router.load_layer_schemas", lambda: type("Schemas", (), {"bronze": "bronze", "silver_candidates": "silver_candidates", "silver": "silver"})())

    save_resp = client.post(f"{base_url}/rules", json={"table_name": "tbl_promo_fail", "rules": ["Step A"]})
    r_rev = save_resp.json()["rule_revision"]

    valid_sql = (
        f"CREATE TABLE silver_candidates.tbl_promo_fail_candidate_{run_id} AS "
        f"WITH step_1 AS (SELECT * FROM bronze.tbl_promo_fail) SELECT * FROM step_1;"
    )
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status, generator_provenance, rule_revision)
            VALUES (?, 'tbl_promo_fail', ?, ?, '2026-07-23T00:00:00Z', 'PENDING', 'ollama_v1_generic', ?)
            """,
            (run_id, valid_sql, json.dumps({"summary": "1 step", "rules": ["Step A"]}), r_rev)
        )
        conn.commit()

    resp = client.post(f"{base_url}/execute/{run_id}")
    assert resp.status_code == 500

    with get_connection() as conn:
        row = conn.execute("SELECT status FROM generated_sql_review WHERE run_id = ?", (run_id,)).fetchone()
        assert row["status"] == "AMBIGUOUS_PROMOTION"


def test_ast_bypasses_extended():
    """Verify additional AST bypasses: catalog-qualified sources, JOINs, VALUES, subqueries, and catalog-qualified CREATE targets."""
    # Catalog-qualified source in step_1
    sql_cat_source = (
        "CREATE TABLE silver_candidates.src_orders_candidate_run1 AS "
        "WITH step_1 AS (SELECT * FROM evil.bronze.src_orders) SELECT * FROM step_1;"
    )
    with pytest.raises(SqlSafetyViolation):
        validate_generated_sql(
            sql_cat_source,
            expected_schema="silver_candidates",
            expected_table_name="src_orders",
            expected_bronze_schema="bronze",
            run_id="run1",
            mode="p2_silver",
        )

    # JOIN in step_1
    sql_join = (
        "CREATE TABLE silver_candidates.src_orders_candidate_run1 AS "
        "WITH step_1 AS (SELECT a.* FROM bronze.src_orders a JOIN bronze.other_table b ON a.id = b.id) SELECT * FROM step_1;"
    )
    with pytest.raises(SqlSafetyViolation, match="must not contain JOINs"):
        validate_generated_sql(
            sql_join,
            expected_schema="silver_candidates",
            expected_table_name="src_orders",
            expected_bronze_schema="bronze",
            run_id="run1",
            mode="p2_silver",
        )

    # VALUES relation in step_1
    sql_values = (
        "CREATE TABLE silver_candidates.src_orders_candidate_run1 AS "
        "WITH step_1 AS (SELECT * FROM (VALUES (1, 2))) SELECT * FROM step_1;"
    )
    with pytest.raises(SqlSafetyViolation):
        validate_generated_sql(
            sql_values,
            expected_schema="silver_candidates",
            expected_table_name="src_orders",
            expected_bronze_schema="bronze",
            run_id="run1",
            mode="p2_silver",
        )

    # Catalog-qualified CREATE target table
    sql_cat_target = (
        "CREATE TABLE evil.silver_candidates.src_orders_candidate_run1 AS "
        "WITH step_1 AS (SELECT * FROM bronze.src_orders) SELECT * FROM step_1;"
    )
    with pytest.raises(SqlSafetyViolation, match="Catalog-qualified target table is not allowed"):
        validate_generated_sql(
            sql_cat_target,
            expected_schema="silver_candidates",
            expected_table_name="src_orders",
            expected_bronze_schema="bronze",
            run_id="run1",
            mode="p2_silver",
        )


def test_p2_bare_select_rejection():
    """Verify bare SELECT query is rejected in mode='p2_silver' but allowed in mode='generic'."""
    bare_sql = "WITH step_1 AS (SELECT * FROM bronze.src_orders) SELECT * FROM step_1;"
    with pytest.raises(SqlSafetyViolation, match="CREATE TABLE AS SELECT"):
        validate_generated_sql(
            bare_sql,
            expected_schema="silver_candidates",
            expected_table_name="src_orders",
            expected_bronze_schema="bronze",
            run_id="run1",
            mode="p2_silver",
        )


def test_is_valid_rule_revision_contract():
    """Verify is_valid_rule_revision enforces strict 64-char lowercase SHA-256 contract."""
    from src.app_state.db import is_valid_rule_revision
    assert is_valid_rule_revision("a" * 64) is True
    assert is_valid_rule_revision("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef") is True
    assert is_valid_rule_revision("a" * 16) is False  # Legacy 16-char
    assert is_valid_rule_revision("A" * 64) is False  # Uppercase
    assert is_valid_rule_revision("g" * 64) is False  # Non-hex
    assert is_valid_rule_revision(None) is False
    assert is_valid_rule_revision(12345) is False
    assert is_valid_rule_revision("") is False


def test_promoting_durability_failure_aborts_promotion(temp_sqlite_db, monkeypatch):
    """Prove that if SQLite status update to PROMOTING returns False, promotion is NOT called."""
    client = TestClient(app)
    base_url = "/api/v1/transform"
    run_id = "run_durability_fail"
    exec_counts = {"execute_candidate": 0, "promote": 0}

    def mock_execute_candidate_sql(*args, **kwargs):
        exec_counts["execute_candidate"] += 1

    def mock_promote_candidate_table(*args, **kwargs):
        exec_counts["promote"] += 1

    class MockCursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): pass
        def fetchone(self): return (100, 90)

    class MockConnection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def cursor(self): return MockCursor()
        def commit(self): pass

    class MockPool:
        def connection(self): return MockConnection()

    monkeypatch.setattr("api.bronze_silver_router.get_generated_sql_pool", lambda: MockPool())
    monkeypatch.setattr("api.bronze_silver_router.execute_candidate_sql", mock_execute_candidate_sql)
    monkeypatch.setattr("api.bronze_silver_router.promote_candidate_table", mock_promote_candidate_table)
    monkeypatch.setattr("api.bronze_silver_router.postgres_promotion_conninfo", lambda: "dbname=mock")
    monkeypatch.setattr("api.bronze_silver_router.load_layer_schemas", lambda: type("Schemas", (), {"bronze": "bronze", "silver_candidates": "silver_candidates", "silver": "silver"})())

    # Monkeypatch _update_run_status to fail specifically when status == "PROMOTING"
    from api.bronze_silver_router import _update_run_status as real_update_run_status
    def failing_update_run_status(r_id, status, **kwargs):
        if status == "PROMOTING":
            return False
        return real_update_run_status(r_id, status, **kwargs)

    monkeypatch.setattr("api.bronze_silver_router._update_run_status", failing_update_run_status)

    save_resp = client.post(f"{base_url}/rules", json={"table_name": "tbl_durability", "rules": ["Rule X"]})
    r_rev = save_resp.json()["rule_revision"]

    valid_sql = (
        f"CREATE TABLE silver_candidates.tbl_durability_candidate_{run_id} AS "
        f"WITH step_1 AS (SELECT * FROM bronze.tbl_durability) SELECT * FROM step_1;"
    )
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status, generator_provenance, rule_revision)
            VALUES (?, 'tbl_durability', ?, ?, '2026-07-23T00:00:00Z', 'PENDING', 'ollama_v1_generic', ?)
            """,
            (run_id, valid_sql, json.dumps({"summary": "1 step", "rules": ["Rule X"]}), r_rev)
        )
        conn.commit()

    resp = client.post(f"{base_url}/execute/{run_id}")
    assert resp.status_code == 500
    assert exec_counts["execute_candidate"] == 1
    assert exec_counts["promote"] == 0  # Promotion MUST NOT be called!
