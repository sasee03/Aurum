import json
import uuid

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql

from api.main import app
from src.app_state.db import get_connection
from src.db_config import (
    LayerSchemas,
    apply_role_setup,
    postgres_conninfo,
)
from src.gold_promotion import promotion_backup_name
from src.gold_security import (
    build_approval_snapshot,
    canonical_json,
    insert_gold_security_state,
    new_gold_security_record,
    revision_for,
)


def _relation_identity(cursor, schema_name, relation_name):
    cursor.execute(
        """
        SELECT database.oid,
               namespace.oid,
               relation.oid,
               namespace.nspname,
               relation.relname,
               relation.relkind
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_database AS database
          ON database.datname = pg_catalog.current_database()
        WHERE namespace.nspname = %s
          AND relation.relname = %s
        """,
        (schema_name, relation_name),
    )
    row = cursor.fetchone()
    assert row is not None
    return {
        "database_oid": int(row[0]),
        "namespace_oid": int(row[1]),
        "relation_oid": int(row[2]),
        "schema": str(row[3]),
        "relation_name": str(row[4]),
        "relation_kind": str(row[5]),
    }


def test_live_gold_backup_cleanup_drops_only_persisted_oid(
    isolated_app_state_db,
    monkeypatch,
):
    monkeypatch.setenv("AURUM_ENABLE_DESTRUCTIVE_ADMIN", "true")
    monkeypatch.setenv("AURUM_DESTRUCTIVE_ADMIN_TOKEN", "test-token")
    suffix = uuid.uuid4().hex[:10]
    run_id = f"run_gold_backup_{suffix}"
    source_schema = f"cp1_gold_source_{suffix}"
    candidate_schema = f"cp1_gold_candidates_{suffix}"
    gold_schema = f"cp1_gold_{suffix}"
    silver_candidate_schema = f"cp1_silver_candidates_{suffix}"
    target_name = "approved_output"
    source_name = "source_a"
    promotion_claim_id = f"promote_{suffix}"
    candidate_name = f"{target_name}_candidate_{run_id}"
    backup_name = promotion_backup_name(target_name, promotion_claim_id)
    schemas = LayerSchemas(
        source="source",
        bronze="bronze",
        silver=source_schema,
        gold=gold_schema,
        silver_candidates=silver_candidate_schema,
        gold_candidates=candidate_schema,
    )

    try:
        with psycopg.connect(postgres_conninfo(), autocommit=True) as admin:
            apply_role_setup(admin, schemas=schemas)
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE TABLE {}.{} (value bigint)").format(
                        sql.Identifier(source_schema),
                        sql.Identifier(source_name),
                    )
                )
                cursor.execute(
                    sql.SQL("CREATE TABLE {}.{} (value bigint)").format(
                        sql.Identifier(gold_schema),
                        sql.Identifier(target_name),
                    )
                )
                cursor.execute(
                    sql.SQL("CREATE TABLE {}.{} (value bigint)").format(
                        sql.Identifier(gold_schema),
                        sql.Identifier(backup_name),
                    )
                )
                cursor.execute(
                    sql.SQL("ALTER TABLE {}.{} OWNER TO aurum_promotion").format(
                        sql.Identifier(gold_schema),
                        sql.Identifier(target_name),
                    )
                )
                cursor.execute(
                    sql.SQL("ALTER TABLE {}.{} OWNER TO aurum_promotion").format(
                        sql.Identifier(gold_schema),
                        sql.Identifier(backup_name),
                    )
                )
                source_identity = _relation_identity(
                    cursor,
                    source_schema,
                    source_name,
                )
                final_identity = _relation_identity(
                    cursor,
                    gold_schema,
                    target_name,
                )
                backup_identity = _relation_identity(
                    cursor,
                    gold_schema,
                    backup_name,
                )
                cursor.execute(
                    "SELECT oid, datname FROM pg_catalog.pg_database "
                    "WHERE datname = pg_catalog.current_database()"
                )
                database_oid, database_name = cursor.fetchone()
                cursor.execute(
                    "SELECT oid FROM pg_catalog.pg_namespace WHERE nspname = %s",
                    (candidate_schema,),
                )
                candidate_namespace_oid = cursor.fetchone()[0]

        sql_text = (
            f'CREATE TABLE "{candidate_schema}"."{candidate_name}" '
            f'AS SELECT * FROM "{source_schema}"."{source_name}"'
        )
        record = new_gold_security_record(
            run_id=run_id,
            sql_text=sql_text,
            business_requirement="Controlled cleanup verification.",
            generator_provenance="checkpoint_cleanup_verifier",
            generator_version="1",
            selected_sources=[
                {"schema": source_schema, "table": source_name}
            ],
            target_schema=gold_schema,
            target_name=target_name,
            candidate_schema=candidate_schema,
        )
        target_identity = {
            "state": "existing",
            **{
                **backup_identity,
                "relation_name": target_name,
            },
        }
        candidate_identity = {
            **final_identity,
            "namespace_oid": int(candidate_namespace_oid),
            "schema": candidate_schema,
            "relation_name": candidate_name,
        }
        review_snapshot = json.loads(record["review_snapshot_json"])
        approval_snapshot = build_approval_snapshot(
            review_snapshot=review_snapshot,
            review_revision=record["review_revision"],
            database_oid=int(database_oid),
            database_name=str(database_name),
            source_identities=[source_identity],
            target_identity=target_identity,
            candidate_namespace_identity={
                "database_oid": int(database_oid),
                "namespace_oid": int(candidate_namespace_oid),
                "schema": candidate_schema,
            },
            overwrite_authorized=True,
        )
        with get_connection() as state:
            state.execute(
                """
                INSERT INTO generated_sql_review (
                    run_id, table_name, sql_text, planned_changes_json,
                    created_at, status, candidate_schema,
                    generator_provenance
                )
                VALUES (?, ?, ?, ?, ?, 'PROMOTED', ?, ?)
                """,
                (
                    run_id,
                    target_name,
                    sql_text,
                    canonical_json({"summary": "cleanup verification"}),
                    "2026-07-25T00:00:00+00:00",
                    candidate_schema,
                    "checkpoint_cleanup_verifier",
                ),
            )
            insert_gold_security_state(state, record)
            state.execute(
                """
                UPDATE gold_security_state
                SET approval_snapshot_json = ?,
                    approved_revision = ?,
                    approved_at = ?,
                    overwrite_authorized = 1,
                    source_identities_json = ?,
                    target_identity_json = ?,
                    execution_claim_id = ?,
                    execution_claimed_at = ?,
                    candidate_identity_json = ?,
                    promotion_claim_id = ?,
                    promotion_claimed_at = ?,
                    promoted_target_identity_json = ?,
                    backup_identity_json = ?,
                    backup_cleanup_eligible = 0,
                    promotion_committed_at = ?
                WHERE run_id = ?
                """,
                (
                    canonical_json(approval_snapshot),
                    revision_for(approval_snapshot),
                    "2026-07-25T00:01:00+00:00",
                    canonical_json([source_identity]),
                    canonical_json(target_identity),
                    f"exec_{suffix}",
                    "2026-07-25T00:02:00+00:00",
                    canonical_json(candidate_identity),
                    promotion_claim_id,
                    "2026-07-25T00:03:00+00:00",
                    canonical_json(final_identity),
                    canonical_json(backup_identity),
                    "2026-07-25T00:04:00+00:00",
                    run_id,
                ),
            )
            state.commit()

        client = TestClient(app)
        cleanup_response = client.post(
            f"/api/v1/admin/gold-backup-cleanup/{run_id}?confirm=true",
            headers={"X-Aurum-Operator-Token": "test-token"},
        )
        assert cleanup_response.status_code == 200, cleanup_response.text
        assert cleanup_response.json()["outcome"] == "removed"
        assert (
            cleanup_response.json()["backup_identity"]["relation_oid"]
            == backup_identity["relation_oid"]
        )

        with psycopg.connect(postgres_conninfo(), autocommit=True) as admin:
            with admin.cursor() as cursor:
                cursor.execute(
                    "SELECT to_regclass(%s), to_regclass(%s)",
                    (
                        f'"{gold_schema}"."{backup_name}"',
                        f'"{gold_schema}"."{target_name}"',
                    ),
                )
                removed_backup, retained_target = cursor.fetchone()
                assert removed_backup is None
                assert retained_target is not None
                cursor.execute(
                    sql.SQL("CREATE TABLE {}.{} (value bigint)").format(
                        sql.Identifier(gold_schema),
                        sql.Identifier(backup_name),
                    )
                )
                cursor.execute(
                    sql.SQL("ALTER TABLE {}.{} OWNER TO aurum_promotion").format(
                        sql.Identifier(gold_schema),
                        sql.Identifier(backup_name),
                    )
                )
                replacement_identity = _relation_identity(
                    cursor,
                    gold_schema,
                    backup_name,
                )
                assert (
                    replacement_identity["relation_oid"]
                    != backup_identity["relation_oid"]
                )

        collision_response = client.post(
            f"/api/v1/admin/gold-backup-cleanup/{run_id}?confirm=true",
            headers={"X-Aurum-Operator-Token": "test-token"},
        )
        assert collision_response.status_code == 409, collision_response.text
        assert (
            collision_response.json()["detail"]["error"]
            == "GOLD_BACKUP_IDENTITY_MISMATCH"
        )
        with psycopg.connect(postgres_conninfo()) as verify:
            with verify.cursor() as cursor:
                live_replacement = _relation_identity(
                    cursor,
                    gold_schema,
                    backup_name,
                )
        assert (
            live_replacement["relation_oid"]
            == replacement_identity["relation_oid"]
        )
    finally:
        with psycopg.connect(postgres_conninfo(), autocommit=True) as cleanup:
            with cleanup.cursor() as cursor:
                for schema_name in (
                    source_schema,
                    candidate_schema,
                    gold_schema,
                    silver_candidate_schema,
                ):
                    cursor.execute(
                        sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                            sql.Identifier(schema_name)
                        )
                    )
