"""Builder tests for the Gemini producer feeding Structured Gold V1."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import api.silver_gold_router as router
from api.main import app
from src.app_state.db import get_connection
from src.gold_ai import (
    GoldAIAmbiguousInterpretation,
    GoldAIProposalDefinition,
    GoldAIProposalInvalid,
    GoldAIResponse,
    GoldAISupportedInterpretation,
    GoldAIUnavailable,
    GoldAIUnsupportedInterpretation,
    _parsed_interpretation,
    configured_gold_ai_model,
    interpret_gold_requirement,
)
from src.gold_catalog import GoldCatalogColumn, GoldCatalogSnapshot, StructuredGoldSourceCatalogSnapshot
from src.gold_security import GoldStateMalformed, approval_timestamp, new_gold_run_origin


client = TestClient(app)
SCHEMAS = SimpleNamespace(
    silver="configured_silver",
    gold="configured_gold",
    gold_candidates="configured_gold_candidates",
)


def _column(name: str, type_name: str, aggregations: tuple[str, ...]):
    return GoldCatalogColumn(
        name=name,
        type_oid={"text": 25, "numeric": 1700, "int4": 23}[type_name],
        type_schema="pg_catalog",
        type_name=type_name,
        type_kind="b",
        supported_aggregations=frozenset(aggregations),
    )


COLUMNS = (
    _column("segment", "text", ("min", "max")),
    _column("amount", "numeric", ("sum", "avg", "min", "max")),
    _column("units", "int4", ("sum", "avg", "min", "max")),
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


def _approval_catalog() -> GoldCatalogSnapshot:
    return GoldCatalogSnapshot(
        database_oid=101,
        database_name="isolated_test_database",
        source_identities=(_source_catalog().source_identity,),
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


@pytest.fixture
def ai_catalog(monkeypatch):
    monkeypatch.setattr(router, "load_layer_schemas", lambda: SCHEMAS)
    monkeypatch.setattr(
        router,
        "resolve_structured_gold_source",
        lambda **kwargs: _source_catalog(),
    )
    monkeypatch.setattr(router, "configured_gold_ai_model", lambda: "test-model")


def _payload() -> dict:
    return {
        "source": {"schema": SCHEMAS.silver, "table": "source_facts"},
        "target_table_name": "business_summary",
        "business_requirement": "Summarize the approved measure by segment.",
    }


def _supported(*, expression: dict | None = None, alias: str = "total_amount"):
    return GoldAISupportedInterpretation(
        verdict="SUPPORTED",
        definition=GoldAIProposalDefinition(
            dimension="segment",
            aggregation="sum",
            expression=expression or {"type": "column", "column": "amount"},
            alias=alias,
        ),
    )


def test_configured_model_defaults_and_honors_environment_override(monkeypatch):
    monkeypatch.delenv("AURUM_GEMINI_MODEL", raising=False)
    assert configured_gold_ai_model() == "gemini-2.5-flash"
    monkeypatch.setenv("AURUM_GEMINI_MODEL", "gemini-test-override")
    assert configured_gold_ai_model() == "gemini-test-override"


def test_missing_gemini_key_returns_safe_unavailable(monkeypatch, ai_catalog):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    response = client.post("/api/v1/gold/ai/generate", json=_payload())
    assert response.status_code == 503
    assert response.json() == {"detail": "GOLD_AI_UNAVAILABLE"}


def test_supported_column_uses_real_structured_gold_kernel(monkeypatch, ai_catalog):
    monkeypatch.setattr(router, "interpret_gold_requirement", lambda **kwargs: _supported())
    response = client.post("/api/v1/gold/ai/generate", json=_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "SUPPORTED"
    assert body["generator_provenance"] == router.STRUCTURED_DETERMINISTIC_GOLD_PROVENANCE
    assert body["generator_family"] == "gemini"
    assert body["generator_model"] == "test-model"
    assert 'SUM("amount") AS "total_amount"' in body["sql_text"]
    with get_connection() as conn:
        origin = conn.execute(
            "SELECT generator_family, generator_model FROM gold_run_origin WHERE run_id = ?",
            (body["run_id"],),
        ).fetchone()
    assert tuple(origin) == ("gemini", "test-model")
    assert client.get(f"/api/v1/gold/review/{body['run_id']}").status_code == 200


def test_supported_binary_expression_uses_real_compiler(monkeypatch, ai_catalog):
    monkeypatch.setattr(
        router,
        "interpret_gold_requirement",
        lambda **kwargs: _supported(
            expression={
                "type": "binary",
                "operator": "multiply",
                "left_column": "amount",
                "right_column": "units",
            },
            alias="weighted_amount",
        ),
    )
    response = client.post("/api/v1/gold/ai/generate", json=_payload())
    assert response.status_code == 200
    assert 'SUM("amount" * "units") AS "weighted_amount"' in response.json()["sql_text"]


def test_hallucinated_column_is_rejected_without_run(monkeypatch, ai_catalog):
    monkeypatch.setattr(
        router,
        "interpret_gold_requirement",
        lambda **kwargs: _supported(expression={"type": "column", "column": "invented"}),
    )
    response = client.post("/api/v1/gold/ai/generate", json=_payload())
    assert response.status_code == 422
    assert response.json() == {"detail": "GOLD_AI_PROPOSAL_INVALID"}
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM generated_sql_review").fetchone()[0]
    assert count == 0


@pytest.mark.parametrize(
    "interpretation, expected",
    [
        (
            GoldAIAmbiguousInterpretation(
                verdict="AMBIGUOUS",
                clarifying_question="Which approved amount should be summarized?",
                candidates=["amount", "units"],
            ),
            "AMBIGUOUS",
        ),
        (
            GoldAIUnsupportedInterpretation(
                verdict="UNSUPPORTED",
                reason="Filtering and top-N are not supported by Gold V1.",
            ),
            "UNSUPPORTED",
        ),
    ],
)
def test_non_supported_verdict_creates_no_run(monkeypatch, ai_catalog, interpretation, expected):
    monkeypatch.setattr(router, "interpret_gold_requirement", lambda **kwargs: interpretation)
    response = client.post("/api/v1/gold/ai/generate", json=_payload())
    assert response.status_code == 200
    assert response.json()["verdict"] == expected
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM generated_sql_review").fetchone()[0] == 0


@pytest.mark.parametrize("failure", [GoldAIUnavailable("down"), GoldAIProposalInvalid("bad")])
def test_provider_failure_is_safe(monkeypatch, ai_catalog, failure):
    monkeypatch.setattr(
        router,
        "interpret_gold_requirement",
        lambda **kwargs: (_ for _ in ()).throw(failure),
    )
    response = client.post("/api/v1/gold/ai/generate", json=_payload())
    assert response.status_code == (503 if isinstance(failure, GoldAIUnavailable) else 422)
    assert response.json()["detail"] in {"GOLD_AI_UNAVAILABLE", "GOLD_AI_PROPOSAL_INVALID"}


def test_malformed_parsed_response_is_safe():
    with pytest.raises(GoldAIProposalInvalid):
        _parsed_interpretation(None)


def test_provider_uses_gemini_structured_output_with_only_authorized_metadata(monkeypatch):
    calls = {}

    class FakeModels:
        def generate_content(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "verdict": "UNSUPPORTED",
                        "reason": "The request is outside Gold V1.",
                    }
                )
            )

    class FakeGemini:
        def __init__(self, *, api_key):
            calls["api_key"] = api_key
            self.models = FakeModels()

    fake_types = SimpleNamespace(GenerateContentConfig=lambda **kwargs: kwargs)
    fake_genai = SimpleNamespace(Client=FakeGemini, types=fake_types)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-do-not-persist")
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    interpretation = interpret_gold_requirement(
        source_schema=SCHEMAS.silver,
        source_relation="source_facts",
        columns=COLUMNS,
        business_requirement="Produce a bounded result.",
        model="test-model",
    )
    assert interpretation.verdict == "UNSUPPORTED"
    assert calls["model"] == "test-model"
    assert calls["config"]["response_schema"] is GoldAIResponse
    assert calls["config"]["response_mime_type"] == "application/json"
    prompt = json.loads(calls["contents"])
    assert prompt["authorized_silver_source"] == {
        "schema": SCHEMAS.silver,
        "relation": "source_facts",
        "columns": [
            {
                "name": "segment",
                "postgres_type": "pg_catalog.text",
                "supported_aggregations": ["max", "min"],
            },
            {
                "name": "amount",
                "postgres_type": "pg_catalog.numeric",
                "supported_aggregations": ["avg", "max", "min", "sum"],
            },
            {
                "name": "units",
                "postgres_type": "pg_catalog.int4",
                "supported_aggregations": ["avg", "max", "min", "sum"],
            },
        ],
    }
    assert "gemini-test-do-not-persist" not in calls["contents"]


@pytest.mark.parametrize(
    "definition",
    [
        {
            "dimension": "segment",
            "aggregation": "median",
            "expression": {"type": "column", "column": "amount"},
            "alias": "median_amount",
        },
        {
            "dimension": "segment",
            "aggregation": "sum",
            "expression": {"type": "column", "column": "amount"},
            "alias": "total_amount",
            "filter": {"column": "segment"},
        },
    ],
)
def test_unsupported_provider_operation_is_rejected_by_strict_contract(definition):
    with pytest.raises(ValidationError):
        GoldAIResponse.model_validate({"verdict": "SUPPORTED", "definition": definition})


def test_ai_request_rejects_raw_sql(monkeypatch, ai_catalog):
    payload = _payload()
    payload["sql"] = "SELECT * FROM secret"
    response = client.post("/api/v1/gold/ai/generate", json=payload)
    assert response.status_code == 422


def test_manual_structured_and_controlled_paths_remain_available(monkeypatch, ai_catalog):
    monkeypatch.setattr(router, "resolve_gold_approval_catalog", lambda **kwargs: _approval_catalog())
    structured = client.post(
        "/api/v1/gold/generate-structured",
        json={
            "source": {"schema": SCHEMAS.silver, "table": "source_facts"},
            "dimension": {"column": "segment"},
            "metric": {
                "aggregation": "sum",
                "expression": {"type": "column", "column": "amount"},
                "alias": "total_amount",
            },
            "target_table_name": "manual_summary",
            "business_purpose": "Manual structured Gold remains available.",
        },
    )
    assert structured.status_code == 200
    monkeypatch.setattr(router, "check_table_exists", lambda *args: True)
    controlled = client.post(
        "/api/v1/gold/generate",
        json={
            "target_table_name": "controlled_summary",
            "silver_table_names": ["source_facts"],
            "business_requirement": "Controlled Gold remains available.",
        },
    )
    assert controlled.status_code == 200


def test_gemini_key_is_not_persisted_or_returned(monkeypatch, ai_catalog):
    secret = "gemini-test-do-not-persist"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    monkeypatch.setattr(router, "interpret_gold_requirement", lambda **kwargs: _supported())
    response = client.post("/api/v1/gold/ai/generate", json=_payload())
    assert secret not in response.text
    with get_connection() as conn:
        sqlite_state = "\n".join(conn.iterdump())
    assert secret not in sqlite_state


@pytest.mark.parametrize(
    ("generator_family", "generator_model"),
    [("structured_manual", None), ("gemini", "gemini-2.5-flash")],
)
def test_origin_authority_accepts_structured_manual_and_gemini(
    generator_family,
    generator_model,
):
    source = _source_catalog()
    record = new_gold_run_origin(
        run_id=f"run_origin_{generator_family}",
        origin_provenance=router.STRUCTURED_DETERMINISTIC_GOLD_PROVENANCE,
        generator_family=generator_family,
        generator_model=generator_model,
        generation_database_identity={
            "oid": source.database_oid,
            "name": source.database_name,
        },
        generation_source_identities=[source.source_identity],
        selected_sources=[{"schema": SCHEMAS.silver, "table": "source_facts"}],
        created_at=approval_timestamp(),
    )
    assert record["generator_family"] == generator_family


def test_origin_authority_rejects_removed_openai_family():
    source = _source_catalog()
    with pytest.raises(GoldStateMalformed, match="generator family is unsupported"):
        new_gold_run_origin(
            run_id="run_origin_openai",
            origin_provenance=router.STRUCTURED_DETERMINISTIC_GOLD_PROVENANCE,
            generator_family="openai",
            generator_model="gpt-5.6-terra",
            generation_database_identity={
                "oid": source.database_oid,
                "name": source.database_name,
            },
            generation_source_identities=[source.source_identity],
            selected_sources=[{"schema": SCHEMAS.silver, "table": "source_facts"}],
            created_at=approval_timestamp(),
        )
