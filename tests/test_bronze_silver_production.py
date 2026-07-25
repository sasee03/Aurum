import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.main import app
from api import bronze_silver_router
from src.app_state.db import get_connection
from src.app_state.store import (
    create_project,
    save_data_connection,
    save_validation_run,
)


SOURCE_IDENTITY = {
    "database_oid": 17,
    "namespace_oid": 23,
    "relation_oid": 41,
    "schema": "aurum_session_connector",
    "relation_name": "bronze_any",
    "relation_kind": "r",
}


class ConnectionContext:
    def __enter__(self):
        return object()

    def __exit__(self, *args):
        return None


class Pool:
    def connection(self):
        return ConnectionContext()


def _persist_connector_authority():
    project = create_project("Production path")
    connection_id = "connector-real-metadata"
    save_data_connection(
        connection_id=connection_id,
        project_id=project["id"],
        name="source",
        host="db.internal",
        port=5432,
        database_name="source_db",
        username="reader",
    )
    save_validation_run(
        "connector_real_bronze",
        project_id=project["id"],
        connection_id=connection_id,
        status="completed",
        mode="connector",
        source_schema="source_any",
        source_table="source_any",
        session_schema=SOURCE_IDENTITY["schema"],
        dataset_config="generic",
        bronze_identity=SOURCE_IDENTITY,
    )
    return project["id"], connection_id


def _patch_server_dependencies(monkeypatch, live_identity=SOURCE_IDENTITY):
    monkeypatch.setattr(
        bronze_silver_router,
        "resolve_config_by_name",
        lambda name: SimpleNamespace(
            tables=SimpleNamespace(
                bronze="bronze_any",
                silver="silver_any",
            )
        ),
    )
    monkeypatch.setattr(
        bronze_silver_router,
        "load_layer_schemas",
        lambda: SimpleNamespace(
            bronze="bronze",
            silver_candidates="silver_candidates",
            silver="silver",
        ),
    )
    monkeypatch.setattr(
        bronze_silver_router,
        "load_postgres_config",
        lambda: SimpleNamespace(dbname="aurum"),
    )
    monkeypatch.setattr(
        bronze_silver_router,
        "get_generated_sql_pool",
        lambda: Pool(),
    )
    monkeypatch.setattr(
        bronze_silver_router,
        "resolve_relation_identity",
        lambda conn, schema, table: live_identity,
    )


def test_materialize_derives_all_authority_server_side(
    isolated_app_state_db,
    monkeypatch,
):
    project_id, connection_id = _persist_connector_authority()
    _patch_server_dependencies(monkeypatch)

    captured = {}

    def fake_execute(run_id):
        with get_connection() as conn:
            captured.update(
                dict(
                    conn.execute(
                        "SELECT * FROM generated_sql_review WHERE run_id = ?",
                        (run_id,),
                    ).fetchone()
                )
            )
        return {"status": "success", "run_id": run_id}

    monkeypatch.setattr(bronze_silver_router, "execute_sql", fake_execute)

    response = TestClient(app).post(
        "/api/v1/transform/materialize",
        json={"source_run_id": "connector_real_bronze"},
    )

    assert response.status_code == 200
    assert captured["project_id"] == project_id
    assert captured["connection_id"] == connection_id
    assert captured["source_validation_run_id"] == "connector_real_bronze"
    assert json.loads(captured["source_identity_json"]) == SOURCE_IDENTITY
    assert captured["table_name"] == "silver_any"
    assert captured["candidate_schema"] == "silver_candidates"
    assert (
        captured["generator_provenance"]
        == bronze_silver_router.SERVER_PASSTHROUGH_PROVENANCE
    )
    assert '"aurum_session_connector"."bronze_any"' in captured["sql_text"]
    assert "SELECT *" in captured["sql_text"]


def test_materialize_rejects_client_fabricated_authority(
    isolated_app_state_db,
    monkeypatch,
):
    _persist_connector_authority()
    _patch_server_dependencies(monkeypatch)

    response = TestClient(app).post(
        "/api/v1/transform/materialize",
        json={
            "source_run_id": "connector_real_bronze",
            "project_id": "attacker",
            "connection_id": "attacker",
            "source_identity_json": SOURCE_IDENTITY,
            "sql_text": "SELECT 1",
        },
    )

    assert response.status_code == 422


def test_materialize_rejects_same_name_with_changed_bronze_oid(
    isolated_app_state_db,
    monkeypatch,
):
    _persist_connector_authority()
    replacement = {**SOURCE_IDENTITY, "relation_oid": 99}
    _patch_server_dependencies(monkeypatch, live_identity=replacement)

    response = TestClient(app).post(
        "/api/v1/transform/materialize",
        json={"source_run_id": "connector_real_bronze"},
    )

    assert response.status_code == 409
    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM generated_sql_review"
        ).fetchone()[0]
    assert count == 0
