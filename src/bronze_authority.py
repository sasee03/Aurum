from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from src.app_state.db import get_connection, validate_promoted_identity_json


class BronzeAuthorityError(ValueError):
    """Persisted Bronze authority is missing, malformed, or stale."""


BRONZE_INGEST_CLAIMED = "CLAIMED"
BRONZE_INGEST_CREATING = "CREATING"
BRONZE_INGEST_COMMIT_IN_PROGRESS = "COMMIT_IN_PROGRESS"
BRONZE_INGEST_READY = "READY"
BRONZE_INGEST_FAILED_RETRYABLE = "FAILED_RETRYABLE"
BRONZE_INGEST_RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


def _row_value(row: Mapping[str, Any], key: str) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def load_bronze_authority(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate one exact READY Connect-to-Bronze authority record."""
    if row is None:
        raise BronzeAuthorityError("Bronze ingest authority was not found")
    required_text = (
        "ingest_id",
        "project_id",
        "connection_id",
        "database_name",
        "source_schema",
        "source_relation",
        "bronze_schema",
        "bronze_relation",
        "created_at",
    )
    result: dict[str, Any] = {}
    for field in required_text:
        value = _row_value(row, field)
        if not isinstance(value, str) or not value.strip():
            raise BronzeAuthorityError(
                f"Bronze ingest authority has invalid {field}"
            )
        result[field] = value
    if _row_value(row, "status") != "READY":
        raise BronzeAuthorityError("Bronze ingest authority is not READY")
    try:
        created_at = datetime.fromisoformat(result["created_at"])
    except ValueError as exc:
        raise BronzeAuthorityError(
            "Bronze ingest authority has an invalid created_at"
        ) from exc
    if created_at.tzinfo is None:
        raise BronzeAuthorityError(
            "Bronze ingest authority created_at must include a timezone"
        )
    source_identity = validate_promoted_identity_json(
        _row_value(row, "source_identity_json")
    )
    bronze_identity = validate_promoted_identity_json(
        _row_value(row, "bronze_identity_json")
    )
    if source_identity is None or bronze_identity is None:
        raise BronzeAuthorityError(
            "Bronze ingest authority contains malformed relation identity"
        )
    if (
        source_identity["schema"] != result["source_schema"]
        or source_identity["relation_name"] != result["source_relation"]
        or bronze_identity["schema"] != result["bronze_schema"]
        or bronze_identity["relation_name"] != result["bronze_relation"]
        or source_identity["database_oid"] != bronze_identity["database_oid"]
    ):
        raise BronzeAuthorityError(
            "Bronze ingest authority relation coordinates are inconsistent"
        )
    result["status"] = "READY"
    result["source_identity"] = source_identity
    result["bronze_identity"] = bronze_identity
    return result


def get_bronze_authority(ingest_id: str) -> dict[str, Any]:
    if not isinstance(ingest_id, str) or not ingest_id.strip():
        raise BronzeAuthorityError("Bronze ingest ID is required")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM bronze_ingest_authority WHERE ingest_id = ?",
            (ingest_id,),
        ).fetchone()
    return load_bronze_authority(row)


def find_ready_bronze_authority(
    *,
    bronze_schema: str,
    bronze_relation: str,
) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM bronze_ingest_authority
            WHERE bronze_schema = ?
              AND bronze_relation = ?
              AND status = 'READY'
            """,
            (bronze_schema, bronze_relation),
        ).fetchone()
    if row is None:
        return None
    return load_bronze_authority(row)


def get_bronze_ingest_operation(ingest_id: str) -> dict[str, Any]:
    if not isinstance(ingest_id, str) or not ingest_id.strip():
        raise BronzeAuthorityError("Bronze ingest ID is required")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM bronze_ingest_operations WHERE ingest_id = ?",
            (ingest_id,),
        ).fetchone()
    if row is None:
        raise BronzeAuthorityError("Bronze ingest operation was not found")
    result = dict(row)
    for field in (
        "ingest_id",
        "project_id",
        "connection_id",
        "database_name",
        "source_schema",
        "source_relation",
        "bronze_schema",
        "bronze_relation",
        "status",
        "created_at",
        "updated_at",
    ):
        if not isinstance(result.get(field), str) or not result[field].strip():
            raise BronzeAuthorityError(
                f"Bronze ingest operation has invalid {field}"
            )
    for field in (
        "database_oid",
        "source_namespace_oid",
        "bronze_namespace_oid",
    ):
        value = result.get(field)
        if type(value) is not int or value <= 0:
            raise BronzeAuthorityError(
                f"Bronze ingest operation has invalid {field}"
            )
    for json_field, output_field in (
        ("source_identity_json", "source_identity"),
        ("provisional_bronze_identity_json", "provisional_bronze_identity"),
    ):
        raw = result.get(json_field)
        parsed = validate_promoted_identity_json(raw) if raw is not None else None
        if raw is not None and parsed is None:
            raise BronzeAuthorityError(
                f"Bronze ingest operation has malformed {json_field}"
            )
        result[output_field] = parsed
    return result


def claim_bronze_ingest_operation(
    *,
    ingest_id: str,
    project_id: str,
    connection_id: str,
    database_name: str,
    database_oid: int,
    source_schema: str,
    source_namespace_oid: int,
    source_relation: str,
    bronze_schema: str,
    bronze_namespace_oid: int,
    bronze_relation: str,
) -> dict[str, Any]:
    """Serialize one logical Bronze target before PostgreSQL mutation."""
    for field, value in {
        "database_oid": database_oid,
        "source_namespace_oid": source_namespace_oid,
        "bronze_namespace_oid": bronze_namespace_oid,
    }.items():
        if type(value) is not int or value <= 0:
            raise BronzeAuthorityError(
                f"Bronze ingest claim has invalid {field}"
            )
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            """
            SELECT ingest_id, status
            FROM bronze_ingest_operations
            WHERE bronze_schema = ?
              AND bronze_relation = ?
              AND status IN (
                  'CLAIMED', 'CREATING', 'COMMIT_IN_PROGRESS',
                  'RECONCILIATION_REQUIRED'
              )
            """,
            (bronze_schema, bronze_relation),
        ).fetchone()
        if active is not None:
            conn.rollback()
            raise BronzeAuthorityError(
                "Bronze ingest target already has an active or unresolved "
                f"operation ({active['ingest_id']}: {active['status']})"
            )
        retryable = conn.execute(
            """
            SELECT ingest_id
            FROM bronze_ingest_operations
            WHERE project_id = ?
              AND connection_id = ?
              AND database_name = ?
              AND database_oid = ?
              AND source_schema = ?
              AND source_namespace_oid = ?
              AND source_relation = ?
              AND bronze_schema = ?
              AND bronze_namespace_oid = ?
              AND bronze_relation = ?
              AND status = 'FAILED_RETRYABLE'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (
                project_id,
                connection_id,
                database_name,
                database_oid,
                source_schema,
                source_namespace_oid,
                source_relation,
                bronze_schema,
                bronze_namespace_oid,
                bronze_relation,
            ),
        ).fetchone()
        selected_ingest_id = retryable["ingest_id"] if retryable else ingest_id
        if retryable:
            update = conn.execute(
                """
                UPDATE bronze_ingest_operations
                SET status = 'CLAIMED',
                    source_identity_json = NULL,
                    provisional_bronze_identity_json = NULL,
                    failure_code = NULL,
                    updated_at = ?
                WHERE ingest_id = ?
                  AND status = 'FAILED_RETRYABLE'
                """,
                (now, selected_ingest_id),
            )
            if update.rowcount != 1:
                conn.rollback()
                raise BronzeAuthorityError("Bronze ingest retry claim failed")
        else:
            conn.execute(
                """
                INSERT INTO bronze_ingest_operations (
                    ingest_id, project_id, connection_id, database_name,
                    database_oid, source_schema, source_namespace_oid,
                    source_relation, bronze_schema, bronze_namespace_oid,
                    bronze_relation, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLAIMED', ?, ?)
                """,
                (
                    ingest_id,
                    project_id,
                    connection_id,
                    database_name,
                    database_oid,
                    source_schema,
                    source_namespace_oid,
                    source_relation,
                    bronze_schema,
                    bronze_namespace_oid,
                    bronze_relation,
                    now,
                    now,
                ),
            )
        conn.commit()
    return get_bronze_ingest_operation(selected_ingest_id)


def mark_bronze_ingest_creating(
    ingest_id: str,
    *,
    source_identity: dict[str, Any],
) -> None:
    source = validate_promoted_identity_json(source_identity)
    if source is None:
        raise BronzeAuthorityError("Bronze source identity is malformed")
    operation = get_bronze_ingest_operation(ingest_id)
    if (
        operation["status"] != BRONZE_INGEST_CLAIMED
        or source["database_oid"] != operation["database_oid"]
        or source["namespace_oid"] != operation["source_namespace_oid"]
        or source["schema"] != operation["source_schema"]
        or source["relation_name"] != operation["source_relation"]
        or source["relation_kind"] not in {"r", "p"}
    ):
        raise BronzeAuthorityError(
            "Bronze source identity does not match immutable ingest coordinates"
        )
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        update = conn.execute(
            """
            UPDATE bronze_ingest_operations
            SET status = 'CREATING',
                source_identity_json = ?,
                updated_at = ?
            WHERE ingest_id = ?
              AND status = 'CLAIMED'
            """,
            (
                json.dumps(source, sort_keys=True, separators=(",", ":")),
                now,
                ingest_id,
            ),
        )
        conn.commit()
    if update.rowcount != 1:
        raise BronzeAuthorityError("Bronze ingest creating transition failed")


def mark_bronze_ingest_commit_in_progress(
    ingest_id: str,
    *,
    bronze_identity: dict[str, Any],
) -> None:
    bronze = validate_promoted_identity_json(bronze_identity)
    if bronze is None:
        raise BronzeAuthorityError("Provisional Bronze identity is malformed")
    operation = get_bronze_ingest_operation(ingest_id)
    source = operation["source_identity"]
    if (
        operation["status"] != BRONZE_INGEST_CREATING
        or source is None
        or source["database_oid"] != operation["database_oid"]
        or source["namespace_oid"] != operation["source_namespace_oid"]
        or source["schema"] != operation["source_schema"]
        or source["relation_name"] != operation["source_relation"]
        or source["relation_kind"] not in {"r", "p"}
        or bronze["database_oid"] != operation["database_oid"]
        or bronze["database_oid"] != source["database_oid"]
        or bronze["namespace_oid"] != operation["bronze_namespace_oid"]
        or bronze["schema"] != operation["bronze_schema"]
        or bronze["relation_name"] != operation["bronze_relation"]
        or bronze["relation_kind"] != "r"
    ):
        raise BronzeAuthorityError(
            "Provisional Bronze identity does not match immutable ingest coordinates"
        )
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        update = conn.execute(
            """
            UPDATE bronze_ingest_operations
            SET status = 'COMMIT_IN_PROGRESS',
                provisional_bronze_identity_json = ?,
                failure_code = NULL,
                updated_at = ?
            WHERE ingest_id = ?
              AND status = 'CREATING'
            """,
            (
                json.dumps(bronze, sort_keys=True, separators=(",", ":")),
                now,
                ingest_id,
            ),
        )
        conn.commit()
    if update.rowcount != 1:
        raise BronzeAuthorityError(
            "Bronze provisional identity transition failed"
        )


def mark_bronze_ingest_outcome(
    ingest_id: str,
    *,
    status: str,
    failure_code: str,
) -> None:
    if status not in {
        BRONZE_INGEST_FAILED_RETRYABLE,
        BRONZE_INGEST_RECONCILIATION_REQUIRED,
    }:
        raise BronzeAuthorityError("Unsupported Bronze ingest outcome")
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        update = conn.execute(
            """
            UPDATE bronze_ingest_operations
            SET status = ?, failure_code = ?, updated_at = ?
            WHERE ingest_id = ?
              AND status IN (
                  'CLAIMED', 'CREATING', 'COMMIT_IN_PROGRESS',
                  'RECONCILIATION_REQUIRED'
              )
            """,
            (status, failure_code, now, ingest_id),
        )
        conn.commit()
    if update.rowcount != 1:
        raise BronzeAuthorityError("Bronze ingest outcome transition failed")


def validate_bronze_operation_identities(
    operation: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fail closed unless persisted identity evidence matches the operation claim."""
    source = operation.get("source_identity")
    bronze = operation.get("provisional_bronze_identity")
    if source is None or bronze is None:
        raise BronzeAuthorityError("Bronze finalization identity is missing")
    if (
        source["database_oid"] != operation["database_oid"]
        or source["namespace_oid"] != operation["source_namespace_oid"]
        or source["schema"] != operation["source_schema"]
        or source["relation_name"] != operation["source_relation"]
        or source["relation_kind"] not in {"r", "p"}
        or bronze["database_oid"] != operation["database_oid"]
        or bronze["database_oid"] != source["database_oid"]
        or bronze["namespace_oid"] != operation["bronze_namespace_oid"]
        or bronze["schema"] != operation["bronze_schema"]
        or bronze["relation_name"] != operation["bronze_relation"]
        or bronze["relation_kind"] != "r"
    ):
        raise BronzeAuthorityError(
            "Persisted Bronze identities do not match immutable ingest coordinates"
        )
    return source, bronze


def finalize_bronze_ingest_ready(ingest_id: str) -> dict[str, Any]:
    """Atomically publish exact authority and only then supersede the old READY."""
    try:
        operation = get_bronze_ingest_operation(ingest_id)
    except BronzeAuthorityError:
        try:
            mark_bronze_ingest_outcome(
                ingest_id,
                status=BRONZE_INGEST_RECONCILIATION_REQUIRED,
                failure_code="PERSISTED_OPERATION_IDENTITY_INVALID",
            )
        except BronzeAuthorityError:
            pass
        raise
    if operation["status"] == BRONZE_INGEST_READY:
        return get_bronze_authority(ingest_id)
    if operation["status"] not in {
        BRONZE_INGEST_COMMIT_IN_PROGRESS,
        BRONZE_INGEST_RECONCILIATION_REQUIRED,
    }:
        raise BronzeAuthorityError("Bronze ingest is not ready for finalization")
    try:
        source, bronze = validate_bronze_operation_identities(operation)
    except BronzeAuthorityError:
        mark_bronze_ingest_outcome(
            ingest_id,
            status=BRONZE_INGEST_RECONCILIATION_REQUIRED,
            failure_code="PERSISTED_IDENTITY_COORDINATE_MISMATCH",
        )
        raise
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE bronze_ingest_authority
            SET status = 'SUPERSEDED'
            WHERE bronze_schema = ?
              AND bronze_relation = ?
              AND status = 'READY'
            """,
            (operation["bronze_schema"], operation["bronze_relation"]),
        )
        conn.execute(
            """
            INSERT INTO bronze_ingest_authority (
                ingest_id, project_id, connection_id, database_name,
                source_schema, source_relation, source_identity_json,
                bronze_schema, bronze_relation, bronze_identity_json,
                status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'READY', ?, ?)
            """,
            (
                ingest_id,
                operation["project_id"],
                operation["connection_id"],
                operation["database_name"],
                operation["source_schema"],
                operation["source_relation"],
                json.dumps(source, sort_keys=True, separators=(",", ":")),
                operation["bronze_schema"],
                operation["bronze_relation"],
                json.dumps(bronze, sort_keys=True, separators=(",", ":")),
                now,
                now,
            ),
        )
        update = conn.execute(
            """
            UPDATE bronze_ingest_operations
            SET status = 'READY', failure_code = NULL, updated_at = ?
            WHERE ingest_id = ?
              AND status IN ('COMMIT_IN_PROGRESS', 'RECONCILIATION_REQUIRED')
            """,
            (now, ingest_id),
        )
        if update.rowcount != 1:
            conn.rollback()
            raise BronzeAuthorityError("Bronze READY transition failed")
        conn.commit()
    return get_bronze_authority(ingest_id)
