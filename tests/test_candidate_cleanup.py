"""Tests for candidate table retry collision fix and bulk hygiene cleanup utility."""

from __future__ import annotations

import datetime
import json
import uuid

import psycopg
import pytest

import src.candidate_cleanup as candidate_cleanup
from src.db_config import load_layer_schemas, postgres_promotion_conninfo, get_generated_sql_pool
from src.sql_safety import execute_candidate_sql, SqlSafetyViolation
from src.promotion import discard_candidate_table, resolve_relation_identity
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
                execution_failure_code = ?,
                promotion_claim_id = ?,
                promotion_claimed_at = ?
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
                (
                    f"promo_{run_id}"
                    if status == "AMBIGUOUS_PROMOTION"
                    else None
                ),
                (
                    approval_timestamp()
                    if status == "AMBIGUOUS_PROMOTION"
                    else None
                ),
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


def _seed_silver_cleanup_state(
    schemas,
    *,
    run_id,
    target,
    status,
    candidate_identity,
    promoted_target_identity=None,
):
    old_time = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=1)
    ).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review (
                run_id, table_name, sql_text, planned_changes_json,
                created_at, status, candidate_schema, candidate_identity_json,
                promoted_target_identity_json
            )
            VALUES (?, ?, ?, '{}', ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                target,
                (
                    f"CREATE TABLE {schemas.silver_candidates}."
                    f"{candidate_identity['relation_name']} AS SELECT 1"
                ),
                old_time,
                status,
                schemas.silver_candidates,
                json.dumps(candidate_identity),
                (
                    json.dumps(promoted_target_identity)
                    if isinstance(promoted_target_identity, dict)
                    else promoted_target_identity
                ),
            ),
        )
        conn.commit()


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
    for index, status in enumerate(
        (
            "EXECUTING",
            "PROMOTING",
            "AMBIGUOUS_PROMOTION",
            "EXECUTION_FAILED",
        )
    ):
        run_id = f"run_cleanup_{index}"
        target = f"active_{index}"
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
            candidate_identity=(
                identity
                if status in {"PROMOTING", "AMBIGUOUS_PROMOTION"}
                else None
            ),
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
        item["relation_name"] for item in identities[:3]
    )
    assert [item["table"] for item in result["untracked_candidates"]] == [
        identities[3]["relation_name"]
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


def test_silver_cleanup_noneligible_lifecycle_states_are_preserved(monkeypatch):
    schemas = load_layer_schemas()
    identities = []
    statuses = (
        "PENDING",
        "EXECUTING",
        "PROMOTING",
        "PROMOTED",
        "AMBIGUOUS_PROMOTION",
        "FUTURE_STATE",
    )
    for status in statuses:
        run_id = f"run_silver_cleanup_{status.lower()}"
        target = f"silver_{status.lower()}"
        table = f"{target}_candidate_{run_id}"
        ident = {
            "database_oid": 101,
            "namespace_oid": 105,
            "relation_oid": 501 + len(identities),
            "schema": schemas.silver_candidates,
            "relation_name": table,
            "relation_kind": "r",
        }
        identities.append(ident)
        _seed_silver_cleanup_state(
            schemas,
            run_id=run_id,
            target=target,
            status=status,
            candidate_identity=ident,
            promoted_target_identity=(
                {
                    **ident,
                    "schema": schemas.silver,
                    "relation_name": target,
                }
                if status == "PROMOTED"
                else None
            ),
        )
    _mock_cleanup_catalog(monkeypatch, schemas, identities)
    monkeypatch.setattr(
        candidate_cleanup,
        "discard_owned_gold_candidate",
        lambda **kwargs: pytest.fail(
            "non-cleanup-eligible Silver lifecycle must never reach DROP"
        ),
    )

    result = cleanup_orphaned_candidate_tables(age_threshold_seconds=1)

    assert result["removed_candidates"] == []
    assert {item["table"] for item in result["in_flight_candidates"]} == {
        identities[index]["relation_name"] for index in (1, 2, 4)
    }
    assert {item["table"] for item in result["untracked_candidates"]} == {
        identities[index]["relation_name"] for index in (0, 3, 5)
    }


def test_silver_cleanup_promoted_with_malformed_final_identity_is_preserved(
    monkeypatch,
):
    schemas = load_layer_schemas()
    run_id = "run_silver_cleanup_promoted_malformed"
    target = "silver_promoted_malformed"
    identity = {
        "database_oid": 101,
        "namespace_oid": 105,
        "relation_oid": 601,
        "schema": schemas.silver_candidates,
        "relation_name": f"{target}_candidate_{run_id}",
        "relation_kind": "r",
    }
    _seed_silver_cleanup_state(
        schemas,
        run_id=run_id,
        target=target,
        status="PROMOTED",
        candidate_identity=identity,
        promoted_target_identity="{malformed",
    )
    _mock_cleanup_catalog(monkeypatch, schemas, [identity])
    monkeypatch.setattr(
        candidate_cleanup,
        "discard_owned_gold_candidate",
        lambda **kwargs: pytest.fail(
            "malformed PROMOTED state must never reach DROP"
        ),
    )

    result = cleanup_orphaned_candidate_tables(age_threshold_seconds=1)

    assert result["removed_candidates"] == []
    assert [item["table"] for item in result["untracked_candidates"]] == [
        identity["relation_name"]
    ]


def test_silver_cleanup_failed_exact_identity_is_cleanup_eligible(monkeypatch):
    schemas = load_layer_schemas()
    run_id = "run_silver_cleanup_failed"
    target = "silver_failed"
    identity = {
        "database_oid": 101,
        "namespace_oid": 105,
        "relation_oid": 701,
        "schema": schemas.silver_candidates,
        "relation_name": f"{target}_candidate_{run_id}",
        "relation_kind": "r",
    }
    _seed_silver_cleanup_state(
        schemas,
        run_id=run_id,
        target=target,
        status="FAILED",
        candidate_identity=identity,
    )
    _mock_cleanup_catalog(monkeypatch, schemas, [identity])
    discarded = []
    monkeypatch.setattr(
        candidate_cleanup,
        "discard_owned_gold_candidate",
        lambda expected_identity, expected_database_name, promotion_conninfo: (
            discarded.append(expected_identity)
            or candidate_cleanup.GOLD_CLEANUP_REMOVED
        ),
    )

    result = cleanup_orphaned_candidate_tables(age_threshold_seconds=1)

    assert discarded == [identity]
    assert [item["table"] for item in result["removed_candidates"]] == [
        identity["relation_name"]
    ]


def test_silver_cleanup_failed_same_name_oid_drift_is_preserved(monkeypatch):
    schemas = load_layer_schemas()
    run_id = "run_silver_cleanup_failed_drift"
    target = "silver_failed_drift"
    persisted = {
        "database_oid": 101,
        "namespace_oid": 105,
        "relation_oid": 801,
        "schema": schemas.silver_candidates,
        "relation_name": f"{target}_candidate_{run_id}",
        "relation_kind": "r",
    }
    live = {**persisted, "relation_oid": 802}
    _seed_silver_cleanup_state(
        schemas,
        run_id=run_id,
        target=target,
        status="FAILED",
        candidate_identity=persisted,
    )
    _mock_cleanup_catalog(monkeypatch, schemas, [live])
    monkeypatch.setattr(
        candidate_cleanup,
        "discard_owned_gold_candidate",
        lambda **kwargs: pytest.fail("OID drift must never reach DROP"),
    )

    result = cleanup_orphaned_candidate_tables(age_threshold_seconds=1)

    assert result["removed_candidates"] == []
    assert [item["table"] for item in result["untracked_candidates"]] == [
        live["relation_name"]
    ]


def test_retry_collision_recovery():
    """Verify execute_candidate_sql fails closed when candidate table already exists."""
    schemas = load_layer_schemas()
    run_id = f"test_retry_{uuid.uuid4().hex[:8]}"
    target_table = f"orders_retry_{run_id}"
    candidate_table = f"{target_table}_candidate_{run_id}"
    
    # 1. Simulate an existing candidate table owned by aurum_promotion
    with psycopg.connect(postgres_promotion_conninfo()) as pconn:
        with pconn.cursor() as cur:
            cur.execute(f'CREATE TABLE "{schemas.silver_candidates}"."{candidate_table}" (id int)')
            pconn.commit()

    # Verify existing table exists
    with get_generated_sql_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT to_regclass(\'"{schemas.silver_candidates}"."{candidate_table}"\')')
            assert cur.fetchone()[0] is not None

    # 2. Re-attempt execution using execute_candidate_sql -> expect SqlSafetyViolation fail-closed
    sql = f'CREATE TABLE {schemas.silver_candidates}.{candidate_table} AS SELECT 1 AS id'
    with get_generated_sql_pool().connection() as conn:
        with pytest.raises(SqlSafetyViolation, match="already exists"):
            execute_candidate_sql(sql, conn, expected_schema=schemas.silver_candidates, run_id=run_id, expected_table_name=target_table)

    # 3. Confirm existing candidate table remains intact in Postgres
    with get_generated_sql_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT to_regclass(\'"{schemas.silver_candidates}"."{candidate_table}"\')')
            assert cur.fetchone()[0] is not None

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
    
    # Seed SQLite metadata with candidate_schema and candidate_identity_json
    stale_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)).isoformat()
    fresh_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    with psycopg.connect(postgres_promotion_conninfo()) as p_conn:
        with p_conn.cursor() as cur:
            cur.execute(f'CREATE TABLE "{schemas.silver_candidates}"."{tbl_stale}" (id int)')
            cur.execute(f'CREATE TABLE "{schemas.silver_candidates}"."{tbl_fresh}" (id int)')
            cur.execute(f'CREATE TABLE "{schemas.silver_candidates}"."{tbl_untracked}" (id int)')
        p_conn.commit()

    with psycopg.connect(postgres_promotion_conninfo()) as p_conn:
        stale_ident = resolve_relation_identity(p_conn, schemas.silver_candidates, tbl_stale)
        fresh_ident = resolve_relation_identity(p_conn, schemas.silver_candidates, tbl_fresh)

    with get_connection() as conn:
        init_schema(conn)
        conn.execute(
            "INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status, candidate_schema, candidate_identity_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_stale, "stale_test", f"CREATE TABLE {schemas.silver_candidates}.{tbl_stale} AS SELECT 1", "{}", stale_time, "FAILED", schemas.silver_candidates, json.dumps(stale_ident))
        )
        conn.execute(
            "INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status, candidate_schema, candidate_identity_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_fresh, "fresh_test", f"CREATE TABLE {schemas.silver_candidates}.{tbl_fresh} AS SELECT 1", "{}", fresh_time, "FAILED", schemas.silver_candidates, json.dumps(fresh_ident))
        )
        conn.commit()
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


def test_admin_cleanup_endpoint_requires_operator_and_confirmation(monkeypatch):
    """Authorization runs before confirmation and before cleanup acquisition."""
    from fastapi.testclient import TestClient
    from api.main import app
    import api.admin_router as admin_router

    client = TestClient(app)
    calls = []
    monkeypatch.setattr(
        admin_router,
        "cleanup_orphaned_candidate_tables",
        lambda **kwargs: calls.append(kwargs) or {"status": "success"},
    )

    disabled = client.post("/api/v1/admin/candidate-cleanup?confirm=true")
    assert disabled.status_code == 404
    assert calls == []

    monkeypatch.setenv("AURUM_ENABLE_DESTRUCTIVE_ADMIN", "true")
    missing_token = client.post(
        "/api/v1/admin/candidate-cleanup?confirm=true",
        headers={"X-Aurum-Operator-Token": "operator-secret"},
    )
    assert missing_token.status_code == 404
    assert calls == []

    monkeypatch.setenv("AURUM_DESTRUCTIVE_ADMIN_TOKEN", "operator-secret")

    unauthorized = client.post(
        "/api/v1/admin/candidate-cleanup?confirm=true",
        headers={"X-Aurum-Operator-Token": "wrong-secret"},
    )
    assert unauthorized.status_code == 403
    assert calls == []

    resp_no_confirm = client.post(
        "/api/v1/admin/candidate-cleanup",
        headers={"X-Aurum-Operator-Token": "operator-secret"},
    )
    assert resp_no_confirm.status_code == 400
    assert "explicit confirmation" in resp_no_confirm.json()["detail"]
    assert calls == []

    resp_confirm = client.post(
        "/api/v1/admin/candidate-cleanup?confirm=true&age_threshold_seconds=17",
        headers={"X-Aurum-Operator-Token": "operator-secret"},
    )
    assert resp_confirm.status_code == 200
    assert resp_confirm.json()["status"] == "success"
    assert calls == [{"age_threshold_seconds": 17}]
