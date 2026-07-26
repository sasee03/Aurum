"""Metadata discovery unit and API tests."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from src.metadata_discovery import (
    _quote_ident,
    classify_layer,
    discover_demo_session_metadata,
    discover_from_connection,
    infer_candidate_keys,
    list_tables,
    merge_table_spec_overrides,
    profile_columns,
)
from src.table_specs import build_table_specs


@pytest.fixture
def client():
    with TestClient(api_main.app) as test_client:
        yield test_client


def test_classify_layer_patterns():
    assert classify_layer("public", "bronze_orders") == "bronze"
    assert classify_layer("public", "silver_orders") == "silver"
    assert classify_layer("public", "gold_metrics") == "gold"
    assert classify_layer("public", "random_table") == "unknown"


def test_quote_ident_allows_valid_postgres_identifiers_with_spaces():
    quoted = _quote_ident("invalid name with spaces").as_string(None)
    assert quoted == '"invalid name with spaces"'


def test_infer_candidate_keys_accepts_high_uniqueness_zero_nulls():
    profiles = [
        {
            "name": "order_id",
            "data_type": "text",
            "null_percent": 0.0,
            "distinct_count": 100,
            "uniqueness_percent": 99.8,
        }
    ]
    assert infer_candidate_keys(profiles, row_count=100) == ["order_id"]


def test_infer_candidate_keys_rejects_nullable_high_unique():
    profiles = [
        {
            "name": "maybe_id",
            "data_type": "text",
            "null_percent": 1.0,
            "distinct_count": 100,
            "uniqueness_percent": 100.0,
        }
    ]
    assert infer_candidate_keys(profiles, row_count=100) == []


def test_infer_candidate_keys_rejects_low_uniqueness():
    profiles = [
        {
            "name": "country",
            "data_type": "text",
            "null_percent": 0.0,
            "distinct_count": 10,
            "uniqueness_percent": 10.0,
        }
    ]
    assert infer_candidate_keys(profiles, row_count=100) == []


def test_infer_candidate_keys_empty_when_row_count_zero():
    profiles = [
        {
            "name": "order_id",
            "data_type": "text",
            "null_percent": 0.0,
            "distinct_count": 100,
            "uniqueness_percent": 100.0,
        }
    ]
    assert infer_candidate_keys(profiles, row_count=0) == []


def test_infer_candidate_keys_skips_json_and_jsonb():
    profiles = [
        {
            "name": "payload",
            "data_type": "json",
            "null_percent": 0.0,
            "distinct_count": None,
            "uniqueness_percent": None,
        },
        {
            "name": "meta",
            "data_type": "jsonb",
            "null_percent": 0.0,
            "distinct_count": 100,
            "uniqueness_percent": 100.0,
        },
    ]
    assert infer_candidate_keys(profiles, row_count=100) == []


def test_infer_candidate_keys_skips_when_distinct_stats_null():
    profiles = [
        {
            "name": "payload",
            "data_type": "json",
            "null_percent": 0.0,
            "distinct_count": None,
            "uniqueness_percent": None,
        }
    ]
    assert infer_candidate_keys(profiles, row_count=100) == []


@patch("src.metadata_discovery.get_row_count", return_value=100)
@patch("src.metadata_discovery.describe_table")
def test_sample_limit_affects_only_sample_values(mock_describe, mock_row_count):
    mock_describe.return_value = [
        {
            "name": "invoice_no",
            "data_type": "text",
            "nullable": False,
            "ordinal_position": 1,
        }
    ]

    def make_profiles(sample_limit: int):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchone.side_effect = [(0,), (100,)]
        cursor.fetchall.return_value = [("A",), ("B",)] if sample_limit == 2 else [
            ("A",),
            ("B",),
            ("C",),
        ][:sample_limit]
        return profile_columns(conn, "public", "bronze_orders", sample_limit=sample_limit)

    profiles_small = make_profiles(2)
    profiles_large = make_profiles(5)

    assert profiles_small[0]["distinct_count"] == 100
    assert profiles_large[0]["distinct_count"] == 100
    assert len(profiles_small[0]["sample_values"]) == 2
    assert profiles_small[0]["uniqueness_percent"] == 100.0

    keys = infer_candidate_keys(profiles_small, row_count=100)
    assert keys == ["invoice_no"]


@patch("src.metadata_discovery.get_row_count", return_value=10)
@patch("src.metadata_discovery.describe_table")
def test_json_column_profiling_safety(mock_describe, mock_row_count):
    """Test 12: json columns must not run DISTINCT and must not become candidate keys."""
    mock_describe.return_value = [
        {
            "name": "payload",
            "data_type": "json",
            "nullable": True,
            "ordinal_position": 1,
        }
    ]
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = (0,)

    profiles = profile_columns(conn, "public", "events", sample_limit=3)
    profile = profiles[0]

    assert profile["data_type"] == "json"
    assert profile["distinct_count"] is None
    assert profile["uniqueness_percent"] is None
    assert profile["sample_values"] == []
    executed = " ".join(str(call.args[0]) for call in cursor.execute.call_args_list)
    assert "COUNT(DISTINCT" not in executed
    assert "SELECT DISTINCT" not in executed
    assert infer_candidate_keys(profiles, row_count=10) == []


def test_candidate_key_skips_unsupported_distinct():
    """Test 13: columns with null uniqueness_percent are never candidate keys."""
    profiles = [
        {
            "name": "blob_col",
            "data_type": "text",
            "null_percent": 0.0,
            "distinct_count": None,
            "uniqueness_percent": None,
        }
    ]
    assert infer_candidate_keys(profiles, row_count=100) == []


@patch("src.metadata_discovery.get_row_count", return_value=10)
@patch("src.metadata_discovery.describe_table")
def test_profile_columns_json_skips_distinct_operations(mock_describe, mock_row_count):
    mock_describe.return_value = [
        {
            "name": "payload",
            "data_type": "json",
            "nullable": True,
            "ordinal_position": 1,
        }
    ]
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = (0,)

    profiles = profile_columns(conn, "public", "events", sample_limit=3)
    profile = profiles[0]

    assert profile["distinct_count"] is None
    assert profile["uniqueness_percent"] is None
    assert profile["sample_values"] == []
    executed = " ".join(str(call.args[0]) for call in cursor.execute.call_args_list)
    assert "COUNT(DISTINCT" not in executed
    assert "SELECT DISTINCT" not in executed


@patch("src.metadata_discovery.get_row_count", return_value=10)
@patch("src.metadata_discovery.describe_table")
def test_profile_columns_jsonb_runs_distinct_but_not_candidate_key(
    mock_describe, mock_row_count
):
    mock_describe.return_value = [
        {
            "name": "meta",
            "data_type": "jsonb",
            "nullable": False,
            "ordinal_position": 1,
        }
    ]
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = [(0,), (10,)]
    cursor.fetchall.return_value = [({"k": 1},)]

    profiles = profile_columns(conn, "public", "events", sample_limit=3)
    profile = profiles[0]

    assert profile["distinct_count"] == 10
    assert profile["uniqueness_percent"] == 100.0
    assert profile["sample_values"] == [{"k": 1}]
    assert infer_candidate_keys(profiles, row_count=10) == []


def test_merge_table_spec_overrides_adds_static_spec_without_overwriting():
    discovered = {
        "schema": "public",
        "table": "bronze_orders",
        "layer": "bronze",
        "row_count": 10,
        "column_count": 3,
    }
    merged = merge_table_spec_overrides(discovered, build_table_specs())
    assert merged["row_count"] == 10
    assert merged["spec_overrides"] == build_table_specs()["bronze_orders"]
    assert merged is not discovered


def _mock_pg_connect(monkeypatch):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.__exit__.return_value = False
    mock_cursor.__enter__.return_value = mock_cursor
    mock_cursor.__exit__.return_value = False
    mock_conn.cursor.return_value = mock_cursor
    monkeypatch.setattr(api_main.psycopg, "connect", lambda *args, **kwargs: mock_conn)
    return mock_cursor


def test_metadata_health_ok(client, monkeypatch):
    _mock_pg_connect(monkeypatch)
    response = client.get("/metadata/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metadata_health_degraded(client, monkeypatch):
    def fail_connect(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(api_main.psycopg, "connect", fail_connect)
    response = client.get("/metadata/health")
    assert response.status_code == 503
    assert response.json() == {"status": "error", "detail": "Database unavailable"}


def test_get_metadata_response_shape(client, monkeypatch):
    payload = {
        "database": {"type": "postgres", "status": "ok", "source": "live"},
        "summary": {
            "total_tables": 1,
            "bronze_tables": 1,
            "silver_tables": 0,
            "gold_tables": 0,
            "unknown_tables": 0,
            "total_columns": 2,
        },
        "tables": [
            {
                "schema": "public",
                "table": "bronze_orders",
                "layer": "bronze",
                "row_count": 1,
                "column_count": 2,
                "candidate_keys": [],
                "columns": [],
                "spec_overrides": {},
            }
        ],
    }
    monkeypatch.setattr(api_main, "discover_live_metadata", lambda **kwargs: payload)
    response = client.get("/metadata")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"database", "summary", "tables"}
    assert body["database"]["source"] == "live"


def test_get_metadata_tables_is_lightweight(client, monkeypatch):
    lightweight_payload = {
        "database": {"type": "postgres", "status": "ok", "source": "live"},
        "summary": {
            "total_tables": 1,
            "bronze_tables": 1,
            "silver_tables": 0,
            "gold_tables": 0,
            "unknown_tables": 0,
            "total_columns": 2,
        },
        "tables": [
            {
                "schema": "public",
                "table": "bronze_orders",
                "layer": "bronze",
                "row_count": 1,
                "column_count": 2,
            }
        ],
    }

    with patch(
        "api.main.discover_live_tables_lightweight",
        return_value=lightweight_payload,
    ) as mock_light:
        with patch("src.metadata_discovery.profile_columns") as mock_profile:
            with patch("src.metadata_discovery.infer_candidate_keys") as mock_infer:
                response = client.get("/metadata/tables")

    assert response.status_code == 200
    mock_light.assert_called_once()
    mock_profile.assert_not_called()
    mock_infer.assert_not_called()
    table = response.json()["tables"][0]
    assert "candidate_keys" not in table
    assert "columns" not in table


def test_list_tables_hides_session_schemas_by_default_but_allows_explicit_schema():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchall.side_effect = [
        [
            ("aurum_session_deadbeef", "bronze_orders"),
            ("public", "bronze_orders"),
        ],
        [("aurum_session_deadbeef", "bronze_orders")],
    ]

    default_tables = list_tables(conn)
    explicit_tables = list_tables(conn, schema_filter="aurum_session_deadbeef")

    assert default_tables == [
        {"schema": "public", "table": "bronze_orders", "layer": "bronze"}
    ]
    assert explicit_tables == [
        {
            "schema": "aurum_session_deadbeef",
            "table": "bronze_orders",
            "layer": "bronze",
        }
    ]


@patch("src.metadata_discovery.discover_from_connection")
@patch("src.data_loader.DataLoader")
def test_post_demo_session_cleanup_on_failure(mock_loader_cls, mock_discover):
    loader = MagicMock()
    loader._pg_conn = MagicMock()
    loader.session_schema = "aurum_session_test"
    mock_loader_cls.return_value = loader
    mock_discover.side_effect = RuntimeError("profile failed")

    with pytest.raises(RuntimeError, match="profile failed"):
        discover_demo_session_metadata(sample_limit=5)

    loader.close.assert_called_once()
    mock_discover.assert_called_once()
    assert mock_discover.call_args.kwargs["schema"] == "aurum_session_test"


@patch("src.metadata_discovery.discover_from_connection")
@patch("src.data_loader.DataLoader")
def test_post_demo_session_profiles_exact_loader_schema(mock_loader_cls, mock_discover):
    loader = MagicMock()
    loader._pg_conn = MagicMock()
    loader.session_schema = "aurum_session_test"
    mock_loader_cls.return_value = loader
    mock_discover.return_value = {
        "database": {"type": "postgres", "status": "ok", "source": "demo_session"},
        "summary": {
            "total_tables": 0,
            "bronze_tables": 0,
            "silver_tables": 0,
            "gold_tables": 0,
            "unknown_tables": 0,
            "total_columns": 0,
        },
        "tables": [],
    }

    result = discover_demo_session_metadata(sample_limit=3)

    mock_discover.assert_called_once_with(
        loader._pg_conn,
        schema="aurum_session_test",
        sample_limit=3,
        source="demo_session",
        lightweight=False,
    )
    loader.close.assert_called_once()
    assert result["database"]["source"] == "demo_session"


def test_metadata_responses_do_not_leak_credentials(client, monkeypatch):
    payload = {
        "database": {"type": "postgres", "status": "ok", "source": "live"},
        "summary": {
            "total_tables": 0,
            "bronze_tables": 0,
            "silver_tables": 0,
            "gold_tables": 0,
            "unknown_tables": 0,
            "total_columns": 0,
        },
        "tables": [],
    }
    monkeypatch.setattr(api_main, "discover_live_metadata", lambda **kwargs: payload)
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret:password@host/db")
    response = client.get("/metadata")
    body = json.dumps(response.json())
    assert "DATABASE_URL" not in body
    assert "password" not in body.lower()


def test_discover_from_connection_lightweight_skips_profile_and_keys():
    conn = MagicMock()
    listed = [
        {"schema": "public", "table": "bronze_orders", "layer": "bronze"},
    ]
    with patch("src.metadata_discovery.list_tables", return_value=listed):
        with patch(
            "src.metadata_discovery.discover_table_metadata_lightweight",
            return_value={
                "schema": "public",
                "table": "bronze_orders",
                "layer": "bronze",
                "row_count": 1,
                "column_count": 2,
            },
        ) as mock_light:
            with patch("src.metadata_discovery.discover_table_metadata") as mock_full:
                result = discover_from_connection(
                    conn, source="live", lightweight=True
                )

    mock_light.assert_called_once()
    mock_full.assert_not_called()
    assert result["tables"][0]["row_count"] == 1
    assert "candidate_keys" not in result["tables"][0]


def test_metadata_table_preview_returns_bounded_live_rows(client, monkeypatch):
    payload = {
        "schema": "tenant_gold",
        "table": "curated_output",
        "row_count": 2,
        "column_count": 2,
        "columns": [
            {"name": "record_id", "data_type": "integer", "nullable": False},
            {"name": "score", "data_type": "numeric", "nullable": True},
        ],
        "rows": [
            {"record_id": 1, "score": 10.5},
            {"record_id": 2, "score": None},
        ],
    }
    calls = []

    def preview_spy(*, table_name, schema, limit):
        calls.append((table_name, schema, limit))
        return payload

    monkeypatch.setattr(api_main, "discover_live_table_preview", preview_spy)

    response = client.get(
        "/metadata/tables/curated_output/preview"
        "?schema=tenant_gold&limit=2"
    )

    assert response.status_code == 200
    assert response.json() == payload
    assert calls == [("curated_output", "tenant_gold", 2)]
