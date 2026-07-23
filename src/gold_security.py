"""Strict immutable security-state contract for Gold review and approval."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence


GOLD_MODEL_VERSION = "gold-security-state-v1"
GOLD_POLICY_VERSION = "gold-ctas-policy-v2"
GOLD_SELECTED_SOURCES_VERSION = "gold-selected-sources-v1"
GOLD_REVIEW_SNAPSHOT_VERSION = "gold-review-snapshot-v1"
GOLD_APPROVAL_SNAPSHOT_VERSION = "gold-approval-snapshot-v1"
GOLD_PIPELINE = "gold"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REVISION_RE = re.compile(r"^[0-9a-f]{64}$")
_GENERATOR_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_RELATION_KINDS = frozenset({"r", "p"})
POSTGRES_IDENTIFIER_MAX_BYTES = 63


class GoldSecurityError(ValueError):
    """Base class for rejected Gold security state."""


class GoldStateMalformed(GoldSecurityError):
    """Persisted Gold security state is malformed or internally inconsistent."""


class GoldStateStale(GoldSecurityError):
    """The persisted review no longer describes the current logical plan."""


@dataclass(frozen=True)
class GoldSecurityState:
    run_id: str
    model_version: str
    policy_version: str
    business_requirement: str
    selected_sources: tuple[dict[str, str], ...]
    target: dict[str, str]
    candidate: dict[str, str]
    generator_provenance: str
    generator_version: str
    review_snapshot: dict[str, Any]
    review_revision: str
    approval_snapshot: dict[str, Any] | None
    approved_revision: str | None
    approved_at: str | None
    overwrite_authorized: bool | None
    source_identities: tuple[dict[str, Any], ...] | None
    target_identity: dict[str, Any] | None
    candidate_namespace_identity: dict[str, Any] | None
    execution_claim_id: str | None
    execution_claimed_at: str | None
    candidate_identity: dict[str, Any] | None
    execution_failure_code: str | None


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GoldStateMalformed("duplicate JSON object key")
        result[key] = value
    return result


def strict_json_loads(raw: Any, *, field: str) -> Any:
    if not isinstance(raw, str):
        raise GoldStateMalformed(f"{field} must be JSON text")
    try:
        return json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
    except GoldStateMalformed:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise GoldStateMalformed(f"{field} contains malformed JSON") from exc


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise GoldStateMalformed("security snapshot is not canonicalizable") from exc


def revision_for(snapshot: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()


def _require_exact_keys(
    value: Any,
    expected: set[str],
    *,
    field: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise GoldStateMalformed(f"{field} has invalid keys")
    return value


def _require_nonempty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GoldStateMalformed(f"{field} must be a non-empty string")
    return value


def _require_identifier(value: Any, *, field: str) -> str:
    value = _require_nonempty_string(value, field=field)
    if (
        not _IDENTIFIER_RE.fullmatch(value)
        or len(value.encode("utf-8")) > POSTGRES_IDENTIFIER_MAX_BYTES
    ):
        raise GoldStateMalformed(f"{field} is not a valid identifier")
    return value


def _require_revision(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _REVISION_RE.fullmatch(value):
        raise GoldStateMalformed(f"{field} is not a SHA-256 revision")
    return value


def _require_generator_token(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _GENERATOR_TOKEN_RE.fullmatch(value):
        raise GoldStateMalformed(f"{field} is not a valid generator token")
    return value


def _require_oid(value: Any, *, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise GoldStateMalformed(f"{field} is not a valid PostgreSQL OID")
    return value


def _relation_ref(value: Any, *, field: str) -> dict[str, str]:
    item = _require_exact_keys(value, {"schema", "table"}, field=field)
    return {
        "schema": _require_identifier(item["schema"], field=f"{field}.schema"),
        "table": _require_identifier(item["table"], field=f"{field}.table"),
    }


def selected_sources_document(
    sources: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    normalized = [_relation_ref(dict(item), field="selected source") for item in sources]
    normalized.sort(key=lambda item: (item["schema"], item["table"]))
    identities = [(item["schema"], item["table"]) for item in normalized]
    if not normalized:
        raise GoldStateMalformed("at least one selected source is required")
    if len(identities) != len(set(identities)):
        raise GoldStateMalformed("selected sources contain duplicates")
    return {
        "version": GOLD_SELECTED_SOURCES_VERSION,
        "sources": normalized,
    }


def parse_selected_sources(value: Any) -> tuple[dict[str, str], ...]:
    document = _require_exact_keys(
        value,
        {"version", "sources"},
        field="selected_sources",
    )
    if document["version"] != GOLD_SELECTED_SOURCES_VERSION:
        raise GoldStateMalformed("unsupported selected-sources version")
    if not isinstance(document["sources"], list):
        raise GoldStateMalformed("selected_sources.sources must be a list")
    canonical = selected_sources_document(document["sources"])
    if document != canonical:
        raise GoldStateMalformed("selected sources are not canonically ordered")
    return tuple(canonical["sources"])


def expected_candidate_name(target_name: str, run_id: str) -> str:
    target_name = _require_identifier(target_name, field="target_name")
    run_id = _require_identifier(run_id, field="run_id")
    return _require_identifier(
        f"{target_name}_candidate_{run_id}",
        field="candidate_name",
    )


def build_review_snapshot(
    *,
    run_id: str,
    sql_text: str,
    business_requirement: str,
    generator_provenance: str,
    generator_version: str,
    selected_sources: Iterable[Mapping[str, Any]],
    target_schema: str,
    target_name: str,
    candidate_schema: str,
    candidate_name: str,
    model_version: str = GOLD_MODEL_VERSION,
    policy_version: str = GOLD_POLICY_VERSION,
) -> dict[str, Any]:
    if model_version != GOLD_MODEL_VERSION:
        raise GoldStateMalformed("unsupported Gold security model version")
    if policy_version != GOLD_POLICY_VERSION:
        raise GoldStateMalformed("unsupported Gold policy version")
    run_id = _require_identifier(run_id, field="run_id")
    sql_text = _require_nonempty_string(sql_text, field="sql_text")
    business_requirement = _require_nonempty_string(
        business_requirement,
        field="business_requirement",
    )
    generator_provenance = _require_generator_token(
        generator_provenance,
        field="generator_provenance",
    )
    generator_version = _require_generator_token(
        generator_version,
        field="generator_version",
    )
    source_document = selected_sources_document(selected_sources)
    target = {
        "schema": _require_identifier(target_schema, field="target_schema"),
        "table": _require_identifier(target_name, field="target_name"),
    }
    candidate = {
        "schema": _require_identifier(candidate_schema, field="candidate_schema"),
        "table": _require_identifier(candidate_name, field="candidate_name"),
    }
    if candidate == target:
        raise GoldStateMalformed("candidate cannot equal the final target")
    if candidate["table"] != expected_candidate_name(target["table"], run_id):
        raise GoldStateMalformed("candidate identity is not server-controlled")
    return {
        "snapshot_version": GOLD_REVIEW_SNAPSHOT_VERSION,
        "model_version": model_version,
        "policy_version": policy_version,
        "pipeline": GOLD_PIPELINE,
        "run_id": run_id,
        "sql_text": sql_text,
        "business_requirement": business_requirement,
        "generator": {
            "provenance": generator_provenance,
            "version": generator_version,
        },
        "selected_sources": source_document["sources"],
        "target": target,
        "candidate": candidate,
    }


def _parse_review_snapshot(value: Any) -> dict[str, Any]:
    snapshot = _require_exact_keys(
        value,
        {
            "snapshot_version",
            "model_version",
            "policy_version",
            "pipeline",
            "run_id",
            "sql_text",
            "business_requirement",
            "generator",
            "selected_sources",
            "target",
            "candidate",
        },
        field="review_snapshot",
    )
    if snapshot["snapshot_version"] != GOLD_REVIEW_SNAPSHOT_VERSION:
        raise GoldStateMalformed("unsupported review snapshot version")
    if snapshot["model_version"] != GOLD_MODEL_VERSION:
        raise GoldStateMalformed("unsupported review model version")
    if snapshot["policy_version"] != GOLD_POLICY_VERSION:
        raise GoldStateMalformed("unsupported review policy version")
    if snapshot["pipeline"] != GOLD_PIPELINE:
        raise GoldStateMalformed("review snapshot has the wrong pipeline")
    generator = _require_exact_keys(
        snapshot["generator"],
        {"provenance", "version"},
        field="review_snapshot.generator",
    )
    if not isinstance(snapshot["selected_sources"], list):
        raise GoldStateMalformed("review selected sources must be a list")
    source_document = selected_sources_document(snapshot["selected_sources"])
    target = _relation_ref(snapshot["target"], field="review_snapshot.target")
    candidate = _relation_ref(
        snapshot["candidate"],
        field="review_snapshot.candidate",
    )
    normalized = {
        "snapshot_version": GOLD_REVIEW_SNAPSHOT_VERSION,
        "model_version": GOLD_MODEL_VERSION,
        "policy_version": GOLD_POLICY_VERSION,
        "pipeline": GOLD_PIPELINE,
        "run_id": _require_identifier(
            snapshot["run_id"],
            field="review_snapshot.run_id",
        ),
        "sql_text": _require_nonempty_string(
            snapshot["sql_text"],
            field="review_snapshot.sql_text",
        ),
        "business_requirement": _require_nonempty_string(
            snapshot["business_requirement"],
            field="review_snapshot.business_requirement",
        ),
        "generator": {
            "provenance": _require_generator_token(
                generator["provenance"],
                field="review_snapshot.generator.provenance",
            ),
            "version": _require_generator_token(
                generator["version"],
                field="review_snapshot.generator.version",
            ),
        },
        "selected_sources": source_document["sources"],
        "target": target,
        "candidate": candidate,
    }
    if snapshot != normalized:
        raise GoldStateMalformed("review snapshot is not in strict canonical form")
    return normalized


def new_gold_security_record(
    *,
    run_id: str,
    sql_text: str,
    business_requirement: str,
    generator_provenance: str,
    generator_version: str,
    selected_sources: Iterable[Mapping[str, Any]],
    target_schema: str,
    target_name: str,
    candidate_schema: str,
) -> dict[str, Any]:
    candidate_name = expected_candidate_name(target_name, run_id)
    source_document = selected_sources_document(selected_sources)
    review_snapshot = build_review_snapshot(
        run_id=run_id,
        sql_text=sql_text,
        business_requirement=business_requirement,
        generator_provenance=generator_provenance,
        generator_version=generator_version,
        selected_sources=source_document["sources"],
        target_schema=target_schema,
        target_name=target_name,
        candidate_schema=candidate_schema,
        candidate_name=candidate_name,
    )
    return {
        "run_id": run_id,
        "model_version": GOLD_MODEL_VERSION,
        "policy_version": GOLD_POLICY_VERSION,
        "business_requirement": business_requirement,
        "selected_sources_json": canonical_json(source_document),
        "target_schema": target_schema,
        "target_name": target_name,
        "candidate_schema": candidate_schema,
        "candidate_name": candidate_name,
        "generator_provenance": generator_provenance,
        "generator_version": generator_version,
        "review_snapshot_json": canonical_json(review_snapshot),
        "review_revision": revision_for(review_snapshot),
    }


def insert_gold_security_state(
    conn: sqlite3.Connection,
    record: Mapping[str, Any],
) -> None:
    """Insert a new immutable review state alongside an existing Gold run envelope."""
    conn.execute(
        """
        INSERT INTO gold_security_state (
            run_id, model_version, policy_version, business_requirement,
            selected_sources_json, target_schema, target_name,
            candidate_schema, candidate_name, generator_provenance,
            generator_version, review_snapshot_json, review_revision
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tuple(
            record[key]
            for key in (
                "run_id",
                "model_version",
                "policy_version",
                "business_requirement",
                "selected_sources_json",
                "target_schema",
                "target_name",
                "candidate_schema",
                "candidate_name",
                "generator_provenance",
                "generator_version",
                "review_snapshot_json",
                "review_revision",
            )
        ),
    )


def _parse_relation_identity(value: Any, *, field: str) -> dict[str, Any]:
    item = _require_exact_keys(
        value,
        {
            "database_oid",
            "namespace_oid",
            "relation_oid",
            "schema",
            "relation_name",
            "relation_kind",
        },
        field=field,
    )
    kind = _require_nonempty_string(item["relation_kind"], field=f"{field}.relation_kind")
    if kind not in _RELATION_KINDS:
        raise GoldStateMalformed(f"{field} has an unsupported relation kind")
    return {
        "database_oid": _require_oid(item["database_oid"], field=f"{field}.database_oid"),
        "namespace_oid": _require_oid(
            item["namespace_oid"],
            field=f"{field}.namespace_oid",
        ),
        "relation_oid": _require_oid(item["relation_oid"], field=f"{field}.relation_oid"),
        "schema": _require_identifier(item["schema"], field=f"{field}.schema"),
        "relation_name": _require_identifier(
            item["relation_name"],
            field=f"{field}.relation_name",
        ),
        "relation_kind": kind,
    }


def _parse_source_identities(
    value: Any,
    *,
    selected_sources: Sequence[Mapping[str, str]],
    database_oid: int | None = None,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or len(value) != len(selected_sources):
        raise GoldStateMalformed("source identities do not match selected sources")
    parsed = tuple(
        _parse_relation_identity(item, field="source identity")
        for item in value
    )
    refs = [(item["schema"], item["relation_name"]) for item in parsed]
    expected = [(item["schema"], item["table"]) for item in selected_sources]
    if refs != expected or len(refs) != len(set(refs)):
        raise GoldStateMalformed("source identities do not match selected sources")
    if database_oid is not None and any(
        item["database_oid"] != database_oid for item in parsed
    ):
        raise GoldStateMalformed("source database identity is inconsistent")
    return parsed


def _parse_target_identity(
    value: Any,
    *,
    target: Mapping[str, str],
    database_oid: int | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GoldStateMalformed("target identity must be an object")
    state = value.get("state")
    common = {
        "state",
        "database_oid",
        "namespace_oid",
        "schema",
        "relation_name",
    }
    if state == "absent":
        item = _require_exact_keys(value, common, field="target identity")
    elif state == "existing":
        item = _require_exact_keys(
            value,
            common | {"relation_oid", "relation_kind"},
            field="target identity",
        )
    else:
        raise GoldStateMalformed("target identity state is invalid")
    parsed: dict[str, Any] = {
        "state": state,
        "database_oid": _require_oid(
            item["database_oid"],
            field="target identity.database_oid",
        ),
        "namespace_oid": _require_oid(
            item["namespace_oid"],
            field="target identity.namespace_oid",
        ),
        "schema": _require_identifier(
            item["schema"],
            field="target identity.schema",
        ),
        "relation_name": _require_identifier(
            item["relation_name"],
            field="target identity.relation_name",
        ),
    }
    if state == "existing":
        parsed["relation_oid"] = _require_oid(
            item["relation_oid"],
            field="target identity.relation_oid",
        )
        kind = _require_nonempty_string(
            item["relation_kind"],
            field="target identity.relation_kind",
        )
        if kind not in _RELATION_KINDS:
            raise GoldStateMalformed("target identity has unsupported relation kind")
        parsed["relation_kind"] = kind
    if (parsed["schema"], parsed["relation_name"]) != (
        target["schema"],
        target["table"],
    ):
        raise GoldStateMalformed("target identity does not match the reviewed target")
    if database_oid is not None and parsed["database_oid"] != database_oid:
        raise GoldStateMalformed("target database identity is inconsistent")
    return parsed


def _parse_candidate_namespace_identity(
    value: Any,
    *,
    candidate: Mapping[str, str],
    database_oid: int | None = None,
) -> dict[str, Any]:
    item = _require_exact_keys(
        value,
        {"database_oid", "namespace_oid", "schema"},
        field="candidate namespace identity",
    )
    parsed = {
        "database_oid": _require_oid(
            item["database_oid"],
            field="candidate namespace identity.database_oid",
        ),
        "namespace_oid": _require_oid(
            item["namespace_oid"],
            field="candidate namespace identity.namespace_oid",
        ),
        "schema": _require_identifier(
            item["schema"],
            field="candidate namespace identity.schema",
        ),
    }
    if parsed["schema"] != candidate["schema"]:
        raise GoldStateMalformed(
            "candidate namespace identity does not match the reviewed candidate"
        )
    if database_oid is not None and parsed["database_oid"] != database_oid:
        raise GoldStateMalformed("candidate namespace database identity is inconsistent")
    return parsed


def build_approval_snapshot(
    *,
    review_snapshot: Mapping[str, Any],
    review_revision: str,
    database_oid: int,
    database_name: str,
    source_identities: Sequence[Mapping[str, Any]],
    target_identity: Mapping[str, Any],
    candidate_namespace_identity: Mapping[str, Any],
    overwrite_authorized: bool,
) -> dict[str, Any]:
    _require_revision(review_revision, field="review_revision")
    database_oid = _require_oid(database_oid, field="database_oid")
    database_name = _require_nonempty_string(database_name, field="database_name")
    if type(overwrite_authorized) is not bool:
        raise GoldStateMalformed("overwrite authorization must be boolean")
    selected_sources = review_snapshot.get("selected_sources")
    target = review_snapshot.get("target")
    candidate = review_snapshot.get("candidate")
    if (
        not isinstance(selected_sources, list)
        or not isinstance(target, dict)
        or not isinstance(candidate, dict)
    ):
        raise GoldStateMalformed("review snapshot is malformed")
    parsed_sources = _parse_source_identities(
        list(source_identities),
        selected_sources=selected_sources,
        database_oid=database_oid,
    )
    parsed_target = _parse_target_identity(
        dict(target_identity),
        target=target,
        database_oid=database_oid,
    )
    parsed_candidate_namespace = _parse_candidate_namespace_identity(
        dict(candidate_namespace_identity),
        candidate=candidate,
        database_oid=database_oid,
    )
    if parsed_target["state"] == "existing" and not overwrite_authorized:
        raise GoldStateMalformed("existing target requires overwrite authorization")
    if parsed_target["state"] == "absent" and overwrite_authorized:
        raise GoldStateMalformed("overwrite cannot be authorized for an absent target")
    return {
        "snapshot_version": GOLD_APPROVAL_SNAPSHOT_VERSION,
        "review_revision": review_revision,
        "review_snapshot": dict(review_snapshot),
        "database": {
            "oid": database_oid,
            "name": database_name,
        },
        "source_identities": list(parsed_sources),
        "target_identity": parsed_target,
        "candidate_namespace_identity": parsed_candidate_namespace,
        "overwrite_authorized": overwrite_authorized,
    }


def _parse_approval_snapshot(
    value: Any,
    *,
    state: GoldSecurityState,
) -> dict[str, Any]:
    snapshot = _require_exact_keys(
        value,
        {
            "snapshot_version",
            "review_revision",
            "review_snapshot",
            "database",
            "source_identities",
            "target_identity",
            "candidate_namespace_identity",
            "overwrite_authorized",
        },
        field="approval_snapshot",
    )
    if snapshot["snapshot_version"] != GOLD_APPROVAL_SNAPSHOT_VERSION:
        raise GoldStateMalformed("unsupported approval snapshot version")
    database = _require_exact_keys(
        snapshot["database"],
        {"oid", "name"},
        field="approval_snapshot.database",
    )
    rebuilt = build_approval_snapshot(
        review_snapshot=snapshot["review_snapshot"],
        review_revision=snapshot["review_revision"],
        database_oid=database["oid"],
        database_name=database["name"],
        source_identities=snapshot["source_identities"],
        target_identity=snapshot["target_identity"],
        candidate_namespace_identity=snapshot["candidate_namespace_identity"],
        overwrite_authorized=snapshot["overwrite_authorized"],
    )
    if snapshot["review_snapshot"] != state.review_snapshot:
        raise GoldStateMalformed("approval does not bind the persisted review snapshot")
    if snapshot["review_revision"] != state.review_revision:
        raise GoldStateMalformed("approval does not bind the persisted review revision")
    return rebuilt


def _row_value(row: Mapping[str, Any], key: str) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError) as exc:
        raise GoldStateMalformed(f"missing persisted field {key}") from exc


def load_gold_security_state(
    security_row: Mapping[str, Any] | None,
    envelope_row: Mapping[str, Any],
    *,
    configured_silver_schema: str,
    configured_gold_schema: str,
    configured_candidate_schema: str,
) -> GoldSecurityState:
    """Strictly decode state and prove it still matches its shared run envelope."""
    if security_row is None:
        raise GoldStateMalformed("Gold run has no companion security state")
    run_id = _require_identifier(_row_value(security_row, "run_id"), field="run_id")
    model_version = _row_value(security_row, "model_version")
    policy_version = _row_value(security_row, "policy_version")
    if model_version != GOLD_MODEL_VERSION:
        raise GoldStateMalformed("unsupported Gold security model version")
    if policy_version != GOLD_POLICY_VERSION:
        raise GoldStateMalformed("unsupported Gold policy version")
    business_requirement = _require_nonempty_string(
        _row_value(security_row, "business_requirement"),
        field="business_requirement",
    )
    selected_sources_raw = strict_json_loads(
        _row_value(security_row, "selected_sources_json"),
        field="selected_sources_json",
    )
    selected_sources = parse_selected_sources(selected_sources_raw)
    target = {
        "schema": _require_identifier(
            _row_value(security_row, "target_schema"),
            field="target_schema",
        ),
        "table": _require_identifier(
            _row_value(security_row, "target_name"),
            field="target_name",
        ),
    }
    candidate = {
        "schema": _require_identifier(
            _row_value(security_row, "candidate_schema"),
            field="candidate_schema",
        ),
        "table": _require_identifier(
            _row_value(security_row, "candidate_name"),
            field="candidate_name",
        ),
    }
    if candidate == target:
        raise GoldStateMalformed("candidate cannot equal the final target")
    if candidate["table"] != expected_candidate_name(target["table"], run_id):
        raise GoldStateMalformed("candidate identity is not server-controlled")
    provenance = _require_generator_token(
        _row_value(security_row, "generator_provenance"),
        field="generator_provenance",
    )
    generator_version = _require_generator_token(
        _row_value(security_row, "generator_version"),
        field="generator_version",
    )
    review_snapshot = _parse_review_snapshot(
        strict_json_loads(
            _row_value(security_row, "review_snapshot_json"),
            field="review_snapshot_json",
        )
    )
    review_revision = _require_revision(
        _row_value(security_row, "review_revision"),
        field="review_revision",
    )
    if _row_value(envelope_row, "run_id") != run_id:
        raise GoldStateMalformed("companion run does not match its envelope")
    if _row_value(envelope_row, "table_name") != target["table"]:
        raise GoldStateStale("Gold target changed after review")
    if _row_value(envelope_row, "generator_provenance") != provenance:
        raise GoldStateStale("Gold generator provenance changed after review")
    if _row_value(envelope_row, "candidate_schema") != candidate["schema"]:
        raise GoldStateStale("Gold candidate schema changed after review")
    if target["schema"] != _require_identifier(
        configured_gold_schema,
        field="configured_gold_schema",
    ):
        raise GoldStateStale("configured Gold schema changed after review")
    if candidate["schema"] != _require_identifier(
        configured_candidate_schema,
        field="configured_candidate_schema",
    ):
        raise GoldStateStale("configured Gold candidate schema changed after review")
    configured_silver_schema = _require_identifier(
        configured_silver_schema,
        field="configured_silver_schema",
    )
    if any(item["schema"] != configured_silver_schema for item in selected_sources):
        raise GoldStateStale("configured Silver schema changed after review")
    rebuilt_review = build_review_snapshot(
        run_id=run_id,
        sql_text=_row_value(envelope_row, "sql_text"),
        business_requirement=business_requirement,
        generator_provenance=provenance,
        generator_version=generator_version,
        selected_sources=selected_sources,
        target_schema=target["schema"],
        target_name=target["table"],
        candidate_schema=candidate["schema"],
        candidate_name=candidate["table"],
        model_version=model_version,
        policy_version=policy_version,
    )
    if review_snapshot != rebuilt_review:
        raise GoldStateStale("persisted review snapshot is stale")
    if canonical_json(review_snapshot) != _row_value(
        security_row,
        "review_snapshot_json",
    ):
        raise GoldStateMalformed("review snapshot JSON is not canonical")
    if revision_for(rebuilt_review) != review_revision:
        raise GoldStateStale("persisted review revision is stale")

    approval_values = {
        "approval_snapshot_json": _row_value(security_row, "approval_snapshot_json"),
        "approved_revision": _row_value(security_row, "approved_revision"),
        "approved_at": _row_value(security_row, "approved_at"),
        "overwrite_authorized": _row_value(security_row, "overwrite_authorized"),
        "source_identities_json": _row_value(security_row, "source_identities_json"),
        "target_identity_json": _row_value(security_row, "target_identity_json"),
    }
    present = {key: value is not None for key, value in approval_values.items()}
    if any(present.values()) and not all(present.values()):
        raise GoldStateMalformed("approval state is only partially persisted")

    state = GoldSecurityState(
        run_id=run_id,
        model_version=model_version,
        policy_version=policy_version,
        business_requirement=business_requirement,
        selected_sources=selected_sources,
        target=target,
        candidate=candidate,
        generator_provenance=provenance,
        generator_version=generator_version,
        review_snapshot=review_snapshot,
        review_revision=review_revision,
        approval_snapshot=None,
        approved_revision=None,
        approved_at=None,
        overwrite_authorized=None,
        source_identities=None,
        target_identity=None,
        candidate_namespace_identity=None,
        execution_claim_id=None,
        execution_claimed_at=None,
        candidate_identity=None,
        execution_failure_code=None,
    )
    if not any(present.values()):
        return state

    approval_snapshot = strict_json_loads(
        approval_values["approval_snapshot_json"],
        field="approval_snapshot_json",
    )
    approved_revision = _require_revision(
        approval_values["approved_revision"],
        field="approved_revision",
    )
    approved_at = _require_nonempty_string(
        approval_values["approved_at"],
        field="approved_at",
    )
    try:
        parsed_timestamp = datetime.fromisoformat(approved_at)
    except ValueError as exc:
        raise GoldStateMalformed("approved_at is not an ISO-8601 timestamp") from exc
    if parsed_timestamp.tzinfo is None:
        raise GoldStateMalformed("approved_at must include a timezone")
    overwrite_raw = approval_values["overwrite_authorized"]
    if type(overwrite_raw) is not int or overwrite_raw not in (0, 1):
        raise GoldStateMalformed("overwrite authorization is malformed")
    overwrite_authorized = bool(overwrite_raw)
    source_identities_value = strict_json_loads(
        approval_values["source_identities_json"],
        field="source_identities_json",
    )
    source_identities = _parse_source_identities(
        source_identities_value,
        selected_sources=selected_sources,
    )
    target_identity_value = strict_json_loads(
        approval_values["target_identity_json"],
        field="target_identity_json",
    )
    target_identity = _parse_target_identity(
        target_identity_value,
        target=target,
    )
    approved_state = GoldSecurityState(
        **{
            **state.__dict__,
            "approval_snapshot": approval_snapshot,
            "approved_revision": approved_revision,
            "approved_at": approved_at,
            "overwrite_authorized": overwrite_authorized,
            "source_identities": source_identities,
            "target_identity": target_identity,
            "candidate_namespace_identity": None,
        }
    )
    parsed_approval = _parse_approval_snapshot(
        approval_snapshot,
        state=approved_state,
    )
    if canonical_json(parsed_approval) != approval_values["approval_snapshot_json"]:
        raise GoldStateMalformed("approval snapshot JSON is not canonical")
    if revision_for(parsed_approval) != approved_revision:
        raise GoldStateMalformed("approved revision does not match approval snapshot")
    if list(source_identities) != parsed_approval["source_identities"]:
        raise GoldStateMalformed("captured source identities are inconsistent")
    if target_identity != parsed_approval["target_identity"]:
        raise GoldStateMalformed("captured target identity is inconsistent")
    candidate_namespace_identity = parsed_approval[
        "candidate_namespace_identity"
    ]
    if overwrite_authorized != parsed_approval["overwrite_authorized"]:
        raise GoldStateMalformed("captured overwrite authorization is inconsistent")
    approved_state = GoldSecurityState(
        **{
            **approved_state.__dict__,
            "approval_snapshot": parsed_approval,
            "candidate_namespace_identity": candidate_namespace_identity,
        }
    )
    execution_claim_id = _row_value(security_row, "execution_claim_id")
    execution_claimed_at = _row_value(security_row, "execution_claimed_at")
    candidate_identity_json = _row_value(security_row, "candidate_identity_json")
    execution_failure_code = _row_value(security_row, "execution_failure_code")
    execution_values = (
        execution_claim_id,
        execution_claimed_at,
        candidate_identity_json,
        execution_failure_code,
    )
    if all(value is None for value in execution_values):
        return approved_state
    execution_claim_id = _require_generator_token(
        execution_claim_id,
        field="execution_claim_id",
    )
    execution_claimed_at = _require_nonempty_string(
        execution_claimed_at,
        field="execution_claimed_at",
    )
    try:
        claimed_timestamp = datetime.fromisoformat(execution_claimed_at)
    except ValueError as exc:
        raise GoldStateMalformed(
            "execution_claimed_at is not an ISO-8601 timestamp"
        ) from exc
    if claimed_timestamp.tzinfo is None:
        raise GoldStateMalformed("execution_claimed_at must include a timezone")

    status = _row_value(envelope_row, "status")
    candidate_identity = None
    if candidate_identity_json is not None:
        candidate_identity = _parse_relation_identity(
            strict_json_loads(
                candidate_identity_json,
                field="candidate_identity_json",
            ),
            field="candidate identity",
        )
        if (
            candidate_identity["schema"],
            candidate_identity["relation_name"],
        ) != (candidate["schema"], candidate["table"]):
            raise GoldStateMalformed(
                "candidate identity does not match the approved candidate"
            )
        if candidate_identity["relation_kind"] != "r":
            raise GoldStateMalformed("candidate identity is not an ordinary table")
        if (
            candidate_identity["database_oid"]
            != approved_state.approval_snapshot["database"]["oid"]
        ):
            raise GoldStateMalformed(
                "candidate database identity is inconsistent"
            )
        if (
            candidate_identity["namespace_oid"]
            != approved_state.candidate_namespace_identity["namespace_oid"]
        ):
            raise GoldStateMalformed(
                "candidate namespace identity is inconsistent"
            )
    if execution_failure_code is not None:
        execution_failure_code = _require_generator_token(
            execution_failure_code,
            field="execution_failure_code",
        )
    if status == "EXECUTING":
        if candidate_identity is not None:
            raise GoldStateMalformed("executing state cannot contain candidate identity")
    elif status == "PROMOTING":
        if candidate_identity is None or execution_failure_code is not None:
            raise GoldStateMalformed("promoting state is internally inconsistent")
    elif status == "EXECUTION_FAILED":
        if candidate_identity is not None or execution_failure_code is None:
            raise GoldStateMalformed("failed execution state is internally inconsistent")
    else:
        raise GoldStateMalformed("execution metadata is invalid for run status")
    return GoldSecurityState(
        **{
            **approved_state.__dict__,
            "execution_claim_id": execution_claim_id,
            "execution_claimed_at": execution_claimed_at,
            "candidate_identity": candidate_identity,
            "execution_failure_code": execution_failure_code,
        }
    )


def load_persisted_gold_security_state(
    security_row: Mapping[str, Any] | None,
    envelope_row: Mapping[str, Any],
) -> GoldSecurityState:
    """Strictly validate immutable state without consulting current layer config.

    This is reserved for returning an already persisted approval. It validates the
    complete companion state and envelope while treating the reviewed schemas as
    immutable inputs, so an HTTP retry does not become a new authorization against
    current configuration or PostgreSQL state.
    """
    if security_row is None:
        raise GoldStateMalformed("Gold run has no companion security state")
    selected_sources = parse_selected_sources(
        strict_json_loads(
            _row_value(security_row, "selected_sources_json"),
            field="selected_sources_json",
        )
    )
    return load_gold_security_state(
        security_row,
        envelope_row,
        configured_silver_schema=selected_sources[0]["schema"],
        configured_gold_schema=_row_value(security_row, "target_schema"),
        configured_candidate_schema=_row_value(
            security_row,
            "candidate_schema",
        ),
    )


def approval_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
