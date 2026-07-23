"""Tests for candidate table retry collision fix and bulk hygiene cleanup utility."""

from __future__ import annotations

import datetime
import json
import uuid

import psycopg
import pytest

import src.candidate_cleanup as candidate_cleanup
from src.db_config import load_layer_schemas, postgres_promotion_conninfo, get_generated_sql_pool
from src.sql_safety import execute_candidate_sql
from src.promotion import discard_candidate_table
from src.app_state.db import get_connection, init_schema
from src.candidate_cleanup import cleanup_orphaned_candidate_tables
from src.gold_security import (
    approval_timestamp,
    build_approval_snapshot,
    canonical_json,
    insert_gold_security_state,
    new_gold_security_record,
    revision_for,
)


def _candidate_identity(
    schemas,
    *,
    target: str,
    run_id: str,
    relation_oid: int = 401,
    namespace_oid: int = 104,
) -> dict:
    return {
        "database_oid": 101,
        "namespace_oid": namespace_oid,
        "relation_oid": relation_oid,
        "schema": schemas.gold_candidates,
        "relation_name": f"{target}_candidate_{run_id}",
        "relation_kind": "r",
    }


def _seed_gold_cleanup_state(
    schemas,
    *,
    run_id: str,
    target: str,
    status: str,
    candidate_identity: dict | None = None,
    failure_code: str | None = None,
) -> dict:
    sql_text = (
        f"CREATE TABLE {schemas.gold_candidates}.{target}_candidate_{run_id} "
        f"AS SELECT * FROM {schemas.silver}.source_a"
    )
    record = new_gold_security_record(
        run_id=run_id,
        sql_text=sql_text,
        business_requirement="Cleanup ownership test.",
        generator_provenance="gold_cleanup_test",
        generator_version="cleanup-v1",
        selected_sources=(
            {"schema": schemas.silver, "table": "source_a"},
        ),
        target_schema=schemas.gold,
        target_name=target,
        candidate_schema=schemas.gold_candidates,
    )
    source_identity = {
        "database_oid": 101,
        "namespace_oid": 102,
        "relation_oid": 201,
        "schema": schemas.silver,
        "relation_name": "source_a",
        "relation_kind": "r",
    }
    target_identity = {
        "state": "absent",
        "database_oid": 101,
        "namespace_oid": 103,
        "schema": schemas.gold,
        "relation_name": target,
    }
    candidate_namespace_identity = {
        "database_oid": 101,
        "namespace_oid": 104,
        "schema": schemas.gold_candidates,
    }
    approval = build_approval_snapshot(
        review_snapshot=json.loads(record["review_snapshot_json"]),
        review_revision=record["review_revision"],
        database_oid=101,
        database_name="cleanup_test_database",
        source_identities=(source_identity,),
        target_identity=target_identity,
        candidate_namespace_identity=candidate_namespace_identity,
        overwrite_authorized=False,
    )
    old_time = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=1)
    ).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review (
                run_id, table_name, sql_text, planned_changes_json,
                created_at, status, candidate_schema, generator_provenance
            )
            VALUES (?, ?, ?, '{}', ?, ?, ?, ?)
            """,
            (
                run_id,
                target,
                sql_text,
                old_time,
                status,
                schemas.gold_candidates,
                "gold_cleanup_test",
            ),
        )
        insert_gold_security_state(conn, record)
        conn.execute(
            """
            UPDATE gold_security_state
            SET approval_snapshot_json = ?,
                approved_revision = ?,
                approved_at = ?,
                overwrite_authorized = 0,
                source_identities_json = ?,
                target_identity_json = ?,
                execution_claim_id = ?,
                execution_claimed_at = ?,
                candidate_identity_json = ?,
                execution_failure_code = ?
            WHERE run_id = ?
            """,
            (
                canonical_json(approval),
                revision_for(approval),
                approval_timestamp(),
                canonical_json([source_identity]),
                canonical_json(target_identity),
                f"exec_{run_id}",
                approval_timestamp(),
                (
                    canonical_json(candidate_identity)
                    if candidate_identity is not None
                    else None
                ),
                failure_code,
                run_id,
            ),
        )
        conn.commit()
    return candidate_identity or _candidate_identity(
        schemas,
        target=target,
        run_id=run_id,
    )


def _mock_cleanup_catalog(monkeypatch, schemas, identities):
    class Cursor:
        def __init__(self):
            self.params = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            self.params = params

        def fetchall(self):
            selected_schema = self.params[0]
            return [
                (
                    item["database_oid"],
                    "cleanup_test_database",
                    item["namespace_oid"],
                    item["relation_oid"],
                    item["schema"],
                    item["relation_name"],
                    item["relation_kind"],
                )
                for item in identities
                if item["schema"] == selected_schema
            ]

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(
        candidate_cleanup.psycopg,
        "connect",
        lambda *args, **kwargs: Connection(),
    )


class _GoldCleanupCursor:
    def __init__(
        self,
        *,
        initial_identity,
        locked_identity=None,
        drop_error=None,
    ):
        self.initial_identity = initial_identity
        self.locked_identity = (
            initial_identity if locked_identity is None else locked_identity
        )
        self.drop_error = drop_error
        self.commands = []
        self.current = None
        self.resolve_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        rendered = query.as_string(None) if hasattr(query, "as_string") else query
        normalized = " ".join(str(rendered).split())
        self.commands.append((normalized, params))
        if "FROM pg_catalog.pg_class AS relation" in normalized:
            identity = (
                self.initial_identity
                if self.resolve_count == 0
                else self.locked_identity
            )
            self.resolve_count += 1
            if identity is None:
                self.current = None
            else:
                self.current = (
                    "cleanup_test_database",
                    identity["database_oid"],
                    identity["namespace_oid"],
                    identity["relation_oid"],
                    identity["schema"],
                    identity["relation_name"],
                    identity["relation_kind"],
                )
        elif normalized.startswith("DROP TABLE"):
            if self.drop_error is not None:
                raise self.drop_error
            self.current = None
        elif normalized.startswith("LOCK TABLE"):
            self.current = None
        else:
            raise AssertionError(f"unexpected cleanup command: {normalized}")

    def fetchone(self):
        return self.current


class _GoldCleanupTransaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.transaction_events.append("enter")
        return self

    def __exit__(self, exc_type, exc, tb):
        name = exc_type.__name__ if exc_type else "none"
        self.connection.transaction_events.append(f"exit:{name}")
        if exc_type is None and self.connection.commit_error is not None:
            raise self.connection.commit_error
        return False


class _GoldCleanupConnection:
    def __init__(self, cursor, *, commit_error=None):
        self.cursor_instance = cursor
        self.commit_error = commit_error
        self.transaction_events = []
        self.closed = False

    def transaction(self):
        return _GoldCleanupTransaction(self)

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


def _install_gold_cleanup_connection(monkeypatch, connection):
    calls = []

    def connect(conninfo, *, autocommit):
        calls.append((conninfo, autocommit))
        return connection

    monkeypatch.setattr(candidate_cleanup.psycopg, "connect", connect)
    return calls


def test_no_valid_batch45b_gold_lifecycle_reaches_destructive_cleanup(
    monkeypatch,
):
    schemas = load_layer_schemas()
    identities = []
    for status in ("EXECUTING", "PROMOTING", "EXECUTION_FAILED"):
        run_id = f"run_cleanup_{status.lower()}"
        target = f"active_{status.lower()}"
        identity = _candidate_identity(
            schemas,
            target=target,
            run_id=run_id,
        )
        identities.append(identity)
        _seed_gold_cleanup_state(
            schemas,
            run_id=run_id,
            target=target,
            status=status,
            candidate_identity=identity if status == "PROMOTING" else None,
            failure_code=(
                "GOLD_EXECUTION_FAILED"
                if status == "EXECUTION_FAILED"
                else None
            ),
        )
    _mock_cleanup_catalog(monkeypatch, schemas, identities)
    monkeypatch.setattr(
        candidate_cleanup,
        "discard_owned_gold_candidate",
        lambda *args, **kwargs: pytest.fail(
            "Batch 4.5B has no valid destructively cleanable Gold lifecycle"
        ),
    )
    result = cleanup_orphaned_candidate_tables(age_threshold_seconds=1)
    assert {item["table"] for item in result["in_flight_candidates"]} == set(
        item["relation_name"] for item in identities[:2]
    )
    assert [item["table"] for item in result["untracked_candidates"]] == [
        identities[2]["relation_name"]
    ]
    assert result["removed_candidates"] == []


def test_gold_cleanup_same_name_replacement_is_not_dropped_and_uses_one_transaction(
    monkeypatch,
):
    schemas = load_layer_schemas()
    expected = _candidate_identity(
        schemas,
        target="owned_race",
        run_id="run_owned_race",
        relation_oid=100,
    )
    replacement = {**expected, "relation_oid": 200}
    cursor = _GoldCleanupCursor(
        initial_identity=expected,
        locked_identity=replacement,
    )
    connection = _GoldCleanupConnection(cursor)
    connect_calls = _install_gold_cleanup_connection(monkeypatch, connection)

    result = candidate_cleanup.discard_owned_gold_candidate(
        expected_identity=expected,
        expected_database_name="cleanup_test_database",
        promotion_conninfo="isolated-cleanup-conninfo",
    )

    assert result == candidate_cleanup.GOLD_CLEANUP_IDENTITY_MISMATCH
    assert connect_calls == [("isolated-cleanup-conninfo", False)]
    assert connection.transaction_events == ["enter", "exit:none"]
    assert connection.closed
    assert cursor.commands[1][0] == (
        f'LOCK TABLE "{schemas.gold_candidates}".'
        f'"{expected["relation_name"]}" IN ACCESS EXCLUSIVE MODE'
    )
    assert not any(
        command.startswith("DROP TABLE")
        for command, _ in cursor.commands
    )


def test_gold_cleanup_identity_match_requires_every_physical_identity_field():
    schemas = load_layer_schemas()
    persisted = _candidate_identity(
        schemas,
        target="owned",
        run_id="run_owned_identity",
    )
    assert candidate_cleanup._gold_candidate_identity_matches(
        persisted,
        dict(persisted),
    )
    assert not candidate_cleanup._gold_candidate_identity_matches(None, persisted)
    for field, value in (
        ("database_oid", 999),
        ("namespace_oid", 999),
        ("relation_oid", 999),
        ("schema", "replacement_candidates"),
        ("relation_name", "replacement_candidate"),
        ("relation_kind", "p"),
    ):
        assert not candidate_cleanup._gold_candidate_identity_matches(
            persisted,
            {**persisted, field: value},
        )


def test_gold_collision_without_captured_identity_is_never_dropped(monkeypatch):
    schemas = load_layer_schemas()
    run_id = "run_cleanup_collision"
    target = "collision"
    colliding_identity = _seed_gold_cleanup_state(
        schemas,
        run_id=run_id,
        target=target,
        status="EXECUTION_FAILED",
        failure_code="GOLD_CANDIDATE_CONFLICT",
    )
    colliding_identity = {**colliding_identity, "relation_oid": 777}
    _mock_cleanup_catalog(monkeypatch, schemas, [colliding_identity])
    monkeypatch.setattr(
        candidate_cleanup,
        "discard_candidate_table",
        lambda *args, **kwargs: pytest.fail(
            "a colliding relation Aurum never created must not be dropped"
        ),
    )

    result = cleanup_orphaned_candidate_tables(age_threshold_seconds=1)

    assert result["removed_candidates"] == []
    assert [item["table"] for item in result["untracked_candidates"]] == [
        colliding_identity["relation_name"]
    ]
    with get_connection() as conn:
        persisted = conn.execute(
            """
            SELECT candidate_identity_json
            FROM gold_security_state
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
    assert persisted["candidate_identity_json"] is None


def test_gold_cleanup_namespace_mismatch_under_lock_is_not_dropped(
    monkeypatch,
):
    schemas = load_layer_schemas()
    expected = _candidate_identity(
        schemas,
        target="owned_namespace",
        run_id="run_owned_namespace",
    )
    replacement = {**expected, "namespace_oid": 999}
    cursor = _GoldCleanupCursor(
        initial_identity=expected,
        locked_identity=replacement,
    )
    connection = _GoldCleanupConnection(cursor)
    _install_gold_cleanup_connection(monkeypatch, connection)

    result = candidate_cleanup.discard_owned_gold_candidate(
        expected_identity=expected,
        expected_database_name="cleanup_test_database",
        promotion_conninfo="isolated-cleanup-conninfo",
    )

    assert result == candidate_cleanup.GOLD_CLEANUP_IDENTITY_MISMATCH
    assert not any(
        command.startswith("DROP TABLE")
        for command, _ in cursor.commands
    )


def test_gold_cleanup_primitive_locks_revalidates_and_drops_on_one_connection(
    monkeypatch,
):
    schemas = load_layer_schemas()
    expected = _candidate_identity(
        schemas,
        target="owned_exact",
        run_id="run_owned_exact",
    )
    cursor = _GoldCleanupCursor(initial_identity=expected)
    connection = _GoldCleanupConnection(cursor)
    connect_calls = _install_gold_cleanup_connection(monkeypatch, connection)

    result = candidate_cleanup.discard_owned_gold_candidate(
        expected_identity=expected,
        expected_database_name="cleanup_test_database",
        promotion_conninfo="isolated-cleanup-conninfo",
    )

    assert result == candidate_cleanup.GOLD_CLEANUP_REMOVED
    assert connect_calls == [("isolated-cleanup-conninfo", False)]
    assert connection.transaction_events == ["enter", "exit:none"]
    assert [command for command, _ in cursor.commands] == [
        cursor.commands[0][0],
        (
            f'LOCK TABLE "{schemas.gold_candidates}".'
            f'"{expected["relation_name"]}" IN ACCESS EXCLUSIVE MODE'
        ),
        cursor.commands[2][0],
        (
            f'DROP TABLE "{schemas.gold_candidates}".'
            f'"{expected["relation_name"]}"'
        ),
    ]
    assert "FROM pg_catalog.pg_class AS relation" in cursor.commands[0][0]
    assert "FROM pg_catalog.pg_class AS relation" in cursor.commands[2][0]


def test_gold_cleanup_drop_failure_rolls_back_without_claiming_removal(
    monkeypatch,
):
    schemas = load_layer_schemas()
    expected = _candidate_identity(
        schemas,
        target="owned_rollback",
        run_id="run_owned_rollback",
    )
    cursor = _GoldCleanupCursor(
        initial_identity=expected,
        drop_error=psycopg.OperationalError("isolated DROP failure"),
    )
    connection = _GoldCleanupConnection(cursor)
    _install_gold_cleanup_connection(monkeypatch, connection)

    with pytest.raises(candidate_cleanup.GoldCandidateCleanupError):
        candidate_cleanup.discard_owned_gold_candidate(
            expected_identity=expected,
            expected_database_name="cleanup_test_database",
            promotion_conninfo="isolated-cleanup-conninfo",
        )

    assert connection.transaction_events == [
        "enter",
        "exit:OperationalError",
    ]


def test_gold_cleanup_commit_acknowledgement_loss_is_reported_as_unknown(
    monkeypatch,
):
    schemas = load_layer_schemas()
    expected = _candidate_identity(
        schemas,
        target="owned_commit_unknown",
        run_id="run_owned_commit_unknown",
    )
    cursor = _GoldCleanupCursor(initial_identity=expected)
    connection = _GoldCleanupConnection(
        cursor,
        commit_error=psycopg.OperationalError(
            "isolated commit acknowledgement loss"
        ),
    )
    _install_gold_cleanup_connection(monkeypatch, connection)

    with pytest.raises(candidate_cleanup.GoldCandidateCleanupOutcomeUnknown):
        candidate_cleanup.discard_owned_gold_candidate(
            expected_identity=expected,
            expected_database_name="cleanup_test_database",
            promotion_conninfo="isolated-cleanup-conninfo",
        )

    assert any(
        command.startswith("DROP TABLE")
        for command, _ in cursor.commands
    )
    assert connection.transaction_events == ["enter", "exit:none"]


def test_gold_cleanup_malformed_security_state_is_preserved(monkeypatch):
    schemas = load_layer_schemas()
    run_id = "run_cleanup_malformed"
    target = "malformed"
    live_identity = _seed_gold_cleanup_state(
        schemas,
        run_id=run_id,
        target=target,
        status="EXECUTION_FAILED",
        failure_code="GOLD_EXECUTION_FAILED",
    )
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE gold_security_state
            SET approval_snapshot_json = '{}'
            WHERE run_id = ?
            """,
            (run_id,),
        )
        conn.commit()
    _mock_cleanup_catalog(monkeypatch, schemas, [live_identity])
    monkeypatch.setattr(
        candidate_cleanup,
        "discard_candidate_table",
        lambda *args, **kwargs: pytest.fail(
            "malformed Gold ownership state must preserve the live relation"
        ),
    )

    result = cleanup_orphaned_candidate_tables(age_threshold_seconds=1)

    assert result["removed_candidates"] == []
    assert [item["table"] for item in result["untracked_candidates"]] == [
        live_identity["relation_name"]
    ]


def test_silver_cleanup_stale_and_active_behavior_is_unchanged(monkeypatch):
    schemas = load_layer_schemas()
    old_time = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=1)
    ).isoformat()
    identities = []
    with get_connection() as conn:
        for status in ("PENDING", "EXECUTING"):
            run_id = f"run_silver_cleanup_{status.lower()}"
            target = f"silver_{status.lower()}"
            table = f"{target}_candidate_{run_id}"
            conn.execute(
                """
                INSERT INTO generated_sql_review (
                    run_id, table_name, sql_text, planned_changes_json,
                    created_at, status, candidate_schema
                )
                VALUES (?, ?, ?, '{}', ?, ?, ?)
                """,
                (
                    run_id,
                    target,
                    (
                        f"CREATE TABLE {schemas.silver_candidates}.{table} "
                        "AS SELECT 1"
                    ),
                    old_time,
                    status,
                    schemas.silver_candidates,
                ),
            )
            identities.append({
                "database_oid": 101,
                "namespace_oid": 105,
                "relation_oid": 501 + len(identities),
                "schema": schemas.silver_candidates,
                "relation_name": table,
                "relation_kind": "r",
            })
        conn.commit()
    _mock_cleanup_catalog(monkeypatch, schemas, identities)
    discarded = []
    monkeypatch.setattr(
        candidate_cleanup,
        "discard_candidate_table",
        lambda table, schema, conninfo: discarded.append((schema, table)),
    )

    result = cleanup_orphaned_candidate_tables(age_threshold_seconds=1)

    assert discarded == [
        (schemas.silver_candidates, identities[0]["relation_name"])
    ]
    assert [item["table"] for item in result["in_flight_candidates"]] == [
        identities[1]["relation_name"]
    ]


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
