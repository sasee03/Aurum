"""Focused API/state-machine proof for Batch 4.5C promotion."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api.silver_gold_router as router
from api.main import app
from src.app_state.db import get_connection, init_schema
from src.generator_trust import GeneratorTrustPolicy
from src.gold_promotion import (
    GoldPromotionOutcomeUnknown,
    GoldPromotionReconciliation,
    GoldPromotionRejected,
    GoldPromotionResult,
)
from src.gold_security import (
    build_approval_snapshot,
    canonical_json,
    insert_gold_security_state,
    load_persisted_gold_security_state,
    new_gold_security_record,
    promotion_backup_name,
    revision_for,
)


client = TestClient(app)
TRUSTED_PROVENANCE = "gold_promotion_test_hardened"
SCHEMAS = SimpleNamespace(
    silver="configured_silver",
    gold="configured_gold",
    gold_candidates="configured_gold_candidates",
)


def _relation(
    schema: str,
    name: str,
    relation_oid: int,
    namespace_oid: int,
) -> dict:
    return {
        "database_oid": 101,
        "namespace_oid": namespace_oid,
        "relation_oid": relation_oid,
        "schema": schema,
        "relation_name": name,
        "relation_kind": "r",
    }


def _seed_promoting(
    run_id: str,
    *,
    existing_target: bool = False,
) -> dict:
    target_name = "approved_output"
    candidate_name = f"{target_name}_candidate_{run_id}"
    sql_text = (
        f"CREATE TABLE {SCHEMAS.gold_candidates}.{candidate_name} "
        f"AS SELECT * FROM {SCHEMAS.silver}.source_a"
    )
    record = new_gold_security_record(
        run_id=run_id,
        sql_text=sql_text,
        business_requirement="Produce one approved output.",
        generator_provenance=TRUSTED_PROVENANCE,
        generator_version="promotion-test-1",
        selected_sources=[
            {"schema": SCHEMAS.silver, "table": "source_a"}
        ],
        target_schema=SCHEMAS.gold,
        target_name=target_name,
        candidate_schema=SCHEMAS.gold_candidates,
    )
    source_identity = _relation(
        SCHEMAS.silver,
        "source_a",
        201,
        102,
    )
    target_identity = {
        "state": "absent",
        "database_oid": 101,
        "namespace_oid": 103,
        "schema": SCHEMAS.gold,
        "relation_name": target_name,
    }
    if existing_target:
        target_identity = {
            "state": "existing",
            **_relation(SCHEMAS.gold, target_name, 301, 103),
        }
    candidate_namespace = {
        "database_oid": 101,
        "namespace_oid": 104,
        "schema": SCHEMAS.gold_candidates,
    }
    review_snapshot = json.loads(record["review_snapshot_json"])
    approval_snapshot = build_approval_snapshot(
        review_snapshot=review_snapshot,
        review_revision=record["review_revision"],
        database_oid=101,
        database_name="isolated_promotion_database",
        source_identities=[source_identity],
        target_identity=target_identity,
        candidate_namespace_identity=candidate_namespace,
        overwrite_authorized=existing_target,
    )
    candidate_identity = _relation(
        SCHEMAS.gold_candidates,
        candidate_name,
        401,
        104,
    )
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review (
                run_id, table_name, sql_text, planned_changes_json,
                created_at, status, candidate_schema, generator_provenance
            )
            VALUES (?, ?, ?, ?, ?, 'PROMOTING', ?, ?)
            """,
            (
                run_id,
                target_name,
                sql_text,
                canonical_json({"summary": "promotion test"}),
                "2026-07-24T00:00:00+00:00",
                SCHEMAS.gold_candidates,
                TRUSTED_PROVENANCE,
            ),
        )
        insert_gold_security_state(conn, record)
        conn.execute(
            """
            UPDATE gold_security_state
            SET approval_snapshot_json = ?,
                approved_revision = ?,
                approved_at = ?,
                overwrite_authorized = ?,
                source_identities_json = ?,
                target_identity_json = ?,
                execution_claim_id = ?,
                execution_claimed_at = ?,
                candidate_identity_json = ?
            WHERE run_id = ?
            """,
            (
                canonical_json(approval_snapshot),
                revision_for(approval_snapshot),
                "2026-07-24T00:01:00+00:00",
                int(existing_target),
                canonical_json([source_identity]),
                canonical_json(target_identity),
                "exec_123",
                "2026-07-24T00:02:00+00:00",
                canonical_json(candidate_identity),
                run_id,
            ),
        )
        conn.commit()
    return {
        "candidate": candidate_identity,
        "target_identity": target_identity,
        "final": {
            **candidate_identity,
            "namespace_oid": 103,
            "schema": SCHEMAS.gold,
            "relation_name": target_name,
        },
    }


@pytest.fixture
def trusted_gold_promotion(monkeypatch):
    monkeypatch.setattr(
        router,
        "GOLD_GENERATOR_TRUST",
        GeneratorTrustPolicy(
            pipeline="gold",
            trusted_hardened_provenances=frozenset({TRUSTED_PROVENANCE}),
        ),
    )


def _persisted(run_id: str):
    with get_connection() as conn:
        envelope = conn.execute(
            "SELECT * FROM generated_sql_review WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        security = conn.execute(
            "SELECT * FROM gold_security_state WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return envelope, load_persisted_gold_security_state(
            security,
            envelope,
        )


def test_promotion_schema_migration_is_idempotent():
    with get_connection() as conn:
        init_schema(conn)
        init_schema(conn)
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(gold_security_state)"
            )
        }
    assert {
        "promotion_claim_id",
        "promotion_claimed_at",
        "promotion_failure_code",
        "promoted_target_identity_json",
        "backup_identity_json",
        "backup_cleanup_eligible",
        "promotion_committed_at",
    } <= columns


def test_promote_api_claims_once_persists_exact_target_and_is_idempotent(
    trusted_gold_promotion,
    monkeypatch,
):
    run_id = "run_promote_success"
    identities = _seed_promoting(run_id)
    calls = {"count": 0}

    def committed(state):
        calls["count"] += 1
        return GoldPromotionResult(identities["final"], None)

    monkeypatch.setattr(router, "promote_gold_candidate", committed)
    first = client.post(f"/api/v1/gold/promote/{run_id}")
    retry = client.post(f"/api/v1/gold/promote/{run_id}")

    assert first.status_code == retry.status_code == 200
    assert first.json()["status"] == retry.json()["status"] == "PROMOTED"
    assert first.json()["target"]["relation_oid"] == 401
    assert calls["count"] == 1
    envelope, state = _persisted(run_id)
    assert envelope["status"] == "PROMOTED"
    assert state.promoted_target_identity == identities["final"]
    assert state.promotion_claim_id.startswith("promo_")
    assert state.promotion_failure_code is None


def test_overwrite_persists_exact_backup_identity_and_never_deletes_it(
    trusted_gold_promotion,
    monkeypatch,
):
    run_id = "run_promote_overwrite"
    identities = _seed_promoting(run_id, existing_target=True)

    def committed(state):
        backup = _relation(
            SCHEMAS.gold,
            promotion_backup_name(
                "approved_output",
                state.promotion_claim_id,
            ),
            301,
            103,
        )
        return GoldPromotionResult(identities["final"], backup)

    monkeypatch.setattr(router, "promote_gold_candidate", committed)
    response = client.post(f"/api/v1/gold/promote/{run_id}")

    assert response.status_code == 200
    assert response.json()["backup"]["relation_oid"] == 301
    envelope, state = _persisted(run_id)
    assert envelope["status"] == "PROMOTED"
    assert state.backup_identity["relation_oid"] == 301
    assert state.backup_cleanup_eligible is False
    assert state.backup_identity["relation_name"].startswith(
        "approved_output__aurum_backup_"
    )


def test_deterministic_promotion_failure_is_terminal_and_never_retried(
    trusted_gold_promotion,
    monkeypatch,
):
    run_id = "run_promote_target_changed"
    _seed_promoting(run_id)
    calls = {"count": 0}

    def rejected(state):
        calls["count"] += 1
        raise GoldPromotionRejected(
            router.GOLD_TARGET_IDENTITY_CHANGED
        )

    monkeypatch.setattr(router, "promote_gold_candidate", rejected)
    first = client.post(f"/api/v1/gold/promote/{run_id}")
    retry = client.post(f"/api/v1/gold/promote/{run_id}")

    assert first.status_code == retry.status_code == 409
    assert first.json() == retry.json() == {
        "detail": router.GOLD_TARGET_IDENTITY_CHANGED
    }
    assert calls["count"] == 1
    envelope, state = _persisted(run_id)
    assert envelope["status"] == "PROMOTION_FAILED"
    assert (
        state.promotion_failure_code
        == router.GOLD_TARGET_IDENTITY_CHANGED
    )
    assert state.promoted_target_identity is None


def test_ambiguous_commit_reconciles_by_oid_without_second_mutation(
    trusted_gold_promotion,
    monkeypatch,
):
    run_id = "run_promote_ambiguous"
    identities = _seed_promoting(run_id)
    calls = {"count": 0}

    def unknown(state):
        calls["count"] += 1
        raise GoldPromotionOutcomeUnknown(
            GoldPromotionResult(identities["final"], None)
        )

    monkeypatch.setattr(router, "promote_gold_candidate", unknown)
    first = client.post(f"/api/v1/gold/promote/{run_id}")
    assert first.status_code == 409
    assert first.json() == {"detail": router.GOLD_PROMOTION_AMBIGUOUS}
    envelope, state = _persisted(run_id)
    assert envelope["status"] == "AMBIGUOUS_PROMOTION"
    assert state.promoted_target_identity is None

    monkeypatch.setattr(
        router,
        "reconcile_gold_promotion",
        lambda state: GoldPromotionReconciliation(
            "promoted",
            final_target_identity=identities["final"],
        ),
    )
    retry = client.post(f"/api/v1/gold/promote/{run_id}")
    assert retry.status_code == 200
    assert retry.json()["status"] == "PROMOTED"
    assert calls["count"] == 1


def test_postgres_commit_then_sqlite_failure_reconciles_without_second_mutation(
    trusted_gold_promotion,
    monkeypatch,
):
    run_id = "run_promote_sqlite_window"
    identities = _seed_promoting(run_id)
    calls = {"count": 0}

    def committed(state):
        calls["count"] += 1
        return GoldPromotionResult(identities["final"], None)

    real_persist = router._persist_gold_promoted
    persist_calls = {"count": 0}

    def fail_first_persistence(*args, **kwargs):
        persist_calls["count"] += 1
        if persist_calls["count"] == 1:
            return False
        return real_persist(*args, **kwargs)

    monkeypatch.setattr(router, "promote_gold_candidate", committed)
    monkeypatch.setattr(
        router,
        "_persist_gold_promoted",
        fail_first_persistence,
    )
    first = client.post(f"/api/v1/gold/promote/{run_id}")
    assert first.status_code == 409
    assert first.json() == {
        "detail": router.GOLD_PROMOTION_RECONCILIATION_REQUIRED
    }
    envelope, state = _persisted(run_id)
    assert envelope["status"] == "AMBIGUOUS_PROMOTION"
    assert state.promoted_target_identity is None

    monkeypatch.setattr(
        router,
        "reconcile_gold_promotion",
        lambda state: GoldPromotionReconciliation(
            "promoted",
            final_target_identity=identities["final"],
        ),
    )
    retry = client.post(f"/api/v1/gold/promote/{run_id}")
    assert retry.status_code == 200
    assert retry.json()["status"] == "PROMOTED"
    assert calls["count"] == 1


def test_two_same_run_requests_share_one_mutation_claim(
    trusted_gold_promotion,
    monkeypatch,
):
    run_id = "run_promote_race"
    identities = _seed_promoting(run_id)
    mutation_entered = Event()
    reconciliation_entered = Event()
    release = Event()
    calls = {"count": 0}
    calls_lock = Lock()

    def controlled_mutation(state):
        with calls_lock:
            calls["count"] += 1
        mutation_entered.set()
        assert release.wait(timeout=5)
        return GoldPromotionResult(identities["final"], None)

    def controlled_reconciliation(state):
        reconciliation_entered.set()
        assert release.wait(timeout=5)
        return GoldPromotionReconciliation(
            "promoted",
            final_target_identity=identities["final"],
        )

    monkeypatch.setattr(
        router,
        "promote_gold_candidate",
        controlled_mutation,
    )
    monkeypatch.setattr(
        router,
        "reconcile_gold_promotion",
        controlled_reconciliation,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            client.post,
            f"/api/v1/gold/promote/{run_id}",
        )
        assert mutation_entered.wait(timeout=5)
        second_future = executor.submit(
            client.post,
            f"/api/v1/gold/promote/{run_id}",
        )
        assert reconciliation_entered.wait(timeout=5)
        release.set()
        first = first_future.result(timeout=5)
        second = second_future.result(timeout=5)

    assert first.status_code == second.status_code == 200
    assert calls["count"] == 1
    envelope, state = _persisted(run_id)
    assert envelope["status"] == "PROMOTED"
    assert state.promoted_target_identity["relation_oid"] == 401


def test_malformed_promoted_state_fails_closed_before_postgres(
    trusted_gold_promotion,
    monkeypatch,
):
    run_id = "run_promote_malformed"
    _seed_promoting(run_id)
    with get_connection() as conn:
        conn.execute(
            "UPDATE generated_sql_review SET status = 'PROMOTED' "
            "WHERE run_id = ?",
            (run_id,),
        )
        conn.commit()
    monkeypatch.setattr(
        router,
        "promote_gold_candidate",
        lambda state: pytest.fail("malformed state must not mutate PostgreSQL"),
    )
    response = client.post(f"/api/v1/gold/promote/{run_id}")
    assert response.status_code == 422
    assert response.json() == {"detail": router.GOLD_RUN_MALFORMED}


@pytest.mark.parametrize(
    ("status", "candidate_sql", "failure_code"),
    [
        ("PENDING", "candidate_identity_json = NULL", None),
        ("EXECUTING", "candidate_identity_json = NULL", None),
        (
            "EXECUTION_FAILED",
            "candidate_identity_json = NULL",
            "GOLD_EXECUTION_FAILED",
        ),
    ],
)
def test_non_promoting_lifecycle_states_cannot_promote(
    trusted_gold_promotion,
    monkeypatch,
    status,
    candidate_sql,
    failure_code,
):
    run_id = f"run_no_promote_{status.lower()}"
    _seed_promoting(run_id)
    with get_connection() as conn:
        conn.execute(
            "UPDATE generated_sql_review SET status = ? WHERE run_id = ?",
            (status, run_id),
        )
        if status == "PENDING":
            conn.execute(
                """
                UPDATE gold_security_state
                SET execution_claim_id = NULL,
                    execution_claimed_at = NULL,
                    candidate_identity_json = NULL,
                    execution_failure_code = NULL
                WHERE run_id = ?
                """,
                (run_id,),
            )
        else:
            conn.execute(
                f"""
                UPDATE gold_security_state
                SET {candidate_sql},
                    execution_failure_code = ?
                WHERE run_id = ?
                """,
                (failure_code, run_id),
            )
        conn.commit()
    monkeypatch.setattr(
        router,
        "promote_gold_candidate",
        lambda state: pytest.fail("invalid lifecycle must not mutate PostgreSQL"),
    )
    response = client.post(f"/api/v1/gold/promote/{run_id}")
    assert response.status_code == 409
    assert response.json() == {"detail": router.GOLD_STATE_CONFLICT}


def test_partial_promotion_claim_metadata_fails_closed(
    trusted_gold_promotion,
    monkeypatch,
):
    run_id = "run_partial_promotion_claim"
    _seed_promoting(run_id)
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE gold_security_state
            SET promotion_claim_id = 'promo_partial'
            WHERE run_id = ?
            """,
            (run_id,),
        )
        conn.commit()
    monkeypatch.setattr(
        router,
        "promote_gold_candidate",
        lambda state: pytest.fail("partial claim must not mutate PostgreSQL"),
    )
    response = client.post(f"/api/v1/gold/promote/{run_id}")
    assert response.status_code == 422
    assert response.json() == {"detail": router.GOLD_RUN_MALFORMED}
