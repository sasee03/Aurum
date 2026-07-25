from __future__ import annotations

import threading

import pytest

import api.source_ingest_router as source_router
from src.app_state.db import get_connection
from src.bronze_authority import (
    BRONZE_INGEST_RECONCILIATION_REQUIRED,
    BronzeAuthorityError,
    claim_bronze_ingest_operation,
    finalize_bronze_ingest_ready,
    get_bronze_ingest_operation,
    mark_bronze_ingest_commit_in_progress,
    mark_bronze_ingest_creating,
    mark_bronze_ingest_outcome,
)


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "AURUM_APP_STATE_DB",
        str(tmp_path / "bronze_lifecycle.sqlite"),
    )
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO projects (
                id, name, description, environment, created_at, updated_at,
                status
            )
            VALUES ('project', 'Project', '', 'Development', 'now', 'now',
                    'active')
            """
        )
        conn.execute(
            """
            INSERT INTO data_connections (
                id, project_id, type, name, host, port, database_name,
                username, status, created_at, updated_at
            )
            VALUES ('connection', 'project', 'postgres', 'Connection',
                    'localhost', 5433, 'aurum', 'user', 'active', 'now', 'now')
            """
        )
        conn.commit()


def _identity(oid: int, *, schema: str, name: str) -> dict:
    return {
        "database_oid": 11,
        "namespace_oid": 22 if schema == "source" else 23,
        "relation_oid": oid,
        "schema": schema,
        "relation_name": name,
        "relation_kind": "r",
    }


def _claim(ingest_id: str):
    return claim_bronze_ingest_operation(
        ingest_id=ingest_id,
        project_id="project",
        connection_id="connection",
        database_name="aurum",
        database_oid=11,
        source_schema="source",
        source_namespace_oid=22,
        source_relation="arbitrary",
        bronze_schema="bronze",
        bronze_namespace_oid=23,
        bronze_relation="arbitrary",
    )


def _provisional(ingest_id: str, oid: int):
    mark_bronze_ingest_creating(
        ingest_id,
        source_identity=_identity(100, schema="source", name="arbitrary"),
    )
    mark_bronze_ingest_commit_in_progress(
        ingest_id,
        bronze_identity=_identity(oid, schema="bronze", name="arbitrary"),
    )


def _install_reconcile_catalog(monkeypatch, live):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, *args, **kwargs):
            return None

    class Transaction:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    class Connection:
        def cursor(self):
            return Cursor()

        def transaction(self):
            return Transaction()

    class Context:
        def __enter__(self):
            return Connection()

        def __exit__(self, *args):
            return None

    class Pool:
        def connection(self):
            return Context()

    monkeypatch.setattr(source_router, "get_ingestion_pool", lambda: Pool())
    monkeypatch.setattr(
        source_router,
        "_database_identity",
        lambda conn: {"database_name": "aurum", "database_oid": 11},
    )
    monkeypatch.setattr(
        source_router,
        "resolve_relation_identity",
        lambda *args: live,
    )


def test_provisional_exact_identity_precedes_ready_and_finalizes(
    isolated_state,
):
    _claim("ingest_one")
    _provisional("ingest_one", 200)
    operation = get_bronze_ingest_operation("ingest_one")
    assert operation["status"] == "COMMIT_IN_PROGRESS"
    assert operation["provisional_bronze_identity"]["relation_oid"] == 200
    authority = finalize_bronze_ingest_ready("ingest_one")
    assert authority["status"] == "READY"
    assert authority["bronze_identity"]["relation_oid"] == 200


def test_failed_new_ingest_does_not_supersede_previous_ready(isolated_state):
    _claim("ingest_old")
    _provisional("ingest_old", 200)
    finalize_bronze_ingest_ready("ingest_old")

    _claim("ingest_new")
    mark_bronze_ingest_outcome(
        "ingest_new",
        status="FAILED_RETRYABLE",
        failure_code="BODY_ROLLED_BACK",
    )
    with get_connection() as conn:
        old = conn.execute(
            "SELECT status FROM bronze_ingest_authority WHERE ingest_id = ?",
            ("ingest_old",),
        ).fetchone()
    assert old["status"] == "READY"


def test_successful_new_ingest_supersedes_only_during_ready_finalize(
    isolated_state,
):
    _claim("ingest_old")
    _provisional("ingest_old", 200)
    finalize_bronze_ingest_ready("ingest_old")
    _claim("ingest_new")
    _provisional("ingest_new", 201)
    with get_connection() as conn:
        assert conn.execute(
            "SELECT status FROM bronze_ingest_authority WHERE ingest_id = ?",
            ("ingest_old",),
        ).fetchone()["status"] == "READY"
    finalize_bronze_ingest_ready("ingest_new")
    with get_connection() as conn:
        assert conn.execute(
            "SELECT status FROM bronze_ingest_authority WHERE ingest_id = ?",
            ("ingest_old",),
        ).fetchone()["status"] == "SUPERSEDED"


def test_commit_unknown_preserves_exact_identity_for_reconciliation(
    isolated_state,
):
    _claim("ingest_unknown")
    _provisional("ingest_unknown", 333)
    mark_bronze_ingest_outcome(
        "ingest_unknown",
        status=BRONZE_INGEST_RECONCILIATION_REQUIRED,
        failure_code="POSTGRESQL_COMMIT_UNKNOWN",
    )
    operation = get_bronze_ingest_operation("ingest_unknown")
    assert operation["status"] == "RECONCILIATION_REQUIRED"
    assert operation["provisional_bronze_identity"]["relation_oid"] == 333


def test_concurrent_same_target_has_one_claimant(isolated_state):
    outcomes = []
    barrier = threading.Barrier(2)

    def claim(ingest_id):
        barrier.wait()
        try:
            outcomes.append(_claim(ingest_id)["ingest_id"])
        except BronzeAuthorityError:
            outcomes.append("rejected")

    threads = [
        threading.Thread(target=claim, args=("ingest_a",)),
        threading.Thread(target=claim, args=("ingest_b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert outcomes.count("rejected") == 1
    assert len(outcomes) == 2


def test_same_name_different_oid_reconciliation_never_adopts(
    isolated_state, monkeypatch
):
    _claim("ingest_conflict")
    _provisional("ingest_conflict", 400)
    mark_bronze_ingest_outcome(
        "ingest_conflict",
        status=BRONZE_INGEST_RECONCILIATION_REQUIRED,
        failure_code="POSTGRESQL_COMMIT_UNKNOWN",
    )

    replacement = _identity(401, schema="bronze", name="arbitrary")
    _install_reconcile_catalog(monkeypatch, replacement)
    result = source_router.reconcile_bronze_ingest("ingest_conflict")
    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert result["replacement_preserved"] is True
    assert (
        get_bronze_ingest_operation("ingest_conflict")[
            "provisional_bronze_identity"
        ]["relation_oid"]
        == 400
    )


def test_exact_provisional_oid_reconciles_to_ready(
    isolated_state, monkeypatch
):
    _claim("ingest_exact")
    _provisional("ingest_exact", 500)
    mark_bronze_ingest_outcome(
        "ingest_exact",
        status=BRONZE_INGEST_RECONCILIATION_REQUIRED,
        failure_code="READY_PERSISTENCE_FAILED",
    )
    expected = _identity(500, schema="bronze", name="arbitrary")
    _install_reconcile_catalog(monkeypatch, expected)
    result = source_router.reconcile_bronze_ingest("ingest_exact")
    assert result["status"] == "READY"
    assert result["bronze_identity"] == expected


def test_absent_provisional_oid_reconciles_to_retryable(
    isolated_state, monkeypatch
):
    _claim("ingest_absent")
    _provisional("ingest_absent", 600)
    mark_bronze_ingest_outcome(
        "ingest_absent",
        status=BRONZE_INGEST_RECONCILIATION_REQUIRED,
        failure_code="POSTGRESQL_COMMIT_UNKNOWN",
    )
    _install_reconcile_catalog(monkeypatch, None)
    result = source_router.reconcile_bronze_ingest("ingest_absent")
    assert result["status"] == "FAILED_RETRYABLE"

"""Gold backup cleanup operational lifecycle and exact-authority tests."""

