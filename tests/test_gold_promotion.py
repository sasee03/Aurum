"""Focused isolated proof for Batch 4.5C Gold promotion."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event, Lock
from types import SimpleNamespace

import psycopg
import pytest

import src.gold_promotion as promotion
from src.gold_promotion import (
    GoldPromotionOutcomeUnknown,
    GoldPromotionRejected,
)
from src.gold_security import promotion_backup_name


DATABASE_OID = 101
TARGET_NAMESPACE_OID = 103
CANDIDATE_NAMESPACE_OID = 104
DATABASE_NAME = "isolated_promotion_database"
TARGET_SCHEMA = "configured_gold"
CANDIDATE_SCHEMA = "configured_gold_candidates"
TARGET_NAME = "approved_output"
CANDIDATE_NAME = "approved_output_candidate_run_promotion"


def _identity(
    schema: str,
    name: str,
    relation_oid: int,
    namespace_oid: int,
    *,
    kind: str = "r",
) -> dict:
    return {
        "database_oid": DATABASE_OID,
        "namespace_oid": namespace_oid,
        "relation_oid": relation_oid,
        "schema": schema,
        "relation_name": name,
        "relation_kind": kind,
    }


def _state(*, existing_target: bool = False, overwrite: bool = False):
    candidate = _identity(
        CANDIDATE_SCHEMA,
        CANDIDATE_NAME,
        401,
        CANDIDATE_NAMESPACE_OID,
    )
    target_identity = {
        "state": "absent",
        "database_oid": DATABASE_OID,
        "namespace_oid": TARGET_NAMESPACE_OID,
        "schema": TARGET_SCHEMA,
        "relation_name": TARGET_NAME,
    }
    if existing_target:
        target_identity = {
            "state": "existing",
            **_identity(
                TARGET_SCHEMA,
                TARGET_NAME,
                301,
                TARGET_NAMESPACE_OID,
            ),
        }
    return SimpleNamespace(
        run_id="run_promotion",
        approval_snapshot={
            "database": {"oid": DATABASE_OID, "name": DATABASE_NAME}
        },
        approved_revision="a" * 64,
        target={"schema": TARGET_SCHEMA, "table": TARGET_NAME},
        candidate={"schema": CANDIDATE_SCHEMA, "table": CANDIDATE_NAME},
        target_identity=target_identity,
        candidate_namespace_identity={
            "database_oid": DATABASE_OID,
            "namespace_oid": CANDIDATE_NAMESPACE_OID,
            "schema": CANDIDATE_SCHEMA,
        },
        candidate_identity=candidate,
        execution_claim_id="exec_123",
        promotion_claim_id="promo_123",
        promotion_claimed_at="2026-07-24T00:00:00+00:00",
        overwrite_authorized=overwrite,
    )


class _CatalogCursor:
    def __init__(self, catalog):
        self.catalog = catalog
        self.commands = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        rendered = query.as_string(None) if hasattr(query, "as_string") else query
        self.commands.append((rendered, params))
        if not isinstance(rendered, str):
            return
        rename = re.fullmatch(
            r'ALTER TABLE "([^"]+)"\."([^"]+)" RENAME TO "([^"]+)"',
            rendered,
        )
        if rename:
            schema, old_name, new_name = rename.groups()
            relation = self.catalog.pop((schema, old_name))
            relation["relation_name"] = new_name
            self.catalog[(schema, new_name)] = relation
            return
        move = re.fullmatch(
            r'ALTER TABLE "([^"]+)"\."([^"]+)" SET SCHEMA "([^"]+)"',
            rendered,
        )
        if move:
            old_schema, name, new_schema = move.groups()
            relation = self.catalog.pop((old_schema, name))
            relation["schema"] = new_schema
            relation["namespace_oid"] = TARGET_NAMESPACE_OID
            self.catalog[(new_schema, name)] = relation


class _Transaction:
    def __init__(self, commit_error=None):
        self.commit_error = commit_error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None and self.commit_error is not None:
            raise self.commit_error
        return False


class _Connection:
    def __init__(self, catalog, *, commit_error=None, cleanup_error=None):
        self.cursor_instance = _CatalogCursor(catalog)
        self.commit_error = commit_error
        self.cleanup_error = cleanup_error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None and self.cleanup_error is not None:
            raise self.cleanup_error
        return False

    def transaction(self):
        return _Transaction(self.commit_error)

    def cursor(self):
        return self.cursor_instance


class _Pool:
    def __init__(self, catalog, *, commit_error=None, cleanup_error=None):
        self.connection_instance = _Connection(
            catalog,
            commit_error=commit_error,
            cleanup_error=cleanup_error,
        )

    def connection(self):
        return self.connection_instance


def _install_catalog(monkeypatch, catalog):
    monkeypatch.setattr(
        promotion,
        "_database_identity",
        lambda cursor: (DATABASE_OID, DATABASE_NAME),
    )
    monkeypatch.setattr(
        promotion,
        "_namespace_oid",
        lambda cursor, schema: {
            TARGET_SCHEMA: TARGET_NAMESPACE_OID,
            CANDIDATE_SCHEMA: CANDIDATE_NAMESPACE_OID,
        }.get(schema),
    )

    def by_name(cursor, *, schema, relation_name, **kwargs):
        relation = cursor.catalog.get((schema, relation_name))
        return deepcopy(relation) if relation is not None else None

    def by_oid(cursor, *, relation_oid, **kwargs):
        for relation in cursor.catalog.values():
            if relation["relation_oid"] == relation_oid:
                return deepcopy(relation)
        return None

    monkeypatch.setattr(promotion, "_relation_identity_by_name", by_name)
    monkeypatch.setattr(promotion, "_relation_identity_by_oid", by_oid)


def _initial_catalog(state):
    catalog = {
        (CANDIDATE_SCHEMA, CANDIDATE_NAME): deepcopy(
            state.candidate_identity
        )
    }
    if state.target_identity["state"] == "existing":
        catalog[(TARGET_SCHEMA, TARGET_NAME)] = {
            key: value
            for key, value in state.target_identity.items()
            if key != "state"
        }
    return catalog


def test_target_absent_promotes_exact_oid_with_transaction_scoped_lock(
    monkeypatch,
):
    state = _state()
    catalog = _initial_catalog(state)
    _install_catalog(monkeypatch, catalog)
    pool = _Pool(catalog)

    result = promotion.promote_gold_candidate(state, pool=pool)

    assert result.final_target_identity == _identity(
        TARGET_SCHEMA,
        TARGET_NAME,
        401,
        TARGET_NAMESPACE_OID,
    )
    assert result.backup_identity is None
    commands = pool.connection_instance.cursor_instance.commands
    assert commands[0] == (
        "SELECT pg_catalog.set_config(%s, %s, true)",
        ("search_path", "pg_catalog"),
    )
    assert commands[1][0] == (
        "SELECT pg_catalog.pg_advisory_xact_lock(%s)"
    )
    assert commands[2][0] == (
        f'LOCK TABLE "{CANDIDATE_SCHEMA}"."{CANDIDATE_NAME}" '
        "IN ACCESS EXCLUSIVE MODE"
    )
    assert [command for command, _ in commands[-2:]] == [
        (
            f'ALTER TABLE "{CANDIDATE_SCHEMA}"."{CANDIDATE_NAME}" '
            f'SET SCHEMA "{TARGET_SCHEMA}"'
        ),
        (
            f'ALTER TABLE "{TARGET_SCHEMA}"."{CANDIDATE_NAME}" '
            f'RENAME TO "{TARGET_NAME}"'
        ),
    ]


def test_candidate_same_name_replacement_after_lock_fails_before_ddl(
    monkeypatch,
):
    state = _state()
    catalog = _initial_catalog(state)
    _install_catalog(monkeypatch, catalog)
    real_resolve = promotion._relation_identity_by_name
    candidate_reads = {"count": 0}

    def replaced_on_second_read(cursor, *, schema, relation_name, **kwargs):
        live = real_resolve(
            cursor,
            schema=schema,
            relation_name=relation_name,
            **kwargs,
        )
        if (schema, relation_name) == (CANDIDATE_SCHEMA, CANDIDATE_NAME):
            candidate_reads["count"] += 1
            if candidate_reads["count"] == 2:
                return {**live, "relation_oid": 999}
        return live

    monkeypatch.setattr(
        promotion,
        "_relation_identity_by_name",
        replaced_on_second_read,
    )
    pool = _Pool(catalog)
    with pytest.raises(GoldPromotionRejected) as rejected:
        promotion.promote_gold_candidate(state, pool=pool)
    assert rejected.value.code == promotion.GOLD_CANDIDATE_IDENTITY_CHANGED
    assert not any(
        str(command).startswith("ALTER TABLE")
        for command, _ in pool.connection_instance.cursor_instance.commands
    )


def test_candidate_namespace_replacement_fails_before_relation_mutation(
    monkeypatch,
):
    state = _state()
    catalog = _initial_catalog(state)
    _install_catalog(monkeypatch, catalog)
    monkeypatch.setattr(
        promotion,
        "_namespace_oid",
        lambda cursor, schema: (
            999
            if schema == CANDIDATE_SCHEMA
            else TARGET_NAMESPACE_OID
        ),
    )
    pool = _Pool(catalog)
    with pytest.raises(GoldPromotionRejected) as rejected:
        promotion.promote_gold_candidate(state, pool=pool)
    assert rejected.value.code == promotion.GOLD_CANDIDATE_IDENTITY_CHANGED
    assert not any(
        str(command).startswith("ALTER TABLE")
        for command, _ in pool.connection_instance.cursor_instance.commands
    )


def test_target_namespace_replacement_fails_before_relation_mutation(
    monkeypatch,
):
    state = _state()
    catalog = _initial_catalog(state)
    _install_catalog(monkeypatch, catalog)
    monkeypatch.setattr(
        promotion,
        "_namespace_oid",
        lambda cursor, schema: (
            999
            if schema == TARGET_SCHEMA
            else CANDIDATE_NAMESPACE_OID
        ),
    )
    pool = _Pool(catalog)
    with pytest.raises(GoldPromotionRejected) as rejected:
        promotion.promote_gold_candidate(state, pool=pool)
    assert rejected.value.code == promotion.GOLD_TARGET_IDENTITY_CHANGED
    assert not any(
        str(command).startswith("ALTER TABLE")
        for command, _ in pool.connection_instance.cursor_instance.commands
    )


def test_approved_absent_target_that_appears_is_never_overwritten(
    monkeypatch,
):
    state = _state()
    catalog = _initial_catalog(state)
    catalog[(TARGET_SCHEMA, TARGET_NAME)] = _identity(
        TARGET_SCHEMA,
        TARGET_NAME,
        777,
        TARGET_NAMESPACE_OID,
    )
    _install_catalog(monkeypatch, catalog)
    pool = _Pool(catalog)
    with pytest.raises(GoldPromotionRejected) as rejected:
        promotion.promote_gold_candidate(state, pool=pool)
    assert rejected.value.code == promotion.GOLD_TARGET_IDENTITY_CHANGED
    assert catalog[(TARGET_SCHEMA, TARGET_NAME)]["relation_oid"] == 777
    assert not any(
        str(command).startswith("ALTER TABLE")
        for command, _ in pool.connection_instance.cursor_instance.commands
    )


def test_existing_target_overwrite_tracks_exact_backup_and_oid_lineage(
    monkeypatch,
):
    state = _state(existing_target=True, overwrite=True)
    catalog = _initial_catalog(state)
    _install_catalog(monkeypatch, catalog)
    pool = _Pool(catalog)

    result = promotion.promote_gold_candidate(state, pool=pool)

    backup_name = promotion_backup_name(
        TARGET_NAME,
        state.promotion_claim_id,
    )
    assert result.final_target_identity["relation_oid"] == 401
    assert result.backup_identity == _identity(
        TARGET_SCHEMA,
        backup_name,
        301,
        TARGET_NAMESPACE_OID,
    )
    commands = [
        command for command, _ in pool.connection_instance.cursor_instance.commands
    ]
    assert commands.index(
        f'LOCK TABLE "{CANDIDATE_SCHEMA}"."{CANDIDATE_NAME}" '
        "IN ACCESS EXCLUSIVE MODE"
    ) < commands.index(
        f'LOCK TABLE "{TARGET_SCHEMA}"."{TARGET_NAME}" '
        "IN ACCESS EXCLUSIVE MODE"
    )
    assert (
        f'ALTER TABLE "{TARGET_SCHEMA}"."{TARGET_NAME}" '
        f'RENAME TO "{backup_name}"'
    ) in commands
    assert catalog[(TARGET_SCHEMA, backup_name)]["relation_oid"] == 301
    assert catalog[(TARGET_SCHEMA, TARGET_NAME)]["relation_oid"] == 401


def test_existing_target_without_overwrite_authority_has_no_mutation(
    monkeypatch,
):
    state = _state(existing_target=True, overwrite=False)
    catalog = _initial_catalog(state)
    _install_catalog(monkeypatch, catalog)
    pool = _Pool(catalog)
    with pytest.raises(GoldPromotionRejected) as rejected:
        promotion.promote_gold_candidate(state, pool=pool)
    assert rejected.value.code == promotion.GOLD_OVERWRITE_NOT_AUTHORIZED
    assert not pool.connection_instance.cursor_instance.commands


def test_approved_existing_target_that_disappears_is_not_replaced(
    monkeypatch,
):
    state = _state(existing_target=True, overwrite=True)
    catalog = {
        (CANDIDATE_SCHEMA, CANDIDATE_NAME): deepcopy(
            state.candidate_identity
        )
    }
    _install_catalog(monkeypatch, catalog)
    pool = _Pool(catalog)
    with pytest.raises(GoldPromotionRejected) as rejected:
        promotion.promote_gold_candidate(state, pool=pool)
    assert rejected.value.code == promotion.GOLD_TARGET_IDENTITY_CHANGED
    assert not any(
        str(command).startswith("ALTER TABLE")
        for command, _ in pool.connection_instance.cursor_instance.commands
    )


def test_target_same_name_replacement_under_lock_is_never_renamed(
    monkeypatch,
):
    state = _state(existing_target=True, overwrite=True)
    catalog = _initial_catalog(state)
    _install_catalog(monkeypatch, catalog)
    real_resolve = promotion._relation_identity_by_name
    target_reads = {"count": 0}

    def replaced_on_second_read(cursor, *, schema, relation_name, **kwargs):
        live = real_resolve(
            cursor,
            schema=schema,
            relation_name=relation_name,
            **kwargs,
        )
        if (schema, relation_name) == (TARGET_SCHEMA, TARGET_NAME):
            target_reads["count"] += 1
            if target_reads["count"] == 2:
                return {**live, "relation_oid": 999}
        return live

    monkeypatch.setattr(
        promotion,
        "_relation_identity_by_name",
        replaced_on_second_read,
    )
    pool = _Pool(catalog)
    with pytest.raises(GoldPromotionRejected) as rejected:
        promotion.promote_gold_candidate(state, pool=pool)
    assert rejected.value.code == promotion.GOLD_TARGET_IDENTITY_CHANGED
    assert catalog[(TARGET_SCHEMA, TARGET_NAME)]["relation_oid"] == 301
    assert not any(
        str(command).startswith("ALTER TABLE")
        for command, _ in pool.connection_instance.cursor_instance.commands
    )


def test_deterministic_ddl_failure_is_known_not_committed(monkeypatch):
    state = _state(existing_target=True, overwrite=True)
    catalog = _initial_catalog(state)
    _install_catalog(monkeypatch, catalog)
    pool = _Pool(catalog)
    cursor = pool.connection_instance.cursor_instance
    real_execute = cursor.execute

    def fail_first_ddl(query, params=None):
        rendered = query.as_string(None) if hasattr(query, "as_string") else query
        if isinstance(rendered, str) and rendered.startswith("ALTER TABLE"):
            raise RuntimeError("isolated deterministic DDL error")
        return real_execute(query, params)

    cursor.execute = fail_first_ddl
    with pytest.raises(GoldPromotionRejected) as rejected:
        promotion.promote_gold_candidate(state, pool=pool)
    assert rejected.value.code == promotion.GOLD_PROMOTION_FAILED
    assert rejected.value.phase == promotion.TRANSACTION_BODY
    assert catalog[(TARGET_SCHEMA, TARGET_NAME)]["relation_oid"] == 301
    assert catalog[(CANDIDATE_SCHEMA, CANDIDATE_NAME)]["relation_oid"] == 401


def test_commit_acknowledgement_loss_preserves_observed_oid_result(
    monkeypatch,
):
    state = _state(existing_target=True, overwrite=True)
    catalog = _initial_catalog(state)
    _install_catalog(monkeypatch, catalog)
    pool = _Pool(
        catalog,
        commit_error=psycopg.OperationalError("lost commit acknowledgement"),
    )
    with pytest.raises(GoldPromotionOutcomeUnknown) as unknown:
        promotion.promote_gold_candidate(state, pool=pool)
    assert unknown.value.phase == promotion.COMMIT_IN_PROGRESS
    assert unknown.value.result.final_target_identity["relation_oid"] == 401
    assert unknown.value.result.backup_identity["relation_oid"] == 301


def test_acknowledged_commit_survives_pool_cleanup_failure(monkeypatch):
    state = _state()
    catalog = _initial_catalog(state)
    _install_catalog(monkeypatch, catalog)
    result = promotion.promote_gold_candidate(
        state,
        pool=_Pool(
            catalog,
            cleanup_error=RuntimeError("isolated pool-return error"),
        ),
    )
    assert result.phase == promotion.POST_COMMIT_POOL_CLEANUP
    assert result.final_target_identity["relation_oid"] == 401


def test_reconciliation_proves_absent_target_promotion_by_candidate_oid(
    monkeypatch,
):
    state = _state()
    catalog = {
        (TARGET_SCHEMA, TARGET_NAME): _identity(
            TARGET_SCHEMA,
            TARGET_NAME,
            401,
            TARGET_NAMESPACE_OID,
        )
    }
    _install_catalog(monkeypatch, catalog)
    result = promotion.reconcile_gold_promotion(state, pool=_Pool(catalog))
    assert result.outcome == "promoted"
    assert result.final_target_identity["relation_oid"] == 401


def test_reconciliation_proves_known_not_committed_without_retrying_ddl(
    monkeypatch,
):
    state = _state()
    catalog = _initial_catalog(state)
    _install_catalog(monkeypatch, catalog)
    pool = _Pool(catalog)
    result = promotion.reconcile_gold_promotion(state, pool=pool)
    assert result.outcome == "not_committed"
    assert not any(
        str(command).startswith("ALTER TABLE")
        for command, _ in pool.connection_instance.cursor_instance.commands
    )


def test_overwrite_reconciliation_requires_both_candidate_and_backup_oids(
    monkeypatch,
):
    state = _state(existing_target=True, overwrite=True)
    backup_name = promotion_backup_name(
        TARGET_NAME,
        state.promotion_claim_id,
    )
    promoted_catalog = {
        (TARGET_SCHEMA, TARGET_NAME): _identity(
            TARGET_SCHEMA,
            TARGET_NAME,
            401,
            TARGET_NAMESPACE_OID,
        ),
        (TARGET_SCHEMA, backup_name): _identity(
            TARGET_SCHEMA,
            backup_name,
            301,
            TARGET_NAMESPACE_OID,
        ),
    }
    _install_catalog(monkeypatch, promoted_catalog)
    proven = promotion.reconcile_gold_promotion(
        state,
        pool=_Pool(promoted_catalog),
    )
    assert proven.outcome == "promoted"
    assert proven.backup_identity["relation_oid"] == 301

    wrong_backup = deepcopy(promoted_catalog)
    wrong_backup[(TARGET_SCHEMA, backup_name)]["relation_oid"] = 999
    _install_catalog(monkeypatch, wrong_backup)
    ambiguous = promotion.reconcile_gold_promotion(
        state,
        pool=_Pool(wrong_backup),
    )
    assert ambiguous.outcome == "ambiguous"


def test_advisory_key_is_stable_target_scoped_and_not_python_hash():
    authority = {
        "database_oid": DATABASE_OID,
        "target_namespace_oid": TARGET_NAMESPACE_OID,
        "target_schema": TARGET_SCHEMA,
        "target_relation": TARGET_NAME,
    }
    first = promotion.promotion_advisory_lock_key(**authority)
    second = promotion.promotion_advisory_lock_key(**dict(reversed(
        list(authority.items())
    )))
    unrelated = promotion.promotion_advisory_lock_key(
        **{**authority, "target_relation": "unrelated_target"}
    )
    assert first == second
    assert first != unrelated
    assert -(2**63) <= first < 2**63


def test_different_runs_same_target_serialize_then_revalidate(monkeypatch):
    first_state = _state()
    second_state = deepcopy(first_state)
    second_name = "approved_output_candidate_run_second"
    second_state.run_id = "run_second"
    second_state.candidate = {
        "schema": CANDIDATE_SCHEMA,
        "table": second_name,
    }
    second_state.candidate_identity = _identity(
        CANDIDATE_SCHEMA,
        second_name,
        402,
        CANDIDATE_NAMESPACE_OID,
    )
    second_state.execution_claim_id = "exec_456"
    second_state.promotion_claim_id = "promo_456"
    catalog = _initial_catalog(first_state)
    catalog[(CANDIDATE_SCHEMA, second_name)] = deepcopy(
        second_state.candidate_identity
    )
    _install_catalog(monkeypatch, catalog)

    target_lock = Lock()
    allocation_lock = Lock()
    first_holds_candidate = Event()
    second_attempted_advisory = Event()
    release_first = Event()

    class SerializedTransaction:
        def __init__(self, connection):
            self.connection = connection

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            if self.connection.holds_advisory:
                self.connection.holds_advisory = False
                target_lock.release()
            return False

    class SerializedCursor(_CatalogCursor):
        def __init__(self, shared_catalog, connection):
            super().__init__(shared_catalog)
            self.connection = connection

        def execute(self, query, params=None):
            rendered = (
                query.as_string(None)
                if hasattr(query, "as_string")
                else query
            )
            if rendered == "SELECT pg_catalog.pg_advisory_xact_lock(%s)":
                self.commands.append((rendered, params))
                if self.connection.index == 1:
                    second_attempted_advisory.set()
                target_lock.acquire()
                self.connection.holds_advisory = True
                return
            super().execute(query, params)
            if (
                self.connection.index == 0
                and isinstance(rendered, str)
                and rendered.startswith("LOCK TABLE")
                and CANDIDATE_NAME in rendered
            ):
                first_holds_candidate.set()
                assert release_first.wait(timeout=5)

    class SerializedConnection:
        def __init__(self, shared_catalog, index):
            self.index = index
            self.holds_advisory = False
            self.cursor_instance = SerializedCursor(shared_catalog, self)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def transaction(self):
            return SerializedTransaction(self)

        def cursor(self):
            return self.cursor_instance

    class SerializedPool:
        def __init__(self):
            self.next_index = 0

        def connection(self):
            with allocation_lock:
                index = self.next_index
                self.next_index += 1
            return SerializedConnection(catalog, index)

    pool = SerializedPool()
    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            promotion.promote_gold_candidate,
            first_state,
            pool=pool,
        )
        assert first_holds_candidate.wait(timeout=5)
        second_future = executor.submit(
            promotion.promote_gold_candidate,
            second_state,
            pool=pool,
        )
        assert second_attempted_advisory.wait(timeout=5)
        release_first.set()
        first_result = first_future.result(timeout=5)
        with pytest.raises(GoldPromotionRejected) as second_rejected:
            second_future.result(timeout=5)

    assert first_result.final_target_identity["relation_oid"] == 401
    assert (
        second_rejected.value.code
        == promotion.GOLD_TARGET_IDENTITY_CHANGED
    )
    assert catalog[(TARGET_SCHEMA, TARGET_NAME)]["relation_oid"] == 401
    assert catalog[(CANDIDATE_SCHEMA, second_name)]["relation_oid"] == 402
