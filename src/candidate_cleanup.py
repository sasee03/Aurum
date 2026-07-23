"""Candidate Table Hygiene and Cleanup Utilities for Aurum."""

from __future__ import annotations

import datetime
import logging
import re
from typing import Dict, List, Any, Optional

import psycopg
from psycopg import sql
from src.app_state.db import get_connection
from src.db_config import load_layer_schemas, postgres_promotion_conninfo, get_generated_sql_pool
from src.gold_security import (
    GoldSecurityError,
    load_gold_security_state,
)
from src.promotion import discard_candidate_table, PromotionError


logger = logging.getLogger(__name__)

_CANDIDATE_PARSE_REGEX = re.compile(
    r"^(?P<target_table>[A-Za-z_][A-Za-z0-9_]*)_candidate_(?P<run_id>run_[A-Za-z0-9_]+)$",
    re.IGNORECASE
)

GOLD_CLEANUP_REMOVED = "removed"
GOLD_CLEANUP_MISSING = "missing"
GOLD_CLEANUP_IDENTITY_MISMATCH = "identity_mismatch"


class GoldCandidateCleanupError(RuntimeError):
    """Gold cleanup failed before a destructive commit was acknowledged."""


class GoldCandidateCleanupOutcomeUnknown(RuntimeError):
    """Gold DROP ran, but PostgreSQL did not acknowledge its commit outcome."""


def _parse_iso_datetime(dt_str: str) -> Optional[datetime.datetime]:
    try:
        # Handle ISO strings with optional Z or fractional seconds
        clean_str = dt_str.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(clean_str)
    except Exception:
        return None


def _gold_candidate_identity_matches(
    persisted_identity: Any,
    live_identity: Any,
) -> bool:
    """Require exact durable/live identity equality before destructive cleanup."""
    required = {
        "database_oid",
        "namespace_oid",
        "relation_oid",
        "schema",
        "relation_name",
        "relation_kind",
    }
    return (
        isinstance(persisted_identity, dict)
        and isinstance(live_identity, dict)
        and set(persisted_identity) == required
        and set(live_identity) == required
        and persisted_identity == live_identity
        and persisted_identity["relation_kind"] == "r"
    )


def _resolve_live_gold_candidate_identity(
    cursor: Any,
    *,
    schema: str,
    relation_name: str,
) -> tuple[str, dict[str, Any]] | None:
    cursor.execute(
        """
        SELECT database.datname,
               database.oid,
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
    return (
        str(row[0]),
        {
            "database_oid": int(row[1]),
            "namespace_oid": int(row[2]),
            "relation_oid": int(row[3]),
            "schema": str(row[4]),
            "relation_name": str(row[5]),
            "relation_kind": str(row[6]),
        },
    )


def _close_gold_cleanup_connection(connection: Any) -> None:
    try:
        connection.close()
    except Exception:
        logger.warning(
            "Gold cleanup PostgreSQL connection close failed",
            exc_info=True,
        )


def discard_owned_gold_candidate(
    *,
    expected_identity: dict[str, Any],
    expected_database_name: str,
    promotion_conninfo: str,
) -> str:
    """Drop an exactly owned Gold candidate in one locked transaction.

    The initial catalog lookup is only a fast ownership check. ACCESS EXCLUSIVE
    is then acquired by identifier and the complete identity is resolved again
    while that lock is held. A same-name replacement can therefore be locked,
    but it cannot pass the post-lock OID/namespace identity check or be dropped.
    """
    if (
        not _gold_candidate_identity_matches(
            expected_identity,
            expected_identity,
        )
        or not isinstance(expected_database_name, str)
        or not expected_database_name
    ):
        raise GoldCandidateCleanupError(
            "Gold candidate cleanup authority is malformed"
        )

    try:
        connection = psycopg.connect(promotion_conninfo, autocommit=False)
    except Exception as exc:
        raise GoldCandidateCleanupError(
            "Gold candidate cleanup database is unavailable"
        ) from exc

    try:
        transaction = connection.transaction()
        transaction.__enter__()
    except Exception as exc:
        _close_gold_cleanup_connection(connection)
        raise GoldCandidateCleanupError(
            "Gold candidate cleanup transaction could not start"
        ) from exc

    result: str | None = None
    pending_error: Exception | None = None
    pending_cause: Exception | None = None
    drop_executed = False
    try:
        with connection.cursor() as cursor:
            live = _resolve_live_gold_candidate_identity(
                cursor,
                schema=expected_identity["schema"],
                relation_name=expected_identity["relation_name"],
            )
            if live is None:
                result = GOLD_CLEANUP_MISSING
            elif (
                live[0] != expected_database_name
                or not _gold_candidate_identity_matches(
                    expected_identity,
                    live[1],
                )
            ):
                result = GOLD_CLEANUP_IDENTITY_MISMATCH
            else:
                cursor.execute(
                    sql.SQL(
                        "LOCK TABLE {}.{} IN ACCESS EXCLUSIVE MODE"
                    ).format(
                        sql.Identifier(expected_identity["schema"]),
                        sql.Identifier(expected_identity["relation_name"]),
                    )
                )
                locked = _resolve_live_gold_candidate_identity(
                    cursor,
                    schema=expected_identity["schema"],
                    relation_name=expected_identity["relation_name"],
                )
                if locked is None:
                    result = GOLD_CLEANUP_MISSING
                elif (
                    locked[0] != expected_database_name
                    or not _gold_candidate_identity_matches(
                        expected_identity,
                        locked[1],
                    )
                ):
                    result = GOLD_CLEANUP_IDENTITY_MISMATCH
                else:
                    cursor.execute(
                        sql.SQL("DROP TABLE {}.{}").format(
                            sql.Identifier(expected_identity["schema"]),
                            sql.Identifier(expected_identity["relation_name"]),
                        )
                    )
                    drop_executed = True
                    result = GOLD_CLEANUP_REMOVED
    except Exception as exc:
        try:
            transaction.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:
            logger.warning(
                "Gold candidate cleanup rollback failed",
                exc_info=True,
            )
        if isinstance(exc, psycopg.errors.UndefinedTable):
            result = GOLD_CLEANUP_MISSING
        else:
            pending_error = GoldCandidateCleanupError(
                "Gold candidate cleanup rolled back"
            )
            pending_cause = exc
    else:
        try:
            transaction.__exit__(None, None, None)
        except Exception as exc:
            pending_cause = exc
            if drop_executed:
                pending_error = GoldCandidateCleanupOutcomeUnknown(
                    "Gold candidate cleanup commit outcome is unknown"
                )
            else:
                pending_error = GoldCandidateCleanupError(
                    "Gold candidate cleanup transaction completion failed"
                )

    _close_gold_cleanup_connection(connection)
    if pending_error is not None:
        raise pending_error from pending_cause
    if result is None:
        raise GoldCandidateCleanupError(
            "Gold candidate cleanup produced no result"
        )
    return result


def _discard_cleanup_candidate(
    *,
    table: str,
    schema: str,
    promotion_conninfo: str,
    gold_state: Any | None,
) -> str:
    if gold_state is None:
        discard_candidate_table(table, schema, promotion_conninfo)
        return GOLD_CLEANUP_REMOVED
    return discard_owned_gold_candidate(
        expected_identity=gold_state.candidate_identity,
        expected_database_name=gold_state.approval_snapshot["database"]["name"],
        promotion_conninfo=promotion_conninfo,
    )


def _gold_cleanup_non_removal_reason(result: str) -> str:
    if result == GOLD_CLEANUP_MISSING:
        return (
            "Gold candidate disappeared before identity-locked cleanup; "
            "no removal was recorded."
        )
    return (
        "Gold candidate identity changed before destructive cleanup; "
        "the replacement was preserved."
    )


def cleanup_orphaned_candidate_tables(age_threshold_seconds: int = 3600) -> Dict[str, Any]:
    """
    Scans candidate schemas (silver_candidates, gold_candidates) for leftover tables.
    
    Categorizes tables into:
    1. removed_candidates: Tables older than age_threshold_seconds with non-promoted status in SQLite.
    2. in_flight_candidates: Tables created within age_threshold_seconds (preserved).
    3. untracked_candidates: Tables with no matching SQLite metadata record or mismatched table_name (preserved for human review).
    """
    schemas = load_layer_schemas()
    candidate_schemas = [schemas.silver_candidates, schemas.gold_candidates]
    
    # 1. Fetch metadata records from SQLite
    sqlite_records: Dict[str, dict] = {}
    gold_security_records: Dict[str, Any] = {}
    with get_connection() as conn_db:
        rows = conn_db.execute(
            "SELECT * FROM generated_sql_review"
        ).fetchall()
        for row in rows:
            sqlite_records[row["run_id"]] = dict(row)
        security_rows = conn_db.execute(
            "SELECT * FROM gold_security_state"
        ).fetchall()
        gold_security_records = {
            row["run_id"]: row
            for row in security_rows
        }
            
    # 2. Fetch active candidate tables from Postgres information_schema using promotion connection
    postgres_candidates: List[dict] = []
    with psycopg.connect(postgres_promotion_conninfo()) as p_conn:
        with p_conn.cursor() as cur:
            for schema_name in candidate_schemas:
                cur.execute(
                    """
                    SELECT database.oid,
                           database.datname,
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
                      AND relation.relkind IN ('r', 'p')
                    """,
                    (schema_name,)
                )
                for (
                    database_oid,
                    database_name,
                    namespace_oid,
                    relation_oid,
                    live_schema,
                    tbl_name,
                    relation_kind,
                ) in cur.fetchall():
                    postgres_candidates.append({
                        "schema": schema_name,
                        "table": tbl_name,
                        "database_name": str(database_name),
                        "identity": {
                            "database_oid": int(database_oid),
                            "namespace_oid": int(namespace_oid),
                            "relation_oid": int(relation_oid),
                            "schema": str(live_schema),
                            "relation_name": str(tbl_name),
                            "relation_kind": str(relation_kind),
                        },
                    })

    removed_candidates: List[dict] = []
    in_flight_candidates: List[dict] = []
    untracked_candidates: List[dict] = []
    
    # 3. Classify and process each candidate table
    for candidate in postgres_candidates:
        schema = candidate["schema"]
        table = candidate["table"]
        
        match = _CANDIDATE_PARSE_REGEX.match(table)
        if not match:
            untracked_candidates.append({
                "schema": schema,
                "table": table,
                "reason": "Candidate table name does not match expected pattern <target>_candidate_<run_id>."
            })
            continue

        parsed_target = match.group("target_table")
        parsed_run_id = match.group("run_id")
        
        if parsed_run_id not in sqlite_records:
            untracked_candidates.append({
                "schema": schema,
                "table": table,
                "reason": "No matching metadata record in generated_sql_review table."
            })
            continue

        rec = sqlite_records[parsed_run_id]

        # Require exact match on target table name prefix
        if rec["table_name"] != parsed_target:
            untracked_candidates.append({
                "schema": schema,
                "table": table,
                "reason": f"Target table name mismatch: Postgres candidate target '{parsed_target}' != SQLite metadata table '{rec['table_name']}'."
            })
            continue

        # Require exact match on candidate schema (cross-pipeline protection)
        expected_candidate_schema = rec.get("candidate_schema")
        if expected_candidate_schema:
            if expected_candidate_schema != schema:
                untracked_candidates.append({
                    "schema": schema,
                    "table": table,
                    "reason": f"Schema mismatch: Postgres candidate schema '{schema}' != SQLite metadata candidate_schema '{expected_candidate_schema}'."
                })
                continue
        elif schema not in rec.get("sql_text", ""):
            # Fallback for legacy records created prior to candidate_schema column migration
            untracked_candidates.append({
                "schema": schema,
                "table": table,
                "reason": f"Schema mismatch: Postgres candidate schema '{schema}' not targeted in SQLite SQL text."
            })
            continue
        created_dt = _parse_iso_datetime(rec["created_at"])
        
        if created_dt is None:
            # Unparseable timestamp, treat as untracked for safety
            untracked_candidates.append({
                "schema": schema,
                "table": table,
                "reason": f"Unparseable timestamp '{rec['created_at']}' in SQLite record."
            })
            continue

        now = datetime.datetime.now(tz=created_dt.tzinfo)
        age_seconds = (now - created_dt).total_seconds()
        status = rec.get("status")
        is_promoted = status == "PROMOTED"

        is_gold_candidate = schema == schemas.gold_candidates
        gold_state = None
        if is_gold_candidate:
            security_row = gold_security_records.get(parsed_run_id)
            if security_row is None:
                untracked_candidates.append({
                    "schema": schema,
                    "table": table,
                    "reason": (
                        "Gold candidate has no security state proving ownership; "
                        "preserved for review."
                    ),
                })
                continue
            try:
                gold_state = load_gold_security_state(
                    security_row,
                    rec,
                    configured_silver_schema=schemas.silver,
                    configured_gold_schema=schemas.gold,
                    configured_candidate_schema=schemas.gold_candidates,
                )
            except (GoldSecurityError, TypeError, ValueError):
                untracked_candidates.append({
                    "schema": schema,
                    "table": table,
                    "reason": (
                        "Gold security state is malformed or stale; "
                        "candidate preserved for review."
                    ),
                })
                continue
            if status in {"EXECUTING", "PROMOTING"}:
                in_flight_candidates.append({
                    "schema": schema,
                    "table": table,
                    "run_id": parsed_run_id,
                    "age_seconds": int(age_seconds),
                    "reason": f"Protected active Gold execution state: {status}.",
                })
                continue
            if not _gold_candidate_identity_matches(
                gold_state.candidate_identity,
                candidate.get("identity"),
            ) or (
                candidate.get("database_name")
                != gold_state.approval_snapshot["database"]["name"]
            ):
                untracked_candidates.append({
                    "schema": schema,
                    "table": table,
                    "reason": (
                        "Gold candidate ownership identity is missing or does "
                        "not match the live relation; preserved for review."
                    ),
                })
                continue

        if status in {"EXECUTING", "PROMOTING"}:
            in_flight_candidates.append({
                "schema": schema,
                "table": table,
                "run_id": parsed_run_id,
                "age_seconds": int(age_seconds),
                "reason": f"Protected active candidate state: {status}.",
            })
        elif is_promoted:
            # Table is marked promoted but still present in candidate schema (unexpected edge case)
            if age_seconds > age_threshold_seconds:
                try:
                    cleanup_result = _discard_cleanup_candidate(
                        table=table,
                        schema=schema,
                        promotion_conninfo=postgres_promotion_conninfo(),
                        gold_state=gold_state,
                    )
                    if cleanup_result != GOLD_CLEANUP_REMOVED:
                        untracked_candidates.append({
                            "schema": schema,
                            "table": table,
                            "reason": _gold_cleanup_non_removal_reason(
                                cleanup_result
                            ),
                        })
                        continue
                    removed_candidates.append({
                        "schema": schema,
                        "table": table,
                        "run_id": parsed_run_id,
                        "age_seconds": int(age_seconds),
                        "reason": "Stale leftover table from previously promoted run."
                    })
                except GoldCandidateCleanupOutcomeUnknown:
                    untracked_candidates.append({
                        "schema": schema,
                        "table": table,
                        "reason": (
                            "Gold candidate cleanup commit outcome is unknown; "
                            "manual reconciliation is required."
                        ),
                    })
                except (PromotionError, GoldCandidateCleanupError) as e:
                    untracked_candidates.append({
                        "schema": schema,
                        "table": table,
                        "reason": f"Failed to discard promoted leftover: {e}"
                    })
            else:
                in_flight_candidates.append({
                    "schema": schema,
                    "table": table,
                    "run_id": parsed_run_id,
                    "reason": "Marked promoted recently."
                })
        elif age_seconds <= age_threshold_seconds:
            in_flight_candidates.append({
                "schema": schema,
                "table": table,
                "run_id": parsed_run_id,
                "age_seconds": int(age_seconds),
                "reason": f"Created recently ({int(age_seconds)}s <= threshold {age_threshold_seconds}s)."
            })
        else:
            # Safe to auto-remove: older than threshold and non-promoted
            try:
                cleanup_result = _discard_cleanup_candidate(
                    table=table,
                    schema=schema,
                    promotion_conninfo=postgres_promotion_conninfo(),
                    gold_state=gold_state,
                )
                if cleanup_result != GOLD_CLEANUP_REMOVED:
                    untracked_candidates.append({
                        "schema": schema,
                        "table": table,
                        "reason": _gold_cleanup_non_removal_reason(
                            cleanup_result
                        ),
                    })
                    continue
                removed_candidates.append({
                    "schema": schema,
                    "table": table,
                    "run_id": parsed_run_id,
                    "age_seconds": int(age_seconds),
                    "reason": "Orphaned stale candidate table from failed or abandoned run."
                })
            except GoldCandidateCleanupOutcomeUnknown:
                untracked_candidates.append({
                    "schema": schema,
                    "table": table,
                    "reason": (
                        "Gold candidate cleanup commit outcome is unknown; "
                        "manual reconciliation is required."
                    ),
                })
            except (PromotionError, GoldCandidateCleanupError) as e:
                untracked_candidates.append({
                    "schema": schema,
                    "table": table,
                    "reason": f"Failed to discard orphaned candidate: {e}"
                })

    return {
        "status": "success",
        "threshold_seconds": age_threshold_seconds,
        "removed_candidates": removed_candidates,
        "in_flight_candidates": in_flight_candidates,
        "untracked_candidates": untracked_candidates
    }
