"""Focused builder tests for the Structured Gold V1 producer."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api.silver_gold_router as router
from api.main import app
import src.gold_catalog as gold_catalog
import src.gold_execution as gold_execution
from src.app_state.db import get_connection
from src.gold_catalog import (
    GoldCatalogColumn,
    GoldCatalogResolutionError,
    GoldCatalogSnapshot,
    StructuredGoldSourceCatalogSnapshot,
)
from src.gold_execution import GoldExecutionRejected
from src.gold_security import (
    GoldStateMalformed,
    build_approval_snapshot,
    canonical_json,
    load_gold_security_state,
    revision_for,
)
from src.sql_safety import validate_generated_sql
from src.structured_gold import (
    StructuredGoldDefinitionError,
    compile_structured_gold_sql,
    validate_structured_gold_definition,
)


client = TestClient(app)
SCHEMAS = SimpleNamespace(
    silver="configured_silver",
    gold="configured_gold",
    gold_candidates="configured_gold_candidates",
)


def _column(
    name: str,
    *,
    type_name: str,
    supported_aggregations: tuple[str, ...],
) -> GoldCatalogColumn:
    return GoldCatalogColumn(
        name=name,
        type_oid={
            "int4": 23,
            "numeric": 1700,
            "text": 25,
        }[type_name],
        type_schema="pg_catalog",
        type_name=type_name,
        type_kind="b",
        supported_aggregations=frozenset(supported_aggregations),
    )


COLUMNS = (
    _column(
        "segment",
        type_name="text",
        supported_aggregations=("min", "max"),
    ),
    _column(
        "amount",
        type_name="numeric",
        supported_aggregations=("sum", "avg", "min", "max"),
    ),
    _column(
        "units",
        type_name="int4",
        supported_aggregations=("sum", "avg", "min", "max"),
    ),
    _column(
        "description",
        type_name="text",
        supported_aggregations=("min", "max"),
    ),
)


def _source_catalog() -> StructuredGoldSourceCatalogSnapshot:
    return StructuredGoldSourceCatalogSnapshot(
        database_oid=101,
        database_name="isolated_test_database",
        source_identity={
            "database_oid": 101,
            "namespace_oid": 102,
            "relation_oid": 103,
            "schema": SCHEMAS.silver,
            "relation_name": "source_facts",
            "relation_kind": "r",
        },
        columns=COLUMNS,
    )


def _approval_catalog(
    source_identity: dict | None = None,
) -> GoldCatalogSnapshot:
    return GoldCatalogSnapshot(
        database_oid=101,
        database_name="isolated_test_database",
        source_identities=(
            source_identity or _source_catalog().source_identity,
        ),
        target_identity={
            "state": "absent",
            "database_oid": 101,
            "namespace_oid": 104,
            "schema": SCHEMAS.gold,
            "relation_name": "business_summary",
        },
        candidate_namespace_identity={
            "database_oid": 101,
            "namespace_oid": 105,
            "schema": SCHEMAS.gold_candidates,
        },
    )


def _payload(
    *,
    aggregation: str = "sum",
    expression: dict | None = None,
    alias: str = "metric_value",
) -> dict:
    return {
        "source": {
            "schema": SCHEMAS.silver,
            "table": "source_facts",
        },
        "dimension": {"column": "segment"},
        "metric": {
            "aggregation": aggregation,
            "expression": expression or {"type": "column", "column": "amount"},
            "alias": alias,
        },
        "target_table_name": "business_summary",
        "business_purpose": "Summarize an approved measure by one dimension.",
    }


@pytest.fixture
def structured_catalog(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(router, "load_layer_schemas", lambda: SCHEMAS)

    def resolve(*, schema: str, relation_name: str):
        calls.append((schema, relation_name))
        return _source_catalog()

    monkeypatch.setattr(router, "resolve_structured_gold_source", resolve)
    return calls


@pytest.mark.parametrize(
    ("aggregation", "expression", "alias", "sql_fragment"),
    [
        (
            "sum",
            {"type": "column", "column": "amount"},
            "total_amount",
            'SUM("amount") AS "total_amount"',
        ),
        (
            "sum",
            {
                "type": "binary",
                "operator": "multiply",
                "left_column": "amount",
                "right_column": "units",
            },
            "weighted_amount",
            'SUM("amount" * "units") AS "weighted_amount"',
        ),
        (
            "sum",
            {
                "type": "binary",
                "operator": "add",
                "left_column": "amount",
                "right_column": "units",
            },
            "combined_amount",
            'SUM("amount" + "units") AS "combined_amount"',
        ),
        (
            "sum",
            {
                "type": "binary",
                "operator": "subtract",
                "left_column": "amount",
                "right_column": "units",
            },
            "net_amount",
            'SUM("amount" - "units") AS "net_amount"',
        ),
        (
            "count",
            {"type": "column", "column": "description"},
            "description_count",
            'COUNT("description") AS "description_count"',
        ),
        (
            "avg",
            {"type": "column", "column": "amount"},
            "average_amount",
            'AVG("amount") AS "average_amount"',
        ),
        (
            "min",
            {"type": "column", "column": "description"},
            "first_description",
            'MIN("description") AS "first_description"',
        ),
        (
            "max",
            {"type": "column", "column": "description"},
            "last_description",
            'MAX("description") AS "last_description"',
        ),
    ],
)
def test_structured_generate_compiles_validates_and_persists_review_state(
    aggregation,
    expression,
    alias,
    sql_fragment,
    structured_catalog,
):
    response = client.post(
        "/api/v1/gold/generate-structured",
        json=_payload(
            aggregation=aggregation,
            expression=expression,
            alias=alias,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["generator_provenance"] == (
        router.STRUCTURED_DETERMINISTIC_GOLD_PROVENANCE
    )
    assert structured_catalog == [(SCHEMAS.silver, "source_facts")]
    assert sql_fragment in body["sql_text"]
    assert (
        f'FROM "{SCHEMAS.silver}"."source_facts"'
        in body["sql_text"]
    )
    assert 'GROUP BY "segment"' in body["sql_text"]
    assert body["planned_changes"]["dimension"] == "segment"
    assert body["planned_changes"]["metric"]["alias"] == alias

    with get_connection() as conn:
        review = conn.execute(
            "SELECT * FROM generated_sql_review WHERE run_id = ?",
            (body["run_id"],),
        ).fetchone()
        security = conn.execute(
            "SELECT * FROM gold_security_state WHERE run_id = ?",
            (body["run_id"],),
        ).fetchone()
    assert review is not None
    assert security is not None
    assert json.loads(security["selected_sources_json"])["sources"] == [
        {"schema": SCHEMAS.silver, "table": "source_facts"}
    ]
    persisted_review = json.loads(security["review_snapshot_json"])
    assert persisted_review["snapshot_version"] == "gold-review-snapshot-v2"
    assert persisted_review["generation_source_identities"] == [
        _source_catalog().source_identity
    ]

    review_response = client.get(f"/api/v1/gold/review/{body['run_id']}")
    assert review_response.status_code == 200
    assert review_response.json()["executable"] is True
    assert review_response.json()["generator_provenance"] == (
        router.STRUCTURED_DETERMINISTIC_GOLD_PROVENANCE
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dimension", "missing_dimension"),
        ("metric", "missing_metric"),
        ("dimension", 'segment"; DROP TABLE x; --'),
        ("metric", 'amount"; DROP TABLE x; --'),
    ],
)
def test_invented_or_injected_columns_are_rejected(
    field,
    value,
    structured_catalog,
):
    payload = _payload()
    if field == "dimension":
        payload["dimension"]["column"] = value
    else:
        payload["metric"]["expression"]["column"] = value

    response = client.post("/api/v1/gold/generate-structured", json=payload)

    assert response.status_code == 422
    assert "exact authorized Silver relation" in response.json()["detail"]


@pytest.mark.parametrize(
    ("aggregation", "expression", "expected_detail"),
    [
        (
            "sum",
            {"type": "column", "column": "description"},
            "SUM requires a numeric expression",
        ),
        (
            "avg",
            {"type": "column", "column": "description"},
            "AVG requires a numeric expression",
        ),
        (
            "sum",
            {
                "type": "binary",
                "operator": "add",
                "left_column": "amount",
                "right_column": "description",
            },
            "binary expressions require numeric operands",
        ),
    ],
)
def test_incompatible_metric_types_are_rejected(
    aggregation,
    expression,
    expected_detail,
    structured_catalog,
):
    response = client.post(
        "/api/v1/gold/generate-structured",
        json=_payload(aggregation=aggregation, expression=expression),
    )

    assert response.status_code == 422
    assert expected_detail in response.json()["detail"]


def test_count_binary_expression_is_rejected(structured_catalog):
    response = client.post(
        "/api/v1/gold/generate-structured",
        json=_payload(
            aggregation="count",
            expression={
                "type": "binary",
                "operator": "add",
                "left_column": "amount",
                "right_column": "units",
            },
        ),
    )

    assert response.status_code == 422
    assert "COUNT requires an explicit column expression" in response.json()["detail"]


def test_non_silver_source_is_rejected_before_catalog_resolution(
    monkeypatch,
):
    monkeypatch.setattr(router, "load_layer_schemas", lambda: SCHEMAS)
    monkeypatch.setattr(
        router,
        "resolve_structured_gold_source",
        lambda **kwargs: pytest.fail("unauthorized source must not reach catalog"),
    )
    payload = _payload()
    payload["source"]["schema"] = "unauthorized_schema"

    response = client.post("/api/v1/gold/generate-structured", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Structured Gold source must use the configured Silver schema."
    )


def test_unresolved_or_stale_source_identity_is_rejected(monkeypatch):
    monkeypatch.setattr(router, "load_layer_schemas", lambda: SCHEMAS)

    def unresolved(**kwargs):
        raise GoldCatalogResolutionError(
            "source",
            "selected source relation is unresolved",
        )

    monkeypatch.setattr(router, "resolve_structured_gold_source", unresolved)

    response = client.post(
        "/api/v1/gold/generate-structured",
        json=_payload(),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "Structured Gold Silver source is unavailable."
    )


def test_catalog_resolution_returns_exact_relation_identity_and_column_types(
    monkeypatch,
):
    class FakeCursor:
        def __init__(self):
            self.query = ""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, params=None):
            self.query = str(query)

        def fetchone(self):
            if "pg_database" in self.query:
                return (101, "isolated_test_database")
            if "pg_namespace" in self.query:
                return (102,)
            if "pg_class" in self.query:
                return (103, "source_facts", "r")
            raise AssertionError(f"Unexpected fetchone query: {self.query}")

        def fetchall(self):
            assert "pg_attribute" in self.query
            return [
                (
                    "amount",
                    1700,
                    "pg_catalog",
                    "numeric",
                    "b",
                    ["avg", "max", "min", "sum"],
                )
            ]

    class Context:
        def __enter__(self):
            return self.value

        def __exit__(self, *args):
            return None

    class FakeConnection:
        def __init__(self):
            self.cursor_value = FakeCursor()

        def transaction(self):
            context = Context()
            context.value = self
            return context

        def cursor(self):
            context = Context()
            context.value = self.cursor_value
            return context

    class FakePool:
        def __init__(self):
            self.connection_value = FakeConnection()

        def connection(self):
            context = Context()
            context.value = self.connection_value
            return context

    monkeypatch.setattr(
        gold_catalog,
        "get_generated_sql_pool",
        lambda: FakePool(),
    )

    snapshot = gold_catalog.resolve_structured_gold_source(
        schema=SCHEMAS.silver,
        relation_name="source_facts",
    )

    assert snapshot.database_oid == 101
    assert snapshot.source_identity == {
        "database_oid": 101,
        "namespace_oid": 102,
        "relation_oid": 103,
        "schema": SCHEMAS.silver,
        "relation_name": "source_facts",
        "relation_kind": "r",
    }
    assert snapshot.columns == (
        GoldCatalogColumn(
            name="amount",
            type_oid=1700,
            type_schema="pg_catalog",
            type_name="numeric",
            type_kind="b",
            supported_aggregations=frozenset({"avg", "max", "min", "sum"}),
        ),
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["metric"].update(
            {"alias": 'metric"; DROP TABLE x; --'}
        ),
        lambda payload: payload["metric"].update({"aggregation": "median"}),
        lambda payload: payload["metric"]["expression"].update(
            {"operator": "divide"}
        ),
        lambda payload: payload["metric"]["expression"].update(
            {"operator": "power"}
        ),
        lambda payload: payload["metric"].update(
            {"expression": {"type": "binary", "left_column": "amount"}}
        ),
        lambda payload: payload.update({"sql": "SELECT * FROM secret"}),
        lambda payload: payload["metric"]["expression"].update(
            {"sql": "amount * units"}
        ),
    ],
)
def test_unsupported_or_raw_sql_shapes_are_rejected_by_request_model(
    mutate,
    structured_catalog,
):
    payload = _payload(
        expression={
            "type": "binary",
            "operator": "multiply",
            "left_column": "amount",
            "right_column": "units",
        }
    )
    mutate(payload)

    response = client.post("/api/v1/gold/generate-structured", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "spoofed_field",
    ["database_oid", "namespace_oid", "relation_oid", "source_identity"],
)
def test_client_cannot_spoof_structured_source_identity(
    spoofed_field,
    structured_catalog,
):
    payload = _payload()
    payload["source"][spoofed_field] = (
        {"relation_oid": 999}
        if spoofed_field == "source_identity"
        else 999
    )

    response = client.post("/api/v1/gold/generate-structured", json=payload)

    assert response.status_code == 422


def _generate_for_authority_test(structured_catalog) -> dict:
    response = client.post(
        "/api/v1/gold/generate-structured",
        json=_payload(),
    )
    assert response.status_code == 200
    return response.json()


def _approve(run: dict, *, overwrite: bool = False):
    return client.post(
        f"/api/v1/gold/approve/{run['run_id']}",
        json={
            "review_revision": run["review_revision"],
            "overwrite": overwrite,
        },
    )


def _load_generated_state(run_id: str):
    with get_connection() as conn:
        row, security = router._load_gold_rows(conn, run_id)
    assert row is not None
    return load_gold_security_state(
        security,
        row,
        configured_silver_schema=SCHEMAS.silver,
        configured_gold_schema=SCHEMAS.gold,
        configured_candidate_schema=SCHEMAS.gold_candidates,
    )


def _persisted_review_snapshot(run_id: str) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT review_snapshot_json FROM gold_security_state WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    assert row is not None
    return json.loads(row["review_snapshot_json"])


def _rewrite_review_snapshot(run_id: str, snapshot: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE gold_security_state
            SET review_snapshot_json = ?, review_revision = ?
            WHERE run_id = ?
            """,
            (canonical_json(snapshot), revision_for(snapshot), run_id),
        )
        conn.commit()


def _assert_structured_run_is_malformed(run: dict) -> None:
    review_response = client.get(f"/api/v1/gold/review/{run['run_id']}")
    assert review_response.status_code == 422
    assert review_response.json() == {"detail": router.GOLD_RUN_MALFORMED}

    approval_response = _approve(run)
    assert approval_response.status_code == 422
    assert approval_response.json() == {"detail": router.GOLD_RUN_MALFORMED}


def test_structured_complete_v2_snapshot_loads_successfully(structured_catalog):
    run = _generate_for_authority_test(structured_catalog)

    snapshot = _persisted_review_snapshot(run["run_id"])
    assert snapshot["snapshot_version"] == "gold-review-snapshot-v2"
    assert snapshot["generation_database"] == {
        "oid": 101,
        "name": "isolated_test_database",
    }
    assert snapshot["generation_source_identities"] == [
        _source_catalog().source_identity
    ]

    state = _load_generated_state(run["run_id"])
    assert state.generation_database_identity == snapshot["generation_database"]
    assert state.generation_source_identities == tuple(
        snapshot["generation_source_identities"]
    )


def test_authenticated_origin_blocks_cross_provenance_rewrite_after_approval(
    monkeypatch,
    structured_catalog,
):
    run = _generate_for_authority_test(structured_catalog)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: _approval_catalog(),
    )
    assert _approve(run).status_code == 200

    with get_connection() as conn:
        security = conn.execute(
            "SELECT * FROM gold_security_state WHERE run_id = ?",
            (run["run_id"],),
        ).fetchone()
        assert security is not None
        review = json.loads(security["review_snapshot_json"])
        review["snapshot_version"] = "gold-review-snapshot-v1"
        review.pop("generation_database")
        review.pop("generation_source_identities")
        review["generator"]["provenance"] = (
            router.MANUAL_CONTROLLED_GOLD_PROVENANCE
        )
        rewritten_revision = revision_for(review)
        approval = build_approval_snapshot(
            review_snapshot=review,
            review_revision=rewritten_revision,
            database_oid=101,
            database_name="isolated_test_database",
            source_identities=[_source_catalog().source_identity],
            target_identity=_approval_catalog().target_identity,
            candidate_namespace_identity=(
                _approval_catalog().candidate_namespace_identity
            ),
            overwrite_authorized=False,
        )
        conn.execute(
            """
            UPDATE generated_sql_review
            SET generator_provenance = ?
            WHERE run_id = ?
            """,
            (router.MANUAL_CONTROLLED_GOLD_PROVENANCE, run["run_id"]),
        )
        conn.execute(
            """
            UPDATE gold_security_state
            SET generator_provenance = ?, review_snapshot_json = ?,
                review_revision = ?, approval_snapshot_json = ?,
                approved_revision = ?
            WHERE run_id = ?
            """,
            (
                router.MANUAL_CONTROLLED_GOLD_PROVENANCE,
                canonical_json(review),
                rewritten_revision,
                canonical_json(approval),
                revision_for(approval),
                run["run_id"],
            ),
        )
        conn.commit()

    response = client.post(
        f"/api/v1/gold/execute/{run['run_id']}", json={"overwrite": False}
    )
    assert response.status_code == 422
    assert response.json() == {"detail": router.GOLD_RUN_MALFORMED}


def test_origin_and_approval_mac_are_required_for_authority(
    monkeypatch,
    structured_catalog,
):
    run = _generate_for_authority_test(structured_catalog)
    with get_connection() as conn:
        conn.execute(
            "UPDATE gold_run_origin SET origin_mac = ? WHERE run_id = ?",
            ("0" * 64, run["run_id"]),
        )
        conn.commit()
    assert client.get(f"/api/v1/gold/review/{run['run_id']}").status_code == 422

    run = _generate_for_authority_test(structured_catalog)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: _approval_catalog(),
    )
    assert _approve(run).status_code == 200
    with get_connection() as conn:
        conn.execute(
            "UPDATE gold_security_state SET approval_mac = NULL WHERE run_id = ?",
            (run["run_id"],),
        )
        conn.commit()
    response = client.post(
        f"/api/v1/gold/execute/{run['run_id']}", json={"overwrite": False}
    )
    assert response.status_code == 422


def test_missing_authority_hmac_key_fails_gold_generation_closed(
    monkeypatch,
    structured_catalog,
):
    monkeypatch.delenv("AURUM_AUTHORITY_HMAC_KEY")
    response = client.post("/api/v1/gold/generate-structured", json=_payload())
    assert response.status_code == 503


def test_structured_v1_downgrade_with_recomputed_revision_is_rejected(
    structured_catalog,
):
    run = _generate_for_authority_test(structured_catalog)
    snapshot = _persisted_review_snapshot(run["run_id"])

    assert snapshot["snapshot_version"] == "gold-review-snapshot-v2"
    snapshot["snapshot_version"] = "gold-review-snapshot-v1"
    snapshot.pop("generation_database")
    snapshot.pop("generation_source_identities")
    _rewrite_review_snapshot(run["run_id"], snapshot)

    with get_connection() as conn:
        row = conn.execute(
            "SELECT review_revision FROM gold_security_state WHERE run_id = ?",
            (run["run_id"],),
        ).fetchone()
    assert row is not None
    assert row["review_revision"] == revision_for(snapshot)

    _assert_structured_run_is_malformed(run)


@pytest.mark.parametrize(
    "case",
    [
        "missing_snapshot_version",
        "incomplete_database_identity",
        "incomplete_source_identity",
        "null_database_identity",
        "null_source_identity",
        "malformed_v2",
    ],
)
def test_structured_rejects_incomplete_or_malformed_v2_snapshot(
    case,
    structured_catalog,
):
    run = _generate_for_authority_test(structured_catalog)
    snapshot = _persisted_review_snapshot(run["run_id"])

    if case == "missing_snapshot_version":
        snapshot.pop("snapshot_version")
    elif case == "incomplete_database_identity":
        snapshot["generation_database"] = {"oid": 101}
    elif case == "incomplete_source_identity":
        snapshot["generation_source_identities"][0].pop("relation_oid")
    elif case == "null_database_identity":
        snapshot["generation_database"]["oid"] = None
    elif case == "null_source_identity":
        snapshot["generation_source_identities"][0]["relation_oid"] = None
    else:
        snapshot["generation_source_identities"] = {"invalid": "structure"}

    _rewrite_review_snapshot(run["run_id"], snapshot)

    _assert_structured_run_is_malformed(run)


def test_structured_same_oid_approval_and_normal_execution_succeed(
    monkeypatch,
    structured_catalog,
):
    run = _generate_for_authority_test(structured_catalog)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: _approval_catalog(),
    )

    approved = _approve(run)

    assert approved.status_code == 200
    state = _load_generated_state(run["run_id"])
    assert state.generation_database_identity == {
        "oid": 101,
        "name": "isolated_test_database",
    }
    assert state.generation_source_identities == (
        _source_catalog().source_identity,
    )
    assert state.source_identities == state.generation_source_identities

    monkeypatch.setattr(
        router,
        "execute_gold_candidate",
        lambda state, sql_text: {
            "database_oid": 101,
            "namespace_oid": 105,
            "relation_oid": 106,
            "schema": SCHEMAS.gold_candidates,
            "relation_name": state.candidate["table"],
            "relation_kind": "r",
        },
    )
    executed = client.post(
        f"/api/v1/gold/execute/{run['run_id']}",
        json={"overwrite": False},
    )

    assert executed.status_code == 200
    assert executed.json()["status"] == "PROMOTING"


def test_structured_approval_rejects_different_generation_and_live_oid(
    monkeypatch,
    structured_catalog,
):
    run = _generate_for_authority_test(structured_catalog)
    replacement = {
        **_source_catalog().source_identity,
        "relation_oid": 999,
    }
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: _approval_catalog(replacement),
    )

    response = _approve(run)

    assert response.status_code == 409
    assert response.json() == {
        "detail": router.GOLD_SOURCE_IDENTITY_CHANGED
    }
    state = _load_generated_state(run["run_id"])
    assert state.generation_source_identities == (
        _source_catalog().source_identity,
    )
    assert state.approved_revision is None


def test_structured_approval_rejects_generation_database_change(
    monkeypatch,
    structured_catalog,
):
    run = _generate_for_authority_test(structured_catalog)
    current = _approval_catalog()
    changed_database = GoldCatalogSnapshot(
        database_oid=current.database_oid,
        database_name="replacement_database",
        source_identities=current.source_identities,
        target_identity=current.target_identity,
        candidate_namespace_identity=current.candidate_namespace_identity,
    )
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: changed_database,
    )

    response = _approve(run)

    assert response.status_code == 409
    assert response.json()["detail"] == router.GOLD_SOURCE_IDENTITY_CHANGED


def test_structured_same_name_replacement_is_rejected_before_approval(
    monkeypatch,
    structured_catalog,
):
    run = _generate_for_authority_test(structured_catalog)
    generated = _source_catalog().source_identity
    same_name_replacement = {
        **generated,
        "relation_oid": generated["relation_oid"] + 1,
    }
    assert (
        same_name_replacement["schema"],
        same_name_replacement["relation_name"],
    ) == (generated["schema"], generated["relation_name"])
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: _approval_catalog(same_name_replacement),
    )

    response = _approve(run)

    assert response.status_code == 409
    assert response.json()["detail"] == router.GOLD_SOURCE_IDENTITY_CHANGED


def test_structured_execution_rejects_replacement_after_approval(
    monkeypatch,
    structured_catalog,
):
    run = _generate_for_authority_test(structured_catalog)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: _approval_catalog(),
    )
    assert _approve(run).status_code == 200
    state = _load_generated_state(run["run_id"])
    live_after_replacement = SimpleNamespace(
        database_oid=state.approval_snapshot["database"]["oid"],
        database_name=state.approval_snapshot["database"]["name"],
        source_identities=(
            {
                **state.source_identities[0],
                "relation_oid": state.source_identities[0]["relation_oid"] + 1,
            },
        ),
        target_identity=state.target_identity,
        candidate_namespace_identity=state.candidate_namespace_identity,
    )

    with pytest.raises(GoldExecutionRejected) as rejected:
        gold_execution._assert_live_approval_identity(
            state,
            live_after_replacement,
        )

    assert rejected.value.code == gold_execution.GOLD_SOURCE_IDENTITY_CHANGED


def test_structured_compiler_is_deterministic_and_passes_gold_validator():
    columns = {column.name: column for column in COLUMNS}
    definition = validate_structured_gold_definition(
        dimension="segment",
        aggregation="sum",
        expression={
            "type": "binary",
            "operator": "multiply",
            "left_column": "amount",
            "right_column": "units",
        },
        alias="weighted_amount",
        columns=columns,
    )
    compile_args = {
        "candidate_schema": SCHEMAS.gold_candidates,
        "candidate_name": "business_summary_candidate_run_deterministic",
        "source_schema": SCHEMAS.silver,
        "source_relation": "source_facts",
        "definition": definition,
    }

    first = compile_structured_gold_sql(**compile_args)
    second = compile_structured_gold_sql(**compile_args)

    assert first == second
    assert validate_generated_sql(
        first,
        expected_schema=SCHEMAS.gold_candidates,
        expected_table_name="business_summary",
        run_id="run_deterministic",
        mode="gold_ctas",
        selected_sources=((SCHEMAS.silver, "source_facts"),),
        expected_candidate_name=compile_args["candidate_name"],
    ) == first


def test_uci_country_sum_quantity_times_unit_price_regression():
    columns = {
        column.name: column
        for column in (
            _column(
                "country",
                type_name="text",
                supported_aggregations=("min", "max"),
            ),
            _column(
                "quantity",
                type_name="int4",
                supported_aggregations=("sum", "avg", "min", "max"),
            ),
            _column(
                "unit_price",
                type_name="numeric",
                supported_aggregations=("sum", "avg", "min", "max"),
            ),
        )
    }
    definition = validate_structured_gold_definition(
        dimension="country",
        aggregation="sum",
        expression={
            "type": "binary",
            "operator": "multiply",
            "left_column": "quantity",
            "right_column": "unit_price",
        },
        alias="total_sales",
        columns=columns,
    )

    sql_text = compile_structured_gold_sql(
        candidate_schema=SCHEMAS.gold_candidates,
        candidate_name="uci_summary_candidate_run_uci_regression",
        source_schema=SCHEMAS.silver,
        source_relation="online_retail_uci",
        definition=definition,
    )

    assert 'SELECT "country",' in sql_text
    assert (
        'SUM("quantity" * "unit_price") AS "total_sales"'
        in sql_text
    )
    assert 'GROUP BY "country"' in sql_text


def test_direct_definition_validation_rejects_division():
    with pytest.raises(
        StructuredGoldDefinitionError,
        match="binary operator is unsupported",
    ):
        validate_structured_gold_definition(
            dimension="segment",
            aggregation="sum",
            expression={
                "type": "binary",
                "operator": "divide",
                "left_column": "amount",
                "right_column": "units",
            },
            alias="ratio_value",
            columns={column.name: column for column in COLUMNS},
        )


def test_manual_controlled_route_keeps_its_original_provenance(monkeypatch):
    monkeypatch.setattr(router, "load_layer_schemas", lambda: SCHEMAS)
    monkeypatch.setattr(router, "check_table_exists", lambda schema, table: True)
    monkeypatch.setattr(
        router,
        "resolve_gold_approval_catalog",
        lambda **kwargs: _approval_catalog(),
    )

    response = client.post(
        "/api/v1/gold/generate",
        json={
            "target_table_name": "controlled_output",
            "silver_table_names": ["source_facts"],
            "business_requirement": "Preserve the controlled projection.",
        },
    )

    assert response.status_code == 200
    assert response.json()["generator_provenance"] == (
        router.MANUAL_CONTROLLED_GOLD_PROVENANCE
    )
    with get_connection() as conn:
        security = conn.execute(
            "SELECT review_snapshot_json FROM gold_security_state "
            "WHERE run_id = ?",
            (response.json()["run_id"],),
        ).fetchone()
    manual_review = json.loads(security["review_snapshot_json"])
    assert manual_review["snapshot_version"] == "gold-review-snapshot-v1"
    assert "generation_source_identities" not in manual_review
    review_response = client.get(
        f"/api/v1/gold/review/{response.json()['run_id']}"
    )
    assert review_response.status_code == 200
    assert router.GOLD_GENERATOR_TRUST.trusts_run(
        router.STRUCTURED_DETERMINISTIC_GOLD_PROVENANCE
    )
