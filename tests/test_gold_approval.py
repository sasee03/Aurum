"""Focused isolated proof for the Batch 4.5A Gold approval contract."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier, Event, Lock, get_ident
from types import SimpleNamespace

import pytest
import psycopg
from fastapi.testclient import TestClient

import api.silver_gold_router as router
import src.gold_catalog as gold_catalog
import src.gold_execution as gold_execution
import src.sql_safety as sql_safety
from api.main import app
from src.app_state.db import get_connection, init_schema
from src.generator_trust import GeneratorTrustPolicy
from src.gold_catalog import (
    GoldCatalogResolutionError,
    GoldCatalogSnapshot,
    GoldExecutionCatalogSnapshot,
    lock_gold_sources,
)
from src.gold_execution import (
    GoldCommitOutcomeUnknown,
    GoldExecutionRejected,
)
from src.gold_security import (
    GoldStateMalformed,
    GoldStateStale,
    build_approval_snapshot,
    build_review_snapshot,
    canonical_json,
    insert_gold_security_state,
    load_gold_security_state,
    new_gold_security_record,
    expected_candidate_name,
    revision_for,
)


client = TestClient(app)
TRUSTED_PROVENANCE = "gold_test_hardened"
GENERATOR_VERSION = "test-generator-1"
SCHEMAS = SimpleNamespace(
    silver="configured_silver",
    gold="configured_gold",
    gold_candidates="configured_gold_candidates",
)


def _sql(run_id: str, target: str = "approved_output") -> str:
    return (
        f"CREATE TABLE {SCHEMAS.gold_candidates}.{target}_candidate_{run_id} "
        f"AS SELECT * FROM {SCHEMAS.silver}.source_a"
    )


def _seed_run(
    run_id: str = "run_gold_approval",
    *,
    provenance: str = TRUSTED_PROVENANCE,
    target: str = "approved_output",
    sources: tuple[str, ...] = ("source_a",),
    with_security: bool = True,
    sql_text_override: str | None = None,
) -> dict | None:
    sql_text = sql_text_override or _sql(run_id, target)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review (
                run_id, table_name, sql_text, planned_changes_json,
                created_at, status, candidate_schema, generator_provenance
            )
            VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?)
            """,
            (
                run_id,
                target,
                sql_text,
                canonical_json({"summary": "test Gold plan"}),
                "2026-07-23T00:00:00+00:00",
                SCHEMAS.gold_candidates,
                provenance,
            ),
        )
        if not with_security:
            conn.commit()
            return None
        record = new_gold_security_record(
            run_id=run_id,
            sql_text=sql_text,
            business_requirement="Produce the approved output.",
            generator_provenance=provenance,
            generator_version=GENERATOR_VERSION,
            selected_sources=[
                {"schema": SCHEMAS.silver, "table": source}
                for source in sources
            ],
            target_schema=SCHEMAS.gold,
            target_name=target,
            candidate_schema=SCHEMAS.gold_candidates,
        )
        insert_gold_security_state(conn, record)
        conn.commit()
    return record


def _source_identity(
    table: str = "source_a",
    *,
    relation_oid: int = 201,
) -> dict:
    return {
        "database_oid": 101,
        "namespace_oid": 102,
        "relation_oid": relation_oid,
        "schema": SCHEMAS.silver,
        "relation_name": table,
        "relation_kind": "r",
    }


def _target_absent(target: str = "approved_output") -> dict:
    return {
        "state": "absent",
        "database_oid": 101,
        "namespace_oid": 103,
        "schema": SCHEMAS.gold,
        "relation_name": target,
    }


def _target_existing(target: str = "approved_output") -> dict:
    return {
        "state": "existing",
        "database_oid": 101,
        "namespace_oid": 103,
        "relation_oid": 301,
        "schema": SCHEMAS.gold,
        "relation_name": target,
        "relation_kind": "p",
    }


def _candidate_namespace_identity(*, namespace_oid: int = 104) -> dict:
    return {
        "database_oid": 101,
        "namespace_oid": namespace_oid,
        "schema": SCHEMAS.gold_candidates,
    }


def _catalog(
    target_identity: dict | None = None,
    *,
    source_identities: tuple[dict, ...] | None = None,
) -> GoldCatalogSnapshot:
    return GoldCatalogSnapshot(
        database_oid=101,
        database_name="isolated_test_database",
        source_identities=source_identities or (_source_identity(),),
        target_identity=target_identity or _target_absent(),
        candidate_namespace_identity=_candidate_namespace_identity(),
    )


@pytest.fixture
def trusted_gold(monkeypatch):
    monkeypatch.setattr(
        router,
        "GOLD_GENERATOR_TRUST",
        GeneratorTrustPolicy(
            pipeline="gold",
            trusted_hardened_provenances=frozenset({TRUSTED_PROVENANCE}),
        ),
    )
    monkeypatch.setattr(router, "load_layer_schemas", lambda: SCHEMAS)


def _security_row(run_id: str):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM gold_security_state WHERE run_id = ?",
            (run_id,),
        ).fetchone()


def _load_state(run_id: str):
    with get_connection() as conn:
        envelope = conn.execute(
            """
            SELECT run_id, table_name, sql_text, status, candidate_schema,
                   generator_provenance
            FROM generated_sql_review
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        security = conn.execute(
            "SELECT * FROM gold_security_state WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return load_gold_security_state(
            security,
            envelope,
            configured_silver_schema=SCHEMAS.silver,
            configured_gold_schema=SCHEMAS.gold,
            configured_candidate_schema=SCHEMAS.gold_candidates,
        )


def test_gold_security_table_initialization_is_idempotent():
    with get_connection() as conn:
        init_schema(conn)
        init_schema(conn)
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(gold_security_state)"
            ).fetchall()
        }
        foreign_keys = conn.execute(
            "PRAGMA foreign_key_list(gold_security_state)"
        ).fetchall()
    assert {
        "run_id",
        "review_snapshot_json",
        "review_revision",
        "approval_snapshot_json",
        "approved_revision",
        "source_identities_json",
        "target_identity_json",
    } <= columns
    assert len(foreign_keys) == 1
    assert foreign_keys[0]["table"] == "generated_sql_review"


def test_historical_gold_run_without_companion_fails_closed(trusted_gold):
    run_id = "run_historical"
    _seed_run(run_id, with_security=False)
    response = client.post(
        f"/api/v1/gold/execute/{run_id}",
        json={"overwrite": False},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": router.GOLD_RUN_MALFORMED}


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("selected_sources_json", "{broken"),
        ("model_version", "unsupported"),
        ("policy_version", "unsupported"),
        ("review_revision", "not-a-revision"),
        ("generator_version", ""),
        ("generator_version", "invalid version"),
    ],
)
def test_malformed_or_unsupported_persisted_state_is_rejected(
    column,
    value,
):
    run_id = f"run_malformed_{column}"
    _seed_run(run_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE gold_security_state SET {column} = ? WHERE run_id = ?",
            (value, run_id),
        )
        conn.commit()
    with pytest.raises(GoldStateMalformed):
        _load_state(run_id)


def test_unsupported_persisted_review_snapshot_version_is_rejected():
    run_id = "run_snapshot_version"
    _seed_run(run_id)
    row = _security_row(run_id)
    snapshot = json.loads(row["review_snapshot_json"])
    snapshot["snapshot_version"] = "unsupported"
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE gold_security_state
            SET review_snapshot_json = ?
            WHERE run_id = ?
            """,
            (canonical_json(snapshot), run_id),
        )
        conn.commit()
    with pytest.raises(GoldStateMalformed):
        _load_state(run_id)


def test_duplicate_selected_sources_are_rejected():
    run_id = "run_duplicate_sources"
    _seed_run(run_id)
    duplicate_document = {
        "version": "gold-selected-sources-v1",
        "sources": [
            {"schema": SCHEMAS.silver, "table": "source_a"},
            {"schema": SCHEMAS.silver, "table": "source_a"},
        ],
    }
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE gold_security_state
            SET selected_sources_json = ?
            WHERE run_id = ?
            """,
            (canonical_json(duplicate_document), run_id),
        )
        conn.commit()
    with pytest.raises(GoldStateMalformed):
        _load_state(run_id)


def test_impossible_candidate_and_partial_approval_states_are_rejected():
    run_id = "run_impossible_state"
    _seed_run(run_id)
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE gold_security_state
            SET candidate_schema = target_schema,
                candidate_name = target_name
            WHERE run_id = ?
            """,
            (run_id,),
        )
        conn.commit()
    with pytest.raises(GoldStateMalformed):
        _load_state(run_id)

    run_id = "run_partial_approval"
    _seed_run(run_id)
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE gold_security_state
            SET approved_revision = ?
            WHERE run_id = ?
            """,
            ("a" * 64, run_id),
        )
        conn.commit()
    with pytest.raises(GoldStateMalformed):
        _load_state(run_id)


def test_review_revision_is_deterministic_and_source_order_is_canonical():
    common = {
        "run_id": "run_revision",
        "sql_text": _sql("run_revision"),
        "business_requirement": "Produce the approved output.",
        "generator_provenance": TRUSTED_PROVENANCE,
        "generator_version": GENERATOR_VERSION,
        "target_schema": SCHEMAS.gold,
        "target_name": "approved_output",
        "candidate_schema": SCHEMAS.gold_candidates,
        "candidate_name": "approved_output_candidate_run_revision",
    }
    source_a = {"schema": SCHEMAS.silver, "table": "source_a"}
    source_b = {"schema": SCHEMAS.silver, "table": "source_b"}
    first = build_review_snapshot(
        **common,
        selected_sources=[source_b, source_a],
    )
    second = build_review_snapshot(
        **common,
        selected_sources=[source_a, source_b],
    )
    assert canonical_json(first) == canonical_json(second)
    assert revision_for(first) == revision_for(second)
    assert first["selected_sources"] == [source_a, source_b]


def test_server_candidate_name_rejects_postgres_identifier_truncation():
    with pytest.raises(GoldStateMalformed):
        expected_candidate_name("x" * 50, "run_length")


def test_each_review_sensitive_input_changes_or_invalidates_revision():
    base = {
        "run_id": "run_sensitive",
        "sql_text": _sql("run_sensitive"),
        "business_requirement": "Produce the approved output.",
        "generator_provenance": TRUSTED_PROVENANCE,
        "generator_version": GENERATOR_VERSION,
        "selected_sources": [
            {"schema": SCHEMAS.silver, "table": "source_a"}
        ],
        "target_schema": SCHEMAS.gold,
        "target_name": "approved_output",
        "candidate_schema": SCHEMAS.gold_candidates,
        "candidate_name": "approved_output_candidate_run_sensitive",
    }
    baseline = revision_for(build_review_snapshot(**base))
    changes = [
        {"sql_text": _sql("run_sensitive") + " WHERE 1 = 1"},
        {"business_requirement": "Produce a different output."},
        {
            "selected_sources": [
                {"schema": SCHEMAS.silver, "table": "source_b"}
            ]
        },
        {
            "target_name": "different_output",
            "candidate_name": "different_output_candidate_run_sensitive",
            "sql_text": _sql("run_sensitive", "different_output"),
        },
        {"generator_provenance": "different_gold_generator"},
        {"generator_version": "test-generator-2"},
    ]
    for change in changes:
        changed = {**base, **change}
        assert revision_for(build_review_snapshot(**changed)) != baseline

    with pytest.raises(GoldStateMalformed):
        build_review_snapshot(
            **{**base, "candidate_name": "client_selected_candidate"}
        )
    with pytest.raises(GoldStateMalformed):
        build_review_snapshot(
            **{**base, "model_version": "unsupported"}
        )
    with pytest.raises(GoldStateMalformed):
        build_review_snapshot(
            **{**base, "policy_version": "unsupported"}
        )


def test_each_database_identity_field_changes_approved_revision():
    review = build_review_snapshot(
        run_id="run_approval_sensitivity",
        sql_text=_sql("run_approval_sensitivity"),
        business_requirement="Produce the approved output.",
        generator_provenance=TRUSTED_PROVENANCE,
        generator_version=GENERATOR_VERSION,
        selected_sources=[
            {"schema": SCHEMAS.silver, "table": "source_a"}
        ],
        target_schema=SCHEMAS.gold,
        target_name="approved_output",
        candidate_schema=SCHEMAS.gold_candidates,
        candidate_name=(
            "approved_output_candidate_run_approval_sensitivity"
        ),
    )
    baseline = build_approval_snapshot(
        review_snapshot=review,
        review_revision=revision_for(review),
        database_oid=101,
        database_name="isolated_test_database",
        source_identities=[_source_identity()],
        target_identity=_target_existing(),
        candidate_namespace_identity=_candidate_namespace_identity(),
        overwrite_authorized=True,
    )
    variants = {}

    variants["database_oid"] = deepcopy(baseline)
    variants["database_oid"]["database"]["oid"] = 104
    variants["database_oid"]["source_identities"][0]["database_oid"] = 104
    variants["database_oid"]["target_identity"]["database_oid"] = 104

    variants["namespace_oid"] = deepcopy(baseline)
    variants["namespace_oid"]["source_identities"][0]["namespace_oid"] = 105

    variants["candidate_namespace_oid"] = deepcopy(baseline)
    variants["candidate_namespace_oid"]["candidate_namespace_identity"][
        "namespace_oid"
    ] = 199

    variants["source_relation_oid"] = deepcopy(baseline)
    variants["source_relation_oid"]["source_identities"][0]["relation_oid"] = 206

    variants["relation_kind"] = deepcopy(baseline)
    variants["relation_kind"]["source_identities"][0]["relation_kind"] = "p"

    variants["target_state"] = deepcopy(baseline)
    variants["target_state"]["target_identity"] = _target_absent()
    variants["target_state"]["overwrite_authorized"] = False

    variants["target_relation_oid"] = deepcopy(baseline)
    variants["target_relation_oid"]["target_identity"]["relation_oid"] = 307

    variants["overwrite_authorized"] = deepcopy(baseline)
    variants["overwrite_authorized"]["overwrite_authorized"] = False

    baseline_revision = revision_for(baseline)
    changed_revisions = {
        field: revision_for(snapshot)
        for field, snapshot in variants.items()
    }
    assert all(
        changed != baseline_revision
        for changed in changed_revisions.values()
    )
    assert len(set(changed_revisions.values())) == len(variants)


def test_stale_submitted_review_revision_is_rejected_before_catalog(
    trusted_gold,
    monkeypatch,
):
    record = _seed_run("run_stale_submission")
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: pytest.fail("stale approval must not reach PostgreSQL"),
    )
    response = client.post(
        "/api/v1/gold/approve/run_stale_submission",
        json={"review_revision": "0" * 64, "overwrite": False},
    )
    assert record["review_revision"] != "0" * 64
    assert response.status_code == 409
    assert response.json() == {"detail": router.GOLD_APPROVAL_STALE}


def test_sql_must_create_the_exact_server_controlled_candidate(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_wrong_candidate"
    wrong_sql = (
        f"CREATE TABLE {SCHEMAS.gold_candidates}."
        f"other_output_candidate_{run_id} "
        f"AS SELECT * FROM {SCHEMAS.silver}.source_a"
    )
    record = _seed_run(run_id, sql_text_override=wrong_sql)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: pytest.fail("invalid candidate must not reach PostgreSQL"),
    )
    response = client.post(
        f"/api/v1/gold/approve/{run_id}",
        json={"review_revision": record["review_revision"], "overwrite": False},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": router.GOLD_RUN_MALFORMED}


def test_non_pending_run_cannot_be_approved(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_not_pending"
    record = _seed_run(run_id)
    with get_connection() as conn:
        conn.execute(
            "UPDATE generated_sql_review SET status = 'PROMOTED' WHERE run_id = ?",
            (run_id,),
        )
        conn.commit()
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: pytest.fail("non-pending run must not reach PostgreSQL"),
    )
    response = client.post(
        f"/api/v1/gold/approve/{run_id}",
        json={"review_revision": record["review_revision"], "overwrite": False},
    )
    assert response.status_code == 409
    assert response.json() == {"detail": router.GOLD_STATE_CONFLICT}


def test_production_empty_trust_set_blocks_approval_before_catalog(monkeypatch):
    record = _seed_run("run_production_untrusted")
    monkeypatch.setattr(router, "load_layer_schemas", lambda: SCHEMAS)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: pytest.fail("empty production trust must contain approval"),
    )
    response = client.post(
        "/api/v1/gold/approve/run_production_untrusted",
        json={"review_revision": record["review_revision"], "overwrite": False},
    )
    assert router.GOLD_GENERATOR_TRUST.generation_available is False
    assert response.status_code == 503
    assert response.json() == {"detail": router.GOLD_UNAVAILABLE}


def test_exact_revision_approval_captures_source_and_absent_target(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_approve_absent"
    record = _seed_run(run_id)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: _catalog(),
    )
    response = client.post(
        f"/api/v1/gold/approve/{run_id}",
        json={"review_revision": record["review_revision"], "overwrite": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["target_state"] == "absent"
    assert body["approved_revision"] != body["review_revision"]
    state = _load_state(run_id)
    assert state.source_identities == (_source_identity(),)
    assert state.target_identity == _target_absent()
    assert state.approval_snapshot["database"] == {
        "oid": 101,
        "name": "isolated_test_database",
    }
    assert state.overwrite_authorized is False
    with get_connection() as conn:
        envelope = conn.execute(
            "SELECT status FROM generated_sql_review WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    assert envelope["status"] == "PENDING"


def test_review_is_read_only_and_does_not_imply_approval(trusted_gold):
    run_id = "run_review_only"
    record = _seed_run(run_id)
    response = client.get(f"/api/v1/gold/review/{run_id}")
    assert response.status_code == 200
    assert isinstance(response.json()["sql_text"], str)
    assert response.json()["sql_text"] == json.loads(
        record["review_snapshot_json"]
    )["sql_text"]
    assert response.json()["review_revision"] == record["review_revision"]
    assert response.json()["approved_revision"] is None
    assert _load_state(run_id).approved_revision is None


class _CatalogCursor:
    def __init__(self, *, target_row=None):
        self.target_row = target_row
        self.current = None
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None):
        normalized = " ".join(str(query).split())
        self.queries.append((normalized, params))
        if normalized == (
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
        ):
            self.current = None
        elif "pg_catalog.pg_database" in normalized:
            self.current = (101, "isolated_test_database")
        elif "pg_catalog.pg_namespace" in normalized:
            namespace_oids = {
                (SCHEMAS.silver,): 102,
                (SCHEMAS.gold,): 103,
                (SCHEMAS.gold_candidates,): 104,
            }
            self.current = (namespace_oids[params],)
        elif params == (102, "source_a"):
            self.current = (201, "source_a", "r")
        elif params == (103, "approved_output"):
            self.current = self.target_row
        else:
            raise AssertionError(f"unexpected catalog query: {normalized}, {params}")

    def fetchone(self):
        return self.current


class _CatalogConnection:
    def __init__(self, cursor):
        self.catalog_cursor = cursor
        self.transaction_events = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self):
        return self.catalog_cursor

    def transaction(self):
        connection = self

        class Transaction:
            def __enter__(self):
                connection.transaction_events.append("enter")
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                name = exc_type.__name__ if exc_type else "none"
                connection.transaction_events.append(f"exit:{name}")
                return False

        return Transaction()


class _CatalogPool:
    def __init__(self, cursor):
        self.catalog_connection = _CatalogConnection(cursor)

    def connection(self):
        return self.catalog_connection


@pytest.mark.parametrize(
    ("target_row", "expected_state"),
    [
        (None, "absent"),
        ((301, "approved_output", "p"), "existing"),
    ],
)
def test_catalog_resolver_uses_pg_oids_and_configured_names(
    monkeypatch,
    target_row,
    expected_state,
):
    cursor = _CatalogCursor(target_row=target_row)
    pool = _CatalogPool(cursor)
    monkeypatch.setattr(
        gold_catalog,
        "get_generated_sql_pool",
        lambda: pool,
    )
    result = gold_catalog.resolve_gold_approval_catalog(
        selected_sources=(
            {"schema": SCHEMAS.silver, "table": "source_a"},
        ),
        target={"schema": SCHEMAS.gold, "table": "approved_output"},
        candidate={
            "schema": SCHEMAS.gold_candidates,
            "table": "approved_output_candidate_run_catalog",
        },
    )
    assert result.database_oid == 101
    assert result.database_name == "isolated_test_database"
    assert result.source_identities == (_source_identity(),)
    assert result.target_identity["state"] == expected_state
    assert result.target_identity["namespace_oid"] == 103
    assert result.candidate_namespace_identity == (
        _candidate_namespace_identity()
    )
    assert cursor.queries[0] == (
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
        None,
    )
    assert all(
        "pg_catalog." in query
        for query, _ in cursor.queries[1:]
    )
    assert (SCHEMAS.silver,) in [params for _, params in cursor.queries]
    assert (SCHEMAS.gold,) in [params for _, params in cursor.queries]
    assert (SCHEMAS.gold_candidates,) in [
        params for _, params in cursor.queries
    ]
    assert pool.catalog_connection.transaction_events == [
        "enter",
        "exit:none",
    ]


def test_catalog_transaction_rolls_back_on_resolution_error(monkeypatch):
    class FailingCursor(_CatalogCursor):
        def execute(self, query, params=None):
            normalized = " ".join(str(query).split())
            if "pg_catalog.pg_class" in normalized:
                self.queries.append((normalized, params))
                raise RuntimeError("simulated catalog failure")
            return super().execute(query, params)

    cursor = FailingCursor()
    pool = _CatalogPool(cursor)
    monkeypatch.setattr(
        gold_catalog,
        "get_generated_sql_pool",
        lambda: pool,
    )
    with pytest.raises(RuntimeError, match="simulated catalog failure"):
        gold_catalog.resolve_gold_approval_catalog(
            selected_sources=(
                {"schema": SCHEMAS.silver, "table": "source_a"},
            ),
            target={"schema": SCHEMAS.gold, "table": "approved_output"},
            candidate={
                "schema": SCHEMAS.gold_candidates,
                "table": "approved_output_candidate_run_catalog_failure",
            },
        )
    assert pool.catalog_connection.transaction_events == [
        "enter",
        "exit:RuntimeError",
    ]


def test_approval_rejects_missing_candidate_namespace(monkeypatch):
    class MissingCandidateNamespaceCursor(_CatalogCursor):
        def execute(self, query, params=None):
            super().execute(query, params)
            if (
                "pg_catalog.pg_namespace" in " ".join(str(query).split())
                and params == (SCHEMAS.gold_candidates,)
            ):
                self.current = None

    cursor = MissingCandidateNamespaceCursor()
    monkeypatch.setattr(
        gold_catalog,
        "get_generated_sql_pool",
        lambda: _CatalogPool(cursor),
    )
    with pytest.raises(GoldCatalogResolutionError) as rejected:
        gold_catalog.resolve_gold_approval_catalog(
            selected_sources=(
                {"schema": SCHEMAS.silver, "table": "source_a"},
            ),
            target={"schema": SCHEMAS.gold, "table": "approved_output"},
            candidate={
                "schema": SCHEMAS.gold_candidates,
                "table": "approved_output_candidate_run_missing_namespace",
            },
        )
    assert rejected.value.area == "candidate_namespace"


def test_approval_database_error_is_sanitized(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_database_unavailable"
    record = _seed_run(run_id)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: (_ for _ in ()).throw(
            psycopg.OperationalError("host=secret password=secret")
        ),
    )
    response = client.post(
        f"/api/v1/gold/approve/{run_id}",
        json={"review_revision": record["review_revision"], "overwrite": False},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": router.GOLD_DATABASE_UNAVAILABLE}
    assert "secret" not in response.text


@pytest.mark.parametrize(
    ("area", "status_code", "detail"),
    [
        ("database", 503, router.GOLD_DATABASE_UNAVAILABLE),
        ("source", 409, router.GOLD_SOURCE_IDENTITY_CHANGED),
        ("target", 409, router.GOLD_TARGET_IDENTITY_CHANGED),
        (
            "candidate_namespace",
            409,
            router.GOLD_TARGET_IDENTITY_CHANGED,
        ),
    ],
)
def test_catalog_resolution_errors_are_mapped_by_area(
    trusted_gold,
    monkeypatch,
    area,
    status_code,
    detail,
):
    run_id = f"run_catalog_error_{area}"
    record = _seed_run(run_id)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: (_ for _ in ()).throw(
            GoldCatalogResolutionError(area, "secret catalog detail")
        ),
    )
    response = client.post(
        f"/api/v1/gold/approve/{run_id}",
        json={"review_revision": record["review_revision"], "overwrite": False},
    )
    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert "secret catalog detail" not in response.text


def test_existing_target_requires_and_captures_explicit_overwrite(
    trusted_gold,
    monkeypatch,
):
    denied_run = "run_overwrite_denied"
    denied_record = _seed_run(denied_run)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: _catalog(_target_existing()),
    )
    denied = client.post(
        f"/api/v1/gold/approve/{denied_run}",
        json={
            "review_revision": denied_record["review_revision"],
            "overwrite": False,
        },
    )
    assert denied.status_code == 409
    assert denied.json() == {"detail": router.GOLD_STATE_CONFLICT}
    assert _load_state(denied_run).approved_revision is None

    approved_run = "run_overwrite_approved"
    approved_record = _seed_run(approved_run)
    approved = client.post(
        f"/api/v1/gold/approve/{approved_run}",
        json={
            "review_revision": approved_record["review_revision"],
            "overwrite": True,
        },
    )
    assert approved.status_code == 200
    state = _load_state(approved_run)
    assert state.target_identity == _target_existing()
    assert state.overwrite_authorized is True


def test_overwrite_cannot_be_authorized_for_absent_target(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_absent_overwrite"
    record = _seed_run(run_id)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: _catalog(),
    )
    response = client.post(
        f"/api/v1/gold/approve/{run_id}",
        json={"review_revision": record["review_revision"], "overwrite": True},
    )
    assert response.status_code == 409
    assert response.json() == {"detail": router.GOLD_STATE_CONFLICT}


def test_retry_after_catalog_outage_and_conflict_do_not_reauthorize(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_idempotent_approval"
    record = _seed_run(run_id)
    catalog_calls = {"count": 0}

    def first_catalog(**kwargs):
        catalog_calls["count"] += 1
        if catalog_calls["count"] != 1:
            pytest.fail("persisted approval retry must not reach PostgreSQL")
        return _catalog()

    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        first_catalog,
    )
    payload = {
        "review_revision": record["review_revision"],
        "overwrite": False,
    }
    first = client.post(f"/api/v1/gold/approve/{run_id}", json=payload)
    assert first.status_code == 200
    original_state = _load_state(run_id)
    config_calls = {"count": 0}

    def unavailable_config():
        config_calls["count"] += 1
        pytest.fail(
            "persisted approval retry must not load current layer configuration"
        )

    monkeypatch.setattr(
        router,
        "load_layer_schemas",
        unavailable_config,
    )
    monkeypatch.setattr(
        sql_safety,
        "load_layer_schemas",
        unavailable_config,
        raising=False,
    )
    retry = client.post(f"/api/v1/gold/approve/{run_id}", json=payload)
    conflict = client.post(
        f"/api/v1/gold/approve/{run_id}",
        json={**payload, "overwrite": True},
    )
    stale = client.post(
        f"/api/v1/gold/approve/{run_id}",
        json={**payload, "review_revision": "0" * 64},
    )
    assert first.status_code == retry.status_code == 200
    assert first.json()["status"] == "approved"
    assert retry.json()["status"] == "unchanged"
    assert first.json()["approved_revision"] == retry.json()["approved_revision"]
    assert first.json()["approved_at"] == retry.json()["approved_at"]
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": router.GOLD_STATE_CONFLICT}
    assert stale.status_code == 409
    assert stale.json() == {"detail": router.GOLD_APPROVAL_STALE}
    persisted_state = _load_state(run_id)
    assert persisted_state.approved_revision == original_state.approved_revision
    assert persisted_state.approved_at == original_state.approved_at
    assert persisted_state.source_identities == original_state.source_identities
    assert persisted_state.target_identity == original_state.target_identity
    assert config_calls["count"] == 0
    assert catalog_calls["count"] == 1


def test_retry_ignores_current_layer_config_drift(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_retry_config_drift"
    record = _seed_run(run_id)
    catalog_calls = {"count": 0}

    def first_catalog(**kwargs):
        catalog_calls["count"] += 1
        return _catalog()

    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        first_catalog,
    )
    payload = {
        "review_revision": record["review_revision"],
        "overwrite": False,
    }
    first = client.post(f"/api/v1/gold/approve/{run_id}", json=payload)
    assert first.status_code == 200
    original_state = _load_state(run_id)
    config_calls = {"count": 0}

    def drifted_config():
        config_calls["count"] += 1
        return SimpleNamespace(
            silver="drifted_silver",
            gold="drifted_gold",
            gold_candidates="drifted_gold_candidates",
        )

    monkeypatch.setattr(router, "load_layer_schemas", drifted_config)
    monkeypatch.setattr(
        sql_safety,
        "load_layer_schemas",
        drifted_config,
        raising=False,
    )
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: pytest.fail(
            "persisted approval retry must not resolve current catalog state"
        ),
    )
    retry = client.post(f"/api/v1/gold/approve/{run_id}", json=payload)
    assert retry.status_code == 200
    assert retry.json()["status"] == "unchanged"
    assert retry.json()["approved_revision"] == first.json()["approved_revision"]
    assert retry.json()["approved_at"] == first.json()["approved_at"]
    persisted_state = _load_state(run_id)
    assert persisted_state.source_identities == original_state.source_identities
    assert persisted_state.target_identity == original_state.target_identity
    assert config_calls["count"] == 0
    assert catalog_calls["count"] == 1


def test_malformed_stored_approval_cannot_use_retry_fast_path(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_malformed_retry"
    record = _seed_run(run_id)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: _catalog(),
    )
    payload = {
        "review_revision": record["review_revision"],
        "overwrite": False,
    }
    first = client.post(f"/api/v1/gold/approve/{run_id}", json=payload)
    assert first.status_code == 200
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE gold_security_state
            SET approved_revision = ?
            WHERE run_id = ?
            """,
            ("d" * 64, run_id),
        )
        conn.commit()
    config_calls = {"count": 0}

    def unavailable_config():
        config_calls["count"] += 1
        pytest.fail("malformed retry must fail before current configuration")

    monkeypatch.setattr(
        router,
        "load_layer_schemas",
        unavailable_config,
    )
    monkeypatch.setattr(
        sql_safety,
        "load_layer_schemas",
        unavailable_config,
        raising=False,
    )
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: pytest.fail(
            "malformed retry must not reach PostgreSQL"
        ),
    )
    retry = client.post(f"/api/v1/gold/approve/{run_id}", json=payload)
    assert retry.status_code == 422
    assert retry.json() == {"detail": router.GOLD_RUN_MALFORMED}
    assert config_calls["count"] == 0


def test_retry_ignores_catalog_drift_and_returns_original_approval(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_retry_catalog_drift"
    record = _seed_run(run_id)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: _catalog(),
    )
    payload = {
        "review_revision": record["review_revision"],
        "overwrite": False,
    }
    first = client.post(f"/api/v1/gold/approve/{run_id}", json=payload)
    assert first.status_code == 200

    retry_catalog_calls = {"count": 0}

    def drifted_catalog(**kwargs):
        retry_catalog_calls["count"] += 1
        return GoldCatalogSnapshot(
            database_oid=101,
            database_name="isolated_test_database",
            source_identities=(
                _source_identity(relation_oid=999),
            ),
            target_identity=_target_absent(),
            candidate_namespace_identity=_candidate_namespace_identity(),
        )

    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        drifted_catalog,
    )
    retry = client.post(f"/api/v1/gold/approve/{run_id}", json=payload)
    assert retry.status_code == 200
    assert retry.json()["status"] == "unchanged"
    assert retry.json()["approved_revision"] == first.json()["approved_revision"]
    assert retry.json()["approved_at"] == first.json()["approved_at"]
    assert retry_catalog_calls["count"] == 0
    assert _load_state(run_id).source_identities == (_source_identity(),)


def test_concurrent_identical_approval_is_one_write_plus_idempotent_retry(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_concurrent_approval"
    record = _seed_run(run_id)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: _catalog(),
    )
    payload = {
        "review_revision": record["review_revision"],
        "overwrite": False,
    }

    def approve():
        with TestClient(app) as thread_client:
            return thread_client.post(
                f"/api/v1/gold/approve/{run_id}",
                json=payload,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: approve(), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.json()["status"] for response in responses) == [
        "approved",
        "unchanged",
    ]
    revisions = {response.json()["approved_revision"] for response in responses}
    assert len(revisions) == 1


def test_synchronized_competing_catalog_snapshots_persist_one_authorization(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_synchronized_catalog_snapshots"
    record = _seed_run(run_id)
    snapshots = (
        _catalog(),
        GoldCatalogSnapshot(
            database_oid=101,
            database_name="isolated_test_database",
            source_identities=(
                _source_identity(relation_oid=999),
            ),
            target_identity=_target_absent(),
            candidate_namespace_identity=_candidate_namespace_identity(),
        ),
    )
    real_get_connection = router.get_connection
    begin_barrier = Barrier(2)
    assignment_lock = Lock()
    snapshot_by_thread = {}
    catalog_relation_oids = []

    class BeginBarrierConnection:
        def __init__(self, connection):
            self._connection = connection

        def __enter__(self):
            self._connection.__enter__()
            return self

        def __exit__(self, *args):
            return self._connection.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self._connection, name)

        def execute(self, sql, parameters=()):
            if sql == "BEGIN IMMEDIATE":
                thread_id = get_ident()
                with assignment_lock:
                    if thread_id not in snapshot_by_thread:
                        snapshot_by_thread[thread_id] = snapshots[
                            len(snapshot_by_thread)
                        ]
                begin_barrier.wait(timeout=5)
            return self._connection.execute(sql, parameters)

    def synchronized_get_connection():
        return BeginBarrierConnection(real_get_connection())

    monkeypatch.setattr(
        router,
        "get_connection",
        synchronized_get_connection,
    )

    def competing_catalog(**kwargs):
        snapshot = snapshot_by_thread[get_ident()]
        with assignment_lock:
            catalog_relation_oids.append(
                snapshot.source_identities[0]["relation_oid"]
            )
        return snapshot

    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        competing_catalog,
    )

    def approve():
        with TestClient(app) as thread_client:
            return thread_client.post(
                f"/api/v1/gold/approve/{run_id}",
                json={
                    "review_revision": record["review_revision"],
                    "overwrite": False,
                },
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(approve) for _ in range(2)]
        responses = [future.result() for future in futures]

    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.json()["status"] for response in responses) == [
        "approved",
        "unchanged",
    ]
    assert len(
        {response.json()["approved_revision"] for response in responses}
    ) == 1
    assert len({response.json()["approved_at"] for response in responses}) == 1
    state = _load_state(run_id)
    assert state.approved_revision is not None
    assert state.approved_at is not None
    assert state.overwrite_authorized is False
    assert state.target_identity == _target_absent()
    persisted_relation_oid = state.source_identities[0]["relation_oid"]
    assert persisted_relation_oid in {201, 999}
    assert catalog_relation_oids == [persisted_relation_oid]
    assert {
        snapshot.source_identities[0]["relation_oid"]
        for snapshot in snapshot_by_thread.values()
    } == {201, 999}


def test_security_sensitive_envelope_change_makes_review_stale():
    run_id = "run_envelope_changed"
    _seed_run(run_id)
    with get_connection() as conn:
        conn.execute(
            "UPDATE generated_sql_review SET sql_text = ? WHERE run_id = ?",
            (_sql(run_id) + " WHERE 1 = 1", run_id),
        )
        conn.commit()
    with pytest.raises(GoldStateStale):
        _load_state(run_id)


def test_execute_rejects_missing_and_malformed_approval_before_postgres(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_approval_required"
    _seed_run(run_id)
    monkeypatch.setattr(
        router,
        "get_generated_sql_pool",
        lambda: pytest.fail("contained execute must not reach PostgreSQL"),
    )
    missing = client.post(
        f"/api/v1/gold/execute/{run_id}",
        json={"overwrite": False},
    )
    assert missing.status_code == 409
    assert missing.json() == {"detail": router.GOLD_APPROVAL_REQUIRED}

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE gold_security_state
            SET approved_revision = ?
            WHERE run_id = ?
            """,
            ("b" * 64, run_id),
        )
        conn.commit()
    malformed = client.post(
        f"/api/v1/gold/execute/{run_id}",
        json={"overwrite": False},
    )
    assert malformed.status_code == 422
    assert malformed.json() == {"detail": router.GOLD_RUN_MALFORMED}


def test_valid_approval_hands_candidate_to_promoting_in_batch_45b(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_approved_contained"
    record = _seed_run(run_id)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: _catalog(),
    )
    approved = client.post(
        f"/api/v1/gold/approve/{run_id}",
        json={"review_revision": record["review_revision"], "overwrite": False},
    )
    assert approved.status_code == 200
    monkeypatch.setattr(
        router,
        "execute_gold_candidate",
        lambda state, sql_text: {
            "database_oid": 101,
            "namespace_oid": 104,
            "relation_oid": 401,
            "schema": SCHEMAS.gold_candidates,
            "relation_name": state.candidate["table"],
            "relation_kind": "r",
        },
    )
    execute = client.post(
        f"/api/v1/gold/execute/{run_id}",
        json={"overwrite": False},
    )
    assert execute.status_code == 200
    assert execute.json()["status"] == "PROMOTING"
    with get_connection() as conn:
        envelope = conn.execute(
            "SELECT status FROM generated_sql_review WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        security = conn.execute(
            """
            SELECT execution_claim_id, candidate_identity_json
            FROM gold_security_state
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
    assert envelope["status"] == "PROMOTING"
    assert security["execution_claim_id"].startswith("exec_")
    assert json.loads(security["candidate_identity_json"])["relation_oid"] == 401


def test_malformed_approved_revision_fails_closed(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_malformed_approved"
    record = _seed_run(run_id)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: _catalog(),
    )
    approved = client.post(
        f"/api/v1/gold/approve/{run_id}",
        json={"review_revision": record["review_revision"], "overwrite": False},
    )
    assert approved.status_code == 200
    with get_connection() as conn:
        conn.execute(
            "UPDATE gold_security_state SET approved_revision = ? WHERE run_id = ?",
            ("c" * 64, run_id),
        )
        conn.commit()
    response = client.post(
        f"/api/v1/gold/execute/{run_id}",
        json={"overwrite": False},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": router.GOLD_RUN_MALFORMED}


def _approve_seeded_run(
    monkeypatch,
    run_id: str,
    *,
    target_identity=None,
    overwrite: bool = False,
    sources: tuple[str, ...] = ("source_a",),
    source_identities: tuple[dict, ...] | None = None,
):
    record = _seed_run(run_id, sources=sources)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: _catalog(
            target_identity,
            source_identities=source_identities,
        ),
    )
    response = client.post(
        f"/api/v1/gold/approve/{run_id}",
        json={
            "review_revision": record["review_revision"],
            "overwrite": overwrite,
        },
    )
    assert response.status_code == 200
    return _load_state(run_id)


def _candidate_identity(state, *, relation_oid: int = 401) -> dict:
    return {
        "database_oid": 101,
        "namespace_oid": 104,
        "relation_oid": relation_oid,
        "schema": state.candidate["schema"],
        "relation_name": state.candidate["table"],
        "relation_kind": "r",
    }


def test_two_execute_requests_have_one_claim_and_one_candidate_mutation(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_execute_race"
    state = _approve_seeded_run(monkeypatch, run_id)
    entered = Event()
    release = Event()
    calls = {"count": 0}
    calls_lock = Lock()

    def controlled_execute(claimed_state, sql_text):
        with calls_lock:
            calls["count"] += 1
        entered.set()
        assert release.wait(timeout=5)
        return _candidate_identity(claimed_state)

    monkeypatch.setattr(router, "execute_gold_candidate", controlled_execute)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            client.post,
            f"/api/v1/gold/execute/{run_id}",
            json={"overwrite": False},
        )
        assert entered.wait(timeout=5)
        second = client.post(
            f"/api/v1/gold/execute/{run_id}",
            json={"overwrite": False},
        )
        release.set()
        first = first_future.result(timeout=5)

    assert first.status_code == 200
    assert first.json()["status"] == "PROMOTING"
    assert second.status_code == 409
    assert second.json() == {"detail": router.GOLD_RECONCILIATION_REQUIRED}
    assert calls["count"] == 1
    assert first.json()["candidate"]["table"] == state.candidate["table"]


def test_retry_while_promoting_never_executes_candidate_again(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_execute_promoting_retry"
    state = _approve_seeded_run(monkeypatch, run_id)
    calls = {"count": 0}

    def execute_once(claimed_state, sql_text):
        calls["count"] += 1
        return _candidate_identity(claimed_state)

    monkeypatch.setattr(router, "execute_gold_candidate", execute_once)
    first = client.post(
        f"/api/v1/gold/execute/{run_id}",
        json={"overwrite": False},
    )
    retry = client.post(
        f"/api/v1/gold/execute/{run_id}",
        json={"overwrite": False},
    )
    assert first.status_code == 200
    assert retry.status_code == 409
    assert retry.json() == {"detail": router.GOLD_RECONCILIATION_REQUIRED}
    assert calls["count"] == 1
    assert first.json()["candidate"]["table"] == state.candidate["table"]


@pytest.mark.parametrize(
    ("case", "error", "expected_status", "expected_code"),
    [
        (
            "conflict",
            GoldExecutionRejected(gold_execution.GOLD_CANDIDATE_CONFLICT),
            "EXECUTION_FAILED",
            gold_execution.GOLD_CANDIDATE_CONFLICT,
        ),
        (
            "failed",
            GoldExecutionRejected(gold_execution.GOLD_EXECUTION_FAILED),
            "EXECUTION_FAILED",
            gold_execution.GOLD_EXECUTION_FAILED,
        ),
        (
            "unknown",
            GoldCommitOutcomeUnknown(),
            "EXECUTING",
            router.GOLD_RECONCILIATION_REQUIRED,
        ),
    ],
)
def test_execution_failure_and_commit_ambiguity_persist_honest_state(
    trusted_gold,
    monkeypatch,
    case,
    error,
    expected_status,
    expected_code,
):
    run_id = f"run_exec_{case}"
    _approve_seeded_run(monkeypatch, run_id)

    def fail_execution(state, sql_text):
        raise error

    monkeypatch.setattr(router, "execute_gold_candidate", fail_execution)
    response = client.post(
        f"/api/v1/gold/execute/{run_id}",
        json={"overwrite": False},
    )
    with get_connection() as conn:
        envelope = conn.execute(
            "SELECT status FROM generated_sql_review WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        security = conn.execute(
            """
            SELECT execution_failure_code, candidate_identity_json
            FROM gold_security_state WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
    assert response.status_code in {409, 500}
    assert envelope["status"] == expected_status
    assert security["execution_failure_code"] == expected_code
    assert security["candidate_identity_json"] is None
    loaded = _load_state(run_id)
    assert loaded.execution_failure_code == expected_code
    assert loaded.candidate_identity is None


@pytest.mark.parametrize(
    ("case", "schemas"),
    [
        (
            "silver",
            SimpleNamespace(
                silver="changed_silver",
                gold=SCHEMAS.gold,
                gold_candidates=SCHEMAS.gold_candidates,
            ),
        ),
        (
            "gold",
            SimpleNamespace(
                silver=SCHEMAS.silver,
                gold="changed_gold",
                gold_candidates=SCHEMAS.gold_candidates,
            ),
        ),
        (
            "candidate",
            SimpleNamespace(
                silver=SCHEMAS.silver,
                gold=SCHEMAS.gold,
                gold_candidates="changed_candidates",
            ),
        ),
    ],
)
def test_execute_rejects_current_layer_config_drift_before_candidate_mutation(
    trusted_gold,
    monkeypatch,
    case,
    schemas,
):
    run_id = f"run_cfg_{case}"
    _approve_seeded_run(monkeypatch, run_id)
    monkeypatch.setattr(router, "load_layer_schemas", lambda: schemas)
    monkeypatch.setattr(
        router,
        "execute_gold_candidate",
        lambda *args: pytest.fail("config drift must fail before PostgreSQL"),
    )
    response = client.post(
        f"/api/v1/gold/execute/{run_id}",
        json={"overwrite": False},
    )
    assert response.status_code == 409
    assert response.json() == {"detail": router.GOLD_APPROVAL_STALE}
    with get_connection() as conn:
        status = conn.execute(
            "SELECT status FROM generated_sql_review WHERE run_id = ?",
            (run_id,),
        ).fetchone()["status"]
    assert status == "PENDING"


def test_unsupported_old_execution_policy_fails_before_candidate_mutation(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_old_execution_policy"
    _approve_seeded_run(monkeypatch, run_id)
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE gold_security_state
            SET policy_version = 'gold-approval-policy-v1'
            WHERE run_id = ?
            """,
            (run_id,),
        )
        conn.commit()
    monkeypatch.setattr(
        router,
        "execute_gold_candidate",
        lambda *args: pytest.fail("old policy must fail before PostgreSQL"),
    )
    response = client.post(
        f"/api/v1/gold/execute/{run_id}",
        json={"overwrite": False},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": router.GOLD_RUN_MALFORMED}


def test_uncommitted_v2_approval_without_candidate_namespace_fails_closed(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_old_v2_approval_shape"
    state = _approve_seeded_run(monkeypatch, run_id)
    old_shape = dict(state.approval_snapshot)
    old_shape.pop("candidate_namespace_identity")
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE gold_security_state
            SET approval_snapshot_json = ?,
                approved_revision = ?
            WHERE run_id = ?
            """,
            (
                canonical_json(old_shape),
                revision_for(old_shape),
                run_id,
            ),
        )
        conn.commit()
    monkeypatch.setattr(
        router,
        "load_layer_schemas",
        lambda: pytest.fail("immutable retry must not load current config"),
    )
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: pytest.fail("immutable retry must not query PostgreSQL"),
    )
    response = client.post(
        f"/api/v1/gold/approve/{run_id}",
        json={
            "review_revision": state.review_revision,
            "overwrite": False,
        },
    )
    assert response.status_code == 422
    assert response.json() == {"detail": router.GOLD_RUN_MALFORMED}


class _ExecutionCursor:
    def __init__(self, *, ctas_error=None):
        self.commands = []
        self.ctas_error = ctas_error
        self.current_params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        try:
            rendered = query.as_string(None) if hasattr(query, "as_string") else str(query)
        except Exception:
            rendered = str(query)
        self.commands.append((rendered, params))
        self.current_params = params
        if (
            self.ctas_error is not None
            and isinstance(rendered, str)
            and rendered.startswith("CREATE TABLE")
        ):
            raise self.ctas_error

    def fetchall(self):
        if self.current_params == (SCHEMAS.silver, "source_b"):
            return [("unsupported_col", "money", "pg_catalog", "b", 790)]
        return [("id", "int4", "pg_catalog", "b", 23)]


class _MissingCandidateNamespaceExecutionCursor(_ExecutionCursor):
    def __init__(self):
        super().__init__()
        self.current = None

    def execute(self, query, params=None):
        super().execute(query, params)
        rendered = query.as_string(None) if hasattr(query, "as_string") else query
        normalized = " ".join(str(rendered).split())
        if "pg_catalog.pg_database" in normalized:
            self.current = (101, "isolated_test_database")
        elif "pg_catalog.pg_namespace" in normalized:
            namespace_oids = {
                (SCHEMAS.silver,): 102,
                (SCHEMAS.gold,): 103,
                (SCHEMAS.gold_candidates,): None,
            }
            namespace_oid = namespace_oids[params]
            self.current = (
                (namespace_oid,)
                if namespace_oid is not None
                else None
            )
        elif "pg_catalog.pg_class" in normalized:
            if params == (102, "source_a"):
                self.current = (201, "source_a", "r")
            elif params == (103, "approved_output"):
                self.current = None
            else:
                raise AssertionError(
                    f"unexpected execution catalog query: {normalized}, {params}"
                )
        else:
            self.current = None

    def fetchone(self):
        return self.current


class _ExecutionTransaction:
    def __init__(self, commit_error=None):
        self.commit_error = commit_error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None and self.commit_error is not None:
            raise self.commit_error
        return False


class _ExecutionConnection:
    def __init__(
        self,
        *,
        commit_error=None,
        cleanup_error=None,
        ctas_error=None,
    ):
        self.cursor_instance = _ExecutionCursor(ctas_error=ctas_error)
        self.commit_error = commit_error
        self.cleanup_error = cleanup_error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None and self.cleanup_error is not None:
            raise self.cleanup_error
        return False

    def transaction(self):
        return _ExecutionTransaction(self.commit_error)

    def cursor(self):
        return self.cursor_instance


class _ExecutionPool:
    def __init__(
        self,
        *,
        commit_error=None,
        cleanup_error=None,
        ctas_error=None,
    ):
        self.connection_instance = _ExecutionConnection(
            commit_error=commit_error,
            cleanup_error=cleanup_error,
            ctas_error=ctas_error,
        )

    def connection(self):
        return self.connection_instance


def _live_execution_snapshot(
    state,
    *,
    candidate_identity=None,
    source_identities=None,
):
    assert state.approval_snapshot is not None
    assert state.source_identities is not None
    assert state.target_identity is not None
    assert state.candidate_namespace_identity is not None
    return GoldExecutionCatalogSnapshot(
        database_oid=state.approval_snapshot["database"]["oid"],
        database_name=state.approval_snapshot["database"]["name"],
        source_identities=(
            state.source_identities
            if source_identities is None
            else source_identities
        ),
        target_identity=state.target_identity,
        candidate_namespace_identity=state.candidate_namespace_identity,
        candidate_identity=candidate_identity,
    )


def test_candidate_transaction_uses_safe_search_path_locks_exact_sql_and_oid(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_candidate_transaction"
    state = _approve_seeded_run(monkeypatch, run_id)
    created = _candidate_identity(state)
    snapshots = [
        _live_execution_snapshot(state),
        _live_execution_snapshot(state, candidate_identity=created),
    ]
    monkeypatch.setattr(
        gold_execution,
        "resolve_gold_execution_catalog",
        lambda *args, **kwargs: snapshots.pop(0),
    )
    pool = _ExecutionPool()
    result = gold_execution.execute_gold_candidate(
        state,
        state.review_snapshot["sql_text"],
        pool=pool,
    )
    commands = pool.connection_instance.cursor_instance.commands
    assert result == created
    assert commands[0] == (
        "SELECT pg_catalog.set_config(%s, %s, true)",
        ("search_path", "pg_catalog"),
    )
    assert commands[1] == ("SET LOCAL ROLE aurum_generated_sql", None)
    assert commands[2][0] == (
        'LOCK TABLE "configured_silver"."source_a" IN ACCESS SHARE MODE'
    )
    assert "a.attname" in commands[3][0] or "pg_attribute" in commands[3][0]
    assert commands[4] == (state.review_snapshot["sql_text"], None)
    assert commands[5] == ("RESET ROLE", None)
    assert commands[6] == (
        (
            f'ALTER TABLE "{state.candidate["schema"]}".'
            f'"{state.candidate["table"]}" OWNER TO "aurum_promotion"'
        ),
        None,
    )
    assert commands[7] == (
        (
            f'GRANT SELECT ON "{state.candidate["schema"]}".'
            f'"{state.candidate["table"]}" TO aurum_generated_sql'
        ),
        None,
    )
    assert all(
        "configured_gold.approved_output" not in command
        for command, _ in commands
        if isinstance(command, str)
    )


def test_gold_execution_ignores_unused_approved_source_with_unsupported_type(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_unused_unsupported_source"
    source_identities = (
        _source_identity("source_a", relation_oid=201),
        _source_identity("source_b", relation_oid=202),
    )
    state = _approve_seeded_run(
        monkeypatch,
        run_id,
        sources=("source_a", "source_b"),
        source_identities=source_identities,
    )
    created = _candidate_identity(state)
    snapshots = [
        _live_execution_snapshot(
            state,
            source_identities=(source_identities[0],),
        ),
        _live_execution_snapshot(
            state,
            candidate_identity=created,
            source_identities=(source_identities[0],),
        ),
    ]
    monkeypatch.setattr(
        gold_execution,
        "resolve_gold_execution_catalog",
        lambda *args, **kwargs: snapshots.pop(0),
    )
    pool = _ExecutionPool()

    result = gold_execution.execute_gold_candidate(
        state,
        state.review_snapshot["sql_text"],
        pool=pool,
    )

    assert result == created
    commands = pool.connection_instance.cursor_instance.commands
    assert any(
        '"configured_silver"."source_a"' in command
        for command, _ in commands
    )
    assert all(
        "source_b" not in command
        and params != (SCHEMAS.silver, "source_b")
        for command, params in commands
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda state, live: GoldExecutionCatalogSnapshot(
            database_oid=999,
            database_name=live.database_name,
            source_identities=live.source_identities,
            target_identity=live.target_identity,
            candidate_namespace_identity=live.candidate_namespace_identity,
            candidate_identity=None,
        ),
        lambda state, live: GoldExecutionCatalogSnapshot(
            database_oid=live.database_oid,
            database_name=live.database_name,
            source_identities=(
                {**live.source_identities[0], "relation_oid": 999},
            ),
            target_identity=live.target_identity,
            candidate_namespace_identity=live.candidate_namespace_identity,
            candidate_identity=None,
        ),
        lambda state, live: GoldExecutionCatalogSnapshot(
            database_oid=live.database_oid,
            database_name=live.database_name,
            source_identities=(
                {**live.source_identities[0], "relation_kind": "p"},
            ),
            target_identity=live.target_identity,
            candidate_namespace_identity=live.candidate_namespace_identity,
            candidate_identity=None,
        ),
    ],
)
def test_execution_rejects_database_or_source_identity_drift(
    trusted_gold,
    monkeypatch,
    mutate,
):
    run_id = f"run_identity_drift_{id(mutate)}"
    state = _approve_seeded_run(monkeypatch, run_id)
    live = mutate(state, _live_execution_snapshot(state))
    monkeypatch.setattr(
        gold_execution,
        "resolve_gold_execution_catalog",
        lambda *args, **kwargs: live,
    )
    pool = _ExecutionPool()
    with pytest.raises(GoldExecutionRejected) as rejected:
        gold_execution.execute_gold_candidate(
            state,
            state.review_snapshot["sql_text"],
            pool=pool,
        )
    assert rejected.value.code == gold_execution.GOLD_SOURCE_IDENTITY_CHANGED
    assert state.review_snapshot["sql_text"] not in {
        command for command, _ in pool.connection_instance.cursor_instance.commands
    }


def test_execution_rejects_replaced_candidate_namespace_before_ctas(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_replaced_candidate_namespace"
    state = _approve_seeded_run(monkeypatch, run_id)
    live = GoldExecutionCatalogSnapshot(
        database_oid=state.approval_snapshot["database"]["oid"],
        database_name=state.approval_snapshot["database"]["name"],
        source_identities=state.source_identities,
        target_identity=state.target_identity,
        candidate_namespace_identity={
            **state.candidate_namespace_identity,
            "namespace_oid": 999,
        },
        candidate_identity=None,
    )

    monkeypatch.setattr(
        gold_execution,
        "resolve_gold_execution_catalog",
        lambda *args, **kwargs: live,
    )
    pool = _ExecutionPool()
    with pytest.raises(GoldExecutionRejected) as rejected:
        gold_execution.execute_gold_candidate(
            state,
            state.review_snapshot["sql_text"],
            pool=pool,
        )
    assert rejected.value.code == gold_execution.GOLD_TARGET_IDENTITY_CHANGED
    assert state.review_snapshot["sql_text"] not in {
        command for command, _ in pool.connection_instance.cursor_instance.commands
    }


def test_missing_candidate_namespace_uses_real_resolver_and_public_drift_code(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_missing_candidate_namespace"
    state = _approve_seeded_run(monkeypatch, run_id)
    direct_cursor = _MissingCandidateNamespaceExecutionCursor()
    with pytest.raises(GoldCatalogResolutionError) as unresolved:
        gold_catalog.resolve_gold_execution_catalog(
            direct_cursor,
            selected_sources=state.selected_sources,
            target=state.target,
            candidate=state.candidate,
        )
    assert unresolved.value.area == "candidate_namespace"

    pool = _ExecutionPool()
    execution_cursor = _MissingCandidateNamespaceExecutionCursor()
    pool.connection_instance.cursor_instance = execution_cursor
    monkeypatch.setattr(
        router,
        "execute_gold_candidate",
        lambda claimed_state, sql_text: gold_execution.execute_gold_candidate(
            claimed_state,
            sql_text,
            pool=pool,
        ),
    )

    response = client.post(
        f"/api/v1/gold/execute/{run_id}",
        json={"overwrite": False},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": gold_execution.GOLD_TARGET_IDENTITY_CHANGED
    }
    assert not any(
        isinstance(command, str) and command.startswith("CREATE TABLE")
        for command, _ in execution_cursor.commands
    )
    with get_connection() as conn:
        persisted = conn.execute(
            """
            SELECT run.status,
                   security.execution_failure_code,
                   security.candidate_identity_json
            FROM generated_sql_review AS run
            JOIN gold_security_state AS security USING (run_id)
            WHERE run.run_id = ?
            """,
            (run_id,),
        ).fetchone()
    assert tuple(persisted) == (
        "EXECUTION_FAILED",
        gold_execution.GOLD_TARGET_IDENTITY_CHANGED,
        None,
    )


@pytest.mark.parametrize(
    "target_identity",
    [
        {
            "state": "existing",
            "database_oid": 101,
            "namespace_oid": 103,
            "relation_oid": 999,
            "schema": SCHEMAS.gold,
            "relation_name": "approved_output",
            "relation_kind": "r",
        },
        {
            "state": "absent",
            "database_oid": 101,
            "namespace_oid": 999,
            "schema": SCHEMAS.gold,
            "relation_name": "approved_output",
        },
    ],
)
def test_execution_rejects_target_identity_drift(
    trusted_gold,
    monkeypatch,
    target_identity,
):
    run_id = f"run_target_drift_{target_identity['namespace_oid']}"
    state = _approve_seeded_run(monkeypatch, run_id)
    live = _live_execution_snapshot(state)
    changed = GoldExecutionCatalogSnapshot(
        database_oid=live.database_oid,
        database_name=live.database_name,
        source_identities=live.source_identities,
        target_identity=target_identity,
        candidate_namespace_identity=live.candidate_namespace_identity,
        candidate_identity=None,
    )
    monkeypatch.setattr(
        gold_execution,
        "resolve_gold_execution_catalog",
        lambda *args, **kwargs: changed,
    )
    with pytest.raises(GoldExecutionRejected) as rejected:
        gold_execution.execute_gold_candidate(
            state,
            state.review_snapshot["sql_text"],
            pool=_ExecutionPool(),
        )
    assert rejected.value.code == gold_execution.GOLD_TARGET_IDENTITY_CHANGED


@pytest.mark.parametrize(
    "changed_target",
    [
        _target_absent(),
        {**_target_existing(), "relation_oid": 999},
        {**_target_existing(), "relation_kind": "r"},
    ],
)
def test_execution_rejects_existing_target_disappearance_or_replacement(
    trusted_gold,
    monkeypatch,
    changed_target,
):
    run_id = f"run_target_existing_{changed_target['state']}_{changed_target.get('relation_oid', 0)}"
    state = _approve_seeded_run(
        monkeypatch,
        run_id,
        target_identity=_target_existing(),
        overwrite=True,
    )
    live = _live_execution_snapshot(state)
    changed = GoldExecutionCatalogSnapshot(
        database_oid=live.database_oid,
        database_name=live.database_name,
        source_identities=live.source_identities,
        target_identity=changed_target,
        candidate_namespace_identity=live.candidate_namespace_identity,
        candidate_identity=None,
    )
    monkeypatch.setattr(
        gold_execution,
        "resolve_gold_execution_catalog",
        lambda *args, **kwargs: changed,
    )
    with pytest.raises(GoldExecutionRejected) as rejected:
        gold_execution.execute_gold_candidate(
            state,
            state.review_snapshot["sql_text"],
            pool=_ExecutionPool(),
        )
    assert rejected.value.code == gold_execution.GOLD_TARGET_IDENTITY_CHANGED


def test_candidate_conflict_fails_closed_without_ctas(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_candidate_conflict"
    state = _approve_seeded_run(monkeypatch, run_id)
    existing = _candidate_identity(state, relation_oid=777)
    live = _live_execution_snapshot(state, candidate_identity=existing)
    monkeypatch.setattr(
        gold_execution,
        "resolve_gold_execution_catalog",
        lambda *args, **kwargs: live,
    )
    pool = _ExecutionPool()
    with pytest.raises(GoldExecutionRejected) as rejected:
        gold_execution.execute_gold_candidate(
            state,
            state.review_snapshot["sql_text"],
            pool=pool,
        )
    assert rejected.value.code == gold_execution.GOLD_CANDIDATE_CONFLICT
    assert state.review_snapshot["sql_text"] not in {
        command for command, _ in pool.connection_instance.cursor_instance.commands
    }


def test_missing_source_is_sanitized_and_fails_before_ctas(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_missing_source"
    state = _approve_seeded_run(monkeypatch, run_id)

    def missing_source(*args, **kwargs):
        raise GoldCatalogResolutionError("source", "raw catalog detail")

    monkeypatch.setattr(
        gold_execution,
        "resolve_gold_execution_catalog",
        missing_source,
    )
    pool = _ExecutionPool()
    with pytest.raises(GoldExecutionRejected) as rejected:
        gold_execution.execute_gold_candidate(
            state,
            state.review_snapshot["sql_text"],
            pool=pool,
        )
    assert rejected.value.code == gold_execution.GOLD_SOURCE_IDENTITY_CHANGED
    assert "raw catalog detail" not in str(rejected.value)
    assert state.review_snapshot["sql_text"] not in {
        command for command, _ in pool.connection_instance.cursor_instance.commands
    }


def test_wrong_candidate_identity_after_ctas_rolls_back_as_known_failure(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_wrong_candidate"
    state = _approve_seeded_run(monkeypatch, run_id)
    wrong = {
        **_candidate_identity(state),
        "relation_name": "different_candidate",
    }
    snapshots = [
        _live_execution_snapshot(state),
        _live_execution_snapshot(state, candidate_identity=wrong),
    ]
    monkeypatch.setattr(
        gold_execution,
        "resolve_gold_execution_catalog",
        lambda *args, **kwargs: snapshots.pop(0),
    )
    with pytest.raises(GoldExecutionRejected) as rejected:
        gold_execution.execute_gold_candidate(
            state,
            state.review_snapshot["sql_text"],
            pool=_ExecutionPool(),
        )
    assert rejected.value.code == gold_execution.GOLD_EXECUTION_FAILED


def test_lost_commit_acknowledgement_is_reported_as_unknown(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_lost_commit_ack"
    state = _approve_seeded_run(monkeypatch, run_id)
    created = _candidate_identity(state)
    snapshots = [
        _live_execution_snapshot(state),
        _live_execution_snapshot(state, candidate_identity=created),
    ]
    monkeypatch.setattr(
        gold_execution,
        "resolve_gold_execution_catalog",
        lambda *args, **kwargs: snapshots.pop(0),
    )
    pool = _ExecutionPool(commit_error=psycopg.OperationalError("lost ack"))
    with pytest.raises(GoldCommitOutcomeUnknown):
        gold_execution.execute_gold_candidate(
            state,
            state.review_snapshot["sql_text"],
            pool=pool,
        )


def test_generic_commit_error_is_reported_as_unknown(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_generic_commit_error"
    state = _approve_seeded_run(monkeypatch, run_id)
    created = _candidate_identity(state)
    snapshots = [
        _live_execution_snapshot(state),
        _live_execution_snapshot(state, candidate_identity=created),
    ]
    monkeypatch.setattr(
        gold_execution,
        "resolve_gold_execution_catalog",
        lambda *args, **kwargs: snapshots.pop(0),
    )
    with pytest.raises(GoldCommitOutcomeUnknown):
        gold_execution.execute_gold_candidate(
            state,
            state.review_snapshot["sql_text"],
            pool=_ExecutionPool(commit_error=RuntimeError("commit ack lost")),
        )


def test_ctas_statement_error_is_known_rollback(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_ctas_statement_error"
    state = _approve_seeded_run(monkeypatch, run_id)
    monkeypatch.setattr(
        gold_execution,
        "resolve_gold_execution_catalog",
        lambda *args, **kwargs: _live_execution_snapshot(state),
    )
    with pytest.raises(GoldExecutionRejected) as rejected:
        gold_execution.execute_gold_candidate(
            state,
            state.review_snapshot["sql_text"],
            pool=_ExecutionPool(ctas_error=RuntimeError("statement failed")),
        )
    assert rejected.value.code == gold_execution.GOLD_EXECUTION_FAILED


def test_acknowledged_commit_survives_generic_pool_cleanup_error(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_post_commit_pool_cleanup"
    state = _approve_seeded_run(monkeypatch, run_id)
    created = _candidate_identity(state)
    snapshots = [
        _live_execution_snapshot(state),
        _live_execution_snapshot(state, candidate_identity=created),
    ]
    monkeypatch.setattr(
        gold_execution,
        "resolve_gold_execution_catalog",
        lambda *args, **kwargs: snapshots.pop(0),
    )
    result = gold_execution.execute_gold_candidate(
        state,
        state.review_snapshot["sql_text"],
        pool=_ExecutionPool(
            cleanup_error=RuntimeError("pool return failed after commit")
        ),
    )
    assert result == created


def test_post_commit_sqlite_handoff_failure_requires_reconciliation_and_no_retry(
    trusted_gold,
    monkeypatch,
):
    run_id = "run_post_commit_sqlite_handoff"
    _approve_seeded_run(monkeypatch, run_id)
    executor_calls = {"count": 0}

    def committed_candidate(state, sql_text):
        executor_calls["count"] += 1
        return _candidate_identity(state)

    monkeypatch.setattr(router, "execute_gold_candidate", committed_candidate)
    real_get_connection = router.get_connection
    connection_calls = {"count": 0}

    def fail_handoff_connection():
        connection_calls["count"] += 1
        if connection_calls["count"] == 2:
            raise RuntimeError("isolated SQLite handoff failure")
        return real_get_connection()

    monkeypatch.setattr(router, "get_connection", fail_handoff_connection)
    first = client.post(
        f"/api/v1/gold/execute/{run_id}",
        json={"overwrite": False},
    )
    monkeypatch.setattr(router, "get_connection", real_get_connection)
    retry = client.post(
        f"/api/v1/gold/execute/{run_id}",
        json={"overwrite": False},
    )
    assert first.status_code == 409
    assert first.json() == {"detail": router.GOLD_RECONCILIATION_REQUIRED}
    assert retry.status_code == 409
    assert retry.json() == {"detail": router.GOLD_RECONCILIATION_REQUIRED}
    assert executor_calls["count"] == 1
    with get_connection() as conn:
        persisted = conn.execute(
            """
            SELECT run.status,
                   security.execution_failure_code,
                   security.candidate_identity_json
            FROM generated_sql_review AS run
            JOIN gold_security_state AS security USING (run_id)
            WHERE run.run_id = ?
            """,
            (run_id,),
        ).fetchone()
    assert tuple(persisted) == (
        "EXECUTING",
        router.GOLD_RECONCILIATION_REQUIRED,
        None,
    )


def test_source_lock_order_and_identifier_quoting_are_deterministic():
    first = _ExecutionCursor()
    second = _ExecutionCursor()
    sources = (
        {"schema": "tenant_schema", "table": "z_table"},
        {"schema": "tenant_schema", "table": "A_table"},
    )
    lock_gold_sources(first, sources)
    lock_gold_sources(second, tuple(reversed(sources)))
    expected = [
        'LOCK TABLE "tenant_schema"."A_table" IN ACCESS SHARE MODE',
        'LOCK TABLE "tenant_schema"."z_table" IN ACCESS SHARE MODE',
    ]
    assert [command for command, _ in first.commands] == expected
    assert [command for command, _ in second.commands] == expected
