"""Serialized, exact-identity PostgreSQL promotion for approved Gold candidates."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Mapping

import psycopg
from psycopg import sql

from src.db_config import get_promotion_pool
from src.gold_security import GoldSecurityState, promotion_backup_name


logger = logging.getLogger(__name__)

GOLD_CANDIDATE_IDENTITY_CHANGED = "GOLD_CANDIDATE_IDENTITY_CHANGED"
GOLD_TARGET_IDENTITY_CHANGED = "GOLD_TARGET_IDENTITY_CHANGED"
GOLD_OVERWRITE_NOT_AUTHORIZED = "GOLD_OVERWRITE_NOT_AUTHORIZED"
GOLD_PROMOTION_FAILED = "GOLD_PROMOTION_FAILED"
GOLD_PROMOTION_AMBIGUOUS = "GOLD_PROMOTION_AMBIGUOUS"
GOLD_PROMOTION_RECONCILIATION_REQUIRED = (
    "GOLD_PROMOTION_RECONCILIATION_REQUIRED"
)
GOLD_PROMOTION_NOT_COMMITTED = "GOLD_PROMOTION_NOT_COMMITTED"
GOLD_DATABASE_UNAVAILABLE = "GOLD_DATABASE_UNAVAILABLE"

PRE_MUTATION = "PRE_MUTATION"
TRANSACTION_BODY = "TRANSACTION_BODY"
COMMIT_IN_PROGRESS = "COMMIT_IN_PROGRESS"
COMMIT_ACKNOWLEDGED = "COMMIT_ACKNOWLEDGED"
POST_COMMIT_POOL_CLEANUP = "POST_COMMIT_POOL_CLEANUP"


class GoldPromotionRejected(RuntimeError):
    """A deterministic, known-not-committed promotion failure."""

    def __init__(self, code: str, *, phase: str = PRE_MUTATION):
        super().__init__(code)
        self.code = code
        self.phase = phase


class GoldPromotionOutcomeUnknown(RuntimeError):
    """COMMIT was attempted but PostgreSQL acknowledgement was not received."""

    def __init__(self, result: "GoldPromotionResult"):
        super().__init__(GOLD_PROMOTION_AMBIGUOUS)
        self.result = result
        self.phase = COMMIT_IN_PROGRESS


@dataclass(frozen=True)
class GoldPromotionResult:
    final_target_identity: dict[str, Any]
    backup_identity: dict[str, Any] | None
    phase: str = COMMIT_ACKNOWLEDGED


@dataclass(frozen=True)
class GoldPromotionReconciliation:
    outcome: str
    final_target_identity: dict[str, Any] | None = None
    backup_identity: dict[str, Any] | None = None


def promotion_advisory_lock_key(
    *,
    database_oid: int,
    target_namespace_oid: int,
    target_schema: str,
    target_relation: str,
) -> int:
    """Return a deterministic signed 64-bit key for one logical Gold target.

    A versioned, canonical authority tuple is SHA-256 hashed and truncated to
    PostgreSQL's signed bigint advisory-lock namespace. A collision can only
    over-serialize two targets; all relation identity checks still run after
    the lock and therefore do not treat the lock key as ownership authority.
    """
    authority = json.dumps(
        [
            "aurum-gold-promotion-lock-v1",
            database_oid,
            target_namespace_oid,
            target_schema,
            target_relation,
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return int.from_bytes(
        hashlib.sha256(authority).digest()[:8],
        byteorder="big",
        signed=True,
    )


def _database_identity(cursor: Any) -> tuple[int, str]:
    cursor.execute(
        """
        SELECT oid, datname
        FROM pg_catalog.pg_database
        WHERE datname = pg_catalog.current_database()
        """
    )
    row = cursor.fetchone()
    if row is None:
        raise GoldPromotionRejected(GOLD_DATABASE_UNAVAILABLE)
    return int(row[0]), str(row[1])


def _namespace_oid(cursor: Any, schema: str) -> int | None:
    cursor.execute(
        """
        SELECT oid
        FROM pg_catalog.pg_namespace
        WHERE nspname = %s
        """,
        (schema,),
    )
    row = cursor.fetchone()
    return None if row is None else int(row[0])


def _relation_identity_by_name(
    cursor: Any,
    *,
    database_oid: int,
    namespace_oid: int,
    schema: str,
    relation_name: str,
) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT oid, relname, relkind
        FROM pg_catalog.pg_class
        WHERE relnamespace = %s
          AND relname = %s
        """,
        (namespace_oid, relation_name),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        "database_oid": database_oid,
        "namespace_oid": namespace_oid,
        "relation_oid": int(row[0]),
        "schema": schema,
        "relation_name": str(row[1]),
        "relation_kind": str(row[2]),
    }


def _relation_identity_by_oid(
    cursor: Any,
    *,
    database_oid: int,
    relation_oid: int,
) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT c.oid, c.relnamespace, n.nspname, c.relname, c.relkind
        FROM pg_catalog.pg_class AS c
        JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
        WHERE c.oid = %s
        """,
        (relation_oid,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        "database_oid": database_oid,
        "namespace_oid": int(row[1]),
        "relation_oid": int(row[0]),
        "schema": str(row[2]),
        "relation_name": str(row[3]),
        "relation_kind": str(row[4]),
    }


def _lock_relation(
    cursor: Any,
    identity: Mapping[str, Any],
) -> None:
    cursor.execute(
        sql.SQL("LOCK TABLE {}.{} IN ACCESS EXCLUSIVE MODE").format(
            sql.Identifier(identity["schema"]),
            sql.Identifier(identity["relation_name"]),
        )
    )


def _relation_identity_matches(
    live: Mapping[str, Any] | None,
    expected: Mapping[str, Any],
) -> bool:
    return live is not None and all(
        live.get(field) == expected.get(field)
        for field in (
            "database_oid",
            "namespace_oid",
            "relation_oid",
            "schema",
            "relation_name",
            "relation_kind",
        )
    )


def _approved_target_relation(
    state: GoldSecurityState,
) -> dict[str, Any] | None:
    assert state.target_identity is not None
    if state.target_identity["state"] == "absent":
        return None
    return {
        key: value
        for key, value in state.target_identity.items()
        if key != "state"
    }


def _validate_promotion_state(state: GoldSecurityState) -> None:
    if (
        state.approval_snapshot is None
        or state.approved_revision is None
        or state.target_identity is None
        or state.candidate_namespace_identity is None
        or state.candidate_identity is None
        or state.execution_claim_id is None
        or state.promotion_claim_id is None
        or state.promotion_claimed_at is None
        or state.overwrite_authorized is None
    ):
        raise GoldPromotionRejected(GOLD_PROMOTION_FAILED)
    if state.candidate_identity["relation_kind"] != "r":
        raise GoldPromotionRejected(GOLD_CANDIDATE_IDENTITY_CHANGED)
    approved_target = _approved_target_relation(state)
    if approved_target is not None:
        if not state.overwrite_authorized:
            raise GoldPromotionRejected(GOLD_OVERWRITE_NOT_AUTHORIZED)
        if approved_target["relation_kind"] != "r":
            raise GoldPromotionRejected(GOLD_TARGET_IDENTITY_CHANGED)
    elif state.overwrite_authorized:
        raise GoldPromotionRejected(GOLD_TARGET_IDENTITY_CHANGED)


def _validate_database_and_namespaces(
    cursor: Any,
    state: GoldSecurityState,
) -> tuple[int, int, int]:
    assert state.approval_snapshot is not None
    assert state.target_identity is not None
    assert state.candidate_namespace_identity is not None
    approved_database = state.approval_snapshot["database"]
    database_oid, database_name = _database_identity(cursor)
    if (
        database_oid != approved_database["oid"]
        or database_name != approved_database["name"]
    ):
        raise GoldPromotionRejected(GOLD_TARGET_IDENTITY_CHANGED)

    target_namespace_oid = _namespace_oid(cursor, state.target["schema"])
    if target_namespace_oid != state.target_identity["namespace_oid"]:
        raise GoldPromotionRejected(GOLD_TARGET_IDENTITY_CHANGED)
    candidate_namespace_oid = _namespace_oid(cursor, state.candidate["schema"])
    if (
        candidate_namespace_oid
        != state.candidate_namespace_identity["namespace_oid"]
    ):
        raise GoldPromotionRejected(GOLD_CANDIDATE_IDENTITY_CHANGED)
    return database_oid, target_namespace_oid, candidate_namespace_oid


def _deterministic_error(
    exc: Exception,
    *,
    phase: str,
) -> GoldPromotionRejected:
    if isinstance(exc, GoldPromotionRejected):
        return exc
    if isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError)):
        return GoldPromotionRejected(GOLD_DATABASE_UNAVAILABLE, phase=phase)
    return GoldPromotionRejected(GOLD_PROMOTION_FAILED, phase=phase)


def _promote_transaction(
    connection: Any,
    state: GoldSecurityState,
) -> GoldPromotionResult:
    _validate_promotion_state(state)
    transaction = connection.transaction()
    try:
        transaction.__enter__()
    except Exception as exc:
        raise _deterministic_error(exc, phase=PRE_MUTATION) from exc

    result: GoldPromotionResult | None = None
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_catalog.set_config(%s, %s, true)",
                ("search_path", "pg_catalog"),
            )
            assert state.approval_snapshot is not None
            assert state.target_identity is not None
            assert state.candidate_identity is not None
            assert state.promotion_claim_id is not None
            lock_key = promotion_advisory_lock_key(
                database_oid=state.approval_snapshot["database"]["oid"],
                target_namespace_oid=state.target_identity["namespace_oid"],
                target_schema=state.target["schema"],
                target_relation=state.target["table"],
            )
            cursor.execute(
                "SELECT pg_catalog.pg_advisory_xact_lock(%s)",
                (lock_key,),
            )
            (
                database_oid,
                target_namespace_oid,
                candidate_namespace_oid,
            ) = _validate_database_and_namespaces(cursor, state)

            candidate = _relation_identity_by_name(
                cursor,
                database_oid=database_oid,
                namespace_oid=candidate_namespace_oid,
                schema=state.candidate["schema"],
                relation_name=state.candidate["table"],
            )
            if not _relation_identity_matches(
                candidate,
                state.candidate_identity,
            ):
                raise GoldPromotionRejected(
                    GOLD_CANDIDATE_IDENTITY_CHANGED,
                    phase=TRANSACTION_BODY,
                )
            _lock_relation(cursor, state.candidate_identity)
            locked_candidate = _relation_identity_by_name(
                cursor,
                database_oid=database_oid,
                namespace_oid=candidate_namespace_oid,
                schema=state.candidate["schema"],
                relation_name=state.candidate["table"],
            )
            if not _relation_identity_matches(
                locked_candidate,
                state.candidate_identity,
            ):
                raise GoldPromotionRejected(
                    GOLD_CANDIDATE_IDENTITY_CHANGED,
                    phase=TRANSACTION_BODY,
                )

            approved_target = _approved_target_relation(state)
            live_target = _relation_identity_by_name(
                cursor,
                database_oid=database_oid,
                namespace_oid=target_namespace_oid,
                schema=state.target["schema"],
                relation_name=state.target["table"],
            )
            backup_name: str | None = None
            if approved_target is None:
                if live_target is not None:
                    raise GoldPromotionRejected(
                        GOLD_TARGET_IDENTITY_CHANGED,
                        phase=TRANSACTION_BODY,
                    )
            else:
                if not state.overwrite_authorized:
                    raise GoldPromotionRejected(
                        GOLD_OVERWRITE_NOT_AUTHORIZED,
                        phase=TRANSACTION_BODY,
                    )
                if not _relation_identity_matches(
                    live_target,
                    approved_target,
                ):
                    raise GoldPromotionRejected(
                        GOLD_TARGET_IDENTITY_CHANGED,
                        phase=TRANSACTION_BODY,
                    )
                _lock_relation(cursor, approved_target)
                locked_target = _relation_identity_by_name(
                    cursor,
                    database_oid=database_oid,
                    namespace_oid=target_namespace_oid,
                    schema=state.target["schema"],
                    relation_name=state.target["table"],
                )
                if not _relation_identity_matches(
                    locked_target,
                    approved_target,
                ):
                    raise GoldPromotionRejected(
                        GOLD_TARGET_IDENTITY_CHANGED,
                        phase=TRANSACTION_BODY,
                    )
                backup_name = promotion_backup_name(
                    state.target["table"],
                    state.promotion_claim_id,
                )
                if _relation_identity_by_name(
                    cursor,
                    database_oid=database_oid,
                    namespace_oid=target_namespace_oid,
                    schema=state.target["schema"],
                    relation_name=backup_name,
                ) is not None:
                    raise GoldPromotionRejected(
                        GOLD_PROMOTION_FAILED,
                        phase=TRANSACTION_BODY,
                    )
                cursor.execute(
                    sql.SQL("ALTER TABLE {}.{} RENAME TO {}").format(
                        sql.Identifier(state.target["schema"]),
                        sql.Identifier(state.target["table"]),
                        sql.Identifier(backup_name),
                    )
                )

            if state.candidate["schema"] != state.target["schema"]:
                cursor.execute(
                    sql.SQL("ALTER TABLE {}.{} SET SCHEMA {}").format(
                        sql.Identifier(state.candidate["schema"]),
                        sql.Identifier(state.candidate["table"]),
                        sql.Identifier(state.target["schema"]),
                    )
                )
            cursor.execute(
                sql.SQL("ALTER TABLE {}.{} RENAME TO {}").format(
                    sql.Identifier(state.target["schema"]),
                    sql.Identifier(state.candidate["table"]),
                    sql.Identifier(state.target["table"]),
                )
            )

            final_target = _relation_identity_by_name(
                cursor,
                database_oid=database_oid,
                namespace_oid=target_namespace_oid,
                schema=state.target["schema"],
                relation_name=state.target["table"],
            )
            expected_final = {
                **state.candidate_identity,
                "namespace_oid": target_namespace_oid,
                "schema": state.target["schema"],
                "relation_name": state.target["table"],
            }
            if not _relation_identity_matches(final_target, expected_final):
                raise GoldPromotionRejected(
                    GOLD_PROMOTION_FAILED,
                    phase=TRANSACTION_BODY,
                )

            backup_identity = None
            if approved_target is not None:
                assert backup_name is not None
                backup_identity = _relation_identity_by_name(
                    cursor,
                    database_oid=database_oid,
                    namespace_oid=target_namespace_oid,
                    schema=state.target["schema"],
                    relation_name=backup_name,
                )
                expected_backup = {
                    **approved_target,
                    "relation_name": backup_name,
                }
                if not _relation_identity_matches(
                    backup_identity,
                    expected_backup,
                ):
                    raise GoldPromotionRejected(
                        GOLD_PROMOTION_FAILED,
                        phase=TRANSACTION_BODY,
                    )
            result = GoldPromotionResult(
                final_target_identity=final_target,
                backup_identity=backup_identity,
                phase=TRANSACTION_BODY,
            )
    except Exception as exc:
        try:
            transaction.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:
            logger.warning(
                "Gold promotion rollback cleanup raised %s",
                type(exc).__name__,
            )
        rejection = _deterministic_error(exc, phase=TRANSACTION_BODY)
        if rejection is exc:
            raise
        raise rejection from exc

    assert result is not None
    try:
        # Once this call begins, a raised exception cannot prove rollback.
        transaction.__exit__(None, None, None)
    except Exception as exc:
        raise GoldPromotionOutcomeUnknown(result) from exc
    return GoldPromotionResult(
        final_target_identity=result.final_target_identity,
        backup_identity=result.backup_identity,
        phase=COMMIT_ACKNOWLEDGED,
    )


def promote_gold_candidate(
    state: GoldSecurityState,
    *,
    pool: Any | None = None,
) -> GoldPromotionResult:
    """Promote one claimed candidate through the bounded promotion-role pool."""
    active_pool = pool or get_promotion_pool()
    try:
        connection_context = active_pool.connection()
        connection = connection_context.__enter__()
    except Exception as exc:
        raise GoldPromotionRejected(GOLD_DATABASE_UNAVAILABLE) from exc

    result: GoldPromotionResult | None = None
    pending_error: Exception | None = None
    try:
        result = _promote_transaction(connection, state)
    except Exception as exc:
        pending_error = exc

    try:
        connection_context.__exit__(
            type(pending_error) if pending_error is not None else None,
            pending_error,
            pending_error.__traceback__ if pending_error is not None else None,
        )
    except Exception as cleanup_error:
        if result is not None:
            logger.warning(
                "Gold promotion commit was acknowledged; pool cleanup raised %s",
                type(cleanup_error).__name__,
            )
            return GoldPromotionResult(
                final_target_identity=result.final_target_identity,
                backup_identity=result.backup_identity,
                phase=POST_COMMIT_POOL_CLEANUP,
            )
        if pending_error is not None:
            raise pending_error from cleanup_error
        raise GoldPromotionRejected(GOLD_DATABASE_UNAVAILABLE) from cleanup_error

    if pending_error is not None:
        raise pending_error
    if result is None:
        raise GoldPromotionRejected(GOLD_PROMOTION_FAILED)
    return result


def _reconcile_snapshot(
    cursor: Any,
    state: GoldSecurityState,
) -> GoldPromotionReconciliation:
    _validate_promotion_state(state)
    assert state.approval_snapshot is not None
    assert state.target_identity is not None
    assert state.candidate_identity is not None
    assert state.promotion_claim_id is not None
    lock_key = promotion_advisory_lock_key(
        database_oid=state.approval_snapshot["database"]["oid"],
        target_namespace_oid=state.target_identity["namespace_oid"],
        target_schema=state.target["schema"],
        target_relation=state.target["table"],
    )
    cursor.execute(
        "SELECT pg_catalog.pg_advisory_xact_lock(%s)",
        (lock_key,),
    )
    try:
        (
            database_oid,
            target_namespace_oid,
            _candidate_namespace_oid,
        ) = _validate_database_and_namespaces(cursor, state)
    except GoldPromotionRejected:
        return GoldPromotionReconciliation("ambiguous")

    candidate_by_oid = _relation_identity_by_oid(
        cursor,
        database_oid=database_oid,
        relation_oid=state.candidate_identity["relation_oid"],
    )
    target_by_name = _relation_identity_by_name(
        cursor,
        database_oid=database_oid,
        namespace_oid=target_namespace_oid,
        schema=state.target["schema"],
        relation_name=state.target["table"],
    )
    expected_final = {
        **state.candidate_identity,
        "namespace_oid": target_namespace_oid,
        "schema": state.target["schema"],
        "relation_name": state.target["table"],
    }
    promoted = (
        _relation_identity_matches(candidate_by_oid, expected_final)
        and _relation_identity_matches(target_by_name, expected_final)
    )

    approved_target = _approved_target_relation(state)
    backup_identity = None
    if promoted and approved_target is not None:
        backup_name = promotion_backup_name(
            state.target["table"],
            state.promotion_claim_id,
        )
        backup_by_oid = _relation_identity_by_oid(
            cursor,
            database_oid=database_oid,
            relation_oid=approved_target["relation_oid"],
        )
        expected_backup = {
            **approved_target,
            "relation_name": backup_name,
        }
        if not _relation_identity_matches(backup_by_oid, expected_backup):
            promoted = False
        else:
            backup_identity = backup_by_oid
    if promoted:
        return GoldPromotionReconciliation(
            "promoted",
            final_target_identity=candidate_by_oid,
            backup_identity=backup_identity,
        )

    candidate_intact = _relation_identity_matches(
        candidate_by_oid,
        state.candidate_identity,
    )
    if approved_target is None:
        target_intact = target_by_name is None
    else:
        original_target_by_oid = _relation_identity_by_oid(
            cursor,
            database_oid=database_oid,
            relation_oid=approved_target["relation_oid"],
        )
        target_intact = (
            _relation_identity_matches(target_by_name, approved_target)
            and _relation_identity_matches(
                original_target_by_oid,
                approved_target,
            )
        )
    if candidate_intact and target_intact:
        return GoldPromotionReconciliation("not_committed")
    return GoldPromotionReconciliation("ambiguous")


def reconcile_gold_promotion(
    state: GoldSecurityState,
    *,
    pool: Any | None = None,
) -> GoldPromotionReconciliation:
    """Read PostgreSQL reality by OID; never mutate relations during ambiguity."""
    active_pool = pool or get_promotion_pool()
    try:
        with active_pool.connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_catalog.set_config(%s, %s, true)",
                        ("search_path", "pg_catalog"),
                    )
                    return _reconcile_snapshot(cursor, state)
    except GoldPromotionRejected:
        raise
    except Exception as exc:
        raise GoldPromotionRejected(GOLD_DATABASE_UNAVAILABLE) from exc
