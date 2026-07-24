"""Atomic table promotion helpers."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import psycopg
from psycopg import sql


logger = logging.getLogger(__name__)


class PromotionError(Exception):
    """Raised when atomic table promotion fails."""
    pass


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(value: str, label: str) -> None:
    if not _IDENTIFIER_RE.match(value):
        raise PromotionError(f"Unsafe {label}: {value}")


def candidate_table_name(target_table: str, run_id: str) -> str:
    """Return <target>_candidate_<run_id> after validating both identifiers."""
    _validate_identifier(target_table, "target table")
    _validate_identifier(run_id, "run id")
    return f"{target_table}_candidate_{run_id}"


@dataclass(frozen=True)
class PromotionPlan:
    candidate_table: str
    candidate_schema: str
    target_table: str
    target_schema: str


def resolve_relation_identity(conn: Any, schema: str, table: str) -> dict[str, Any] | None:
    """Return exact OID catalog identity dict for a relation, or None if it does not exist."""
    _validate_identifier(schema, "schema")
    _validate_identifier(table, "table")
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.oid, n.oid, c.relname, n.nspname, c.relkind, (SELECT oid FROM pg_database WHERE datname = current_database())
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s
            """,
            (schema, table)
        )
        row = cur.fetchone()
        if not row:
            return None
        if len(row) < 6:
            return {
                "relation_oid": int(row[0]) if len(row) > 0 and row[0] is not None else 0,
                "namespace_oid": int(row[1]) if len(row) > 1 and row[1] is not None else 0,
                "relation_name": str(row[2]) if len(row) > 2 else table,
                "schema": str(row[3]) if len(row) > 3 else schema,
                "relation_kind": str(row[4]) if len(row) > 4 else "r",
                "database_oid": int(row[5]) if len(row) > 5 and row[5] is not None else 0,
            }
        return {
            "relation_oid": int(row[0]),
            "namespace_oid": int(row[1]),
            "relation_name": str(row[2]),
            "schema": str(row[3]),
            "relation_kind": str(row[4]),
            "database_oid": int(row[5]) if row[5] is not None else 0,
        }


import hashlib


def generate_backup_relation_name(target_name: str, run_id: str | None = None) -> str:
    """Generate a PostgreSQL-safe backup relation name <= 63 UTF-8 bytes."""
    encoded_target = target_name.encode("utf-8")
    truncated_target = encoded_target[:30].decode("utf-8", errors="ignore")
    suffix_seed = f"{target_name}:{run_id}" if run_id else target_name
    suffix = hashlib.sha256(suffix_seed.encode("utf-8")).hexdigest()[:16]
    backup_name = f"{truncated_target}_bk_{suffix}"
    if len(backup_name.encode("utf-8")) > 63:
        backup_name = f"bk_{suffix}"
    return backup_name


class SilverPromotionFailedBeforeCommit(PromotionError):
    """Raised when Silver promotion fails deterministically before commit attempt (no commit was attempted)."""
    pass


class SilverPromotionFailedKnownRollback(SilverPromotionFailedBeforeCommit):
    """Raised when Silver promotion fails deterministically before commit attempt and rollback was acknowledged."""
    pass


class SilverPromotionRollbackFailed(SilverPromotionFailedBeforeCommit):
    """Raised when Silver promotion body fails before commit attempt and rollback acknowledgement fails."""
    pass


class SilverPromotionCommitUnknown(PromotionError):
    """Raised when PostgreSQL commit attempt acknowledgement is uncertain."""
    pass


def promote_candidate_table(
    candidate_table: str,
    candidate_schema: str,
    target_table: str,
    target_schema: str,
    promotion_conninfo: str | None = None,
    promoted_owner: str | None = None,
    expected_candidate_identity: dict[str, Any] | None = None,
    expected_target_identity: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """
    Atomically promote a candidate table to the target schema.
    Uses the promotion pool to guarantee correct privileges and connection management.
    Returns (final_target_identity, backup_identity).
    """
    plan = PromotionPlan(candidate_table, candidate_schema, target_table, target_schema)
    for value, label in (
        (plan.candidate_table, "candidate table"),
        (plan.candidate_schema, "candidate schema"),
        (plan.target_table, "target table"),
        (plan.target_schema, "target schema"),
    ):
        _validate_identifier(value, label)
    if promoted_owner is not None:
        _validate_identifier(promoted_owner, "promoted owner")

    phase = "PRE_TRANSACTION"
    try:
        if promotion_conninfo:
            connection_ctx = psycopg.connect(promotion_conninfo, autocommit=False)
        else:
            from src.db_config import get_promotion_pool
            connection_ctx = get_promotion_pool().connection()
    except Exception as exc:
        raise SilverPromotionFailedBeforeCommit(f"Pool checkout or connection failed: {exc}") from exc

    committed_result: tuple[dict[str, Any], dict[str, Any] | None] | None = None
    try:
        with connection_ctx as conn:
            tx = conn.transaction()
            try:
                tx.__enter__()
                phase = "TRANSACTION_ACTIVE"
            except Exception as exc:
                raise SilverPromotionFailedBeforeCommit(f"Failed to enter promotion transaction: {exc}") from exc

            try:
                with conn.cursor() as cur:
                    # 1. Require complete candidate identity
                    if expected_candidate_identity is None:
                        raise PromotionError("Candidate identity parameter is mandatory.")
                    required_keys = ("database_oid", "namespace_oid", "relation_oid", "schema", "relation_name", "relation_kind")
                    if not isinstance(expected_candidate_identity, dict) or not all(k in expected_candidate_identity and expected_candidate_identity[k] is not None for k in required_keys):
                        raise PromotionError("Invalid or incomplete candidate identity structure (missing database_oid or required key).")

                    # 2. Lock candidate table first
                    cur.execute(
                        sql.SQL("SELECT to_regclass({})").format(
                            sql.Literal(f"{candidate_schema}.{candidate_table}")
                        )
                    )
                    if cur.fetchone()[0] is None:
                        raise PromotionError("Candidate table does not exist.")

                    cur.execute(
                        sql.SQL("LOCK TABLE {}.{} IN ACCESS EXCLUSIVE MODE").format(
                            sql.Identifier(candidate_schema),
                            sql.Identifier(candidate_table),
                        )
                    )

                    # 3. Re-resolve/revalidate exact candidate identity under lock
                    cand_ident = resolve_relation_identity(conn, candidate_schema, candidate_table)
                    if cand_ident is None:
                        raise PromotionError("Candidate table missing after lock.")

                    for k in required_keys:
                        if expected_candidate_identity.get(k) != cand_ident.get(k):
                            raise PromotionError(
                                f"Candidate relation identity mismatch under lock on key '{k}': "
                                f"expected {expected_candidate_identity.get(k)}, found {cand_ident.get(k)}"
                            )

                    # 4. Check target relation & exact target identity
                    target_ident = resolve_relation_identity(conn, target_schema, target_table)
                    target_exists = target_ident is not None
                    backup_table = None
                    backup_ident = None
                    if target_exists:
                        if expected_target_identity is None:
                            raise PromotionError("Target relation overwrite unauthorized or missing target identity.")
                        for k in required_keys:
                            if expected_target_identity.get(k) != target_ident.get(k):
                                raise PromotionError(
                                    f"Target relation identity mismatch on key '{k}': "
                                    f"expected {expected_target_identity.get(k)}, found {target_ident.get(k)}"
                                )
                        cur.execute(
                            sql.SQL("LOCK TABLE {}.{} IN ACCESS EXCLUSIVE MODE").format(
                                sql.Identifier(target_schema),
                                sql.Identifier(target_table),
                            )
                        )
                        target_ident_locked = resolve_relation_identity(conn, target_schema, target_table)
                        if target_ident_locked != target_ident:
                            raise PromotionError("Target relation identity mismatch under lock.")

                        backup_table = generate_backup_relation_name(target_table, run_id or candidate_table)
                        cur.execute(
                            sql.SQL("SELECT to_regclass({})").format(
                                sql.Literal(f"{target_schema}.{backup_table}")
                            )
                        )
                        if cur.fetchone()[0] is not None:
                            raise PromotionError(f"Backup relation collision: {target_schema}.{backup_table} already exists.")

                    if target_exists and backup_table:
                        cur.execute(
                            sql.SQL("ALTER TABLE {}.{} RENAME TO {}").format(
                                sql.Identifier(target_schema),
                                sql.Identifier(target_table),
                                sql.Identifier(backup_table),
                            )
                        )
                        backup_ident = resolve_relation_identity(conn, target_schema, backup_table)
                        if backup_ident is None or backup_ident["relation_oid"] != target_ident["relation_oid"] or backup_ident["database_oid"] != target_ident["database_oid"]:
                            raise PromotionError("Backup relation identity mismatch after rename under lock.")

                    cur.execute(
                        sql.SQL("ALTER TABLE {}.{} SET SCHEMA {}").format(
                            sql.Identifier(candidate_schema),
                            sql.Identifier(candidate_table),
                            sql.Identifier(target_schema),
                        )
                    )
                    cur.execute(
                        sql.SQL("ALTER TABLE {}.{} RENAME TO {}").format(
                            sql.Identifier(target_schema),
                            sql.Identifier(candidate_table),
                            sql.Identifier(target_table),
                        )
                    )
                    if promoted_owner is not None:
                        cur.execute(
                            sql.SQL("ALTER TABLE {}.{} OWNER TO {}").format(
                                sql.Identifier(target_schema),
                                sql.Identifier(target_table),
                                sql.Identifier(promoted_owner),
                            )
                        )

                    final_target_ident = resolve_relation_identity(conn, target_schema, target_table)
                    if (
                        final_target_ident is None
                        or final_target_ident["relation_oid"] != cand_ident["relation_oid"]
                        or final_target_ident["database_oid"] != cand_ident["database_oid"]
                    ):
                        raise PromotionError("Final target relation identity mismatch or missing after promotion.")

                    if target_exists and backup_table:
                        backup_ident_before_drop = resolve_relation_identity(conn, target_schema, backup_table)
                        if backup_ident_before_drop is None or backup_ident_before_drop["relation_oid"] != target_ident["relation_oid"]:
                            raise PromotionError("Backup relation identity mismatch before drop.")
                        cur.execute(
                            sql.SQL("DROP TABLE {}.{}").format(
                                sql.Identifier(target_schema), sql.Identifier(backup_table)
                            )
                        )

                    res = (final_target_ident, backup_ident)
            except Exception as exc:
                try:
                    tx.__exit__(type(exc), exc, exc.__traceback__)
                except Exception as rollback_exc:
                    raise SilverPromotionRollbackFailed(f"Promotion body failed and rollback failed: body_error={exc}, rollback_error={rollback_exc}") from exc
                raise SilverPromotionFailedKnownRollback(f"Promotion failed before commit (rolled back): {exc}") from exc

            phase = "COMMIT_IN_PROGRESS"
            try:
                tx.__exit__(None, None, None)
                committed_result = res
                phase = "COMMIT_ACKNOWLEDGED"
            except Exception as exc:
                raise SilverPromotionCommitUnknown(f"Promotion commit acknowledgement uncertain: {exc}") from exc

            return committed_result
    except Exception as exc:
        if phase == "COMMIT_ACKNOWLEDGED" and committed_result is not None:
            logger.warning(
                "Silver promotion commit was acknowledged, but PostgreSQL "
                "connection/pool cleanup failed; preserving committed result",
                exc_info=True,
            )
            return committed_result
        if isinstance(exc, PromotionError):
            raise
        if phase == "COMMIT_IN_PROGRESS":
            raise SilverPromotionCommitUnknown(f"Promotion commit outcome uncertain: {exc}") from exc
        raise SilverPromotionFailedBeforeCommit(f"Promotion connection/transaction error: {exc}") from exc


def discard_candidate_table(candidate_table: str, candidate_schema: str, promotion_conninfo: str | None = None) -> None:
    """Drop the candidate table entirely upon validation failure."""
    _validate_identifier(candidate_table, "candidate table")
    _validate_identifier(candidate_schema, "candidate schema")
    if promotion_conninfo:
        connection_ctx = psycopg.connect(promotion_conninfo, autocommit=True)
    else:
        from src.db_config import get_promotion_pool
        connection_ctx = get_promotion_pool().connection()

    try:
        with connection_ctx as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                        sql.Identifier(candidate_schema), sql.Identifier(candidate_table)
                    )
                )
    except psycopg.Error as e:
        raise PromotionError(f"Failed to discard candidate table: {e}")
