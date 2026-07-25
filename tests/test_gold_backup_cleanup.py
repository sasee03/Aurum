from types import SimpleNamespace

import pytest

from src import gold_backup_cleanup as cleanup


IDENTITY = {
    "database_oid": 17,
    "namespace_oid": 23,
    "relation_oid": 41,
    "schema": "gold",
    "relation_name": "orders_backup",
    "relation_kind": "r",
}


class FakeCursor:
    def __init__(self, *, by_oid, by_name):
        self.by_oid = by_oid
        self.by_name = by_name
        self.next_row = None
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None):
        rendered = str(query)
        self.statements.append((rendered, params))
        if "database.datname" in rendered and "pg_class" not in rendered:
            self.next_row = (17, "aurum")
        elif "relation.oid = %s" in rendered:
            self.next_row = self.by_oid
        elif "namespace.nspname = %s" in rendered:
            self.next_row = self.by_name
        else:
            self.next_row = None

    def fetchone(self):
        return self.next_row


class FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def transaction(self):
        return FakeTransaction()


class FakeConnectionContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *args):
        return None


class FakePool:
    def __init__(self, cursor):
        self.connection_value = FakeConnection(cursor)

    def connection(self):
        return FakeConnectionContext(self.connection_value)


def _catalog_row(identity):
    if identity is None:
        return None
    return (
        identity["database_oid"],
        identity["namespace_oid"],
        identity["relation_oid"],
        identity["schema"],
        identity["relation_name"],
        identity["relation_kind"],
    )


def _state():
    return SimpleNamespace(
        backup_identity=dict(IDENTITY),
        backup_cleanup_eligible=True,
        promotion_committed_at="2026-07-25T00:00:00+00:00",
        approval_snapshot={"database": {"oid": 17, "name": "aurum"}},
    )


def test_exact_identity_is_rechecked_under_lock_before_drop(monkeypatch):
    cursor = FakeCursor(
        by_oid=_catalog_row(IDENTITY),
        by_name=_catalog_row(IDENTITY),
    )
    cleared = []
    monkeypatch.setattr(cleanup, "_load_cleanup_state", lambda run_id: _state())
    monkeypatch.setattr(
        cleanup,
        "_clear_cleanup_eligibility",
        lambda run_id: cleared.append(run_id),
    )

    result = cleanup.cleanup_gold_backup(
        "run_exact",
        pool=FakePool(cursor),
    )

    statements = [statement for statement, _ in cursor.statements]
    assert result.outcome == cleanup.GOLD_BACKUP_REMOVED
    assert any("relation.oid = %s" in statement for statement in statements)
    assert sum("namespace.nspname = %s" in statement for statement in statements) == 2
    assert any("LOCK TABLE" in statement for statement in statements)
    assert any("DROP TABLE" in statement for statement in statements)
    assert cleared == ["run_exact"]


def test_same_name_with_different_oid_is_preserved(monkeypatch):
    replacement = {**IDENTITY, "relation_oid": 99}
    cursor = FakeCursor(
        by_oid=None,
        by_name=_catalog_row(replacement),
    )
    monkeypatch.setattr(cleanup, "_load_cleanup_state", lambda run_id: _state())
    monkeypatch.setattr(cleanup, "_clear_cleanup_eligibility", lambda run_id: None)

    result = cleanup.cleanup_gold_backup(
        "run_collision",
        pool=FakePool(cursor),
    )

    statements = [statement for statement, _ in cursor.statements]
    assert result.outcome == cleanup.GOLD_BACKUP_IDENTITY_MISMATCH
    assert not any("LOCK TABLE" in statement for statement in statements)
    assert not any("DROP TABLE" in statement for statement in statements)


@pytest.mark.parametrize(
    "status",
    ["PROMOTING", "AMBIGUOUS_PROMOTION", "FAILED", "UNKNOWN", None],
)
def test_non_promoted_or_malformed_lifecycle_never_becomes_eligible(
    monkeypatch,
    status,
):
    envelope = {
        "run_id": "run_state",
        "table_name": "orders",
        "sql_text": "SELECT 1",
        "planned_changes_json": "{}",
        "status": status,
        "candidate_schema": "gold_candidates",
        "generator_provenance": "trusted",
    }
    security = {"run_id": "run_state"}

    class Result:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return self.value

    class Connection:
        def __init__(self):
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, statement, params=None):
            if statement == "BEGIN IMMEDIATE":
                return Result(None)
            self.calls += 1
            return Result(envelope if self.calls == 1 else security)

        def rollback(self):
            return None

        def commit(self):
            return None

    state = SimpleNamespace(
        backup_identity=dict(IDENTITY),
        promotion_committed_at="2026-07-25T00:00:00+00:00",
        backup_cleanup_eligible=False,
    )
    monkeypatch.setattr(cleanup, "get_connection", lambda: Connection())
    monkeypatch.setattr(
        cleanup,
        "load_persisted_gold_security_state",
        lambda security_row, envelope_row: state,
    )

    with pytest.raises(
        cleanup.GoldBackupCleanupRejected,
        match="no strictly promoted backup",
    ):
        cleanup.authorize_gold_backup_cleanup("run_state")
