"""Isolated tests for Batch 4B Gold containment and Silver discovery."""

from types import SimpleNamespace
from typing import Optional

import psycopg
import pytest
from fastapi.testclient import TestClient

import api.silver_gold_router as router
from api.bronze_silver_router import TRUSTED_GENERATOR_PROVENANCES
from api.main import app
from src.app_state.db import get_connection


client = TestClient(app)


def _seed_gold_run(run_id: str, provenance: Optional[str]) -> None:
    sql_text = (
        f"CREATE TABLE gold_candidates.aggregate_output_candidate_{run_id} "
        "AS SELECT 1 AS value"
    )
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review (
                run_id,
                table_name,
                sql_text,
                planned_changes_json,
                created_at,
                status,
                candidate_schema,
                generator_provenance
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "aggregate_output",
                sql_text,
                "{}",
                "2026-07-23T00:00:00",
                "PENDING",
                "gold_candidates",
                provenance,
            ),
        )
        conn.commit()


def _gold_run_count() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM generated_sql_review").fetchone()
    return int(row[0])


def test_check_name_contract(monkeypatch):
    existing = {"taken_output"}
    monkeypatch.setattr(
        router,
        "check_table_exists",
        lambda schema_name, table_name: table_name in existing,
    )

    available = client.get("/api/v1/gold/check-name?name=new_output")
    assert available.status_code == 200
    assert available.json()["status"] == "available"

    invalid = client.get("/api/v1/gold/check-name?name=bad-name")
    assert invalid.status_code == 200
    assert invalid.json()["status"] == "invalid"

    taken = client.get("/api/v1/gold/check-name?name=taken_output")
    assert taken.status_code == 200
    assert taken.json()["status"] == "taken"


from src.generator_trust import GeneratorTrustPolicy

def test_generate_is_unavailable_and_persists_no_run(monkeypatch):
    monkeypatch.setattr(
        router,
        "GOLD_GENERATOR_TRUST",
        GeneratorTrustPolicy(
            pipeline="gold",
            trusted_hardened_provenances=frozenset(),
        ),
    )
    monkeypatch.setattr(
        router,
        "get_generated_sql_pool",
        lambda: pytest.fail("Gold containment must not reach PostgreSQL"),
    )
    before = _gold_run_count()

    response = client.post(
        "/api/v1/gold/generate",
        json={
            "target_table_name": "aggregate_output",
            "silver_table_names": ["curated_input"],
            "business_requirement": "Produce the requested aggregate.",
        },
    )

    assert response.status_code == 503
    assert response.json() == {"detail": router.GOLD_GENERATION_UNAVAILABLE}
    assert _gold_run_count() == before


@pytest.mark.parametrize("provenance", [None, "untrusted_legacy"])
def test_legacy_gold_execute_is_rejected_before_postgres(
    provenance,
    monkeypatch,
):
    run_id = f"run_legacy_{'null' if provenance is None else 'marked'}"
    _seed_gold_run(run_id, provenance)
    calls = {"candidate": 0, "promotion": 0, "collision": 0}

    def collision_spy(*args, **kwargs):
        calls["collision"] += 1
        return False

    monkeypatch.setattr(
        router,
        "get_generated_sql_pool",
        lambda: pytest.fail("contained execution must not reach PostgreSQL"),
    )
    monkeypatch.setattr(router, "check_table_exists", collision_spy)

    response = client.post(
        f"/api/v1/gold/execute/{run_id}",
        json={"overwrite": False},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": router.GOLD_EXECUTION_UNAVAILABLE}
    assert calls == {"candidate": 0, "promotion": 0, "collision": 0}


def test_silver_trusted_provenance_does_not_authorize_gold(monkeypatch):
    silver_provenance = next(iter(TRUSTED_GENERATOR_PROVENANCES))
    run_id = "run_silver_provenance"
    _seed_gold_run(run_id, silver_provenance)
    calls = {"candidate": 0, "promotion": 0}

    monkeypatch.setattr(
        router,
        "get_generated_sql_pool",
        lambda: pytest.fail("Silver trust must not reach Gold PostgreSQL"),
    )

    response = client.post(
        f"/api/v1/gold/execute/{run_id}",
        json={"overwrite": True},
    )

    assert response.status_code == 503
    assert calls == {"candidate": 0, "promotion": 0}
    assert router.GOLD_GENERATOR_TRUST.trusts_run(silver_provenance) is False


def test_untrusted_review_does_not_claim_execution_readiness():
    run_id = "run_untrusted_review"
    _seed_gold_run(run_id, "untrusted_legacy")

    response = client.get(f"/api/v1/gold/review/{run_id}")

    assert response.status_code == 503
    assert response.json() == {"detail": router.GOLD_REVIEW_UNAVAILABLE}
    assert "ready for execution" not in response.text.lower()


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params):
        self.params = params

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self):
        return self.fake_cursor


class FakePool:
    def __init__(self, connection):
        self.fake_connection = connection

    def connection(self):
        return self.fake_connection


def _mock_discovery(monkeypatch, rows, configured_schema="tenant_curated"):
    cursor = FakeCursor(rows)
    connection = FakeConnection(cursor)
    monkeypatch.setattr(
        router,
        "load_layer_schemas",
        lambda: SimpleNamespace(silver=configured_schema),
    )
    monkeypatch.setattr(
        router,
        "get_generated_sql_pool",
        lambda: FakePool(connection),
    )
    return cursor


def test_silver_discovery_uses_configured_schema_and_returns_real_names(
    monkeypatch,
):
    cursor = _mock_discovery(
        monkeypatch,
        [("clean_accounts",), ("curated_events",)],
    )

    response = client.get(
        "/api/v1/gold/silver-tables?schema=client_supplied_schema"
    )

    assert response.status_code == 200
    assert response.json() == {
        "tables": [
            {"name": "clean_accounts"},
            {"name": "curated_events"},
        ]
    }
    assert cursor.params == ("tenant_curated",)


def test_silver_discovery_empty_is_honest(monkeypatch):
    _mock_discovery(monkeypatch, [])

    response = client.get("/api/v1/gold/silver-tables")

    assert response.status_code == 200
    assert response.json() == {"tables": []}


def test_silver_discovery_configuration_failure_is_sanitized(monkeypatch):
    def fail_configuration():
        raise RuntimeError("secret configuration detail")

    monkeypatch.setattr(router, "load_layer_schemas", fail_configuration)

    response = client.get("/api/v1/gold/silver-tables")

    assert response.status_code == 500
    assert response.json() == {"detail": "Invalid Silver layer configuration."}
    assert "secret configuration detail" not in response.text


def test_silver_discovery_connectivity_failure_is_sanitized(monkeypatch):
    monkeypatch.setattr(
        router,
        "load_layer_schemas",
        lambda: SimpleNamespace(silver="tenant_curated"),
    )

    def unavailable_pool():
        raise psycopg.OperationalError("password=secret")

    monkeypatch.setattr(router, "get_generated_sql_pool", unavailable_pool)

    response = client.get("/api/v1/gold/silver-tables")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Silver table discovery is currently unavailable."
    }
    assert "password=secret" not in response.text
