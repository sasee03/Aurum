from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from src.app_state.db import get_connection, get_readonly_connection
from src.assistant_context import AssistantContextService, build_assistant_context


def _seed_state(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> None:
    monkeypatch.setenv("AURUM_APP_STATE_DB", str(db_path))
    report = {
        "layer_status": {"bronze": "PASS", "silver": "FAIL"},
        "root_cause": {"summary": "Valid Bronze rows were removed."},
        "checks": {
            "bronze": [{"check_id": "B1", "observed": 10}],
            "silver": [
                {"check_id": "S1", "extra": {"bronze": 10, "silver": 8}},
                {"check_id": "S8", "extra": {"missing": 2}},
                {
                    "check_id": "S10",
                    "extra": {"suspected_filter": "amount > 100"},
                },
            ],
        },
    }
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("project-1", "Context test", "2026-07-28T00:00:00Z", "2026-07-28T00:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO data_connections
                (id, project_id, type, name, host, port, database_name, username, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("conn-1", "project-1", "postgresql", "safe name", "db.example", 5432,
             "warehouse", "analyst", "active", "2026-07-28T00:00:00Z", "2026-07-28T00:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO validation_runs
                (run_id, project_id, connection_id, status, mode, started_at, error_message,
                 source_schema, source_table, dataset_config)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("run-1", "project-1", "conn-1", "completed", "connector", "2026-07-28T01:00:00Z",
             "password=supersecret api_key=topsecret", "public", "orders", "orders-v1"),
        )
        conn.execute(
            "INSERT INTO validation_reports (run_id, report_json, created_at) VALUES (?, ?, ?)",
            ("run-1", json.dumps(report), "2026-07-28T01:01:00Z"),
        )
        conn.execute(
            """
            INSERT INTO bronze_ingest_authority
                (ingest_id, project_id, connection_id, database_name, source_schema, source_relation,
                 source_identity_json, bronze_schema, bronze_relation, bronze_identity_json, status,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("ingest-1", "project-1", "conn-1", "warehouse", "public", "orders", "{}",
             "bronze", "bronze_orders", "{}", "READY", "2026-07-28T01:00:00Z", "2026-07-28T01:02:00Z"),
        )
        conn.execute(
            "INSERT INTO table_rules (table_name, rules_json, rule_revision, updated_at) VALUES (?, ?, ?, ?)",
            ("bronze_orders", json.dumps([{"kind": "filter", "column": "amount"}]), "a" * 64,
             "2026-07-28T01:03:00Z"),
        )
        conn.execute(
            """
            INSERT INTO generated_sql_review
                (run_id, table_name, sql_text, planned_changes_json, created_at, status,
                 candidate_schema, generator_provenance, project_id, connection_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("gold-1", "daily_revenue", "CREATE TABLE never_returned", json.dumps({"metric": "SUM(amount)"}),
             "2026-07-28T02:00:00Z", "PROMOTION_FAILED", "gold_candidates", "structured_deterministic_gold_v1",
             "project-1", "conn-1"),
        )
        conn.execute(
            """
            INSERT INTO gold_security_state
                (run_id, model_version, policy_version, business_requirement, selected_sources_json,
                 target_schema, target_name, candidate_schema, candidate_name, generator_provenance,
                 generator_version, review_snapshot_json, review_revision, promotion_failure_code)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("gold-1", "v1", "v1", "Daily revenue", json.dumps({"sources": [{"schema": "silver", "table": "orders"}]}),
             "gold", "daily_revenue", "gold_candidates", "daily_revenue_candidate", "structured_deterministic_gold_v1",
             "v1", "{}", "b" * 64, "promotion_conflict"),
        )
        conn.commit()


def test_known_context_uses_persisted_pipeline_state(monkeypatch, tmp_path):
    db_path = tmp_path / "app_state.sqlite"
    _seed_state(monkeypatch, db_path)
    service = AssistantContextService(
        state_path=db_path,
        source_columns_reader=lambda *_args: [
            {"name": "order_id", "data_type": "text", "nullable": False, "ordinal_position": 1}
        ],
    )

    context = service.build()

    assert context["run"]["id"] == "run-1"
    assert context["connection"] == {"id": "conn-1", "database_name": "warehouse", "status": "active"}
    assert context["source"]["relation"] == "orders"
    assert context["source"]["columns"][0]["data_type"] == "text"
    assert context["bronze"]["authority_status"] == "READY"
    assert context["bronze"]["row_count"] == 10
    assert context["silver"]["row_count"] == 8
    assert context["silver"]["removed_count"] == 2
    assert context["silver"]["transformation"]["rules"] == [{"kind": "filter", "column": "amount"}]
    assert context["gold"]["status"] == "PROMOTION_FAILED"
    assert context["gold"]["sources"] == [{"schema": "silver", "table": "orders"}]
    assert context["gold"]["planned_calculation"] == {"metric": "SUM(amount)"}
    assert {message["code"] for message in context["messages"]} == {"run_error", "promotion_failed"}


def test_missing_context_is_explicitly_unavailable(tmp_path):
    context = build_assistant_context(state_path=tmp_path / "does-not-exist.sqlite")

    assert context["run"]["id"] is None
    assert context["source"]["columns"] is None
    assert context["silver"]["invalid_count"] is None
    assert context["gold"]["status"] is None


def test_context_redacts_secrets_and_never_returns_sql_or_credentials(monkeypatch, tmp_path):
    db_path = tmp_path / "app_state.sqlite"
    _seed_state(monkeypatch, db_path)

    context = AssistantContextService(state_path=db_path, source_columns_reader=lambda *_args: None).build()
    payload = json.dumps(context)

    assert "supersecret" not in payload
    assert "topsecret" not in payload
    assert "analyst" not in payload
    assert "db.example" not in payload
    assert "CREATE TABLE never_returned" not in payload


def test_context_reader_never_mutates_app_state(monkeypatch, tmp_path):
    db_path = tmp_path / "app_state.sqlite"
    _seed_state(monkeypatch, db_path)
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    AssistantContextService(state_path=db_path, source_columns_reader=lambda *_args: None).build()

    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert after == before
    with get_readonly_connection(db_path) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO projects (id, name, created_at, updated_at) VALUES ('nope', 'nope', 'x', 'x')")


def test_gold_run_only_resolves_grounded_gold_context(monkeypatch, tmp_path):
    db_path = tmp_path / "app_state.sqlite"
    monkeypatch.setenv("AURUM_APP_STATE_DB", str(db_path))
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review
                (run_id, table_name, sql_text, planned_changes_json, created_at, status,
                 candidate_schema, generator_provenance, project_id, connection_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("gold-only-1", "curated_customers", "CREATE TABLE ...", json.dumps({"metric": "COUNT(*)"}),
             "2026-07-28T02:00:00Z", "PROMOTED", "gold_candidates", "manual_controlled_gold_v1",
             "project-1", "conn-1"),
        )
        conn.execute(
            """
            INSERT INTO gold_security_state
                (run_id, model_version, policy_version, business_requirement, selected_sources_json,
                 target_schema, target_name, candidate_schema, candidate_name, generator_provenance,
                 generator_version, review_snapshot_json, review_revision)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("gold-only-1", "v1", "v1", "Summarize customers", json.dumps({"sources": [{"schema": "silver", "table": "customers"}]}),
             "gold", "curated_customers", "gold_candidates", "curated_customers_cand", "manual_controlled_gold_v1",
             "v1", "{}", "c" * 64),
        )
        conn.commit()

    service = AssistantContextService(state_path=db_path)
    context = service.build(run_id="gold-only-1")

    assert context["run"]["id"] == "gold-only-1"
    assert context["run"]["mode"] == "gold"
    assert context["gold"]["status"] == "PROMOTED"
    assert context["gold"]["business_requirement"] == "Summarize customers"
    assert context["gold"]["target"] == {"schema": "gold", "relation": "curated_customers"}


def test_existing_validation_runs_context_preserved(monkeypatch, tmp_path):
    db_path = tmp_path / "app_state.sqlite"
    _seed_state(monkeypatch, db_path)
    service = AssistantContextService(state_path=db_path)

    context = service.build(run_id="run-1")

    assert context["run"]["id"] == "run-1"
    assert context["connection"]["id"] == "conn-1"
    assert context["source"]["relation"] == "orders"


def test_unknown_run_id_returns_empty_context(monkeypatch, tmp_path):
    db_path = tmp_path / "app_state.sqlite"
    _seed_state(monkeypatch, db_path)
    service = AssistantContextService(state_path=db_path)

    context = service.build(run_id="unknown-run-999")

    assert context["run"]["id"] is None
    assert context["gold"]["status"] is None
    assert context["source"]["relation"] is None


def test_no_fabricated_facts_when_lineage_unpersisted(monkeypatch, tmp_path):
    db_path = tmp_path / "app_state.sqlite"
    monkeypatch.setenv("AURUM_APP_STATE_DB", str(db_path))
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO generated_sql_review
                (run_id, table_name, sql_text, planned_changes_json, created_at, status,
                 candidate_schema, generator_provenance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("gold-unlinked-1", "isolated_gold", "CREATE TABLE ...", json.dumps({}),
             "2026-07-28T02:00:00Z", "PROMOTED", "gold_candidates", "manual_controlled_gold_v1"),
        )
        conn.execute(
            """
            INSERT INTO gold_security_state
                (run_id, model_version, policy_version, business_requirement, selected_sources_json,
                 target_schema, target_name, candidate_schema, candidate_name, generator_provenance,
                 generator_version, review_snapshot_json, review_revision)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("gold-unlinked-1", "v1", "v1", "Isolated requirement", json.dumps({"sources": [{"schema": "silver", "table": "isolated_table"}]}),
             "gold", "isolated_gold", "gold_candidates", "isolated_gold_cand", "manual_controlled_gold_v1",
             "v1", "{}", "d" * 64),
        )
        conn.commit()

    service = AssistantContextService(state_path=db_path)
    context = service.build(run_id="gold-unlinked-1")

    assert context["run"]["id"] == "gold-unlinked-1"
    assert context["gold"]["status"] == "PROMOTED"
    assert context["source"]["schema"] is None
    assert context["source"]["relation"] is None
    assert context["bronze"]["authority_status"] is None
    assert context["silver"]["validation_status"] is None


def test_assistant_remains_strictly_read_only(monkeypatch, tmp_path):
    db_path = tmp_path / "app_state.sqlite"
    _seed_state(monkeypatch, db_path)
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    service = AssistantContextService(state_path=db_path)
    service.build(run_id="gold-1")

    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert after == before


def test_gold_run_never_resolves_different_connection_authority(monkeypatch, tmp_path):
    db_path = tmp_path / "app_state.sqlite"
    monkeypatch.setenv("AURUM_APP_STATE_DB", str(db_path))
    with get_connection() as conn:
        conn.execute("INSERT INTO projects (id, name, created_at, updated_at) VALUES ('p1', 'p1', 'x', 'x')")
        conn.execute("INSERT INTO data_connections (id, project_id, type, name, host, port, database_name, username, status, created_at, updated_at) VALUES ('conn-A', 'p1', 'postgresql', 'A', 'localhost', 5432, 'db_a', 'user', 'ACTIVE', 'x', 'x')")
        conn.execute("INSERT INTO data_connections (id, project_id, type, name, host, port, database_name, username, status, created_at, updated_at) VALUES ('conn-B', 'p1', 'postgresql', 'B', 'localhost', 5432, 'db_b', 'user', 'ACTIVE', 'x', 'x')")
        conn.execute(
            """
            INSERT INTO bronze_ingest_authority
                (ingest_id, project_id, connection_id, database_name, source_schema, source_relation,
                 source_identity_json, bronze_schema, bronze_relation, bronze_identity_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("ing-b", "p1", "conn-B", "db_b", "public", "users", "{}", "bronze", "bronze_users_b", "{}", "READY", "x", "x"),
        )
        conn.execute(
            """
            INSERT INTO generated_sql_review
                (run_id, table_name, sql_text, planned_changes_json, created_at, status, candidate_schema, generator_provenance, project_id, connection_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("gold-conn-a", "curated_users", "SELECT...", "{}", "2026-07-28T02:00:00Z", "PROMOTED", "cand", "gen", "p1", "conn-A"),
        )
        conn.execute(
            """
            INSERT INTO gold_security_state
                (run_id, model_version, policy_version, business_requirement, selected_sources_json,
                 target_schema, target_name, candidate_schema, candidate_name, generator_provenance,
                 generator_version, review_snapshot_json, review_revision)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("gold-conn-a", "v1", "v1", "req", json.dumps({"sources": [{"schema": "public", "table": "users"}]}),
             "gold", "curated_users", "cand", "curated_users_c", "gen", "v1", "{}", "c" * 64),
        )
        conn.commit()

    service = AssistantContextService(state_path=db_path)
    context = service.build(run_id="gold-conn-a")

    assert context["run"]["id"] == "gold-conn-a"
    assert context["connection"]["id"] == "conn-A"
    assert context["source"]["relation"] is None
    assert context["bronze"]["relation"] is None


def test_gold_run_matches_exact_schema_on_same_connection(monkeypatch, tmp_path):
    db_path = tmp_path / "app_state.sqlite"
    monkeypatch.setenv("AURUM_APP_STATE_DB", str(db_path))
    with get_connection() as conn:
        conn.execute("INSERT INTO projects (id, name, created_at, updated_at) VALUES ('p1', 'p1', 'x', 'x')")
        conn.execute("INSERT INTO data_connections (id, project_id, type, name, host, port, database_name, username, status, created_at, updated_at) VALUES ('conn-A', 'p1', 'postgresql', 'A', 'localhost', 5432, 'db_a', 'user', 'ACTIVE', 'x', 'x')")
        conn.execute(
            """
            INSERT INTO bronze_ingest_authority
                (ingest_id, project_id, connection_id, database_name, source_schema, source_relation,
                 source_identity_json, bronze_schema, bronze_relation, bronze_identity_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("ing-a1", "p1", "conn-A", "db_a", "source_a", "users", "{}", "bronze", "bronze_users_a", "{}", "READY", "x", "2026-07-28T01:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO bronze_ingest_authority
                (ingest_id, project_id, connection_id, database_name, source_schema, source_relation,
                 source_identity_json, bronze_schema, bronze_relation, bronze_identity_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("ing-a2", "p1", "conn-A", "db_a", "source_b", "users", "{}", "bronze", "bronze_users_b", "{}", "READY", "x", "2026-07-28T02:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO generated_sql_review
                (run_id, table_name, sql_text, planned_changes_json, created_at, status, candidate_schema, generator_provenance, project_id, connection_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("gold-schema-a", "curated_users", "SELECT...", "{}", "2026-07-28T02:00:00Z", "PROMOTED", "cand", "gen", "p1", "conn-A"),
        )
        conn.execute(
            """
            INSERT INTO gold_security_state
                (run_id, model_version, policy_version, business_requirement, selected_sources_json,
                 target_schema, target_name, candidate_schema, candidate_name, generator_provenance,
                 generator_version, review_snapshot_json, review_revision)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("gold-schema-a", "v1", "v1", "req", json.dumps({"sources": [{"schema": "source_a", "table": "users"}]}),
             "gold", "curated_users", "cand", "curated_users_c", "gen", "v1", "{}", "c" * 64),
        )
        conn.commit()

    service = AssistantContextService(state_path=db_path)
    context = service.build(run_id="gold-schema-a")

    assert context["source"]["schema"] == "source_a"
    assert context["source"]["relation"] == "users"
    assert context["bronze"]["relation"] == "bronze_users_a"


def test_gold_run_ambiguous_authority_remains_absent(monkeypatch, tmp_path):
    db_path = tmp_path / "app_state.sqlite"
    monkeypatch.setenv("AURUM_APP_STATE_DB", str(db_path))
    with get_connection() as conn:
        conn.execute("INSERT INTO projects (id, name, created_at, updated_at) VALUES ('p1', 'p1', 'x', 'x')")
        conn.execute("INSERT INTO data_connections (id, project_id, type, name, host, port, database_name, username, status, created_at, updated_at) VALUES ('conn-A', 'p1', 'postgresql', 'A', 'localhost', 5432, 'db_a', 'user', 'ACTIVE', 'x', 'x')")
        conn.execute(
            """
            INSERT INTO bronze_ingest_authority
                (ingest_id, project_id, connection_id, database_name, source_schema, source_relation,
                 source_identity_json, bronze_schema, bronze_relation, bronze_identity_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("ing-a1", "p1", "conn-A", "db_a", "source_a", "users", "{}", "bronze", "bronze_users_a", "{}", "READY", "x", "2026-07-28T01:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO bronze_ingest_authority
                (ingest_id, project_id, connection_id, database_name, source_schema, source_relation,
                 source_identity_json, bronze_schema, bronze_relation, bronze_identity_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("ing-a2", "p1", "conn-A", "db_a", "source_b", "users", "{}", "bronze", "bronze_users_b", "{}", "READY", "x", "2026-07-28T02:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO generated_sql_review
                (run_id, table_name, sql_text, planned_changes_json, created_at, status, candidate_schema, generator_provenance, project_id, connection_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("gold-ambiguous", "curated_users", "SELECT...", "{}", "2026-07-28T02:00:00Z", "PROMOTED", "cand", "gen", "p1", "conn-A"),
        )
        conn.execute(
            """
            INSERT INTO gold_security_state
                (run_id, model_version, policy_version, business_requirement, selected_sources_json,
                 target_schema, target_name, candidate_schema, candidate_name, generator_provenance,
                 generator_version, review_snapshot_json, review_revision)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("gold-ambiguous", "v1", "v1", "req", json.dumps({"sources": [{"table": "users"}]}),
             "gold", "curated_users", "cand", "curated_users_c", "gen", "v1", "{}", "c" * 64),
        )
        conn.commit()

    service = AssistantContextService(state_path=db_path)
    context = service.build(run_id="gold-ambiguous")

    assert context["source"]["relation"] is None
    assert context["bronze"]["relation"] is None


def test_gold_run_exact_connection_schema_relation_resolves(monkeypatch, tmp_path):
    db_path = tmp_path / "app_state.sqlite"
    monkeypatch.setenv("AURUM_APP_STATE_DB", str(db_path))
    with get_connection() as conn:
        conn.execute("INSERT INTO projects (id, name, created_at, updated_at) VALUES ('p1', 'p1', 'x', 'x')")
        conn.execute("INSERT INTO data_connections (id, project_id, type, name, host, port, database_name, username, status, created_at, updated_at) VALUES ('conn-A', 'p1', 'postgresql', 'A', 'localhost', 5432, 'db_a', 'user', 'ACTIVE', 'x', 'x')")
        conn.execute(
            """
            INSERT INTO bronze_ingest_authority
                (ingest_id, project_id, connection_id, database_name, source_schema, source_relation,
                 source_identity_json, bronze_schema, bronze_relation, bronze_identity_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("ing-exact", "p1", "conn-A", "db_a", "prod", "orders", "{}", "bronze", "bronze_orders", "{}", "READY", "x", "2026-07-28T01:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO generated_sql_review
                (run_id, table_name, sql_text, planned_changes_json, created_at, status, candidate_schema, generator_provenance, project_id, connection_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("gold-exact", "curated_orders", "SELECT...", "{}", "2026-07-28T02:00:00Z", "PROMOTED", "cand", "gen", "p1", "conn-A"),
        )
        conn.execute(
            """
            INSERT INTO gold_security_state
                (run_id, model_version, policy_version, business_requirement, selected_sources_json,
                 target_schema, target_name, candidate_schema, candidate_name, generator_provenance,
                 generator_version, review_snapshot_json, review_revision)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("gold-exact", "v1", "v1", "req", json.dumps({"sources": [{"schema": "prod", "table": "orders"}]}),
             "gold", "curated_orders", "cand", "curated_orders_c", "gen", "v1", "{}", "c" * 64),
        )
        conn.commit()

    service = AssistantContextService(state_path=db_path)
    context = service.build(run_id="gold-exact")

    assert context["connection"]["id"] == "conn-A"
    assert context["source"]["schema"] == "prod"
    assert context["source"]["relation"] == "orders"
    assert context["bronze"]["relation"] == "bronze_orders"


