"""Unit tests for atomic table promotion."""

import psycopg
import pytest

import src.promotion as promotion
from src.db_config import postgres_conninfo
from src.promotion import (
    PromotionError,
    SilverPromotionCommitUnknown,
    SilverPromotionFailedBeforeCommit,
    SilverPromotionFailedKnownRollback,
    SilverPromotionRollbackFailed,
    candidate_table_name,
    promote_candidate_table,
)

@pytest.fixture
def promotion_conn():
    # Use superuser for testing setup
    return postgres_conninfo()

from src.promotion import resolve_relation_identity

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
            
    dummy_cand_ident = {
        "database_oid": 1,
        "namespace_oid": 1,
        "relation_oid": 1,
        "schema": "test_candidate",
        "relation_name": "missing_cand_table",
        "relation_kind": "r",
    }
    with pytest.raises(PromotionError, match="Candidate table does not exist"):
        promote_candidate_table(
            "missing_cand_table",
            "test_candidate",
            "real_table",
            "test_active",
            promotion_conn,
            expected_candidate_identity=dummy_cand_ident,
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
            cur.execute("DROP TABLE IF EXISTS test_active.real_table;")
            cur.execute("DROP TABLE IF EXISTS test_candidate.real_table_candidate_run_1;")
            cur.execute("CREATE TABLE test_active.real_table AS SELECT 1 AS v;")
            cur.execute("CREATE TABLE test_candidate.real_table_candidate_run_1 AS SELECT 2 AS v;")

    with psycopg.connect(promotion_conn) as conn:
        target_ident = resolve_relation_identity(conn, "test_active", "real_table")
        cand_ident = resolve_relation_identity(conn, "test_candidate", "real_table_candidate_run_1")

    promote_candidate_table(
        "real_table_candidate_run_1",
        "test_candidate",
        "real_table",
        "test_active",
        promotion_conn,
        expected_candidate_identity=cand_ident,
        expected_target_identity=target_ident,
    )

    with psycopg.connect(promotion_conn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT v FROM test_active.real_table;")
            assert cur.fetchone()[0] == 2
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

    with psycopg.connect(promotion_conn) as conn:
        cand_ident = resolve_relation_identity(conn, "test_candidate", "first_table_candidate_run_1")

    promote_candidate_table(
        "first_table_candidate_run_1",
        "test_candidate",
        "first_table",
        "test_active",
        promotion_conn,
        expected_candidate_identity=cand_ident,
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
    dummy_cand_ident = {
        "database_oid": 1,
        "namespace_oid": 1,
        "relation_oid": 1,
        "schema": "candidate_schema",
        "relation_name": "candidate_table",
        "relation_kind": "r",
    }
    with pytest.raises(PromotionError, match="Unsafe promoted owner"):
        promote_candidate_table(
            "candidate_table",
            "candidate_schema",
            "target_table",
            "target_schema",
            promotion_conn,
            promoted_owner="bad-owner",
            expected_candidate_identity=dummy_cand_ident,
        )


def test_promotion_rejects_candidate_identity_mismatch(promotion_conn):
    with psycopg.connect(promotion_conn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS test_candidate;")
            cur.execute("CREATE SCHEMA IF NOT EXISTS test_active;")
            cur.execute("DROP TABLE IF EXISTS test_active.identity_table;")
            cur.execute("DROP TABLE IF EXISTS test_candidate.identity_cand_run_1;")
            cur.execute("CREATE TABLE test_candidate.identity_cand_run_1 AS SELECT 10 AS v;")

    with psycopg.connect(promotion_conn) as conn:
        real_ident = resolve_relation_identity(conn, "test_candidate", "identity_cand_run_1")

    assert real_ident is not None
    bad_ident = dict(real_ident)
    bad_ident["relation_oid"] = 999999

    with pytest.raises(PromotionError, match="Candidate relation identity mismatch"):
        promote_candidate_table(
            "identity_cand_run_1",
            "test_candidate",
            "identity_table",
            "test_active",
            promotion_conn,
            expected_candidate_identity=bad_ident,
        )


def test_promotion_rejects_incomplete_candidate_identity_missing_database_oid(promotion_conn):
    incomplete_ident = {
        "namespace_oid": 100,
        "relation_oid": 200,
        "schema": "test_candidate",
        "relation_name": "cand",
        "relation_kind": "r",
    }
    with pytest.raises(PromotionError, match="Invalid or incomplete candidate identity structure"):
        promote_candidate_table(
            "cand",
            "test_candidate",
            "target",
            "test_active",
            promotion_conn,
            expected_candidate_identity=incomplete_ident,
        )


def test_promotion_rejects_unauthorized_target_overwrite_without_identity(promotion_conn):
    with psycopg.connect(promotion_conn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS test_candidate;")
            cur.execute("CREATE SCHEMA IF NOT EXISTS test_active;")
            cur.execute("DROP TABLE IF EXISTS test_active.overwrite_table;")
            cur.execute("DROP TABLE IF EXISTS test_candidate.overwrite_cand_run_1;")
            cur.execute("CREATE TABLE test_active.overwrite_table AS SELECT 1 AS v;")
            cur.execute("CREATE TABLE test_candidate.overwrite_cand_run_1 AS SELECT 2 AS v;")

    with psycopg.connect(promotion_conn) as conn:
        cand_ident = resolve_relation_identity(conn, "test_candidate", "overwrite_cand_run_1")

    with pytest.raises(PromotionError, match="Target relation overwrite unauthorized"):
        promote_candidate_table(
            "overwrite_cand_run_1",
            "test_candidate",
            "overwrite_table",
            "test_active",
            promotion_conn,
            expected_candidate_identity=cand_ident,
            expected_target_identity=None,
        )


def test_promotion_succeeds_with_matching_candidate_and_target_identities(promotion_conn):
    with psycopg.connect(promotion_conn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS test_candidate;")
            cur.execute("CREATE SCHEMA IF NOT EXISTS test_active;")
            cur.execute("DROP TABLE IF EXISTS test_active.exact_table;")
            cur.execute("DROP TABLE IF EXISTS test_candidate.exact_cand_run_1;")
            cur.execute("CREATE TABLE test_active.exact_table AS SELECT 100 AS v;")
            cur.execute("CREATE TABLE test_candidate.exact_cand_run_1 AS SELECT 200 AS v;")

    with psycopg.connect(promotion_conn) as conn:
        cand_ident = resolve_relation_identity(conn, "test_candidate", "exact_cand_run_1")
        target_ident = resolve_relation_identity(conn, "test_active", "exact_table")

    promote_candidate_table(
        "exact_cand_run_1",
        "test_candidate",
        "exact_table",
        "test_active",
        promotion_conn,
        expected_candidate_identity=cand_ident,
        expected_target_identity=target_ident,
    )

    with psycopg.connect(promotion_conn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT v FROM test_active.exact_table;")
            assert cur.fetchone()[0] == 200


def test_promotion_rejects_backup_name_collision(promotion_conn):
    from src.promotion import generate_backup_relation_name
    backup_name = generate_backup_relation_name("coll_table", "coll_cand_run_1")
    with psycopg.connect(promotion_conn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS test_candidate;")
            cur.execute("CREATE SCHEMA IF NOT EXISTS test_active;")
            cur.execute(f"DROP TABLE IF EXISTS test_active.{backup_name};")
            cur.execute("DROP TABLE IF EXISTS test_active.coll_table;")
            cur.execute("DROP TABLE IF EXISTS test_candidate.coll_cand_run_1;")
            cur.execute("CREATE TABLE test_active.coll_table AS SELECT 1 AS v;")
            cur.execute(f"CREATE TABLE test_active.{backup_name} AS SELECT 999 AS v;")
            cur.execute("CREATE TABLE test_candidate.coll_cand_run_1 AS SELECT 2 AS v;")

    with psycopg.connect(promotion_conn) as conn:
        cand_ident = resolve_relation_identity(conn, "test_candidate", "coll_cand_run_1")
        target_ident = resolve_relation_identity(conn, "test_active", "coll_table")

    with pytest.raises(PromotionError, match="Backup relation collision"):
        promote_candidate_table(
            "coll_cand_run_1",
            "test_candidate",
            "coll_table",
            "test_active",
            promotion_conn,
            expected_candidate_identity=cand_ident,
            expected_target_identity=target_ident,
            run_id="coll_cand_run_1",
        )


def test_custom_schema_role_setup_proof(promotion_conn):
    from src.db_config import apply_role_setup, LayerSchemas
    custom_schemas = LayerSchemas(
        source="cust_src",
        bronze="cust_brz",
        silver="cust_slv",
        gold="cust_gld",
        silver_candidates="cust_slv_cand",
        gold_candidates="cust_gld_cand",
    )
    with psycopg.connect(promotion_conn) as conn:
        apply_role_setup(conn, schemas=custom_schemas)
        with conn.cursor() as cur:
            cur.execute("SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname LIKE 'cust_%'")
            found = {row[0] for row in cur.fetchall()}
            assert found == {"cust_src", "cust_brz", "cust_slv", "cust_gld", "cust_slv_cand", "cust_gld_cand"}


class _SilverPromotionCursor:
    def __init__(self, *, candidate_exists=True):
        self.candidate_exists = candidate_exists
        self.commands = []
        self.current = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        rendered = query.as_string(None) if hasattr(query, "as_string") else str(query)
        self.commands.append((rendered, params))
        if "to_regclass" in rendered:
            self.current = (
                ("test_candidate.candidate",)
                if self.candidate_exists
                else (None,)
            )
        else:
            self.current = None

    def fetchone(self):
        return self.current


class _SilverPromotionTransaction:
    def __init__(self, *, commit_error=None, rollback_error=None):
        self.commit_error = commit_error
        self.rollback_error = rollback_error
        self.events = []

    def __enter__(self):
        self.events.append("enter")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.events.append("rollback" if exc_type else "commit")
        if exc_type and self.rollback_error is not None:
            raise self.rollback_error
        if exc_type is None and self.commit_error is not None:
            raise self.commit_error
        return False


class _SilverPromotionConnection:
    def __init__(
        self,
        *,
        candidate_exists=True,
        commit_error=None,
        rollback_error=None,
        cleanup_error=None,
    ):
        self.cursor_instance = _SilverPromotionCursor(
            candidate_exists=candidate_exists
        )
        self.transaction_instance = _SilverPromotionTransaction(
            commit_error=commit_error,
            rollback_error=rollback_error,
        )
        self.cleanup_error = cleanup_error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None and self.cleanup_error is not None:
            raise self.cleanup_error
        return False

    def cursor(self):
        return self.cursor_instance

    def transaction(self):
        return self.transaction_instance


def _install_silver_promotion_pool(
    monkeypatch,
    *,
    connection=None,
    checkout_error=None,
):
    class Pool:
        def connection(self):
            if checkout_error is not None:
                raise checkout_error
            return connection

    monkeypatch.setattr("src.db_config.get_promotion_pool", lambda: Pool())


def _silver_candidate_identity():
    return {
        "database_oid": 101,
        "namespace_oid": 102,
        "relation_oid": 201,
        "schema": "test_candidate",
        "relation_name": "candidate",
        "relation_kind": "r",
    }


def _install_silver_identity_resolution(monkeypatch):
    candidate = _silver_candidate_identity()
    final = {
        **candidate,
        "namespace_oid": 103,
        "schema": "test_active",
        "relation_name": "target",
    }
    resolutions = [candidate, None, final]
    monkeypatch.setattr(
        promotion,
        "resolve_relation_identity",
        lambda *args, **kwargs: resolutions.pop(0),
    )
    return final


def _run_isolated_silver_promotion():
    return promote_candidate_table(
        candidate_table="candidate",
        candidate_schema="test_candidate",
        target_table="target",
        target_schema="test_active",
        promotion_conninfo=None,
        expected_candidate_identity=_silver_candidate_identity(),
        run_id="run_isolated",
    )


def test_silver_pool_checkout_failure_is_deterministic_precommit(monkeypatch):
    _install_silver_promotion_pool(
        monkeypatch,
        checkout_error=RuntimeError("checkout failed"),
    )

    with pytest.raises(SilverPromotionFailedBeforeCommit, match="Pool checkout"):
        _run_isolated_silver_promotion()


def test_silver_body_failure_with_acknowledged_rollback_is_deterministic(
    monkeypatch,
):
    connection = _SilverPromotionConnection(candidate_exists=False)
    _install_silver_promotion_pool(monkeypatch, connection=connection)

    with pytest.raises(
        SilverPromotionFailedKnownRollback,
        match="rolled back",
    ):
        _run_isolated_silver_promotion()

    assert connection.transaction_instance.events == ["enter", "rollback"]


def test_silver_rollback_failure_is_not_mislabeled_confirmed(monkeypatch):
    connection = _SilverPromotionConnection(
        candidate_exists=False,
        rollback_error=RuntimeError("rollback acknowledgement lost"),
    )
    _install_silver_promotion_pool(monkeypatch, connection=connection)

    with pytest.raises(SilverPromotionRollbackFailed, match="rollback failed"):
        _run_isolated_silver_promotion()

    assert connection.transaction_instance.events == ["enter", "rollback"]


def test_silver_commit_call_error_is_commit_unknown(monkeypatch):
    connection = _SilverPromotionConnection(
        commit_error=RuntimeError("commit acknowledgement lost"),
    )
    _install_silver_promotion_pool(monkeypatch, connection=connection)
    _install_silver_identity_resolution(monkeypatch)

    with pytest.raises(
        SilverPromotionCommitUnknown,
        match="commit acknowledgement uncertain",
    ):
        _run_isolated_silver_promotion()

    assert connection.transaction_instance.events == ["enter", "commit"]


def test_silver_acknowledged_commit_survives_pool_context_cleanup_failure(
    monkeypatch,
):
    connection = _SilverPromotionConnection(
        cleanup_error=RuntimeError("pool reset failed"),
    )
    _install_silver_promotion_pool(monkeypatch, connection=connection)
    expected_final = _install_silver_identity_resolution(monkeypatch)

    final_identity, backup_identity = _run_isolated_silver_promotion()

    assert final_identity == expected_final
    assert backup_identity is None
    assert connection.transaction_instance.events == ["enter", "commit"]
