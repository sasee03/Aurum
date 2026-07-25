import json
import uuid

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql

from api.main import app
from src.app_state.db import get_connection
from src.config_loader import load_dataset_config
from src.db_config import (
    LayerSchemas,
    apply_role_setup,
    load_postgres_config,
    postgres_conninfo,
)


def test_real_connector_bronze_materializes_fresh_silver(
    isolated_app_state_db,
    monkeypatch,
):
    """Live PostgreSQL proof: API Connect→Bronze authority drives Silver CTAS."""
    suffix = uuid.uuid4().hex[:10]
    source_schema = f"cp1_source_{suffix}"
    silver_schema = f"cp1_silver_{suffix}"
    candidate_schema = f"cp1_silver_candidates_{suffix}"
    gold_schema = f"cp1_gold_{suffix}"
    gold_candidate_schema = f"cp1_gold_candidates_{suffix}"
    cfg = load_dataset_config()
    pg_cfg = load_postgres_config()
    schemas = LayerSchemas(
        source="source",
        bronze="bronze",
        silver=silver_schema,
        gold=gold_schema,
        silver_candidates=candidate_schema,
        gold_candidates=gold_candidate_schema,
    )
    for key, value in {
        "AURUM_SCHEMA_SILVER": silver_schema,
        "AURUM_SCHEMA_SILVER_CANDIDATES": candidate_schema,
        "AURUM_SCHEMA_GOLD": gold_schema,
        "AURUM_SCHEMA_GOLD_CANDIDATES": gold_candidate_schema,
    }.items():
        monkeypatch.setenv(key, value)

    session_schema = None
    try:
        with psycopg.connect(postgres_conninfo(), autocommit=True) as admin:
            apply_role_setup(admin, schemas=schemas)
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE SCHEMA {}").format(
                        sql.Identifier(source_schema)
                    )
                )
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE {}.{} (
                            invoice_no text,
                            stock_code text,
                            description text,
                            quantity bigint,
                            invoice_date text,
                            unit_price double precision,
                            customer_id text,
                            country text
                        )
                        """
                    ).format(
                        sql.Identifier(source_schema),
                        sql.Identifier("raw_orders"),
                    )
                )
                cursor.execute(
                    sql.SQL(
                        """
                        INSERT INTO {}.{} (
                            invoice_no, stock_code, description, quantity,
                            invoice_date, unit_price, customer_id, country
                        )
                        VALUES
                            (%s, %s, %s, %s, %s, %s, %s, %s),
                            (%s, %s, %s, %s, %s, %s, %s, %s)
                        """
                    ).format(
                        sql.Identifier(source_schema),
                        sql.Identifier("raw_orders"),
                    ),
                    (
                        "order_1",
                        "sku_1",
                        "first",
                        1,
                        "2026-07-25",
                        10.0,
                        "customer_1",
                        "IN",
                        "order_2",
                        "sku_2",
                        "second",
                        2,
                        "2026-07-25",
                        12.5,
                        "customer_2",
                        "IN",
                    ),
                )

        client = TestClient(app)
        project_response = client.post(
            "/projects",
            json={
                "name": "olist",
                "environment": "Production",
            },
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["id"]

        connect_response = client.post(
            "/connectors/postgres/test",
            json={
                "host": pg_cfg.host,
                "port": pg_cfg.port,
                "database": pg_cfg.dbname,
                "username": pg_cfg.user,
                "password": pg_cfg.password,
                "project_id": project_id,
                "name": "Checkpoint 1 live source",
            },
        )
        assert connect_response.status_code == 200
        assert connect_response.json()["connected"] is True
        connection_id = connect_response.json()["connection_id"]

        validate_response = client.post(
            "/connectors/postgres/validate",
            json={
                "connection_id": connection_id,
                "schema": source_schema,
                "table": "raw_orders",
                "project_id": project_id,
            },
        )
        assert validate_response.status_code == 200, validate_response.text

        with get_connection() as state:
            connector_row = state.execute(
                """
                SELECT *
                FROM validation_runs
                WHERE project_id = ?
                  AND connection_id = ?
                  AND mode = 'connector'
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (project_id, connection_id),
            ).fetchone()
        assert connector_row is not None
        session_schema = connector_row["session_schema"]
        bronze_identity = json.loads(connector_row["bronze_identity_json"])
        assert bronze_identity["schema"] == session_schema
        assert bronze_identity["relation_name"] == cfg.tables.bronze
        assert bronze_identity["database_oid"] > 0
        assert bronze_identity["namespace_oid"] > 0
        assert bronze_identity["relation_oid"] > 0

        materialize_response = client.post(
            "/api/v1/transform/materialize",
            json={"source_run_id": connector_row["run_id"]},
        )
        assert materialize_response.status_code == 200
        body = materialize_response.json()
        assert body["status"] == "success"

        with get_connection() as state:
            silver_run = state.execute(
                """
                SELECT *
                FROM generated_sql_review
                WHERE run_id = ?
                """,
                (body["run_id"],),
            ).fetchone()
        assert silver_run["status"] == "PROMOTED"
        assert silver_run["project_id"] == project_id
        assert silver_run["connection_id"] == connection_id
        assert silver_run["source_validation_run_id"] == connector_row["run_id"]
        assert json.loads(silver_run["source_identity_json"]) == bronze_identity
        assert silver_run["generator_provenance"] == "aurum_server_passthrough_v1"

        promoted_identity = json.loads(
            silver_run["promoted_target_identity_json"]
        )
        with psycopg.connect(postgres_conninfo()) as verify:
            with verify.cursor() as cursor:
                cursor.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                        sql.Identifier(session_schema),
                        sql.Identifier(cfg.tables.bronze),
                    )
                )
                bronze_count = cursor.fetchone()[0]
                cursor.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                        sql.Identifier(silver_schema),
                        sql.Identifier(cfg.tables.silver),
                    )
                )
                silver_count = cursor.fetchone()[0]
                cursor.execute(
                    """
                    SELECT relation.oid,
                           namespace.oid,
                           database.oid,
                           relation.relkind
                    FROM pg_catalog.pg_class AS relation
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    JOIN pg_catalog.pg_database AS database
                      ON database.datname = pg_catalog.current_database()
                    WHERE namespace.nspname = %s
                      AND relation.relname = %s
                    """,
                    (silver_schema, cfg.tables.silver),
                )
                live_target = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = %s
                      AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (session_schema, cfg.tables.bronze),
                )
                bronze_columns = [row[0] for row in cursor.fetchall()]
                cursor.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = %s
                      AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (silver_schema, cfg.tables.silver),
                )
                silver_columns = [row[0] for row in cursor.fetchall()]

        assert bronze_count == silver_count == 2
        assert bronze_columns == silver_columns
        assert int(live_target[0]) == promoted_identity["relation_oid"]
        assert int(live_target[1]) == promoted_identity["namespace_oid"]
        assert int(live_target[2]) == promoted_identity["database_oid"]
        assert str(live_target[3]) == promoted_identity["relation_kind"] == "r"
    finally:
        with psycopg.connect(postgres_conninfo(), autocommit=True) as cleanup:
            with cleanup.cursor() as cursor:
                cleanup_schemas = [
                    source_schema,
                    silver_schema,
                    candidate_schema,
                    gold_schema,
                    gold_candidate_schema,
                ]
                if session_schema:
                    cleanup_schemas.append(session_schema)
                for schema_name in cleanup_schemas:
                    if schema_name.startswith(("cp1_", "aurum_session_")):
                        cursor.execute(
                            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                                sql.Identifier(schema_name)
                            )
                        )
