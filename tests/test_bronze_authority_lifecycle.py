from __future__ import annotations

import json

import pytest

from src.app_state.db import get_connection
from src.bronze_authority import (
    BronzeAuthorityError,
    claim_bronze_ingest_operation,
    finalize_bronze_ingest_ready,
    get_bronze_ingest_operation,
    mark_bronze_ingest_commit_in_progress,
    mark_bronze_ingest_creating,
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


def _prepare(ingest_id: str, bronze_oid: int) -> None:
    claim_bronze_ingest_operation(
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
    mark_bronze_ingest_creating(
        ingest_id,
        source_identity=_identity(100, schema="source", name="arbitrary"),
    )
    mark_bronze_ingest_commit_in_progress(
        ingest_id,
        bronze_identity=_identity(
            bronze_oid,
            schema="bronze",
            name="arbitrary",
        ),
    )


def test_exact_coordinates_publish_ready_authority(isolated_state):
    _prepare("ingest_exact", 200)

    authority = finalize_bronze_ingest_ready("ingest_exact")

    assert authority["status"] == "READY"
    assert authority["source_identity"]["relation_oid"] == 100
    assert authority["bronze_identity"]["relation_oid"] == 200


@pytest.mark.parametrize(
    ("column", "tampered_identity"),
    [
        (
            "source_identity_json",
            {
                **_identity(100, schema="source", name="arbitrary"),
                "namespace_oid": 999,
            },
        ),
        (
            "provisional_bronze_identity_json",
            _identity(201, schema="bronze", name="replacement"),
        ),
    ],
)
def test_tampered_coordinates_never_supersede_previous_ready(
    isolated_state,
    column,
    tampered_identity,
):
    _prepare("ingest_old", 200)
    finalize_bronze_ingest_ready("ingest_old")
    _prepare("ingest_new", 201)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE bronze_ingest_operations SET {column} = ? "
            "WHERE ingest_id = ?",
            (
                json.dumps(
                    tampered_identity,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "ingest_new",
            ),
        )
        conn.commit()

    with pytest.raises(
        BronzeAuthorityError,
        match="immutable ingest coordinates",
    ):
        finalize_bronze_ingest_ready("ingest_new")

    operation = get_bronze_ingest_operation("ingest_new")
    assert operation["status"] == "RECONCILIATION_REQUIRED"
    assert (
        operation["failure_code"]
        == "PERSISTED_IDENTITY_COORDINATE_MISMATCH"
    )
    with get_connection() as conn:
        old = conn.execute(
            "SELECT status FROM bronze_ingest_authority WHERE ingest_id = ?",
            ("ingest_old",),
        ).fetchone()
        new = conn.execute(
            "SELECT status FROM bronze_ingest_authority WHERE ingest_id = ?",
            ("ingest_new",),
        ).fetchone()
    assert old["status"] == "READY"
    assert new is None
