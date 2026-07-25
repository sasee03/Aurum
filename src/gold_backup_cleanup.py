"""Exact-identity cleanup for retained Gold promotion backups."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

import psycopg
from psycopg import sql

from src.app_state.db import get_connection
from src.db_config import get_promotion_pool
from src.gold_security import (
    GoldSecurityState,
    GoldStateMalformed,
    GoldStateStale,
    load_persisted_gold_security_state,
)

logger = logging.getLogger(__name__)

GOLD_BACKUP_REMOVED = "removed"
GOLD_BACKUP_MISSING = "missing"
GOLD_BACKUP_IDENTITY_MISMATCH = "identity_mismatch"


class GoldBackupCleanupRejected(RuntimeError):
    """Cleanup lacks valid persisted lifecycle or exact-identity authority."""


class GoldBackupCleanupOutcomeUnknown(RuntimeError):
    """The DROP ran, but PostgreSQL did not acknowledge the commit outcome."""


class GoldBackupCleanupStateRecordingFailed(RuntimeError):
    """PostgreSQL outcome is known, but closing app-state eligibility failed."""


@dataclass(frozen=True)
class GoldBackupCleanupResult:
    run_id: str
    outcome: str
    backup_identity: dict[str, Any]


_IDENTITY_FIELDS = (
    "database_oid",
    "namespace_oid",
    "relation_oid",
    "schema",
    "relation_name",
    "relation_kind",
)


def _identity_matches(
    live: Mapping[str, Any] | None,
    expected: Mapping[str, Any],
) -> bool:
    return live is not None and all(
        live.get(field) == expected.get(field)
        for field in _IDENTITY_FIELDS
    )


def _relation_by_name(
    cursor: Any,
    *,
    schema: str,
    relation_name: str,
) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT database.oid,
               namespace.oid,
               relation.oid,
               namespace.nspname,
               relation.relname,
               relation.relkind
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_database AS database
          ON database.datname = pg_catalog.current_database()
        WHERE namespace.nspname = %s
          AND relation.relname = %s
        """,
        (schema, relation_name),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        "database_oid": int(row[0]),
        "namespace_oid": int(row[1]),
        "relation_oid": int(row[2]),
        "schema": str(row[3]),
        "relation_name": str(row[4]),
        "relation_kind": str(row[5]),
    }


def _relation_by_oid(
    cursor: Any,
    *,
    database_oid: int,
    relation_oid: int,
) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT database.oid,
               namespace.oid,
               relation.oid,
               namespace.nspname,
               relation.relname,
               relation.relkind
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_database AS database
          ON database.datname = pg_catalog.current_database()
        WHERE database.oid = %s
          AND relation.oid = %s
        """,
        (database_oid, relation_oid),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        "database_oid": int(row[0]),
        "namespace_oid": int(row[1]),
        "relation_oid": int(row[2]),
        "schema": str(row[3]),
        "relation_name": str(row[4]),
        "relation_kind": str(row[5]),
    }


def _load_cleanup_state(run_id: str) -> GoldSecurityState:
    with get_connection() as conn:
        envelope = conn.execute(
            """
            SELECT run_id, table_name, sql_text, planned_changes_json,
                   status, candidate_schema, generator_provenance
            FROM generated_sql_review
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        security = conn.execute(
            "SELECT * FROM gold_security_state WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if envelope is None or security is None:
        raise GoldBackupCleanupRejected("Gold run was not found")
    try:
        state = load_persisted_gold_security_state(security, envelope)
    except (GoldStateMalformed, GoldStateStale) as exc:
        raise GoldBackupCleanupRejected(
            "Gold backup cleanup state is malformed or stale"
        ) from exc
    if (
        envelope["status"] != "PROMOTED"
        or state.backup_identity is None
        or state.backup_cleanup_eligible is not True
        or state.promotion_committed_at is None
    ):
        raise GoldBackupCleanupRejected(
            "Gold backup is not explicitly cleanup-eligible"
        )
    return state


def authorize_gold_backup_cleanup(run_id: str) -> None:
    """Persist explicit cleanup eligibility for one strictly promoted run."""
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        envelope = conn.execute(
            """
            SELECT run_id, table_name, sql_text, planned_changes_json,
                   status, candidate_schema, generator_provenance
            FROM generated_sql_review
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        security = conn.execute(
            "SELECT * FROM gold_security_state WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if envelope is None or security is None:
            conn.rollback()
            raise GoldBackupCleanupRejected("Gold run was not found")
        try:
            state = load_persisted_gold_security_state(security, envelope)
        except (GoldStateMalformed, GoldStateStale) as exc:
            conn.rollback()
            raise GoldBackupCleanupRejected(
                "Gold backup cleanup state is malformed or stale"
            ) from exc
        if (
            envelope["status"] != "PROMOTED"
            or state.backup_identity is None
            or state.promotion_committed_at is None
            or state.backup_cleanup_eligible not in (False, True)
        ):
            conn.rollback()
            raise GoldBackupCleanupRejected(
                "Gold run has no strictly promoted backup eligible for cleanup"
            )
        if state.backup_cleanup_eligible is False:
            updated = conn.execute(
                """
                UPDATE gold_security_state
                SET backup_cleanup_eligible = 1
                WHERE run_id = ?
                  AND backup_cleanup_eligible = 0
                  AND backup_identity_json IS NOT NULL
                  AND promoted_target_identity_json IS NOT NULL
                  AND promotion_committed_at IS NOT NULL
                  AND promotion_failure_code IS NULL
                  AND EXISTS (
                      SELECT 1
                      FROM generated_sql_review
                      WHERE generated_sql_review.run_id =
                            gold_security_state.run_id
                        AND generated_sql_review.status = 'PROMOTED'
                  )
                """,
                (run_id,),
            )
            if updated.rowcount != 1:
                conn.rollback()
                raise GoldBackupCleanupRejected(
                    "Gold backup cleanup eligibility claim failed"
                )
        conn.commit()


def _clear_cleanup_eligibility(run_id: str) -> None:
    with get_connection() as conn:
        updated = conn.execute(
            """
            UPDATE gold_security_state
            SET backup_cleanup_eligible = 0
            WHERE run_id = ?
              AND backup_cleanup_eligible = 1
              AND EXISTS (
                  SELECT 1
                  FROM generated_sql_review
                  WHERE generated_sql_review.run_id =
                        gold_security_state.run_id
                    AND generated_sql_review.status = 'PROMOTED'
              )
            """,
            (run_id,),
        )
        if updated.rowcount != 1:
            conn.rollback()
            raise GoldBackupCleanupRejected(
                "Gold backup cleanup eligibility could not be closed"
            )
        conn.commit()


def cleanup_gold_backup(
    run_id: str,
    *,
    pool: Any | None = None,
) -> GoldBackupCleanupResult:
    """Drop one exact persisted backup after lock-time identity revalidation."""
    state = _load_cleanup_state(run_id)
    assert state.backup_identity is not None
    assert state.approval_snapshot is not None
    expected = state.backup_identity
    if expected["relation_kind"] != "r":
        raise GoldBackupCleanupRejected(
            "Gold backup cleanup authority is not a base table"
        )

    active_pool = pool or get_promotion_pool()
    try:
        context = active_pool.connection()
        connection = context.__enter__()
    except Exception as exc:
        raise GoldBackupCleanupRejected(
            "Gold backup cleanup database is unavailable"
        ) from exc

    result: str | None = None
    pending_error: Exception | None = None
    drop_executed = False
    transaction = connection.transaction()
    try:
        transaction.__enter__()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_catalog.set_config(%s, %s, true)",
                ("search_path", "pg_catalog"),
            )
            cursor.execute(
                "SELECT database.oid, database.datname "
                "FROM pg_catalog.pg_database AS database "
                "WHERE database.datname = pg_catalog.current_database()"
            )
            database_row = cursor.fetchone()
            approved_database = state.approval_snapshot["database"]
            expected_oid = approved_database.get("oid")
            if (
                database_row is None
                or (expected_oid is not None and int(database_row[0]) != expected_oid)
                or str(database_row[1]) != approved_database["name"]
            ):
                raise GoldBackupCleanupRejected(
                    "Gold backup database identity changed"
                )

            by_oid = _relation_by_oid(
                cursor,
                database_oid=expected["database_oid"],
                relation_oid=expected["relation_oid"],
            )
            by_name = _relation_by_name(
                cursor,
                schema=expected["schema"],
                relation_name=expected["relation_name"],
            )
            if by_oid is None and by_name is None:
                result = GOLD_BACKUP_MISSING
            elif (
                not _identity_matches(by_oid, expected)
                or not _identity_matches(by_name, expected)
            ):
                result = GOLD_BACKUP_IDENTITY_MISMATCH
            else:
                cursor.execute(
                    sql.SQL(
                        "LOCK TABLE {}.{} IN ACCESS EXCLUSIVE MODE"
                    ).format(
                        sql.Identifier(expected["schema"]),
                        sql.Identifier(expected["relation_name"]),
                    )
                )
                locked_by_oid = _relation_by_oid(
                    cursor,
                    database_oid=expected["database_oid"],
                    relation_oid=expected["relation_oid"],
                )
                locked_by_name = _relation_by_name(
                    cursor,
                    schema=expected["schema"],
                    relation_name=expected["relation_name"],
                )
                if (
                    not _identity_matches(locked_by_oid, expected)
                    or not _identity_matches(locked_by_name, expected)
                ):
                    result = GOLD_BACKUP_IDENTITY_MISMATCH
                else:
                    cursor.execute(
                        sql.SQL("DROP TABLE {}.{}").format(
                            sql.Identifier(expected["schema"]),
                            sql.Identifier(expected["relation_name"]),
                        )
                    )
                    drop_executed = True
                    result = GOLD_BACKUP_REMOVED
    except Exception as exc:
        try:
            transaction.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:
            logger.warning("Gold backup cleanup rollback failed", exc_info=True)
        pending_error = (
            exc
            if isinstance(exc, GoldBackupCleanupRejected)
            else GoldBackupCleanupRejected("Gold backup cleanup rolled back")
        )
        if pending_error is not exc:
            pending_error.__cause__ = exc
    else:
        try:
            transaction.__exit__(None, None, None)
        except Exception as exc:
            pending_error = (
                GoldBackupCleanupOutcomeUnknown(
                    "Gold backup cleanup commit outcome is unknown"
                )
                if drop_executed
                else GoldBackupCleanupRejected(
                    "Gold backup cleanup transaction completion failed"
                )
            )
            pending_error.__cause__ = exc

    try:
        context.__exit__(
            type(pending_error) if pending_error is not None else None,
            pending_error,
            pending_error.__traceback__ if pending_error is not None else None,
        )
    except Exception as exc:
        if result is None and pending_error is None:
            pending_error = GoldBackupCleanupRejected(
                "Gold backup cleanup pool release failed"
            )
            pending_error.__cause__ = exc
        elif drop_executed and pending_error is None:
            logger.warning(
                "Gold backup cleanup commit was acknowledged; "
                "pool release failed",
                exc_info=True,
            )

    if pending_error is not None:
        raise pending_error
    if result is None:
        raise GoldBackupCleanupRejected(
            "Gold backup cleanup produced no result"
        )
    try:
        _clear_cleanup_eligibility(run_id)
    except GoldBackupCleanupRejected as exc:
        raise GoldBackupCleanupStateRecordingFailed(
            "Gold backup cleanup outcome is known, but app-state recording failed"
        ) from exc
    return GoldBackupCleanupResult(
        run_id=run_id,
        outcome=result,
        backup_identity=dict(expected),
    )
